"""集中 SessionEvent → AgentEvent 映射函数的单元测试。

为什么单独测映射函数（不只靠 run_stream 端到端）：
- 映射是事件流契约的单一构造点；字段演进只在这里改一次。
- 任何字段漂移（如新增 agent_id、未来 time 透传）都在这里锁死，
  不靠逐个 run_stream 断言点间接验证。
"""

from __future__ import annotations

import pytest

from agent_harness.agent import AgentEvent
from agent_harness.agent.types import to_agent_event
from agent_harness.session import SessionEvent


def _make_event(**overrides) -> SessionEvent:
    defaults = {
        "seq": 7,
        "type": "model/completed",
        "session_id": "s1",
        "run_id": "r1",
        "step_id": 3,
        "data": {"content": "hi"},
    }
    return SessionEvent(**{**defaults, **overrides})


class TestToAgentEvent:
    def test_copies_all_fields(self) -> None:
        """type / data / seq / run_id / step_id 五字段全部镜像。"""
        event = _make_event()
        agent = to_agent_event(event)
        assert isinstance(agent, AgentEvent)
        assert agent.type == "model/completed"
        assert agent.data == {"content": "hi"}
        assert agent.seq == 7
        assert agent.run_id == "r1"
        assert agent.step_id == 3

    def test_none_fields_preserved(self) -> None:
        """run_id / step_id 为 None 时也正确镜像（user/message 这类事件）。"""
        event = _make_event(run_id=None, step_id=None, type="user/message", data={"content": "x"})
        agent = to_agent_event(event)
        assert agent.run_id is None
        assert agent.step_id is None
        assert agent.type == "user/message"

    def test_is_durable_consistent_with_seq(self) -> None:
        """映射后的 AgentEvent.is_durable 与 seq 保持一致。"""
        durable = to_agent_event(_make_event(seq=5))
        assert durable.is_durable is True
        # AgentEvent 默认 seq=None（流式信号），映射函数不改变这条不变量
        # （SessionEvent 永远有 seq ≥ 0，所以映射产物始终 durable）
        non_durable_manual = AgentEvent(type="model/delta", data={"delta": "x"})
        assert non_durable_manual.is_durable is False

    @pytest.mark.parametrize(
        "event_type",
        [
            "user/message",
            "run/started",
            "model/completed",
            "tool/call",
            "tool/result",
            "run/completed",
            "run/failed",
            "artifact/created",
            "context/compacted",
            "memory/degraded",
        ],
    )
    def test_all_durable_event_types_mirror(self, event_type: str) -> None:
        """每种持久化事件类型都能无差别被镜像（契约覆盖 Phase 5 全词汇表）。"""
        event = _make_event(type=event_type)
        agent = to_agent_event(event)
        assert agent.type == event_type
        assert agent.seq == 7
