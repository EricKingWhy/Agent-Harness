"""压缩运行期投影，保留完整 tool interaction 与当前用户 turn。"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agent_harness.context.tokens import estimate_message_tokens
from agent_harness.prompt import DEFAULT_REGISTRY
from agent_harness.session.event import SessionEvent


class ContextWindowExceededError(RuntimeError):
    """无法构造安全的模型上下文，调用方必须停止当前 run。"""


@dataclass
class CompactionResult:
    messages: list[AnyMessage]
    compacted_turn_count: int
    token_estimate: int
    fallback_used: bool
    # T4 (#134)：bracket 元数据——被压缩段的 seq 区间 + 唯一 bracket_id。
    source_seq_start: int | None = None
    source_seq_end: int | None = None
    bracket_id: str | None = None
    summary: str | None = None


#: T4 (#134)：六段式摘要 prompt 的正文已迁到 `agent_harness.prompt.builtin`
#: （section `aux:compaction`）——改文案开那一个文件。


class ContextCompactor:
    def __init__(self, model_provider: Any, *, max_context_tokens: int = 200_000,
                 auto_compact_threshold: float = 0.80,
                 hard_guard_threshold: float = 0.90,
                 keep_recent_tokens: int = 20_000,
                 summary_timeout_seconds: float = 30.0) -> None:
        if max_context_tokens <= 0 or not 0 < auto_compact_threshold <= hard_guard_threshold <= 1:
            raise ValueError("invalid context budget")
        if summary_timeout_seconds <= 0:
            raise ValueError("summary_timeout_seconds must be positive")
        self._model = model_provider
        self.auto_compact_threshold = auto_compact_threshold
        self.hard_guard_threshold = hard_guard_threshold
        self.keep_recent_tokens = keep_recent_tokens
        self._hard_limit = max_context_tokens * hard_guard_threshold
        self._auto_limit = max_context_tokens * auto_compact_threshold
        self._summary_timeout = summary_timeout_seconds
        self._max_context_tokens = max_context_tokens
        self.reserve = max(int(max_context_tokens * 0.15), 16384)

    async def compact(
        self,
        messages: list[AnyMessage],
        token_estimate: int,
        *,
        events: list[SessionEvent] | None = None,
    ) -> CompactionResult:
        _validate_tool_blocks(messages)
        prefix_end = 0
        while prefix_end < len(messages) and isinstance(messages[prefix_end], SystemMessage):
            prefix_end += 1
        prefix = messages[:prefix_end]
        cut = max((i for i, message in enumerate(messages)
                   if isinstance(message, HumanMessage)), default=prefix_end)
        early, recent = messages[prefix_end:cut], messages[cut:]
        if not early:
            count = estimate_message_tokens(messages)
            if count > self._hard_limit:
                raise ContextWindowExceededError("No complete early turn can be compacted")
            return CompactionResult(list(messages), 0, count, False)
        prompt = SystemMessage(
            content=DEFAULT_REGISTRY.assemble("aux:compaction").system_text
        )
        transcript = HumanMessage(content=json.dumps(
            [message.model_dump(mode="json") for message in early], ensure_ascii=False,
        ))
        request = [prompt, transcript]
        fallback_used = False
        summary_text: str | None = None
        try:
            if estimate_message_tokens(request) > self._hard_limit:
                raise ContextWindowExceededError("Summary request exceeds hard guard")
            async with asyncio.timeout(self._summary_timeout):
                response = await self._model.ainvoke(request)
            if not isinstance(response, AIMessage) or response.tool_calls:
                raise ValueError("Summary must be text without tool calls")
            summary_text = response.content
            # T4 (#134)：shrink 校验——摘要必须严格小于被压缩段，
            # 否则压缩无意义且可能让上下文更大。
            early_tokens = estimate_message_tokens(early)
            summary_tokens = estimate_message_tokens([SystemMessage(content=summary_text)])
            if summary_tokens >= early_tokens:
                raise ContextWindowExceededError(
                    f"Summary ({summary_tokens} tokens) is not smaller than "
                    f"compressed segment ({early_tokens} tokens)"
                )
            compacted = [*prefix, SystemMessage(content=summary_text), *recent]
            if estimate_message_tokens(compacted) >= self._auto_limit:
                raise ContextWindowExceededError("LLM summary does not reach compaction target")
        except Exception:  # noqa: BLE001
            # Provider/超时/格式错误统一降级；CancelledError 仍向调用方传播。
            fallback_used = True
            compacted = [*prefix, SystemMessage(content=_mechanical_summary(early)), *recent]
        count = estimate_message_tokens(compacted)
        if count > self._hard_limit:
            raise ContextWindowExceededError(
                f"Compaction cannot fit context: {token_estimate} -> {count} tokens; "
                f"hard guard {self._hard_limit:g}"
            )
        # T4 (#134)：从 events 计算 source_seq 区间。
        # projecting events 一一对应 messages（derive_messages 的投影集合），
        # 但 prefix（开头的 SystemMessages）不是由投影事件产生的——
        # 所以产生 early 消息的事件是 projecting[prefix_end:cut]。
        source_seq_start: int | None = None
        source_seq_end: int | None = None
        if events is not None:
            from agent_harness.session.event import (
                MODEL_COMPLETED,
                TOOL_RESULT,
                USER_MESSAGE,
            )
            projecting = [e for e in events if e.type in {
                USER_MESSAGE, MODEL_COMPLETED, TOOL_RESULT,
            }]
            # 如果 dangling 合成注入导致计数失配，放弃 source_seq 计算
            if len(projecting) == len(messages):
                early_events = projecting[prefix_end:cut]
                if early_events:
                    source_seq_start = early_events[0].seq
                    source_seq_end = early_events[-1].seq
        return CompactionResult(
            compacted,
            sum(isinstance(message, HumanMessage) for message in early),
            count, fallback_used,
            source_seq_start=source_seq_start,
            source_seq_end=source_seq_end,
            bracket_id=str(uuid4()) if not fallback_used else None,
            summary=summary_text if not fallback_used else None,
        )


#: mechanical 摘要单字段截断预算（与 human/tool content 的 200/100 同级）。
_MECHANICAL_CAP = 200


def _mechanical_summary(messages: list[AnyMessage]) -> str:
    rows = []
    for message in messages:
        if isinstance(message, HumanMessage):
            rows.append({"type": "human", "content": message.text[:200]})
        elif isinstance(message, AIMessage):
            # tool_call.args 必须截断：args 是模型自由生成的（write 大文件等），
            # 原样嵌入会让摘要本身超硬护栏——历史从不裁剪 + 投影每轮重建，
            # 该 session 从此每次 run 都 context_window_exceeded，永久 brick。
            rows.append({"type": "ai", "tool_calls": [
                {"id": call.get("id"), "name": call.get("name"),
                 "args": _cap_text(json.dumps(call.get("args", {}), ensure_ascii=False))}
                for call in message.tool_calls
            ]})
        elif isinstance(message, ToolMessage):
            rows.append({"type": "tool", "tool_call_id": message.tool_call_id,
                         "content": message.text[:100]})
        elif isinstance(message, SystemMessage):
            rows.append({"type": "system", "content": message.text[:_MECHANICAL_CAP]})
        else:
            # 不丢弃系统约束或未知类型的消息；dump 整体截断成字符串，保证摘要有界。
            rows.append(_cap_text(
                json.dumps(message.model_dump(mode="json"), ensure_ascii=False), 300,
            ))
    return json.dumps({"mechanical_extract": rows}, ensure_ascii=False)


def _cap_text(text: str, cap: int = _MECHANICAL_CAP) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + "…[truncated]"


def _validate_tool_blocks(messages: list[AnyMessage]) -> None:
    """识别完整 AIMessage + ToolMessage 原子块；不接受缺失或孤立结果。"""
    index = 0
    while index < len(messages):
        message = messages[index]
        if isinstance(message, AIMessage) and message.tool_calls:
            expected = [call["id"] for call in message.tool_calls]
            actual = []
            index += 1
            while index < len(messages) and isinstance(messages[index], ToolMessage):
                actual.append(messages[index].tool_call_id)
                index += 1
            if (not all(expected) or len(set(expected)) != len(expected)
                    or sorted(expected) != sorted(actual)):
                raise ContextWindowExceededError("Invalid tool call/result block")
        elif isinstance(message, ToolMessage):
            raise ContextWindowExceededError("Orphan tool result in context")
        else:
            index += 1
