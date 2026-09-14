"""Deterministic assertions（spec 12 §6：代码判断，LLM judge 不做这里的事）。

全部纯函数：输入事件流 / 用例期望，输出结构化指标。零伪造——断不出来
就是 False / 空列表，绝不猜测。
"""

from __future__ import annotations

from agent_harness.session import (
    SESSION_RESUMED,
    TOOL_CALL,
    TOOL_FAILURE_GUARD,
    TOOL_RESULT,
    SessionEvent,
)


def dangling_tool_call_ids(events: list[SessionEvent]) -> list[str]:
    """悬空 tool_call 检测：有 tool/call 无配对 tool/result 的 id 列表。

    spec 12 §9 初始 Gate：dangling tool call = 0。恢复/委派合成的 tool/result
    与 call 全局按 id 配对（tooling 侧同一语义）。
    """
    called: list[str] = []
    answered: set[str] = set()
    for event in events:
        if event.type == TOOL_CALL:
            called.append(str(event.data.get("tool_call_id")))
        elif event.type == TOOL_RESULT:
            answered.add(str(event.data.get("tool_call_id")))
    return [call_id for call_id in called if call_id not in answered]


def tool_selection_ok(events: list[SessionEvent], expected_tools: list[str]) -> bool:
    """tool_selection 断言：run 实际请求的工具集合 == 期望集合（计一次）。

    顺序不敏感（同一批内顺序由调度决定）；多调少调都算失败。
    """
    requested: list[str] = []
    for event in events:
        if event.type == TOOL_CALL:
            name = event.data.get("tool_name")
            if name is not None and name not in requested:
                requested.append(str(name))
    return sorted(requested) == sorted(expected_tools)


def recovery_guard_ok(events: list[SessionEvent]) -> bool:
    """recovery 断言（软熔断路径）：护栏软触发后 run 仍走到成功终态。

    证据链：TOOL_FAILURE_GUARD(level=soft) 在场 + run/completed 存在
    （模型在纠正消息后改变策略并完成），dangling 由调用方统一断言。
    """
    has_soft_guard = any(
        e.type == TOOL_FAILURE_GUARD and e.data.get("level") == "soft"
        for e in events
    )
    has_completed = any(e.type == "run/completed" for e in events)
    return has_soft_guard and has_completed


def kill_resume_ok(events: list[SessionEvent]) -> bool:
    """kill/resume 断言：恢复后的会话补齐合成 tool/result（无悬空）
    且 session/resumed 事件在场。"""
    has_resumed = any(e.type == SESSION_RESUMED for e in events)
    return has_resumed and not dangling_tool_call_ids(events)
