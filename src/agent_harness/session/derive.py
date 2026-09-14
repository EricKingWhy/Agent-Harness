"""derive_messages：从 SessionEvent 序列投影出模型可见 messages 列表。

纯函数，无副作用。负责：
    1. user/message → HumanMessage
    2. model/completed → AIMessage（含 tool_calls）
    3. tool/result → ToolMessage（按 tool_call_id 配对到 AIMessage）
    4. dangling tool_call 检测 → 注入合成 ToolMessage

配对算法：以 AIMessage 为单位。一条 model/completed 带多个 tool_calls 时，
投影成一条 AIMessage(tool_calls=[...])，后续 tool/result 按 tool_call_id
匹配成各自 ToolMessage（符合 OpenAI / Anthropic / LangChain 标准消息格式）。
"""

from __future__ import annotations

import logging

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agent_harness.session.event import (
    COMPACTION_END,
    COMPACTION_START,
    CONTEXT_COMPACTED,
    MODEL_COMPLETED,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    SessionEvent,
)

logger = logging.getLogger("agent_harness.session.derive")

#: 合成 dangling ToolMessage 的固定内容（模型可见，引导自主决策）
DANGLING_TOOL_CONTENT = "工具执行被中断，结果未知"

#: bracket 元数据事件——不投影成消息，仅标记 shadowed 区间。
_BRACKET_META_TYPES = frozenset({
    COMPACTION_START, CONTEXT_COMPACTED, COMPACTION_END,
})


def _normalize_tool_calls_for_projection(
    raw: object,
) -> list[dict[str, object]]:
    """把 MODEL_COMPLETED.tool_calls 规整成投影安全的 list[dict]。

    单事件层容错：tool_calls 可能被旧日志、手工写入、序列化路径污染成非 list
    （dict / str / None）。derive_messages 是恢复链的必经节点，一行坏数据不能
    brick 整个 session 的恢复（违反存储模块"一行坏数据只损失该行"的契约）。
    非法形状降级为无 tool_calls（只丢该事件的工具调用，不让整个投影抛错）；
    单条非 dict 元素跳过。

    缺 id 在投影层保留空串（与事件原始形状一致，仅做消息重建），不在投影层
    合成占位 id；Tool Runtime 边界的 ToolCall.normalize 才升级为 gen_<hex> 占位
    （那是 Ledger 主键与 ToolMessage 配对的关键）。两层策略刻意不同：投影只读、
    Runtime 才赋身份。详见 contract.py:ToolCall.normalize。
    """
    if not isinstance(raw, list):
        if raw:
            logger.warning(
                "MODEL_COMPLETED.tool_calls 形状非法（%s），降级为无 tool_calls",
                type(raw).__name__,
            )
        return []
    normalized: list[dict[str, object]] = []
    for tc in raw:
        if not isinstance(tc, dict):
            logger.warning(
                "tool_call 元素非 dict（%s），跳过该项", type(tc).__name__
            )
            continue
        normalized.append(
            {
                "id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            }
        )
    return normalized


def derive_messages(events: list[SessionEvent]) -> list[AnyMessage]:
    """从事件序列投影出 messages 列表。

    纯函数：不修改输入 events，不产生副作用。
    dangling tool_call（有 tool/call 无匹配 tool/result）会注入合成 ToolMessage。

    T4 (#134)：识别 4-event compaction bracket。bracket 标记的 source_seq 区间
    内的原始投影事件被 shadowed（跳过），CONTEXT_COMPACTED 的 summary 投影成
    SystemMessage 替代被压缩段。
    """
    # 第一遍：收集所有 bracket 的 shadowed seq 区间 + 对应 summary。
    # 每个 bracket 由 COMPACTION_START(source_seq_start..source_seq_end) 标记，
    # CONTEXT_COMPACTED 携带 summary，COMPACTION_END 关闭 bracket。
    shadowed_ranges: list[tuple[int, int]] = []
    bracket_summaries: list[str] = []
    for event in events:
        if event.type == COMPACTION_START:
            start = event.data.get("source_seq_start", 0)
            end = event.data.get("source_seq_end", 0)
            shadowed_ranges.append((start, end))
        elif event.type == CONTEXT_COMPACTED:
            bracket_summaries.append(event.data.get("summary", ""))

    def is_shadowed(seq: int) -> bool:
        return any(start <= seq <= end for start, end in shadowed_ranges)

    # 第二遍：从事件按顺序投影 messages（不含 dangling 合成）。
    #
    # summary SystemMessage 必须在被压缩段的**原位置**注入——即遇到第一个
    # shadowed 事件时插入 summary，而不是在 CONTEXT_COMPACTED 事件的位置
    # 插入。原因：bracket 事件可能排在当前用户消息之后（compaction 在
    # context build 阶段触发，此时 user/message 已经 append），如果按
    # CONTEXT_COMPACTED 的位置投影 summary，summary 会落到当前用户消息
    # 之后，破坏"摘要在前、当前请求在后"的语义。
    messages: list[AnyMessage] = []
    summary_emitted = [False] * len(bracket_summaries)

    for event in events:
        # 遇到某个 bracket 的第一个 shadowed 事件时，先吐 summary
        for bi, (s, _e) in enumerate(shadowed_ranges):
            if not summary_emitted[bi] and event.seq == s:
                if bi < len(bracket_summaries):
                    summary = bracket_summaries[bi]
                    if summary:
                        messages.append(SystemMessage(content=summary))
                summary_emitted[bi] = True
                break

        # CONTEXT_COMPACTED / COMPACTION_START / COMPACTION_END 不投影成消息
        if event.type in _BRACKET_META_TYPES:
            continue

        # 跳过被 bracket shadowed 的原始事件
        if is_shadowed(event.seq):
            continue

        if event.type == USER_MESSAGE:
            content = event.data.get("content", "")
            messages.append(HumanMessage(content=content))

        elif event.type == MODEL_COMPLETED:
            content = event.data.get("content", "")
            tool_calls = _normalize_tool_calls_for_projection(
                event.data.get("tool_calls", [])
            )
            if tool_calls:
                messages.append(AIMessage(content=content, tool_calls=tool_calls))
            else:
                messages.append(AIMessage(content=content))

        elif event.type == TOOL_RESULT:
            tool_call_id = event.data.get("tool_call_id", "")
            content = event.data.get("content", "")
            messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))

    # 第二遍：为 dangling tool_call 注入合成 ToolMessage。
    # 只在 AIMessage 的某个 tool_call 在紧跟的 ToolMessage 块中没有对应结果时注入。
    # 合成消息插入在该 AIMessage 后紧跟的 ToolMessage 块的末尾。
    result: list[AnyMessage] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        result.append(msg)

        if isinstance(msg, AIMessage) and msg.tool_calls:
            # 收集这条 AIMessage 之后紧跟的连续 ToolMessage 块
            block_ids: set[str] = set()
            block_end = i + 1
            while block_end < len(messages) and isinstance(
                messages[block_end], ToolMessage
            ):
                block_ids.add(messages[block_end].tool_call_id)
                result.append(messages[block_end])
                block_end += 1

            # 为块中缺失的 tool_call 追加合成 ToolMessage
            for tc in msg.tool_calls:
                tc_id = tc.get("id", "")
                if tc_id and tc_id not in block_ids:
                    logger.warning(
                        "dangling tool_call 检测：tool_call_id=%s 无匹配 tool/result，"
                        "注入合成 ToolMessage",
                        tc_id,
                    )
                    result.append(
                        ToolMessage(content=DANGLING_TOOL_CONTENT, tool_call_id=tc_id)
                    )
            i = block_end
        else:
            i += 1

    return result


def collect_dangling(
    events: list[SessionEvent],
) -> tuple[set[str], set[str]]:
    """单遍扫描事件，返回 (dangling tool_call_ids, 已有 tool/call 事件的 ids)。

    dangling 的判定必须同时覆盖两个事实源（此前 RecoveryCoordinator 与
    detect_dangling 各维护一份近重复实现，2026-09-09 统一到这里）：
    - tool/call 事件（resume 一致性用）；
    - model/completed 的 tool_calls 字段（derive_messages 的 AIMessage 投影用）。

    MODEL_COMPLETED.tool_calls 经 ``_normalize_tool_calls_for_projection``
    容错（非 list / 非 dict 元素降级跳过——恢复链必经节点，一行坏数据不能
    brick 整个 session 的恢复）。
    """
    requested: set[str] = set()
    call_event_ids: set[str] = set()
    resolved: set[str] = set()
    for event in events:
        if event.type == MODEL_COMPLETED:
            for tc in _normalize_tool_calls_for_projection(
                event.data.get("tool_calls", [])
            ):
                tc_id = tc.get("id", "")
                if tc_id:
                    requested.add(tc_id)
        elif event.type == TOOL_CALL:
            tc_id = event.data.get("tool_call_id", "")
            if tc_id:
                requested.add(tc_id)
                call_event_ids.add(tc_id)
        elif event.type == TOOL_RESULT:
            tc_id = event.data.get("tool_call_id", "")
            if tc_id:
                resolved.add(tc_id)
    return requested - resolved, call_event_ids


def detect_dangling(events: list[SessionEvent]) -> list[str]:
    """返回事件序列中 dangling 的 tool_call_id 列表（有请求无结果）。

    供 Session.append 在 resume 时决定是否需要合成 tool/result 事件。

    真相源与 derive_messages 对齐：请求侧同时看 TOOL_CALL 事件和
    MODEL_COMPLETED.tool_calls。崩溃可能发生在 MODEL_COMPLETED 已持久化但
    TOOL_CALL 还没写的窗口——只看 TOOL_CALL 会让这种 dangling 静默漏掉，
    Session.resume 不合成 tool/result，历史永久悬空（derive_messages 每次
    投影都重复触发 dangling 警告）。
    """
    dangling, _ = collect_dangling(events)
    return sorted(dangling)
