"""Ticket A — SessionEvent DTO + JsonlSessionStore 契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.session import (
    EVENT_TYPES,
    MODEL_COMPLETED,
    SESSION_STARTED,
    TOOL_CALL,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
    SessionEvent,
)
from agent_harness.session.errors import SeqConflict

# ── SessionEvent DTO ──


class TestSessionEventDTO:
    def test_default_fields_populate(self):
        event = SessionEvent(type=SESSION_STARTED, session_id="s1")
        assert event.event_id  # UUID 自动生成
        assert event.seq == 0
        assert event.time  # ISO 时间戳自动生成
        assert event.type == SESSION_STARTED
        assert event.session_id == "s1"
        assert event.run_id is None
        assert event.agent_id is None
        assert event.step_id is None
        assert event.data == {}
        assert event.source_event_ids is None

    def test_all_event_types_registered(self):
        # Durable vocabulary — Phase 1 基础 + Phase 9 model/completed-failed + tool/*
        # + Phase 4 operation/reconcile-required (#30) + Phase 5 artifact/created (#47) + context/compacted
        # + Phase 12/13 reliability & delegation + ADR-0016 streaming（text/delta 合帧
        # 文本增量、reasoning 族、tool/output_delta）。model/started + model/delta
        # 词汇保留 STREAM_ONLY（后者运行时不再发射）。
        expected = {
            "session/started",
            "session/resumed",
            "session/forked",
            "run/started",
            "run/completed",
            "run/failed",
            "run/interrupted",
            "user/message",
            "text/delta",
            "model/completed",
            "model/failed",
            "tool/call",
            "tool/result",
            "tool/output_delta",
            "operation/reconcile-required",
            "artifact/created",
            "artifact/externalized",
            "context/compacted",
            "memory/degraded",
            "tool/failure-guard",
            "model/fallback",
            "agent/delegation-started",
            "agent/delegation-finished",
            "reasoning/started",
            "reasoning/delta",
            "reasoning/completed",
            "reasoning/interrupted",
            "tool/approval-requested",
            "permission/resolved",
            # Phase Multiturn T2 (#132)：续聊队列 + steer 引导（PRD §6）
            "message/queued",
            "queue/cancelled",
            "steer/requested",
            "steer/applied",
            # Phase Multiturn T4 (#134)：dsh 4-event compaction bracket
            "compaction/start",
            "compaction/end",
            # Phase Multiturn T7 (#137)：同 session 内模型切换
            "model/changed",
        }
        assert EVENT_TYPES == expected

    def test_to_dict_omits_none_fields(self):
        event = SessionEvent(seq=1, type=SESSION_STARTED, session_id="s1")
        d = event.to_dict()
        assert "run_id" not in d
        assert "agent_id" not in d
        assert "step_id" not in d
        assert "source_event_ids" not in d
        assert "data" not in d  # 空 dict 也省略
        assert d["seq"] == 1
        assert d["type"] == "session/started"

    def test_to_dict_includes_populated_optional_fields(self):
        event = SessionEvent(
            seq=2,
            type=TOOL_CALL,
            session_id="s1",
            run_id="r1",
            agent_id="default",
            step_id=1,
            data={"command": "ls"},
            source_event_ids=["evt-prev"],
        )
        d = event.to_dict()
        assert d["run_id"] == "r1"
        assert d["agent_id"] == "default"
        assert d["step_id"] == 1
        assert d["data"] == {"command": "ls"}
        assert d["source_event_ids"] == ["evt-prev"]

    def test_from_dict_roundtrip(self):
        original = SessionEvent(
            seq=3,
            type=MODEL_COMPLETED,
            session_id="s1",
            run_id="r1",
            data={"content": "hello"},
        )
        reconstructed = SessionEvent.from_dict(original.to_dict())
        assert reconstructed.seq == original.seq
        assert reconstructed.type == original.type
        assert reconstructed.session_id == original.session_id
        assert reconstructed.run_id == original.run_id
        assert reconstructed.data == original.data
        assert reconstructed.event_id == original.event_id

    def test_frozen_dataclass_is_immutable(self):
        event = SessionEvent(type=SESSION_STARTED, session_id="s1")
        with pytest.raises(AttributeError):
            event.seq = 99  # type: ignore[misc]


# ── JsonlSessionStore ──


class TestJsonlSessionStore:
    def test_append_and_read_roundtrip(self, tmp_path: Path):
        store = JsonlSessionStore(root=tmp_path)
        sid = "session-001"

        events = [
            SessionEvent(seq=0, type=SESSION_STARTED, session_id=sid),
            SessionEvent(seq=1, type=MODEL_COMPLETED, session_id=sid, data={"content": "hi"}),
        ]
        for e in events:
            store.append_event(sid, e)

        loaded = store.read_events(sid)
        assert len(loaded) == 2
        assert loaded[0].seq == 0
        assert loaded[0].type == "session/started"
        assert loaded[1].seq == 1
        assert loaded[1].type == "model/completed"
        assert loaded[1].data == {"content": "hi"}

    def test_read_nonexistent_session_returns_empty(self, tmp_path: Path):
        store = JsonlSessionStore(root=tmp_path)
        assert store.read_events("never-existed") == []

    def test_half_line_is_skipped(self, tmp_path: Path):
        """崩溃安全：半行 JSON（写入被中断）读取时跳过，不影响其它行。"""
        store = JsonlSessionStore(root=tmp_path)
        sid = "crash-test"
        path = store._events_path(sid)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 手写：一行完整 + 一行半截 + 一行完整
        good1 = SessionEvent(seq=0, type=SESSION_STARTED, session_id=sid)
        good2 = SessionEvent(seq=2, type=MODEL_COMPLETED, session_id=sid)

        import json

        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(good1.to_dict(), ensure_ascii=False) + "\n")
            fh.write('{"seq": 1, "type": "model/completed", "session_i')  # 半行，无换行
            fh.write("\n")
            fh.write(json.dumps(good2.to_dict(), ensure_ascii=False) + "\n")

        loaded = store.read_events(sid)
        assert len(loaded) == 2  # 半行被跳过
        assert loaded[0].seq == 0
        assert loaded[1].seq == 2

    def test_blank_lines_are_skipped(self, tmp_path: Path):
        store = JsonlSessionStore(root=tmp_path)
        sid = "blank-test"
        path = store._events_path(sid)
        path.parent.mkdir(parents=True, exist_ok=True)

        event = SessionEvent(seq=0, type=SESSION_STARTED, session_id=sid)
        import json

        with path.open("w", encoding="utf-8") as fh:
            fh.write("\n")  # 前导空行
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            fh.write("   \n")  # 空白行
            fh.write("\n")  # 尾随空行

        loaded = store.read_events(sid)
        assert len(loaded) == 1
        assert loaded[0].seq == 0

    def test_seq_ordering_preserved_as_written(self, tmp_path: Path):
        store = JsonlSessionStore(root=tmp_path)
        sid = "order-test"

        for seq in range(5):
            store.append_event(sid, SessionEvent(seq=seq, type=USER_MESSAGE if seq % 2 else SESSION_STARTED, session_id=sid))

        loaded = store.read_events(sid)
        assert [e.seq for e in loaded] == [0, 1, 2, 3, 4]

    def test_multiple_sessions_isolated(self, tmp_path: Path):
        store = JsonlSessionStore(root=tmp_path)

        store.append_event("s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1"))
        store.append_event("s2", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s2"))
        store.append_event("s1", SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1"))

        assert len(store.read_events("s1")) == 2
        assert len(store.read_events("s2")) == 1


class TestSeqMonotonicityGuard:
    """append-only 的 seq 守卫：重复 / 回退 seq 只能拒写，不能落盘（BUG-011）。

    两个写者各自基于同一份快照取号时，后一个的 seq 会 ≤ 已落盘最大 seq。真机会话
    `dd983104` 就是这么坏的：两条 seq=5 → 任何构造 Session 聚合的路径（load/resume）
    永久失败 → 续聊恒 404（`Send failed: 404`）。规格要求 seq 在单 Session 内严格
    单调（`03_SESSION_EVENT_MODEL.md` §2），故契约是「拒写 + SeqConflict」，而不是
    把重复 seq 静默写进日志。
    """

    def test_duplicate_seq_is_rejected_without_writing(self, tmp_path: Path):
        store = JsonlSessionStore(root=tmp_path)
        store.append_event("s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1"))

        with pytest.raises(SeqConflict):
            store.append_event("s1", SessionEvent(seq=0, type=USER_MESSAGE, session_id="s1"))

        assert [e.seq for e in store.read_events("s1")] == [0], "重复 seq 被写进了日志"

    def test_regressed_seq_is_rejected(self, tmp_path: Path):
        store = JsonlSessionStore(root=tmp_path)
        store.append_event("s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1"))
        store.append_event("s1", SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1"))

        with pytest.raises(SeqConflict):
            store.append_event("s1", SessionEvent(seq=0, type=USER_MESSAGE, session_id="s1"))

        assert [e.seq for e in store.read_events("s1")] == [0, 1]

    def test_sequential_appends_still_pass(self, tmp_path: Path):
        """正向：max+1 正常通过——守卫不得拦住正常追加。"""
        store = JsonlSessionStore(root=tmp_path)
        store.append_event("s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1"))
        store.append_event("s1", SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1"))

        assert [e.seq for e in store.read_events("s1")] == [0, 1]

    def test_fresh_store_instance_takes_disk_as_truth(self, tmp_path: Path):
        """新实例（新进程）必须重新以磁盘为准——进程内缓存不能替磁盘说话。"""
        JsonlSessionStore(root=tmp_path).append_event(
            "s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1")
        )
        other = JsonlSessionStore(root=tmp_path)

        with pytest.raises(SeqConflict):
            other.append_event("s1", SessionEvent(seq=0, type=USER_MESSAGE, session_id="s1"))

    def test_external_append_invalidates_cached_last_seq(self, tmp_path: Path):
        """另一实例先追加 seq=1：本实例缓存陈旧（0），也必须拦住撞号的 seq=1。

        缓存只能加速，不能替磁盘判「这个 seq 还空着」。CLI 与 server 共用同一
        `settings.workspace_dir/sessions`，缓存缝隙漏进来的就是重复 seq。
        """
        store = JsonlSessionStore(root=tmp_path)
        store.append_event("s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1"))
        JsonlSessionStore(root=tmp_path).append_event(
            "s1", SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1")
        )

        with pytest.raises(SeqConflict):
            store.append_event("s1", SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1"))

        assert [e.seq for e in store.read_events("s1")] == [0, 1]

    def test_seq_after_external_append_is_accepted(self, tmp_path: Path):
        """同上场景的放行侧：外部追加 seq=1 后，本实例追 seq=2 必须成功。"""
        store = JsonlSessionStore(root=tmp_path)
        store.append_event("s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1"))
        JsonlSessionStore(root=tmp_path).append_event(
            "s1", SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1")
        )

        store.append_event("s1", SessionEvent(seq=2, type=USER_MESSAGE, session_id="s1"))

        assert [e.seq for e in store.read_events("s1")] == [0, 1, 2]

    def test_guard_does_not_leak_between_sessions(self, tmp_path: Path):
        """每会话独立：s2 的 seq 不受 s1 进度影响。"""
        store = JsonlSessionStore(root=tmp_path)
        store.append_event("s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1"))
        store.append_event("s1", SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1"))

        store.append_event("s2", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s2"))

        assert len(store.read_events("s1")) == 2
        assert len(store.read_events("s2")) == 1

    def test_append_event_is_mutually_exclusive_per_session(self, tmp_path: Path):
        """守卫的「读已落盘最大 seq → 判定 → 写」必须在同一临界区内。

        没有这把锁，两个线程可能都读到同一 last_seq、都通过判定、都落盘——守卫
        本身就不是原子的（这是 BUG-011 修复里锁承重的原因）。直接验证互斥：
        持锁期间另一个线程的 append 不得完成；释放后正常完成。
        """
        import threading

        store = JsonlSessionStore(root=tmp_path)
        store.append_event("s1", SessionEvent(seq=0, type=SESSION_STARTED, session_id="s1"))
        started = threading.Event()
        done = threading.Event()

        def worker() -> None:
            started.set()
            store.append_event("s1", SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1"))
            done.set()

        lock = store._lock_for("s1")
        lock.acquire()
        try:
            thread = threading.Thread(target=worker)
            thread.start()
            assert started.wait(timeout=5), "工作线程未启动"
            assert not done.wait(timeout=0.3), "append 未持锁：检查与写入之间有窗口"
            assert [e.seq for e in store.read_events("s1")] == [0], "被锁挡住却已落盘"
        finally:
            lock.release()
        assert done.wait(timeout=5), "释放锁后 append 未完成"
        assert [e.seq for e in store.read_events("s1")] == [0, 1]


def test_append_event_fsyncs_for_power_loss_durability(tmp_path, monkeypatch):
    """断电不丢（用户决策 D9→实施）：append 必须落 os.fsync，不只是 flush。

    flush 只保证进程内缓冲进 OS page cache——断电时 page cache 丢失，
    已"成功"的事件消失。fsync 把数据真正压到磁盘。
    """
    import os as _os

    store = JsonlSessionStore(root=tmp_path)
    fsynced: list[int] = []
    real_fsync = _os.fsync
    monkeypatch.setattr(_os, "fsync", lambda fd: (fsynced.append(fd), real_fsync(fd))[1])

    session = Session.start(store)
    session.append(USER_MESSAGE, {"content": "hi"})

    assert fsynced, "append_event 未调用 os.fsync"
    events = store.read_events(session.session_id)
    assert events[-1].type == USER_MESSAGE
