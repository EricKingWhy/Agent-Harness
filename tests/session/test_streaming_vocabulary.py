"""Streaming UI 事件词汇 + block_id 信封基座（ADR-0016 决策二，T1）。

语义修订（ADR-0016 §3.1，对 Phase 9 不变量 #4 的有意扩展）：
- 合帧文本增量以新类型 text/delta 落盘（durable；model/delta 词汇保留 stream-only，
  运行时不再发射；规格 02 §9.2 "meaningful raw/coalesced runtime chunks"）；
- 新增 reasoning 事件族（reasoning/started|delta|completed|interrupted）与
  `tool/output_delta`（工具输出增量，channel 保真）；
- `model/started` 保持 stream-only（活跃信号，重放由首个 delta 隐含）。
"""

from __future__ import annotations

import json

from agent_harness.session import (
    EVENT_TYPES,
    MODEL_DELTA,
    MODEL_STARTED,
    STREAM_ONLY_TYPES,
    TEXT_DELTA,
    Session,
    SessionEvent,
)
from agent_harness.session.store import JsonlSessionStore


class TestStreamingVocabulary:
    def test_reasoning_family_is_durable(self):
        from agent_harness.session import (
            REASONING_COMPLETED,
            REASONING_DELTA,
            REASONING_INTERRUPTED,
            REASONING_STARTED,
        )

        assert REASONING_STARTED == "reasoning/started"
        assert REASONING_DELTA == "reasoning/delta"
        assert REASONING_COMPLETED == "reasoning/completed"
        assert REASONING_INTERRUPTED == "reasoning/interrupted"
        assert {REASONING_STARTED, REASONING_DELTA, REASONING_COMPLETED,
                REASONING_INTERRUPTED} <= EVENT_TYPES
        assert not {REASONING_STARTED, REASONING_DELTA, REASONING_COMPLETED,
                    REASONING_INTERRUPTED} & STREAM_ONLY_TYPES

    def test_tool_output_delta_is_durable(self):
        from agent_harness.session import TOOL_OUTPUT_DELTA

        assert TOOL_OUTPUT_DELTA == "tool/output_delta"
        assert TOOL_OUTPUT_DELTA in EVENT_TYPES
        assert TOOL_OUTPUT_DELTA not in STREAM_ONLY_TYPES

    def test_text_delta_is_durable_model_delta_stays_stream_only(self):
        """ADR-0016 §3.1：合帧文本增量 = 新类型 text/delta（durable）；
        协作约束（Phase 14 并行）下 MODEL_DELTA 词汇原样保留 stream-only，
        运行时不再发射。model/started 仍是活跃信号。"""
        from agent_harness.session import TEXT_DELTA

        assert TEXT_DELTA == "text/delta"
        assert TEXT_DELTA in EVENT_TYPES
        assert TEXT_DELTA not in STREAM_ONLY_TYPES
        assert MODEL_DELTA in STREAM_ONLY_TYPES
        assert MODEL_DELTA not in EVENT_TYPES
        assert MODEL_STARTED in STREAM_ONLY_TYPES
        assert MODEL_STARTED not in EVENT_TYPES


class TestAppendStreamingEvents:
    def test_append_accepts_text_delta(self, tmp_path):
        store = JsonlSessionStore(root=tmp_path / "sessions")
        session = Session.start(store)
        event = session.append(TEXT_DELTA, {"delta": "你好"})
        assert event.seq == session.next_seq - 1
        assert store.read_events(session.session_id)[-1].type == TEXT_DELTA

    def test_append_rejects_model_started(self, tmp_path):
        store = JsonlSessionStore(root=tmp_path / "sessions")
        session = Session.start(store)
        try:
            session.append(MODEL_STARTED, {"step": 1})
        except ValueError:
            return
        raise AssertionError("model/started 必须仍被拒绝持久化")


class TestBlockIdEnvelope:
    def test_block_id_round_trip(self):
        event = SessionEvent(
            seq=3, type="reasoning/delta", session_id="s1",
            block_id="rsn-1-0", data={"delta": "思考", "source": "model"},
        )
        raw = json.loads(json.dumps(event.to_dict(), ensure_ascii=False))
        assert raw["block_id"] == "rsn-1-0"
        restored = SessionEvent.from_dict(raw)
        assert restored.block_id == "rsn-1-0"

    def test_block_id_omitted_when_none(self):
        event = SessionEvent(seq=1, type="user/message", session_id="s1")
        assert "block_id" not in event.to_dict()
        assert SessionEvent.from_dict(event.to_dict()).block_id is None
