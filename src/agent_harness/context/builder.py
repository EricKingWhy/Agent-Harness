"""Session 事件投影到 Runtime Context 的单一入口。"""

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from agent_harness.context.compactor import ContextCompactor, ContextWindowExceededError
from agent_harness.context.provider import ContextProvider
from agent_harness.context.tokens import estimate_message_tokens, estimate_tokens
from agent_harness.session import Session
from agent_harness.session.event import (
    COMPACTION_END,
    COMPACTION_START,
    CONTEXT_COMPACTED,
    MODEL_COMPLETED,
    TOOL_RESULT,
    USER_MESSAGE,
)

logger = logging.getLogger("agent_harness.context")

__all__ = ["ContextBuilder", "ContextWindowExceededError"]

#: 会投影成消息的事件类型——与 derive_messages 的投影集合一一对应
#: （每个此类事件恰好产出一条消息，顺序一致；dangling 合成注入是唯一例外，
#: 由 _estimate_tokens_cached 的计数守卫回退处理）。
_PROJECTING_EVENT_TYPES = frozenset({USER_MESSAGE, MODEL_COMPLETED, TOOL_RESULT})


class ContextBuilder:
    """按预算压缩投影与选择 Provider 内容，不修改历史。"""

    def __init__(
        self,
        model_provider: Any,
        *,
        max_context_tokens: int = 200_000,
        auto_compact_threshold: float = 0.80,
        hard_guard_threshold: float = 0.90,
        context_providers: list[ContextProvider] | None = None,
        system_prompt: str | None = None,
        runtime_context_provider: Callable[[], str] | None = None,
    ) -> None:
        if max_context_tokens <= 0 or not 0 < auto_compact_threshold <= hard_guard_threshold <= 1:
            raise ValueError("require positive budget and 0 < auto <= hard <= 1")
        self.model_provider = model_provider
        self.max_context_tokens = max_context_tokens
        self.auto_compact_threshold = auto_compact_threshold
        self.hard_guard_threshold = hard_guard_threshold
        self.context_providers = list(context_providers or [])
        # Runtime 装配期确定的角色提示（ADR-0020a，agent_profile 运行时消费）：
        # 不是持久历史事件（不变量 #5），不写 JSONL——在 build() 返回前 prepend。
        # 缓存其 token 成本：文本终身不变，复用常量避免每步重估。
        self.system_prompt = system_prompt
        self._system_prompt_tokens: int | None = None
        # 运行时上下文快照（T7 / ADR-0023 D8）：**非持久化**——运行时组装、
        # 不 session.append、不进 derive_messages、不进记忆抽取（extractor 的
        # `has_user_message` 降级保护一旦看到注入消息就会失效，那是本设计的头号红线）。
        # 用 callable 而非静态字符串：快照含"当前日期"，静态值会在跨午夜会话里过期；
        # 每次 build 重新渲染顺带保证工具清单与模型名永远是当前事实。
        # 传 None（默认）→ 行为与 T7 之前完全一致（向后兼容）。
        self._runtime_context_provider = runtime_context_provider
        # (session_id, seq) → 该事件投影消息的 token 成本。事件落盘后其投影
        # 消息内容终身不变，成本是常量——此前每步对全部历史重新 model_dump_json
        # + BPE 编码，剖析实证占循环开销 88%（O(N²)：40 步 run 纯开销 2.2s）。
        # memo 终身 = builder 终身 = runtime 终身 = 单会话，无需淘汰。
        self._token_memo: dict[tuple[str, int], int] = {}
        # 最近一次 build 的估算总量——测试观察口（生产路径走参数传递）。
        self._token_estimate_total: int = 0

    async def build(self, session: Session) -> list[AnyMessage]:
        """不修改历史；估算包含 tool_calls 等结构字段的投影 token 数。"""
        messages = session.derive_messages()
        token_estimate = self._estimate_tokens_cached(session, messages)
        # 运行时上下文快照（T7）：provider 每次 build **只调一次**——token 估算与
        # 注入必须用同一份文本，否则预算与内容可能不一致（且 callable 的调用
        # 次数是对外契约）。**纯空白（含空串）归一为 None**：只挡空串不够——
        # `"   "` 在 Python 里为真，会让模型收到一条内容只有空白的 user 消息，
        # 白占预算且语义为零。取原文本（不 strip），只改"要不要插"的判定。
        raw_runtime_context = (
            self._runtime_context_provider()
            if self._runtime_context_provider is not None
            else None
        )
        runtime_context = (
            raw_runtime_context
            if raw_runtime_context and raw_runtime_context.strip()
            else None
        )
        runtime_context_tokens = 0
        if runtime_context:
            # 快照是 runtime 装配期上下文（非事件），成本单列加总，不进
            # derive_messages 结果——与 system_prompt 同理，避免触发
            # _estimate_tokens_cached 的「事件数 ≠ 消息数」计数失配分支。
            runtime_context_tokens = estimate_message_tokens(
                [HumanMessage(content=runtime_context)]
            )
            token_estimate += runtime_context_tokens
        # system_prompt 是 runtime 装配期上下文（非事件），其 token 成本单列加总，
        # 不进入 derive_messages 结果——避免触发 _estimate_tokens_cached 的
        # 「事件数 ≠ 消息数」计数失配分支（builder.py 的整体重估路径）。
        if self.system_prompt:
            if self._system_prompt_tokens is None:
                self._system_prompt_tokens = estimate_message_tokens(
                    [SystemMessage(content=self.system_prompt)]
                )
            token_estimate += self._system_prompt_tokens
        logger.debug(
            "Context projection token estimate: %s", token_estimate,
            extra={"session_id": session.session_id, "token_estimate": token_estimate},
        )
        if token_estimate <= self.max_context_tokens * self.auto_compact_threshold:
            built = await self._with_providers(session, messages, token_estimate)
            built = self._inject_runtime_context(built, runtime_context)
            return self._prepend_system_prompt(built)
        result = await ContextCompactor(
            self.model_provider, max_context_tokens=self.max_context_tokens,
            auto_compact_threshold=self.auto_compact_threshold,
            hard_guard_threshold=self.hard_guard_threshold,
        ).compact(messages, token_estimate, events=session.events)
        if result.compacted_turn_count:
            # T4 (#134)：写 4-event bracket 替代单个 CONTEXT_COMPACTED。
            # 原始被压缩事件保留在 JSONL 里（shadowed），derive_messages 跳过。
            bracket_id = result.bracket_id or ""
            session.append(COMPACTION_START, {
                "bracket_id": bracket_id,
                "source_seq_start": result.source_seq_start or 0,
                "source_seq_end": result.source_seq_end or 0,
            })
            session.append(CONTEXT_COMPACTED, {
                "schema": "six_section",
                "summary": result.summary or "",
                "source_seq_start": result.source_seq_start or 0,
                "source_seq_end": result.source_seq_end or 0,
                "compacted_turn_count": result.compacted_turn_count,
                "token_estimate": result.token_estimate,
                "fallback_used": result.fallback_used,
                "bracket_id": bracket_id,
            })
            session.append(COMPACTION_END, {
                "bracket_id": bracket_id,
            })
        # 压缩后的 token_estimate 只含 messages，不含 system_prompt / 快照——
        # 两者都要补回，否则 _with_providers 会把它们占用的预算当作可用空间
        # 分配给 provider 内容（快照的补回与 system_prompt 同理由）。
        provider_estimate = (
            result.token_estimate + (self._system_prompt_tokens or 0) + runtime_context_tokens
        )
        built = await self._with_providers(session, result.messages, provider_estimate)
        built = self._inject_runtime_context(built, runtime_context)
        return self._prepend_system_prompt(built)

    def _inject_runtime_context(
        self, messages: list[AnyMessage], runtime_context: str | None,
    ) -> list[AnyMessage]:
        """把运行时快照作为**一条 user-role 消息**插在最后一条 HumanMessage 之前。

        位置理由（ADR-0023 D8）：开头是稳定前缀（system + 早期历史），prefix
        cache 靠它命中；快照含"当前日期"等易变内容，紧贴最新用户消息只动尾部。

        **绝不 session.append**——本类的契约是"不修改历史"（见 `build` docstring）。
        快照一旦落成事件，三个污染面立刻复发：JSONL 永久滞留 / derive_messages
        每轮重放累积 / 记忆抽取的 `has_user_message` 降级保护失效。

        找不到 HumanMessage 时插到末尾——宁可位置退化，不可静默丢弃（有当前
        用户消息才有本次 build，理论上是不可达分支）。

        【已知位置形态】build 发生在**工具回合中途**时（events =
        user/message → model/completed(tool_calls) → tool/result），最后一条
        HumanMessage 是本回合开头那条用户消息，快照因此落在整段历史之前，
        "只动尾部"的缓存收益在该形态下退化为"在头部插一个稳定块"。这是
        PRD §279 选定的语义（"最后一条 HumanMessage 之前"）：宁可位置在
        该形态下不最优，也不把快照塞进 AI(tool_calls)/ToolResult 配对之间。
        配对不会被切开——两个 ToolMessage 之间不可能存在 HumanMessage。
        """
        if not runtime_context:
            return messages
        index = len(messages)
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                index = i
                break
        return [*messages[:index], HumanMessage(content=runtime_context), *messages[index:]]

    def _prepend_system_prompt(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """把 system_prompt 作为列表首条 SystemMessage 注入（runtime context，非事件）。

        在 _with_providers 之后 prepend：provider 内容已按既有约定插在开头
        连续 SystemMessage 之后——这里再加一条 SystemMessage 在最前，不破坏
        provider 的插入位置语义（SystemMessage 前缀更长，provider 仍紧随其后）。
        """
        if not self.system_prompt:
            return messages
        return [SystemMessage(content=self.system_prompt), *messages]

    def _estimate_tokens_cached(
        self, session: Session, messages: list[AnyMessage],
    ) -> int:
        """增量 token 估算：每条投影消息终身只编码一次。

        derive_messages 对投影事件是一一映射（按序各产出一条消息）——
        唯一例外是 dangling 合成注入的块尾 ToolMessage（事件数 ≠ 消息数），
        此时放弃增量假设整体重估（正确性优先；resume 已修复 dangling，
        运行内该路径罕见）。
        """
        projecting = [e for e in session.events
                      if e.type in _PROJECTING_EVENT_TYPES]
        if len(projecting) != len(messages):
            # 计数失配：合成注入等非常规形态。清掉本会话的 memo 整体重估
            #（下一轮恢复一一对应后重新增量起步）。
            sid = session.session_id
            self._token_memo = {
                key: cost for key, cost in self._token_memo.items() if key[0] != sid
            }
            self._token_estimate_total = estimate_message_tokens(messages)
            return self._token_estimate_total
        total = 0
        for event, message in zip(projecting, messages):
            key = (session.session_id, event.seq)
            cost = self._token_memo.get(key)
            if cost is None:
                cost = estimate_tokens(message.model_dump_json())
                self._token_memo[key] = cost
            total += cost
        self._token_estimate_total = total
        return total

    async def _with_providers(
        self, session: Session, messages: list[AnyMessage], token_estimate: int,
    ) -> list[AnyMessage]:
        remaining = int(self.max_context_tokens * self.hard_guard_threshold) - token_estimate
        selected: list[AnyMessage] = []
        for provider in self.context_providers:
            if remaining <= 0:
                break
            try:
                additions = await provider.select(session, remaining)
            except Exception:  # noqa: BLE001 — optional Provider failure cannot stop the loop.
                logger.warning("Context provider unavailable; continuing without its contribution")
                continue
            for message in additions:
                cost = estimate_message_tokens([message])
                if cost <= remaining:
                    selected.append(message)
                    remaining -= cost
        insertion = 0
        while insertion < len(messages) and isinstance(messages[insertion], SystemMessage):
            insertion += 1
        return messages[:insertion] + selected + messages[insertion:]
