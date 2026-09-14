"""Q3 spec test: collect_dangling 返回正确 tuple（含 call_event_ids）。

spec 要求（docs/TECH_DEBT_FIX_SPEC.md §Q3）：
  新增 1 个测试：验证 ``collect_dangling`` 对含 call_event_ids 的场景
  返回正确的 tuple。
"""

from __future__ import annotations

from agent_harness.session.derive import collect_dangling, detect_dangling
from agent_harness.session.event import (
    MODEL_COMPLETED,
    SESSION_STARTED,
    TOOL_CALL,
    TOOL_RESULT,
    SessionEvent,
)


def _event(seq: int, etype: str, **data) -> SessionEvent:
    return SessionEvent(seq=seq, type=etype, data=data)


class TestCollectDangling:
    """``collect_dangling`` 返回 ``(dangling_ids, call_event_ids)``。"""

    def test_returns_empty_sets_for_clean_session(self):
        """无 dangling 的干净 session → 两个空 set。"""
        events = [
            _event(0, SESSION_STARTED),
            _event(1, MODEL_COMPLETED, content="hello"),
        ]
        dangling, call_ids = collect_dangling(events)
        assert dangling == set()
        assert call_ids == set()

    def test_dangling_from_tool_call_without_result(self):
        """TOOL_CALL 有请求无结果 → dangling。"""
        events = [
            _event(0, SESSION_STARTED),
            _event(1, TOOL_CALL, tool_call_id="tc-1", tool_name="read", args={}),
        ]
        dangling, call_ids = collect_dangling(events)
        assert dangling == {"tc-1"}
        assert call_ids == {"tc-1"}

    def test_dangling_from_model_completed_tool_calls(self):
        """MODEL_COMPLETED.tool_calls 有请求无结果 → dangling。"""
        events = [
            _event(0, SESSION_STARTED),
            _event(
                1,
                MODEL_COMPLETED,
                content="",
                tool_calls=[{"id": "tc-1", "name": "read", "args": {}}],
            ),
        ]
        dangling, call_ids = collect_dangling(events)
        assert dangling == {"tc-1"}
        # MODEL_COMPLETED 不产生 call_event_id
        assert call_ids == set()

    def test_resolved_tool_call_not_dangling(self):
        """TOOL_CALL + TOOL_RESULT 配对 → 不 dangling。"""
        events = [
            _event(0, SESSION_STARTED),
            _event(1, TOOL_CALL, tool_call_id="tc-1", tool_name="read", args={}),
            _event(2, TOOL_RESULT, tool_call_id="tc-1", content="result"),
        ]
        dangling, call_ids = collect_dangling(events)
        assert dangling == set()
        assert call_ids == {"tc-1"}

    def test_mixed_dangling_and_resolved(self):
        """混合：tc-1 resolved，tc-2 dangling（来自 MODEL_COMPLETED）。"""
        events = [
            _event(0, SESSION_STARTED),
            _event(1, TOOL_CALL, tool_call_id="tc-1", tool_name="read", args={}),
            _event(2, TOOL_RESULT, tool_call_id="tc-1", content="ok"),
            _event(
                3,
                MODEL_COMPLETED,
                content="",
                tool_calls=[{"id": "tc-2", "name": "write", "args": {}}],
            ),
        ]
        dangling, call_ids = collect_dangling(events)
        assert dangling == {"tc-2"}
        assert call_ids == {"tc-1"}

    def test_detect_dangling_uses_collect_dangling(self):
        """detect_dangling 委托 collect_dangling 并返回 sorted list。"""
        events = [
            _event(0, SESSION_STARTED),
            _event(1, TOOL_CALL, tool_call_id="tc-b", tool_name="read", args={}),
            _event(2, TOOL_CALL, tool_call_id="tc-a", tool_name="read", args={}),
        ]
        result = detect_dangling(events)
        assert result == ["tc-a", "tc-b"]
