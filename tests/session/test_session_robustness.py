"""Session 健壮性契约测试——append 词汇表校验、损坏行容错、增量 seq 计数器。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_harness.session import (
    MODEL_DELTA,
    MODEL_STARTED,
    SESSION_RESUMED,
    SESSION_STARTED,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
    SessionEvent,
)
from agent_harness.session.errors import SeqConflict


@pytest.fixture
def store(tmp_path: Path) -> JsonlSessionStore:
    return JsonlSessionStore(root=tmp_path)


# ── append 词汇表校验（invariant #4：Event ≠ Diagnostic Log）──


class TestAppendVocabularyValidation:
    def test_append_rejects_stream_only_types(self, store: JsonlSessionStore):
        """model/started、model/delta 是流式专属词汇，Session.append 必须拒绝持久化。

        ADR-0016 §3.1：合帧文本增量由新类型 text/delta 承接（durable）；
        model/delta 词汇原样保留 stream-only（运行时不再发射）。
        """
        session = Session.start(store)
        with pytest.raises(ValueError, match=MODEL_STARTED):
            session.append(MODEL_STARTED, {"model": "test-model"})
        with pytest.raises(ValueError, match=MODEL_DELTA):
            session.append(MODEL_DELTA, {"delta": "x"})

    def test_append_rejects_unknown_type(self, store: JsonlSessionStore):
        """未知事件类型（不在 EVENT_TYPES 词汇表）必须拒绝，防止拼写错误悄悄落盘。"""
        session = Session.start(store)
        with pytest.raises(ValueError, match="bogus/type"):
            session.append("bogus/type", {"content": "oops"})

    def test_rejected_append_persists_nothing(self, store: JsonlSessionStore):
        """被拒绝的 append 不得写入任何内容（先校验后写盘）。"""
        session = Session.start(store)
        with pytest.raises(ValueError):
            session.append(MODEL_DELTA, {"delta": "x"})
        # 磁盘上只有 session/started 一条
        assert len(store.read_events(session.session_id)) == 1
        assert session.next_seq == 1

    def test_append_valid_type_still_works(self, store: JsonlSessionStore):
        """合法持久化类型不受校验影响。"""
        session = Session.start(store)
        event = session.append(USER_MESSAGE, {"content": "hello"})
        assert event.type == USER_MESSAGE
        assert event.seq == 1
        assert len(store.read_events(session.session_id)) == 2


# ── read_events 损坏行容错（一行坏数据不能拖垮整个 session）──


def _good_line(sid: str, seq: int, event_type: str = SESSION_STARTED) -> bytes:
    event = SessionEvent(seq=seq, type=event_type, session_id=sid)
    return json.dumps(event.to_dict(), ensure_ascii=False).encode("utf-8") + b"\n"


def _write_events_file(
    store: JsonlSessionStore, sid: str, chunks: list[bytes]
) -> Path:
    """手写 events.jsonl（字节级）——模拟半行崩溃、非法 UTF-8 等磁盘损坏。"""
    path = store._events_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        for chunk in chunks:
            fh.write(chunk)
    return path


class TestReadEventsToleratesCorruptLines:
    def test_mixed_corrupt_lines_skip_and_keep_good_events(
        self, store: JsonlSessionStore
    ):
        """合法 JSON 但非事件字典（null / [1]）、非法 UTF-8 字节行——都按损坏行跳过。"""
        sid = "corrupt-lines"
        _write_events_file(
            store,
            sid,
            [
                _good_line(sid, 0, SESSION_STARTED),
                b"null\n",
                b"[1]\n",
                b"\xff\xfe\n",
                _good_line(sid, 1, USER_MESSAGE),
            ],
        )
        events = store.read_events(sid)
        assert [e.seq for e in events] == [0, 1]
        assert [e.type for e in events] == [SESSION_STARTED, USER_MESSAGE]

    def test_non_int_seq_line_is_skipped(self, store: JsonlSessionStore):
        """{"seq":"x"} 合法 JSON 但 seq 类型非法——跳过，避免污染 next_seq。"""
        sid = "bad-seq"
        _write_events_file(
            store,
            sid,
            [
                _good_line(sid, 0, SESSION_STARTED),
                b'{"seq":"x","type":"user/message","session_id":"bad-seq"}\n',
                _good_line(sid, 1, USER_MESSAGE),
            ],
        )
        events = store.read_events(sid)
        assert [e.seq for e in events] == [0, 1]

    def test_resume_succeeds_after_corrupt_lines(self, store: JsonlSessionStore):
        """一行坏数据不能 brick resume：坏行跳过后 Session.resume 正常，seq 从 max+1 继续。"""
        sid = "brick-resume"
        _write_events_file(
            store,
            sid,
            [
                _good_line(sid, 0, SESSION_STARTED),
                b"null\n",
                b"[1]\n",
                b"\xff\xfe\n",
                _good_line(sid, 1, USER_MESSAGE),
            ],
        )
        session = Session.resume(store, sid)
        # 2 条好事件 + session/resumed
        assert len(session.events) == 3
        assert session.events[-1].type == SESSION_RESUMED
        # 新追加事件从 max+1 继续（started=0, message=1, resumed=2 → 下一条 3）
        event = session.append(USER_MESSAGE, {"content": "after"})
        assert event.seq == 3


# ── 增量 seq 计数器（append 不做 O(n) 全量扫描；resume 一次性校验重算）──


class TestIncrementalSeqCounter:
    def test_append_500_events_seq_monotonic(self, store: JsonlSessionStore):
        """500 次追加：seq 0..499 严格单调递增，磁盘与内存一致。

        行为代理断言：O(n²)→O(1) 的复杂度变化由代码检查证明（见报告），
        此测试守住正确性——seq 分配在任何实现下都必须单调且无空洞。
        """
        session = Session.start(store)
        for i in range(499):
            session.append(USER_MESSAGE, {"content": f"msg-{i}"})
        assert session.next_seq == 500
        disk_events = store.read_events(session.session_id)
        assert [e.seq for e in disk_events] == list(range(500))
        assert [e.seq for e in session.events] == list(range(500))

    def test_resume_recomputes_counter_from_loaded_events(
        self, store: JsonlSessionStore
    ):
        """resume 时从已加载事件一次性重算计数器：新事件 seq = max+1。"""
        s1 = Session.start(store)
        for _ in range(5):
            s1.append(USER_MESSAGE, {"content": "x"})
        s2 = Session.resume(store, s1.session_id)
        # 6 条原事件 + session/resumed → 下一条 seq 7
        assert s2.next_seq == 7
        event = s2.append(USER_MESSAGE, {"content": "after-resume"})
        assert event.seq == 7

    def test_resume_rejects_seq_regression(self, store: JsonlSessionStore):
        """resume 校验 seq 严格递增：回退的损坏历史直接拒绝，不容忍。

        抛 SeqConflict（**不是** SessionNotFound）：日志存在、只是损坏——旧行为是
        裸 ValueError，被 service 一刀切翻成 404「会话不存在」（BUG-011）。
        """
        sid = "seq-regression"
        _write_events_file(
            store,
            sid,
            [
                _good_line(sid, 0, SESSION_STARTED),
                _good_line(sid, 2, USER_MESSAGE),
                _good_line(sid, 1, USER_MESSAGE),
            ],
        )
        with pytest.raises(SeqConflict, match="回退"):
            Session.resume(store, sid)

    def test_resume_rejects_duplicate_seq(self, store: JsonlSessionStore):
        """BUG-011 现场形态：重复 seq 必须被拒。

        真机会话 `dd983104` 就是两条 seq=5（模型项被双击 → 两个并发 POST /model），
        此后该会话任何续聊恒 404。这里钉住加载侧必须拒它，且错误类型是 seq 冲突。
        """
        sid = "seq-duplicate"
        _write_events_file(
            store,
            sid,
            [
                _good_line(sid, 0, SESSION_STARTED),
                _good_line(sid, 1, USER_MESSAGE),
                _good_line(sid, 1, USER_MESSAGE),
            ],
        )
        with pytest.raises(SeqConflict, match="重复"):
            Session.resume(store, sid)


def test_negative_seq_line_is_skipped(store):
    """seq 为负的行不进事件列表，也不污染计数器——好行照常读出。"""
    sid = "neg-seq"
    bad = json.loads(_good_line(sid, 1, USER_MESSAGE).decode("utf-8"))
    bad["seq"] = -5
    _write_events_file(
        store,
        sid,
        [
            _good_line(sid, 0, SESSION_STARTED),
            json.dumps(bad, ensure_ascii=False).encode("utf-8") + b"\n",
        ],
    )
    events = store.read_events(sid)
    assert [e.seq for e in events] == [0]


# ── read_session_summary：列表页快路径（perf-fix 4，损坏 fallback 保精确）──


def _write_lines(store: JsonlSessionStore, sid: str, lines: list[str]) -> None:
    path = store._events_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _event_line(store: JsonlSessionStore, sid: str, seq: int, etype: str,
                data: dict) -> str:
    return json.dumps({"seq": seq, "type": etype, "session_id": sid,
                       "time": f"2026-09-06T00:00:{seq:02d}", "data": data},
                      ensure_ascii=False, separators=(",", ":"))


class TestReadSessionSummary:
    def test_clean_session_matches_full_read(self, store: JsonlSessionStore):
        """无损坏行时：event_count/时间/首条 user 消息与全量解析严格一致。"""
        sid = "summary-clean"
        lines = [_event_line(store, sid, 0, SESSION_STARTED, {})]
        lines.append(_event_line(store, sid, 1, USER_MESSAGE,
                                 {"content": "  帮我分析项目结构  "}))
        lines.append(_event_line(store, sid, 2, "model/completed",
                                 {"content": "好", "tool_calls": []}))
        lines.append(_event_line(store, sid, 3, "tool/result",
                                 {"tool_call_id": "c1", "content": "输出"}))
        _write_lines(store, sid, lines)

        stats = store.read_session_summary(sid)
        full = store.read_events(sid)

        assert stats is not None
        assert stats.event_count == len(full) == 4
        assert stats.first_event_time == full[0].time
        assert stats.last_event_time == full[-1].time
        assert stats.first_user_message == "帮我分析项目结构"  # strip + 无截断触发

    def test_no_user_message_returns_none(self, store: JsonlSessionStore):
        sid = "summary-nouser"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "model/completed", {"content": "hi"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.first_user_message is None
        assert stats.event_count == 2

    def test_first_user_message_after_head_cap_returns_none(self, store: JsonlSessionStore):
        """user/message 出现在头部扫描上限之后 → None（前端有 events 扫描降级）。"""
        sid = "summary-deep"
        lines = [_event_line(store, sid, 0, SESSION_STARTED, {})]
        for i in range(1, 250):
            lines.append(_event_line(store, sid, i, "tool/result",
                                     {"tool_call_id": f"c{i}", "content": "x"}))
        lines.append(_event_line(store, sid, 250, USER_MESSAGE, {"content": "很晚"}))
        _write_lines(store, sid, lines)
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.first_user_message is None
        assert stats.event_count == 251

    def test_corrupt_tail_line_falls_back_to_exact(self, store: JsonlSessionStore):
        """末行半写（崩溃现场）→ 整体回退全量解析，event_count 精确排除坏行。"""
        sid = "summary-tail-corrupt"
        good = [_event_line(store, sid, i, USER_MESSAGE, {"content": f"m{i}"})
                for i in range(3)]
        _write_lines(store, sid, good + ['{"seq": 3, "type": "user/mess'])  # 半行

        stats = store.read_session_summary(sid)
        full = store.read_events(sid)

        assert stats is not None
        assert stats.event_count == len(full) == 3
        assert stats.first_user_message == "m0"
        assert stats.last_event_time == full[-1].time

    def test_corrupt_head_line_falls_back_to_exact(self, store: JsonlSessionStore):
        sid = "summary-head-corrupt"
        good = [_event_line(store, sid, i, USER_MESSAGE, {"content": f"m{i}"})
                for i in range(3)]
        _write_lines(store, sid, ["not-json"] + good)

        stats = store.read_session_summary(sid)
        full = store.read_events(sid)

        assert stats is not None
        assert stats.event_count == len(full) == 3
        assert stats.first_event_time == full[0].time

    # ── OBS-010：列表行回填最近一次 run 的 trace_id ──
    # 口径：只认**最后一个事件**、且必须是 run 终结事件（run/completed|
    # failed|interrupted）——快路径与全量回退严格一致（见 _terminal_trace_field）。

    def test_trace_id_backfilled_from_run_completed(self, store: JsonlSessionStore):
        sid = "summary-trace-completed"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, USER_MESSAGE, {"content": "hi"}),
            _event_line(store, sid, 2, "run/completed",
                        {"final_text": "ok", "trace_id": "tr-abc"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_id == "tr-abc"

    def test_trace_id_backfilled_from_run_failed(self, store: JsonlSessionStore):
        """对称终态：失败 run 在 Langfuse 也有可见 trace，同样回填。"""
        sid = "summary-trace-failed"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/failed",
                        {"final_text": "boom", "trace_id": "tr-fail"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_id == "tr-fail"

    def test_trace_id_none_when_langfuse_disabled(self, store: JsonlSessionStore):
        """Langfuse 未启用 → 终结事件 trace_id 本就是 null → 摘要 None（不伪造）。"""
        sid = "summary-trace-disabled"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/completed",
                        {"final_text": "ok", "trace_id": None}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_id is None

    def test_trace_id_none_when_terminal_is_not_last_event(self, store: JsonlSessionStore):
        """run 终态之后又落了事件（末事件非终结）→ trace_id / trace_url 都为 None。

        锁住「只看最后一个事件」的显式契约（OBS-010 有意的性能取舍）：不向历史
        回溯更早 run 的 trace，因为那要逐行解析到 EOF，会抵消 read_session_summary
        的快路径。典型触发：上一轮已 completed，新轮的 user/message 成了末事件。
        两个字段都断言是**值**断言——早先 run 的 trace_url 不得比 trace_id 多漏一个。
        """
        sid = "summary-trace-not-last"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/completed",
                        {"final_text": "ok", "trace_id": "tr-old",
                         "trace_url": "https://lf.example/trace/tr-old"}),
            _event_line(store, sid, 2, "tool/result",
                        {"tool_call_id": "c1", "content": "x"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert (stats.trace_id, stats.trace_url) == (None, None)

    def test_trace_id_none_for_non_terminal_tail_with_trace(self, store: JsonlSessionStore):
        """末事件类型非 run 终结（即便 data 里恰好有 trace_id）不得被当成 run trace。"""
        sid = "summary-trace-nonterminal"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "model/completed",
                        {"content": "ok", "trace_id": "tr-not-a-run-trace"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_id is None

    def test_trace_id_none_for_run_interrupted(self, store: JsonlSessionStore):
        """恢复扫描补记的 run/interrupted.data 无 trace_id（真实形状）→ None。

        run 崩在半途，Langfuse 没有可跳转的最终 trace；诚实返回「未追踪」。
        """
        sid = "summary-trace-interrupted"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/interrupted",
                        {"interrupted_seq": 3, "reason": "process_restart"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_id is None

    @pytest.mark.parametrize("bad_value", [123, "", None, ["tr-x"], {"id": "tr-x"}])
    def test_trace_id_non_string_is_none(self, store: JsonlSessionStore, bad_value):
        """磁盘被手工改坏成非字符串/空串 → None，不把非法值塞进 API 契约。"""
        sid = f"summary-trace-bad-{type(bad_value).__name__}"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/completed",
                        {"final_text": "ok", "trace_id": bad_value}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_id is None

    def test_trace_id_fallback_path_matches_fast_path(self, store: JsonlSessionStore):
        """头部损坏触发全量回退时，trace_id 与快路径同口径。"""
        sid = "summary-trace-fallback"
        good = [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, USER_MESSAGE, {"content": "hi"}),
            _event_line(store, sid, 2, "run/completed",
                        {"final_text": "ok", "trace_id": "tr-fallback"}),
        ]
        _write_lines(store, sid, ["not-json"] + good)

        stats = store.read_session_summary(sid)
        assert stats is not None
        # 坏行被全量路径排除（证明确实走了 fallback），trace_id 仍正确回填
        assert stats.event_count == 3
        assert stats.trace_id == "tr-fallback"

    # ── ARCH-4b：trace_url 与 trace_id 同源（同一个 run 终结事件、同一套守卫）──
    # 前端 `types.ts::SessionSummary.trace_url` 声明为非可选 `string | null`
    # （契约 2d7f87a / ADR-0018 D7），后端列表过去从不返回该键 → 运行时 undefined、
    # 违反自己声明的类型。这里锁住「同事件、同守卫」：两者只能一起出现或一起为 None。

    def test_trace_url_backfilled_from_run_completed(self, store: JsonlSessionStore):
        sid = "summary-trace-url"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/completed",
                        {"final_text": "ok", "trace_id": "tr-1",
                         "trace_url": "https://lf.example/trace/tr-1"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_url == "https://lf.example/trace/tr-1"

    def test_trace_url_and_trace_id_come_from_the_same_event(
        self, store: JsonlSessionStore
    ):
        """两者必须同源于**末**事件——早先 run 的 trace_url 不得漏进来。

        会话可以有多次 run（OBS-010 的 per-run 语义）；列表页要展示的是末端那次。
        分别取值会给出一条「id 来自末轮、url 来自上一轮」的错配行。
        """
        sid = "summary-trace-url-same-event"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/completed",
                        {"final_text": "old", "trace_id": "tr-old",
                         "trace_url": "https://lf.example/trace/tr-old"}),
            _event_line(store, sid, 2, "run/completed",
                        {"final_text": "new", "trace_id": "tr-new",
                         "trace_url": "https://lf.example/trace/tr-new"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert (stats.trace_id, stats.trace_url) == (
            "tr-new", "https://lf.example/trace/tr-new")

    def test_trace_url_none_when_langfuse_disabled(self, store: JsonlSessionStore):
        """未启用可观测性 → 终结事件两字段都是 null → 摘要都 None（不伪造，不变量 #21）。"""
        sid = "summary-trace-url-disabled"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/completed",
                        {"final_text": "ok", "trace_id": None, "trace_url": None}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert (stats.trace_id, stats.trace_url) == (None, None)

    @pytest.mark.parametrize("bad_value", [123, "", None, ["u"], {"u": "x"}])
    def test_trace_url_non_string_is_none(
        self, store: JsonlSessionStore, bad_value
    ):
        """与 trace_id 同一套守卫：非字符串/空串 → None，不塞进 API 契约。

        断言 trace_id 仍正常——两个字段的守卫互不牵连（不能一个坏值把另一个吃掉）。
        """
        sid = f"summary-trace-url-bad-{type(bad_value).__name__}"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/completed",
                        {"final_text": "ok", "trace_id": "tr-ok",
                         "trace_url": bad_value}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_url is None
        assert stats.trace_id == "tr-ok"

    def test_trace_url_none_for_run_interrupted(self, store: JsonlSessionStore):
        """恢复扫描补记的 run/interrupted 真实形状（无 trace_url 键）→ None。"""
        sid = "summary-trace-url-interrupted"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, "run/interrupted",
                        {"interrupted_seq": 3, "reason": "process_restart"}),
        ])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.trace_url is None

    def test_trace_url_fallback_path_matches_fast_path(self, store: JsonlSessionStore):
        """全量回退路径的 trace_url 与快路径同口径（头部损坏时）。"""
        sid = "summary-trace-url-fallback"
        good = [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, USER_MESSAGE, {"content": "hi"}),
            _event_line(store, sid, 2, "run/completed",
                        {"final_text": "ok", "trace_id": "tr-fb",
                         "trace_url": "https://lf.example/trace/tr-fb"}),
        ]
        _write_lines(store, sid, ["not-json"] + good)

        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.event_count == 3
        assert stats.trace_url == "https://lf.example/trace/tr-fb"

    def test_fast_path_agrees_with_full_parse_on_clean_session(
        self, store: JsonlSessionStore
    ):
        """快路径与全量回退在末事件派生的字段上同口径——契约直接可测，非靠 docstring。

        只比 event_count / last_event_time / trace_id / trace_url：first_user_message
        的头部解析上限是有意的分歧（见 test_first_user_message_after_head_cap_returns_none），
        不在本断言内。
        """
        sid = "summary-agree"
        _write_lines(store, sid, [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, USER_MESSAGE, {"content": "hi"}),
            _event_line(store, sid, 2, "run/completed",
                        {"final_text": "ok", "trace_id": "tr-agree",
                         "trace_url": "https://lf.example/trace/tr-agree"}),
        ])
        fast = store.read_session_summary(sid)
        full = store._summary_fallback(sid)

        assert fast is not None and full is not None
        assert (fast.event_count, fast.last_event_time, fast.trace_id, fast.trace_url) == (
            full.event_count, full.last_event_time, full.trace_id, full.trace_url)

    def test_each_line_is_parsed_at_most_once(
        self, store: JsonlSessionStore, monkeypatch
    ):
        """每行最多解析一次（快路径的性能契约，回归锁）。

        深化前同一末行被解析 3 次（损坏守卫 / 取 last_time / 取 trace_id），
        O(头部上限 + 1) 的解析量因此名不副实。用调用计数钉住。
        """
        sid = "summary-parse-once"
        lines = [
            _event_line(store, sid, 0, SESSION_STARTED, {}),
            _event_line(store, sid, 1, USER_MESSAGE, {"content": "hi"}),
            _event_line(store, sid, 2, "run/completed",
                        {"final_text": "ok", "trace_id": "tr-once"}),
        ]
        _write_lines(store, sid, lines)

        parsed: list[int] = []
        original = JsonlSessionStore._parse_event_line

        def counting(raw_line, path_name, lineno):
            parsed.append(lineno)
            return original(raw_line, path_name, lineno)

        monkeypatch.setattr(store, "_parse_event_line", counting)
        stats = store.read_session_summary(sid)

        assert stats is not None
        assert stats.trace_id == "tr-once"
        assert parsed == [1, 2, 3]  # 三行各一次；重复解析末行会让计数膨胀

    def test_missing_session_returns_none(self, store: JsonlSessionStore):
        assert store.read_session_summary("no-such-session") is None

    def test_empty_file_returns_zero_count(self, store: JsonlSessionStore):
        sid = "summary-empty"
        _write_lines(store, sid, [])
        stats = store.read_session_summary(sid)
        assert stats is not None
        assert stats.event_count == 0
