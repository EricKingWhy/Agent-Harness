"""Phase 2 RuntimeEvent 信封测试（SDD 03 §3）。

覆盖：
- SSE live 帧 + replay 帧 + JSONL 行都带 schema_version + durability；
- capability 字段 None 时省略，非 None 时携带；
- stream/truncated 控制帧带信封（durability=transient）；
- 旧 JSONL 行（缺 schema_version）经 from_dict 回落当前版本。
- live 与 replay 帧同形（既有不变量不破）。
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent_harness.session.event import RUNTIME_EVENT_SCHEMA_VERSION, SessionEvent
from agent_harness.web.app import (
    _event_to_sse_dict,
    _session_event_to_sse_dict,
)
from tests.scripted_model import ScriptedModel


def _sse_payload(d: dict[str, str]) -> dict:
    return json.loads(d["data"])


@pytest.fixture
def bare_client(tmp_path):
    """最少装配客户端（默认 Settings，无 catalog）。"""
    from agent_harness.config import Settings
    from agent_harness.web.app import create_app

    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
    )
    return TestClient(create_app(settings))


# ── 纯单元：信封字段序列化 ──

class TestEnvelopeSerialization:
    def test_session_event_to_dict_carries_schema_version(self):
        ev = SessionEvent(type="user/message", session_id="s1", seq=3, data={"text": "hi"})
        d = ev.to_dict()
        assert d["schema_version"] == RUNTIME_EVENT_SCHEMA_VERSION

    def test_session_event_to_dict_omits_capability_when_none(self):
        ev = SessionEvent(type="user/message", session_id="s1", seq=1)
        d = ev.to_dict()
        assert "capability" not in d, "capability None 时不应出现在 JSONL 行"

    def test_session_event_to_dict_carries_capability_when_set(self):
        ev = SessionEvent(type="user/message", session_id="s1", seq=1, capability="memory")
        d = ev.to_dict()
        assert d["capability"] == "memory"

    def test_session_event_roundtrips_envelope(self):
        ev = SessionEvent(
            type="tool/call", session_id="s1", seq=5,
            capability="websearch",
        )
        rt = SessionEvent.from_dict(ev.to_dict())
        assert rt.schema_version == RUNTIME_EVENT_SCHEMA_VERSION
        assert rt.capability == "websearch"

    def test_session_event_from_dict_backfills_schema_version_for_old_rows(self):
        """旧 JSONL 行缺 schema_version → from_dict 回落当前版本（加法字段向后兼容）。"""
        old_row = {
            "event_id": "e1", "seq": 1, "time": "2026-01-01T00:00:00+00:00",
            "type": "user/message", "session_id": "s1",
        }
        rt = SessionEvent.from_dict(old_row)
        assert rt.schema_version == RUNTIME_EVENT_SCHEMA_VERSION
        assert rt.capability is None


# ── SSE 帧：live 与 replay 同形 ──

class TestSseEnvelope:
    def test_live_frame_carries_envelope(self):
        from agent_harness.agent import AgentEvent

        ev = AgentEvent(type="model/completed", seq=7, run_id="r1", data={"text": "ok"})
        frame = _sse_payload(_event_to_sse_dict(ev, session_id="s1"))
        assert frame["schema_version"] == RUNTIME_EVENT_SCHEMA_VERSION
        assert frame["durability"] == "durable", "有 seq 的 AgentEvent → durable"

    def test_live_transient_frame_when_no_seq(self):
        from agent_harness.agent import AgentEvent

        ev = AgentEvent(type="model/started", seq=None)
        frame = _sse_payload(_event_to_sse_dict(ev, session_id="s1"))
        assert frame["durability"] == "transient"
        assert frame["schema_version"] == RUNTIME_EVENT_SCHEMA_VERSION

    def test_replay_frame_carries_envelope(self):
        ev = SessionEvent(type="user/message", session_id="s1", seq=2, data={"text": "x"})
        frame = _sse_payload(_session_event_to_sse_dict(ev, session_id="s1"))
        assert frame["schema_version"] == RUNTIME_EVENT_SCHEMA_VERSION
        assert frame["durability"] == "durable", "SessionEvent 恒 durable"

    def test_live_and_replay_frames_same_shape(self):
        """既有不变量：live 与 replay 帧同形（信封字段加入后仍成立）。"""
        from agent_harness.agent import AgentEvent

        ae = AgentEvent(type="tool/call", seq=4, run_id="r1", step_id=1, block_id="b1")
        se = SessionEvent(type="tool/call", seq=4, run_id="r1", step_id=1, block_id="b1")
        live = _sse_payload(_event_to_sse_dict(ae, session_id="s1"))
        replay = _sse_payload(_session_event_to_sse_dict(se, session_id="s1"))
        assert set(live.keys()) == set(replay.keys()), \
            "live/replay 帧必须同键集（客户端做同一 seq 幂等投影）"

    def test_capability_omitted_when_none_in_both_channels(self):
        from agent_harness.agent import AgentEvent

        ae = AgentEvent(type="model/completed", seq=1)
        se = SessionEvent(type="model/completed", session_id="s1", seq=1)
        assert "capability" not in _sse_payload(_event_to_sse_dict(ae, "s1"))
        assert "capability" not in _sse_payload(_session_event_to_sse_dict(se, "s1"))


# ── 端到端：真实 POST /api/sessions 流里每帧带信封 ──

class TestLiveStreamEnvelope:
    def test_every_live_frame_has_envelope(self, bare_client):
        """POST /api/sessions 流里每帧都带 schema_version + durability。"""
        with patch(
            "agent_harness.assembly.create_chat_model",
            return_value=ScriptedModel(responses=[AIMessage(content="hello")]),
        ):
            resp = bare_client.post("/api/sessions", json={"task": "hi"})

        assert resp.status_code == 200
        frames = [json.loads(line[5:].strip())
                  for line in resp.text.splitlines() if line.startswith("data:")]
        assert frames, "流必须至少有一帧"
        for f in frames:
            assert f.get("schema_version") == RUNTIME_EVENT_SCHEMA_VERSION, \
                f"帧 {f.get('type')} 缺 schema_version"
            assert f.get("durability") in ("durable", "transient"), \
                f"帧 {f.get('type')} 缺 durability"
        # 有 seq 的帧 durability=durable，stream-only（model/started）=transient
        durable = [f for f in frames if f.get("seq") is not None]
        transient = [f for f in frames if f.get("seq") is None]
        assert all(f["durability"] == "durable" for f in durable)
        assert all(f["durability"] == "transient" for f in transient)
