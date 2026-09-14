"""旧 session step_id 迁移脚本测试（TICKET_STEP_ID_COLLISION_MULTI_TURN 收尾）。

覆盖：重编号规则、幂等、空轮（失败/取消）推进基数、注入消息不计轮、
备份与「只改 step_id」的写入约束、服务在写时拒绝执行、CLI 退出码，
以及**与修复后 runtime 编号逐值一致**的对齐测试。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agent_harness.agent import AgentRuntime
from agent_harness.session import MODEL_COMPLETED, RUN_FAILED, RUN_STARTED, USER_MESSAGE
from agent_harness.session.store import JsonlSessionStore
from agent_harness.tooling import ToolExecutor, ToolRegistry
from scripts.migrate_legacy_step_id import (
    EVENTS_FILENAME,
    apply_session,
    count_pending,
    is_collision_free,
    main,
    normalize_step_ids,
    plan_session,
)
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel


def _event(seq: int, etype: str, *, run_id: str | None = None,
           step_id: int | None = None, **data) -> dict:
    event: dict = {"seq": seq, "type": etype}
    if run_id is not None:
        event["run_id"] = run_id
    if step_id is not None:
        event["step_id"] = step_id
    event["data"] = data
    return event


def _legacy_two_run_session() -> list[dict]:
    """修复前的旧数据：两个 run 都从 step_id=1 起算。"""
    return [
        _event(0, "session/started"),
        _event(1, USER_MESSAGE, content="你好"),
        _event(2, RUN_STARTED, run_id="r1"),
        _event(3, MODEL_COMPLETED, run_id="r1", step_id=1, content="你好啊"),
        _event(4, "run/completed", run_id="r1"),
        _event(5, USER_MESSAGE, content="我是谁"),
        _event(6, RUN_STARTED, run_id="r2"),
        _event(7, MODEL_COMPLETED, run_id="r2", step_id=1, content="你是王浩宇"),
        _event(8, "run/completed", run_id="r2"),
    ]


def _write_session(root: Path, session_id: str, events: list[dict]) -> Path:
    path = root / session_id / EVENTS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n" for e in events),
        encoding="utf-8",
    )
    return path


class TestNormalizeRule:
    def test_second_run_continues_after_first(self):
        """旧数据第二轮从 1 重编号为 2（前端 turn 键与 user 轮对齐）。"""
        events = _legacy_two_run_session()
        ids, runs, unassigned = normalize_step_ids(events)

        assert [i for i in ids if i is not None] == [1, 2]
        assert unassigned == 0
        assert [r.anchor for r in runs] == [1, 2]

    def test_multi_step_run_advances_anchor_past_max(self):
        """多步轮：第二轮锚点 = 前序最大步号 + 1（不是轮数 + 1）。"""
        events = [
            _event(0, "session/started"),
            _event(1, USER_MESSAGE, content="一"),
            _event(2, RUN_STARTED, run_id="r1"),
            _event(3, MODEL_COMPLETED, run_id="r1", step_id=1, content="a"),
            _event(4, "tool/call", run_id="r1", step_id=1, tool_name="echo"),
            _event(5, MODEL_COMPLETED, run_id="r1", step_id=2, content="b"),
            _event(6, "run/completed", run_id="r1"),
            _event(7, USER_MESSAGE, content="二"),
            _event(8, RUN_STARTED, run_id="r2"),
            _event(9, MODEL_COMPLETED, run_id="r2", step_id=1, content="c"),
            _event(10, "run/completed", run_id="r2"),
        ]
        ids, runs, _ = normalize_step_ids(events)

        assert [i for i in ids if i is not None] == [1, 1, 2, 3]
        assert runs[1].anchor == 3

    def test_run_dying_before_model_call_still_advances_base(self):
        """空轮（无任何 step 事件）也占一个 turn：第二轮不得复用 2 以下的号。"""
        events = [
            _event(0, "session/started"),
            _event(1, USER_MESSAGE, content="一"),
            _event(2, RUN_STARTED, run_id="r1"),
            _event(3, RUN_FAILED, run_id="r1", reason="cancelled"),
            _event(4, "session/resumed"),
            _event(5, USER_MESSAGE, content="二"),
            _event(6, RUN_STARTED, run_id="r2"),
            _event(7, MODEL_COMPLETED, run_id="r2", step_id=1, content="ok"),
        ]
        ids, _, _ = normalize_step_ids(events)

        assert ids[7] == 2

    def test_injected_user_message_does_not_allocate_turn(self):
        """熔断注入的纠正消息带 step_id，但不新开 turn（不计入基数）。"""
        events = [
            _event(0, "session/started"),
            _event(1, USER_MESSAGE, content="一"),
            _event(2, RUN_STARTED, run_id="r1"),
            _event(3, MODEL_COMPLETED, run_id="r1", step_id=1, content="a"),
            _event(4, USER_MESSAGE, run_id="r1", step_id=1, content="换个策略",
                   injected_by="tool_failure_guard"),
            _event(5, "run/completed", run_id="r1"),
            _event(6, USER_MESSAGE, content="二"),
            _event(7, RUN_STARTED, run_id="r2"),
            _event(8, MODEL_COMPLETED, run_id="r2", step_id=1, content="b"),
        ]
        ids, _, _ = normalize_step_ids(events)

        assert ids[8] == 2, "注入消息不得把基数推成 2（否则第二轮会错位到 turn 3）"

    def test_events_outside_run_boundary_are_left_alone(self):
        """run 边界之外带 step_id 的事件保守不动，并如实计数。"""
        events = [
            _event(0, "session/started"),
            _event(1, "model/completed", run_id="ghost", step_id=7, content="孤儿"),
        ]
        ids, _, unassigned = normalize_step_ids(events)

        assert ids[1] == 7 and unassigned == 1

    def test_idempotent_and_collision_free(self):
        events = _legacy_two_run_session()
        ids, _, _ = normalize_step_ids(events)
        migrated = [{**e, "step_id": new} if new is not None else e
                    for e, new in zip(events, ids)]

        assert count_pending(migrated) == 0
        assert is_collision_free(migrated) is True
        assert is_collision_free(events) is False


class TestPlanAndApply:
    def test_plan_reports_only_changed_lines(self, tmp_path):
        path = _write_session(tmp_path, "s-legacy", _legacy_two_run_session())
        plan = plan_session(path)

        assert plan.changed == 1, "只有第二轮那一条 step_id 需要改写"
        assert plan.unassigned == 0

    def test_apply_backs_up_and_changes_only_step_id(self, tmp_path):
        original = _legacy_two_run_session()
        path = _write_session(tmp_path, "s-legacy", original)
        before = path.read_text(encoding="utf-8")
        plan = plan_session(path)

        backup = apply_session(plan, backup_dir=tmp_path / "backup")

        assert backup.read_text(encoding="utf-8") == before, "备份必须是原文逐字节"
        after_lines = path.read_text(encoding="utf-8").splitlines()
        after = [json.loads(line) for line in after_lines]
        assert len(after) == len(original)
        for old, new in zip(original, after):
            expected = dict(old)
            if new["seq"] == 7:
                expected["step_id"] = 2
            assert new == expected, "除 step_id 外任何字段/键序变化都是越界"
        # 迁移后仍是合法 store：重新加载 + 二次规划必须为零改动
        store = JsonlSessionStore(root=tmp_path)
        assert [e.step_id for e in store.read_events("s-legacy") if e.step_id] == [1, 2]
        assert count_pending(after) == 0

    def test_apply_refuses_when_file_changed_after_plan(self, tmp_path):
        """规划后文件被 append（服务在写）→ 拒绝覆盖。"""
        path = _write_session(tmp_path, "s-legacy", _legacy_two_run_session())
        plan = plan_session(path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_event(9, "run/completed", run_id="r2")) + "\n")

        with pytest.raises(RuntimeError, match="在规划后被改动"):
            apply_session(plan, backup_dir=tmp_path / "backup")

    def test_new_data_is_noop(self, tmp_path):
        """已修复数据：规划出零改动，apply 不写文件、不建备份。"""
        events = [
            _event(0, "session/started"),
            _event(1, USER_MESSAGE, content="一"),
            _event(2, RUN_STARTED, run_id="r1"),
            _event(3, MODEL_COMPLETED, run_id="r1", step_id=1, content="a"),
            _event(4, "run/completed", run_id="r1"),
            _event(5, USER_MESSAGE, content="二"),
            _event(6, RUN_STARTED, run_id="r2"),
            _event(7, MODEL_COMPLETED, run_id="r2", step_id=2, content="b"),
        ]
        path = _write_session(tmp_path, "s-new", events)
        plan = plan_session(path)

        assert plan.changed == 0
        assert apply_session(plan, backup_dir=tmp_path / "backup") == Path()
        assert not (tmp_path / "backup").exists()


class TestCli:
    def test_dry_run_exit_code_2_then_apply_exit_code_0(self, tmp_path, capsys):
        _write_session(tmp_path, "s-legacy", _legacy_two_run_session())

        assert main(["--root", str(tmp_path)]) == 2
        assert "DRY-RUN" in capsys.readouterr().out

        assert main(["--root", str(tmp_path), "--apply"]) == 0
        assert "已迁移" in capsys.readouterr().out
        # 再跑一次：已无待迁移
        assert main(["--root", str(tmp_path)]) == 0

    def test_missing_root_fails(self, tmp_path):
        assert main(["--root", str(tmp_path / "nope")]) == 1


class TestAlignsWithFixedRuntime:
    @pytest.mark.asyncio
    async def test_migration_rule_matches_runtime_numbering(self, tmp_path):
        """同一段对话：把修复后 runtime 的真实事件「退化」成旧编号，
        再迁移回来，必须逐值等于 runtime 产出的编号。"""
        session = make_session(tmp_path)
        model = ScriptedModel([AIMessage(content="你好啊"), AIMessage(content="你是王浩宇")])
        registry = ToolRegistry()
        runtime = AgentRuntime(model=model, registry=registry,
                               executor=ToolExecutor(registry))
        await runtime.run(session, "你好")
        await runtime.run(session, "我是谁")
        real = [e.to_dict() for e in session.events]

        # 退化成旧后端语义：每个 run 的 step_id 从 1 重数
        legacy, counters = [], []
        for event in real:
            etype = event.get("type")
            if etype == RUN_STARTED:
                counters = []
            if event.get("step_id") is not None:
                counters.append(len(counters) + 1)
                event = {**event, "step_id": counters[-1]}
            legacy.append(event)

        assert [e.get("step_id") for e in legacy if e.get("step_id")] == [1, 1]
        migrated_ids, _, _ = normalize_step_ids(legacy)
        assert migrated_ids == [e.get("step_id") for e in real]
