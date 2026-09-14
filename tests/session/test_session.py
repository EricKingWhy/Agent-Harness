"""Ticket C — Session 聚合根生命周期契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.session import (
    DANGLING_TOOL_CONTENT,
    MODEL_COMPLETED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    SESSION_RESUMED,
    SESSION_STARTED,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
)
from agent_harness.session.errors import SessionNotFound


@pytest.fixture
def store(tmp_path: Path) -> JsonlSessionStore:
    return JsonlSessionStore(root=tmp_path)


# ── start ──


class TestSessionStart:
    def test_start_creates_session_with_started_event(self, store: JsonlSessionStore):
        session = Session.start(store)
        assert session.session_id  # UUID 自动生成
        events = session.events
        assert len(events) == 1
        assert events[0].type == SESSION_STARTED
        assert events[0].session_id == session.session_id
        assert events[0].seq == 0

    def test_start_writes_to_disk(self, store: JsonlSessionStore):
        session = Session.start(store, agent_id="test-agent")
        # 从磁盘重新加载
        loaded = store.read_events(session.session_id)
        assert len(loaded) == 1
        assert loaded[0].type == SESSION_STARTED
        assert loaded[0].agent_id == "test-agent"

    def test_start_assigns_incremental_seq(self, store: JsonlSessionStore):
        session = Session.start(store)
        session.append(USER_MESSAGE, {"content": "hello"})
        session.append(MODEL_COMPLETED, {"content": "hi back"})
        seqs = [e.seq for e in session.events]
        assert seqs == [0, 1, 2]


# ── append ──


class TestSessionAppend:
    def test_append_returns_event_with_correct_seq(self, store: JsonlSessionStore):
        session = Session.start(store)
        event = session.append(USER_MESSAGE, {"content": "test"})
        assert event.seq == 1  # start 占了 seq 0
        assert event.type == USER_MESSAGE
        assert event.data == {"content": "test"}

    def test_append_syncs_memory_and_disk(self, store: JsonlSessionStore):
        session = Session.start(store)
        session.append(USER_MESSAGE, {"content": "msg1"})
        # 内存
        assert len(session.events) == 2
        # 磁盘
        disk_events = store.read_events(session.session_id)
        assert len(disk_events) == 2
        assert disk_events[1].type == USER_MESSAGE

    def test_append_with_run_id_and_step_id(self, store: JsonlSessionStore):
        session = Session.start(store)
        session.append(
            MODEL_COMPLETED,
            {"content": "response"},
            run_id="r1",
            step_id=3,
        )
        last = session.events[-1]
        assert last.run_id == "r1"
        assert last.step_id == 3


# ── derive_messages ──


class TestSessionDeriveMessages:
    def test_derive_after_append_sequence(self, store: JsonlSessionStore):
        session = Session.start(store)
        session.append(USER_MESSAGE, {"content": "你好"})
        session.append(MODEL_COMPLETED, {"content": "你好！"})

        messages = session.derive_messages()
        # session/started 不投影成 message，只有 user + model
        assert len(messages) == 2
        assert messages[0].content == "你好"
        assert messages[1].content == "你好！"


# ── resume ──


class TestSessionResume:
    def test_resume_loads_events_and_appends_resumed(self, store: JsonlSessionStore):
        # 先创建并写入若干事件
        s1 = Session.start(store)
        s1.append(USER_MESSAGE, {"content": "first"})
        s1.append(MODEL_COMPLETED, {"content": "reply"})
        sid = s1.session_id

        # 重新加载
        s2 = Session.resume(store, sid)
        assert s2.session_id == sid
        # start + user + model + resumed = 4
        assert len(s2.events) == 4
        assert s2.events[-1].type == SESSION_RESUMED

    def test_resume_derive_matches_original(self, store: JsonlSessionStore):
        s1 = Session.start(store)
        s1.append(USER_MESSAGE, {"content": "hello"})
        s1.append(MODEL_COMPLETED, {"content": "world"})
        original_messages = s1.derive_messages()

        s2 = Session.resume(store, s1.session_id)
        resumed_messages = s2.derive_messages()
        # resumed 后只多了 session/resumed 事件，不影响消息投影
        assert len(resumed_messages) == len(original_messages)
        assert [m.content for m in resumed_messages] == [
            m.content for m in original_messages
        ]

    def test_resume_nonexistent_session_raises(self, store: JsonlSessionStore):
        # 类型化领域异常（BUG-011）：不再是裸 ValueError——web 层据此翻译成 404，
        # 不再需要 `except ValueError → SessionNotFound` 这种一刀切。
        with pytest.raises(SessionNotFound, match="不存在"):
            Session.resume(store, "fake-session-id")

    def test_resume_repair_dangling_tool_call(self, store: JsonlSessionStore):
        """有 tool/call 无 tool/result → resume 时追加合成 tool/result。"""
        s1 = Session.start(store)
        s1.append(USER_MESSAGE, {"content": "算一下"})
        s1.append(
            MODEL_COMPLETED,
            {
                "content": "算",
                "tool_calls": [{"id": "tc1", "name": "add", "args": {}}],
            },
        )
        s1.append(TOOL_CALL, {"tool_call_id": "tc1", "tool_name": "add", "args": {}})
        # 没有 tool/result——模拟崩溃

        s2 = Session.resume(store, s1.session_id)
        # resume 后应有合成 tool/result
        events_after = s2.events
        tool_results = [e for e in events_after if e.type == TOOL_RESULT]
        assert len(tool_results) == 1
        assert tool_results[0].data["tool_call_id"] == "tc1"
        assert tool_results[0].data["content"] == DANGLING_TOOL_CONTENT
        assert tool_results[0].data.get("dangling") is True

        # derive_messages 现在不该再有 dangling（已被修复）
        messages = s2.derive_messages()
        tool_msgs = [m for m in messages if hasattr(m, "tool_call_id")]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].content == DANGLING_TOOL_CONTENT


# ── Run 生命周期 ──


class TestRunLifecycle:
    def test_begin_run_returns_run_id_and_writes_event(self, store: JsonlSessionStore):
        session = Session.start(store)
        run_id, _ = session.begin_run()
        assert run_id  # UUID
        last = session.events[-1]
        assert last.type == RUN_STARTED
        assert last.run_id == run_id

    def test_begin_run_increments_turn_index(self, store: JsonlSessionStore):
        """T9 #139：每个 run 的 turn_index 递增（1-based）。"""
        session = Session.start(store)
        session.begin_run()
        assert session.events[-1].data["turn_index"] == 1
        session.end_run(session.events[-1].run_id, status="completed", final_text="ok")
        session.begin_run()
        assert session.events[-1].data["turn_index"] == 2
        session.end_run(session.events[-1].run_id, status="completed", final_text="ok2")
        session.begin_run()
        assert session.events[-1].data["turn_index"] == 3

    def test_end_run_completed(self, store: JsonlSessionStore):
        session = Session.start(store)
        run_id, _ = session.begin_run()
        session.append(USER_MESSAGE, {"content": "test"})
        session.end_run(run_id, status="completed", final_text="done")

        last = session.events[-1]
        assert last.type == RUN_COMPLETED
        assert last.run_id == run_id
        assert last.data.get("final_text") == "done"

    def test_end_run_failed(self, store: JsonlSessionStore):
        session = Session.start(store)
        run_id, _ = session.begin_run()
        session.end_run(run_id, status="failed")

        last = session.events[-1]
        assert last.type == RUN_FAILED
        assert last.run_id == run_id

    # ── trace_id / trace_url 契约（trace_url 契约：并列字段，对称终态） ──

    def test_end_run_completed_persists_trace_id_and_trace_url(self, store: JsonlSessionStore):
        session = Session.start(store)
        run_id, _ = session.begin_run()
        session.end_run(
            run_id, status="completed", final_text="done",
            trace_id="tr-001", trace_url="https://lf.example/traces/tr-001",
        )

        last = session.events[-1]
        assert last.data.get("trace_id") == "tr-001"
        assert last.data.get("trace_url") == "https://lf.example/traces/tr-001"

    def test_end_run_failed_symmetrically_persists_trace_id_and_trace_url(
        self, store: JsonlSessionStore,
    ):
        """失败 run 也下发 trace_id / trace_url（契约对称决策：失败 trace 在
        Langfuse 也有排查价值）。补既有 bug：failed 分支此前丢弃了 trace_id。"""
        session = Session.start(store)
        run_id, _ = session.begin_run()
        session.end_run(
            run_id, status="failed", reason="boom",
            trace_id="tr-failed", trace_url="https://lf.example/traces/tr-failed",
        )

        last = session.events[-1]
        assert last.data.get("trace_id") == "tr-failed"
        assert last.data.get("trace_url") == "https://lf.example/traces/tr-failed"
        assert last.data.get("reason") == "boom"

    def test_end_run_trace_fields_null_when_not_provided(self, store: JsonlSessionStore):
        """trace_id / trace_url 键恒存在（前端契约据此降级显示）；未追踪 = null，
        不伪造占位字符串（保持 None 语义；与既有 completed 的 cost_usd 同款）。"""
        session = Session.start(store)
        run_id, _ = session.begin_run()
        session.end_run(run_id, status="completed", final_text="done")

        last = session.events[-1]
        assert "trace_id" in last.data
        assert last.data["trace_id"] is None
        assert "trace_url" in last.data
        assert last.data["trace_url"] is None


# ── next_seq ──


class TestNextSeq:
    def test_next_seq_empty_events(self, store: JsonlSessionStore):
        session = Session("s1", store, events=[])
        assert session.next_seq == 0

    def test_next_seq_after_appends(self, store: JsonlSessionStore):
        session = Session.start(store)  # seq 0
        session.append(USER_MESSAGE, {"content": "a"})  # seq 1
        session.append(MODEL_COMPLETED, {"content": "b"})  # seq 2
        assert session.next_seq == 3


# ── mark / since：Session 拥有"自 X 之后追加的事件"句柄（A1 深化）──


class TestMarkAndSince:
    def test_mark_and_since_roundtrip(self, store: JsonlSessionStore):
        session = Session.start(store)
        marker = session.mark()
        session.append(USER_MESSAGE, {"content": "a"})
        session.append(MODEL_COMPLETED, {"content": "b"})
        fresh = session.since(marker)
        assert [e.type for e in fresh] == [USER_MESSAGE, MODEL_COMPLETED]

    def test_since_before_any_append_is_empty(self, store: JsonlSessionStore):
        session = Session.start(store)
        assert session.since(session.mark()) == []

    def test_since_returns_copy_not_internal_list(self, store: JsonlSessionStore):
        session = Session.start(store)
        marker = session.mark()
        session.append(USER_MESSAGE, {"content": "a"})
        fresh = session.since(marker)
        fresh.clear()
        assert len(session.since(marker)) == 1
