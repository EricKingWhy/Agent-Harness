"""ScriptedChatModel：不访问真实 API 的确定性模型替身（评测/测试共用 seam）。

Phase 15（ADR-0018 D10）从 tests/scripted_model.py 升格进 src：deterministic
eval runner（evaluation/runner.py）需要"脚本化模型 + 真实 AgentRuntime"的
组合——免费、确定、可进 CI。语义不变：
1. 按预设剧本依次返回 AIMessage，剧本耗尽时明确报错，绝不静默循环；
2. 每次被调用时记录 Request Snapshot：Runtime 到底发来了什么
   （messages 消息链 + bind_tools 绑定的工具描述）。
3. astream 把当前剧本 AIMessage 的 content 按 chunk_size 切 chunk 依次 yield。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage


@dataclass
class RequestSnapshot:
    """一次模型调用时 Runtime 实际发来的请求。"""

    messages: list[AnyMessage]
    tools: list | None = None


class ScriptedModel:
    """按剧本响应的假 ChatModel：bind_tools 记住工具，ainvoke/astream 吐剧本 + 记快照。"""

    def __init__(self, responses: list[AIMessage], chunk_size: int = 8) -> None:
        self._responses = list(responses)
        self._cursor = 0  # 下一条要吐的剧本下标
        self.bound_tools: list | None = None
        self.snapshots: list[RequestSnapshot] = []
        # chunk_size 控制 astream 把一条 AIMessage 切成几个 chunk；
        # 默认 8 让测试能验证多 chunk 流式拼接逻辑，又不会太碎。
        self.chunk_size = chunk_size

    def bind_tools(self, tools: list, **kwargs) -> ScriptedModel:
        """记住绑定的工具描述；返回 self，让 demo 能链式调用。

        **kwargs 吞掉 strict 等 Provider 专属参数：替身不需要它们，但必须
        接受被测对象（demo）传过来的任何额外参数，否则签名不匹配会直接 TypeError。
        """
        self.bound_tools = tools
        return self

    def _next_response(self) -> AIMessage:
        """吐下一条剧本 + 记录本次请求快照；剧本耗尽时明确报错。"""
        # 1. 剧本耗尽检查：调用次数超出预期就明确失败，绝不静默重复最后一条
        if self._cursor >= len(self._responses):
            raise RuntimeError("ScriptedModel 剧本耗尽：Runtime 调用次数超出预期")
        # 2. 记录快照：messages 必须拷贝（list(messages)）再存，否则 Runtime
        #    后续往同一个 list extend 新消息时，会把历史快照一起污染
        # 3. 消费剧本：返回当前下标的 AIMessage，然后 cursor 前进
        response = self._responses[self._cursor]
        self._cursor += 1
        return response

    async def ainvoke(self, messages: list[AnyMessage], **kwargs) -> AIMessage:
        """吐下一条剧本 + 记录本次请求快照；剧本耗尽时明确报错。"""
        self.snapshots.append(
            RequestSnapshot(messages=list(messages), tools=self.bound_tools)
        )
        return self._next_response()

    async def astream(self, messages: list[AnyMessage], **kwargs) -> AsyncIterator[AIMessageChunk]:
        """流式吐下一条剧本：把 AIMessage 的 content 按 chunk_size 切成多个 chunk。

        记一次快照（等价于 ainvoke 的一次调用）。tool_calls 不切——放在第一个 chunk
        里整批带出，让 Runtime 能在首个 chunk 就拿到结构化调用决策（真实 Provider 的
        tool_calls 通常也是流式聚合到末尾，但测试替身简化成首 chunk 携带即可）。
        """
        self.snapshots.append(
            RequestSnapshot(messages=list(messages), tools=self.bound_tools)
        )
        response = self._next_response()
        content = response.content if isinstance(response.content, str) else str(response.content)
        tool_calls = response.tool_calls or []

        if not content:
            # 无文本（纯 tool_calls 轮）：yield 一个空 content chunk 带 tool_calls
            yield AIMessageChunk(content="", tool_calls=tool_calls)
            return

        # 按 chunk_size 切 content，最后一个 chunk 带 tool_calls（若有）
        chunks = [content[i:i + self.chunk_size] for i in range(0, len(content), self.chunk_size)]
        for idx, piece in enumerate(chunks):
            is_last = idx == len(chunks) - 1
            yield AIMessageChunk(
                content=piece,
                tool_calls=tool_calls if is_last else [],
            )