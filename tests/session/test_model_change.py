"""T7 (#137)：同 session 内模型切换 + Fork（service 层）。

契约：`docs/integration/PRD_PHASE_MULTITURN_TOTAL.md` §2.3 / §2.4
- `POST /api/sessions/{id}/model` body `{provider, model_id}`
- `MODEL_CHANGED` 事件 data：`from_provider` / `from_model_id` / `to_provider` / `to_model_id`
- runtime 在下一轮 run 时从 session 读取当前模型（而非创建时锁定的模型）
- `POST /api/sessions/{id}/forks` body `{from_seq}` → 新 session_id，复用 `fork.py`

端点层见 `tests/web/test_web_model_fork.py`。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_harness.config import Settings
from agent_harness.session.event import (
    MODEL_CHANGED,
    RUN_COMPLETED,
    RUN_STARTED,
    SESSION_FORKED,
    SESSION_STARTED,
    USER_MESSAGE,
    SessionEvent,
)
from agent_harness.session.service import (
    ActiveRunConflict,
    AmendOptions,
    InvalidForkBoundary,
    SeqConflict,
    SessionNotFound,
    SessionService,
    UnknownModel,
)
from agent_harness.session.session import Session
from agent_harness.session.store import JsonlSessionStore
from agent_harness.storage.sqlite import SqliteSessionMetaStore

#: 两个 catalog 条目，provider 必须命中预设（deepseek / zhipu）。
_CATALOG = (
    '[{"name": "gpt-4o", "provider": "deepseek", "model_name": "gpt-4o-mini"},'
    ' {"name": "glm-4.5", "provider": "zhipu", "model_name": "glm-4.5"}]'
)


def _state(tmp_path) -> MagicMock:
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        model_provider="deepseek",
        model_name="deepseek-chat",
        agent_models=_CATALOG,
    )
    state = MagicMock()
    state.settings = settings
    state.store = JsonlSessionStore(root=tmp_path / "sessions")
    state.workspaces_root = tmp_path
    state.workspace_registry = None
    state.workspace_index = None  # WS-2：项目索引未接线（本文件测模型继承）
    state.run_manager = MagicMock()
    state.run_manager.get_active = MagicMock(return_value=None)
    state.run_manager.launch = MagicMock(
        return_value=(MagicMock(), MagicMock())
    )
    state.get_wiring = AsyncMock(return_value=(MagicMock(), MagicMock()))
    state.ensure_stores = AsyncMock()
    state.stores = MagicMock()
    return state


def _seed_session(state, session_id: str = "sid", *, provider=None, model_id=None) -> Session:
    data = {}
    if provider is not None:
        data["provider"] = provider
    if model_id is not None:
        data["model_id"] = model_id
    return Session.start(
        state.store, session_id=session_id, started_data=data or None
    )


def _resume_capture(state, amend=None) -> dict:
    """驱动 resume_and_launch，返回 build_runtime 收到的关键字参数。"""
    with (
        patch(
            "agent_harness.session.service.build_runtime",
            new_callable=AsyncMock,
        ) as mock_build,
        patch("agent_harness.session.service.Session") as mock_session_cls,
    ):
        mock_session = MagicMock()
        mock_session.session_id = "sid"
        mock_session_cls.resume = MagicMock(return_value=mock_session)
        service = SessionService(state)
        asyncio.run(
            service.resume_and_launch(session_id="sid", task="hi", amend=amend)
        )
    return mock_build.await_args.kwargs


class TestChangeModel:
    def test_appends_model_changed_with_from_and_to(self, tmp_path):
        state = _state(tmp_path)
        _seed_session(state, provider="deepseek", model_id="gpt-4o")
        service = SessionService(state)

        change = asyncio.run(
            service.change_model(
                session_id="sid", provider="zhipu", model_id="glm-4.5"
            )
        )

        assert change.from_provider == "deepseek"
        assert change.from_model_id == "gpt-4o"
        assert change.to_provider == "zhipu"
        assert change.to_model_id == "glm-4.5"

        events = state.store.read_events("sid")
        assert events[-1].type == MODEL_CHANGED
        assert events[-1].data == {
            "from_provider": "deepseek",
            "from_model_id": "gpt-4o",
            "to_provider": "zhipu",
            "to_model_id": "glm-4.5",
        }

    def test_second_change_derives_from_previous_change(self, tmp_path):
        state = _state(tmp_path)
        _seed_session(state, provider="deepseek", model_id="gpt-4o")
        service = SessionService(state)

        asyncio.run(
            service.change_model(session_id="sid", provider="zhipu", model_id="glm-4.5")
        )
        change = asyncio.run(
            service.change_model(session_id="sid", provider="deepseek", model_id="gpt-4o")
        )

        assert change.from_provider == "zhipu"
        assert change.from_model_id == "glm-4.5"
        assert change.to_provider == "deepseek"
        assert change.to_model_id == "gpt-4o"

    def test_unknown_model_raises(self, tmp_path):
        state = _state(tmp_path)
        _seed_session(state)
        service = SessionService(state)

        with pytest.raises(UnknownModel):
            asyncio.run(
                service.change_model(
                    session_id="sid", provider="zhipu", model_id="does-not-exist"
                )
            )

    def test_provider_mismatch_raises(self, tmp_path):
        """catalog 名存在但 provider 不匹配 → 拒绝（防止跨 provider 误选）。"""
        state = _state(tmp_path)
        _seed_session(state)
        service = SessionService(state)

        with pytest.raises(UnknownModel):
            asyncio.run(
                service.change_model(
                    session_id="sid", provider="zhipu", model_id="gpt-4o"
                )
            )

    def test_missing_session_raises(self, tmp_path):
        state = _state(tmp_path)
        service = SessionService(state)

        with pytest.raises(SessionNotFound):
            asyncio.run(
                service.change_model(
                    session_id="nope", provider="zhipu", model_id="glm-4.5"
                )
            )

    def test_unresolvable_model_raises(self, tmp_path):
        """AC「校验 provider 可用性」：catalog 命中但装不起来（无 key）→ 422 级拒绝。

        与创建路径同一判据：POST /model 不能接受一个 POST /sessions 会拒绝的目标。
        """
        state = _state(tmp_path)
        state.settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            model_api_key="",
            model_provider="deepseek",
            model_name="deepseek-chat",
            agent_models=_CATALOG,
        )
        _seed_session(state)

        with pytest.raises(UnknownModel):
            asyncio.run(
                SessionService(state).change_model(
                    session_id="sid", provider="zhipu", model_id="glm-4.5"
                )
            )


class TestRuntimeReadsSessionModel:
    def test_resume_uses_persisted_session_model(self, tmp_path):
        state = _state(tmp_path)
        state.store = MagicMock()
        state.store.read_events = MagicMock(
            return_value=[
                SessionEvent(
                    seq=0,
                    type=SESSION_STARTED,
                    session_id="sid",
                    data={"provider": "deepseek", "model_id": "gpt-4o"},
                )
            ]
        )

        kwargs = _resume_capture(state)

        assert kwargs["model_name"] == "gpt-4o"

    def test_resume_uses_latest_model_changed(self, tmp_path):
        state = _state(tmp_path)
        state.store = MagicMock()
        state.store.read_events = MagicMock(
            return_value=[
                SessionEvent(
                    seq=0,
                    type=SESSION_STARTED,
                    session_id="sid",
                    data={"provider": "deepseek", "model_id": "gpt-4o"},
                ),
                SessionEvent(
                    seq=1,
                    type=MODEL_CHANGED,
                    session_id="sid",
                    data={"to_provider": "zhipu", "to_model_id": "glm-4.5"},
                ),
            ]
        )

        kwargs = _resume_capture(state)

        assert kwargs["model_name"] == "glm-4.5"

    def test_explicit_amend_model_wins(self, tmp_path):
        state = _state(tmp_path)
        state.store = MagicMock()
        state.store.read_events = MagicMock(
            return_value=[
                SessionEvent(
                    seq=0,
                    type=SESSION_STARTED,
                    session_id="sid",
                    data={"provider": "deepseek", "model_id": "gpt-4o"},
                )
            ]
        )

        kwargs = _resume_capture(state, amend=AmendOptions(model="glm-4.5"))

        assert kwargs["model_name"] == "glm-4.5"

    def test_no_session_model_keeps_default_chain(self, tmp_path):
        state = _state(tmp_path)
        state.store = MagicMock()
        state.store.read_events = MagicMock(
            return_value=[
                SessionEvent(seq=0, type=SESSION_STARTED, session_id="sid", data={})
            ]
        )

        kwargs = _resume_capture(state)

        assert kwargs["model_name"] is None

    def test_create_persists_model_into_session_started(self, tmp_path):
        state = _state(tmp_path)
        with (
            patch(
                "agent_harness.session.service.build_runtime",
                new_callable=AsyncMock,
            ),
            patch("agent_harness.session.service.Session") as mock_session_cls,
        ):
            mock_session_cls.start = MagicMock(return_value=MagicMock())
            service = SessionService(state)
            asyncio.run(
                service.create_and_launch(
                    task="hello", amend=AmendOptions(model="gpt-4o")
                )
            )

        assert mock_session_cls.start.call_args.kwargs["started_data"] == {
            "provider": "deepseek",
            "model_id": "gpt-4o",
        }

    def test_derived_model_gone_from_catalog_falls_back_to_default(self, tmp_path):
        """会话记录的模型已不在 catalog（配置漂移）→ 回落默认链，不 500。"""
        state = _state(tmp_path)
        state.store = MagicMock()
        state.store.read_events = MagicMock(
            return_value=[
                SessionEvent(
                    seq=0,
                    type=SESSION_STARTED,
                    session_id="sid",
                    data={"provider": "deepseek", "model_id": "removed-model"},
                )
            ]
        )

        kwargs = _resume_capture(state)

        assert kwargs["model_name"] is None


class TestDefaultModelSelection:
    """选中 ``GET /api/models`` 的 is_default 条目 = 清除会话级覆盖。"""

    def test_change_to_default_writes_none_model_id(self, tmp_path):
        state = _state(tmp_path)
        _seed_session(state, provider="deepseek", model_id="gpt-4o")
        service = SessionService(state)

        change = asyncio.run(
            service.change_model(
                session_id="sid", provider="deepseek", model_id="deepseek-chat"
            )
        )

        assert change.to_provider == "deepseek"
        assert change.to_model_id is None
        assert state.store.read_events("sid")[-1].data["to_model_id"] is None

    def test_after_default_switch_derived_model_is_default_chain(self, tmp_path):
        """切回默认后再续聊 → 不传 model（走默认链），而不是回到旧 catalog 条目。"""
        state = _state(tmp_path)
        _seed_session(state, provider="deepseek", model_id="gpt-4o")
        service = SessionService(state)
        asyncio.run(
            service.change_model(
                session_id="sid", provider="deepseek", model_id="deepseek-chat"
            )
        )

        kwargs = _resume_capture(state)

        assert kwargs["model_name"] is None

    def test_default_alias_literal_also_accepted(self, tmp_path):
        state = _state(tmp_path)
        _seed_session(state, provider="deepseek", model_id="gpt-4o")
        service = SessionService(state)

        change = asyncio.run(
            service.change_model(
                session_id="sid", provider="deepseek", model_id="default"
            )
        )

        assert change.to_model_id is None

    def test_default_selection_wins_over_same_named_catalog_entry(self, tmp_path):
        """catalog 恰有与默认模型同名的条目时，选默认仍 = 清覆盖（不能锁死该条目）。"""
        state = _state(tmp_path)
        state.settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            model_api_key="sk-test",
            model_provider="deepseek",
            model_name="deepseek-chat",
            agent_models=(
                '[{"name": "deepseek-chat", "provider": "deepseek",'
                ' "model_name": "deepseek-reasoner"}]'
            ),
        )
        _seed_session(state, provider="deepseek", model_id="gpt-4o")

        change = asyncio.run(
            SessionService(state).change_model(
                session_id="sid", provider="deepseek", model_id="deepseek-chat"
            )
        )

        assert change.to_provider == "deepseek"
        assert change.to_model_id is None


class TestChangeModelDoesNotResume:
    """`model/changed` 追加不得走 Session.resume（会注入合成 tool/result + resumed）。"""

    def test_change_model_leaves_dangling_tool_call_untouched(self, tmp_path):
        from agent_harness.session.event import TOOL_CALL, TOOL_RESULT

        state = _state(tmp_path)
        session = _seed_session(state, provider="deepseek", model_id="gpt-4o")
        session.append(TOOL_CALL, {"tool_call_id": "tc-1", "tool_name": "bash"})
        before = [e.type for e in state.store.read_events("sid")]

        asyncio.run(
            SessionService(state).change_model(
                session_id="sid", provider="zhipu", model_id="glm-4.5"
            )
        )

        events = state.store.read_events("sid")
        assert [e.type for e in events][: len(before)] == before
        assert events[-1].type == MODEL_CHANGED
        assert all(e.type != TOOL_RESULT for e in events)
        assert all(e.type != "session/resumed" for e in events)

    def test_queue_message_leaves_dangling_tool_call_untouched(self, tmp_path):
        """续聊入队同样只追加（T2/T5 路径复用 helper，不注入合成 tool/result）。"""
        from types import SimpleNamespace

        from agent_harness.session.event import MESSAGE_QUEUED, TOOL_CALL, TOOL_RESULT
        from agent_harness.session.queue import MessageQueueManager

        state = _state(tmp_path)
        state.message_queues = MessageQueueManager()
        session = _seed_session(state, provider="deepseek", model_id="gpt-4o")
        session.append(TOOL_CALL, {"tool_call_id": "tc-1", "tool_name": "bash"})
        state.run_manager.get_active = MagicMock(
            return_value=SimpleNamespace(session=session)
        )

        result = asyncio.run(
            SessionService(state).send_message(
                session_id="sid", content="next", mode="queue"
            )
        )

        assert result.status == "queued"
        events = state.store.read_events("sid")
        assert events[-1].type == MESSAGE_QUEUED
        assert all(e.type != TOOL_RESULT for e in events)
        assert all(e.type != "session/resumed" for e in events)

    def test_change_model_mid_run_reuses_active_session_seq(self, tmp_path):
        """在途 run 持有 Session 时旁路追加走同一聚合——否则 seq 撞号，会话不可 resume。"""
        from types import SimpleNamespace

        from agent_harness.session.event import USER_MESSAGE

        state = _state(tmp_path)
        live = _seed_session(state, provider="deepseek", model_id="gpt-4o")
        live.append(USER_MESSAGE, {"content": "hello"})  # seq 1
        state.run_manager.get_active = MagicMock(
            return_value=SimpleNamespace(session=live)
        )

        asyncio.run(
            SessionService(state).change_model(
                session_id="sid", provider="zhipu", model_id="glm-4.5"
            )
        )
        live.append(USER_MESSAGE, {"content": "after"})

        seqs = [e.seq for e in state.store.read_events("sid")]
        assert seqs == [0, 1, 2, 3]
        # 与 run 的 Session 同源加载 → resume 不会因重复 seq 失败
        assert Session.resume(state.store, "sid") is not None

    def test_change_model_mid_run_reaches_run_listener(self, tmp_path):
        """走 run 持有的 Session = 在册 listener 收到事件（订阅者可实时看到切换）。"""
        from types import SimpleNamespace

        state = _state(tmp_path)
        live = _seed_session(state, provider="deepseek", model_id="gpt-4o")
        seen: list = []
        live.add_listener(seen.append)
        state.run_manager.get_active = MagicMock(
            return_value=SimpleNamespace(session=live)
        )

        asyncio.run(
            SessionService(state).change_model(
                session_id="sid", provider="zhipu", model_id="glm-4.5"
            )
        )

        assert seen[-1].type == MODEL_CHANGED


class TestConcurrentModelChange:
    """BUG-011：两个并发 ``POST /model`` 不得把会话写死。

    真机现场：模型项被双击 → 两个并发请求各自基于同一份快照取号 → 两条 seq=5 落盘
    → 此后任何构造聚合的路径（``Session.load`` / ``resume``）永久失败 → 续聊恒
    404（``Send failed: 404``，会话 ``dd983104``）。契约：并发下两个切换都要生效、
    seq 严格单调、会话仍可 resume。

    并发读的时序靠调度太不稳定（变异验证时抓到「有时红、有时假绿」），故用**冻结
    快照**注入确定性：前两次 ``read_events`` 返回同一份「变更前」快照——正好是
    ``change_model`` 每轮取的那一次快照，两个写者同号即 BUG-011 的机制本身。
    之后回真实磁盘：重试路径据此拿到新号。两个变异都能稳定变红（见 commit 说明）：
    去掉 store 守卫 → 重复 seq；去掉重试 → SeqConflict 直接抛出。
    """

    def test_parallel_changes_keep_seq_strictly_increasing(self, tmp_path, monkeypatch):
        state = _state(tmp_path)
        _seed_session(state, provider="deepseek", model_id="gpt-4o")
        real_read = state.store.read_events
        frozen = real_read("sid")
        reads: list[int] = []

        def read_with_frozen_first_snapshot(session_id: str):
            if len(reads) < 2:  # 两个并发写者各读到一次「变更前」
                reads.append(1)
                return list(frozen)
            return real_read(session_id)

        monkeypatch.setattr(state.store, "read_events", read_with_frozen_first_snapshot)

        async def run_both():
            return await asyncio.gather(
                SessionService(state).change_model(
                    session_id="sid", provider="zhipu", model_id="glm-4.5"
                ),
                SessionService(state).change_model(
                    session_id="sid", provider="deepseek", model_id="gpt-4o"
                ),
            )

        changes = asyncio.run(run_both())

        events = real_read("sid")
        seqs = [e.seq for e in events]
        assert len(seqs) == len(set(seqs)), f"seq 重复：{seqs}"
        assert seqs == sorted(seqs)
        model_changes = [e for e in events if e.type == MODEL_CHANGED]
        # 两个切换都生效——不是「第二个被静默丢掉」
        assert len(model_changes) == 2
        assert {c.to_model_id for c in changes} == {"glm-4.5", "gpt-4o"}
        # 后一条的 from_* 必须看到前一条的结果（冲突后重新取快照，不沿用旧快照）
        assert (
            model_changes[1].data["from_model_id"]
            == model_changes[0].data["to_model_id"]
        )
        # 「没写死」的判据：会话仍能被 resume
        assert Session.resume(state.store, "sid") is not None

    def test_retry_is_bounded_and_surfaces_persistent_conflict(self, tmp_path, monkeypatch):
        """持续冲突（重试用尽）→ 抛 SeqConflict，且重试次数有界。

        断言尝试次数而不是只断言异常类型：否则「零重试」的实现也能通过（假绿）。
        """
        state = _state(tmp_path)
        _seed_session(state, provider="deepseek", model_id="gpt-4o")
        attempts: list[int] = []

        def always_conflict(session_id: str, event):
            attempts.append(1)
            raise SeqConflict("注入：持续冲突")

        monkeypatch.setattr(state.store, "append_event", always_conflict)

        with pytest.raises(SeqConflict):
            asyncio.run(
                SessionService(state).change_model(
                    session_id="sid", provider="zhipu", model_id="glm-4.5"
                )
            )

        assert len(attempts) == 3, f"重试次数应为 3（有界），实际 {len(attempts)}"


class TestFork:
    def _fork_state(self, tmp_path):
        state = _state(tmp_path)
        state.session_meta_store = SqliteSessionMetaStore(tmp_path / "harness.db")
        asyncio.run(state.session_meta_store.initialize())
        return state

    def test_fork_returns_child_with_provenance(self, tmp_path):
        state = self._fork_state(tmp_path)
        parent = _seed_session(state, "parent")
        parent.append(USER_MESSAGE, {"content": "first"})
        parent.append(RUN_STARTED, {})
        parent.append(RUN_COMPLETED, {})
        parent.append(USER_MESSAGE, {"content": "second"})
        service = SessionService(state)

        child_id = asyncio.run(service.fork(session_id="parent", from_seq=1))

        assert child_id != "parent"
        child_events = state.store.read_events(child_id)
        assert child_events[-1].type == SESSION_FORKED
        assert child_events[-1].data["parent_session_id"] == "parent"
        assert child_events[-1].data["boundary_user_message_seq"] == 1

    def test_fork_missing_session_raises(self, tmp_path):
        state = self._fork_state(tmp_path)
        service = SessionService(state)

        with pytest.raises(SessionNotFound):
            asyncio.run(service.fork(session_id="nope", from_seq=0))

    def test_fork_invalid_boundary_raises(self, tmp_path):
        state = self._fork_state(tmp_path)
        _seed_session(state, "parent")
        service = SessionService(state)

        with pytest.raises(InvalidForkBoundary):
            asyncio.run(service.fork(session_id="parent", from_seq=999))

    def test_fork_with_active_run_conflicts(self, tmp_path):
        state = self._fork_state(tmp_path)
        _seed_session(state, "parent")
        state.run_manager.get_active = MagicMock(return_value=MagicMock())
        service = SessionService(state)

        with pytest.raises(ActiveRunConflict):
            asyncio.run(service.fork(session_id="parent", from_seq=0))

    def test_fork_child_inherits_parent_model(self, tmp_path):
        """seed 不含父 session/started → 补一条 model/changed，child 不静默回落默认链。"""
        from agent_harness.session.service import current_model_selection

        state = self._fork_state(tmp_path)
        parent = _seed_session(state, "parent", provider="deepseek", model_id="gpt-4o")
        parent.append(USER_MESSAGE, {"content": "first"})
        parent.append(RUN_STARTED, {})
        parent.append(RUN_COMPLETED, {})

        child_id = asyncio.run(
            SessionService(state).fork(session_id="parent", from_seq=1)
        )

        assert current_model_selection(
            state.store.read_events(child_id)
        ) == ("deepseek", "gpt-4o")

    def test_fork_child_stays_on_default_chain_when_parent_does(self, tmp_path):
        from agent_harness.session.service import current_model_selection

        state = self._fork_state(tmp_path)
        parent = _seed_session(state, "parent")
        parent.append(USER_MESSAGE, {"content": "first"})
        parent.append(RUN_STARTED, {})
        parent.append(RUN_COMPLETED, {})

        child_id = asyncio.run(
            SessionService(state).fork(session_id="parent", from_seq=1)
        )

        assert current_model_selection(
            state.store.read_events(child_id)
        ) == (None, None)
