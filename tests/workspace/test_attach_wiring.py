"""WS-2 / #152 接线验收：会话创建 / fork 真的把会话送进项目账本。

与 `test_workspace_index.py` 的区别：这里**不经替身**——真 `AppState`、真
JSONL 会话日志、真 SQLite、真 `SessionService.create_and_launch`，只把 runtime
装配与 run 启动打桩（它们与本票无关）。因此它证明的是"接线成立"，而不是"索引
类自己能跑"。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_harness.assembly import initialize_stores, recovery_stores
from agent_harness.config import Settings
from agent_harness.session import USER_MESSAGE, Session
from agent_harness.session.event import RUN_COMPLETED, RUN_STARTED
from agent_harness.session.service import SessionService
from agent_harness.session.store import JsonlSessionStore
from agent_harness.web.app import AppState


def _state(tmp_path: Path, *, model: MagicMock | None = None) -> AppState:
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        enable_cors=False,
    )
    state = AppState(settings)
    state.run_manager = MagicMock()
    state.run_manager.get_active = MagicMock(return_value=None)
    state.run_manager.launch = MagicMock(return_value=(MagicMock(), MagicMock()))
    state.get_wiring = AsyncMock(return_value=(MagicMock(), MagicMock()))
    return state


def _launch(state: AppState, **kwargs) -> object:
    with patch(
        "agent_harness.session.service.build_runtime", new_callable=AsyncMock
    ) as build:
        build.return_value = MagicMock()
        return asyncio.run(SessionService(state).create_and_launch(
            task="hello", max_steps=1, **kwargs
        ))


class TestCreateWiring:
    def test_named_workspace_creates_project_and_attaches(self, tmp_path: Path) -> None:
        """命名 workspace → 建项目实体 + 会话进账本（AC5/AC9/AC16）。"""
        state = _state(tmp_path)
        result = _launch(state, workspace_name="proj1")
        session_id = result.session.session_id  # type: ignore[attr-defined]

        workspaces = state.workspace_index.list()
        assert [w.title for w in workspaces] == ["proj1"]
        assert workspaces[0].session_ids == (session_id,)
        assert workspaces[0].status() == "ok"
        # 项目 path == 会话 header 的规范 cwd（AC5/AC6 双重校验的前提）
        assert state.store.read_started_header(session_id).cwd == workspaces[0].path

    def test_same_workspace_name_shares_one_project(self, tmp_path: Path) -> None:
        """同名 workspace 的多个会话 = 一个项目多个会话（本票的核心目标）。"""
        state = _state(tmp_path)
        first = _launch(state, workspace_name="shared").session.session_id  # type: ignore[attr-defined]
        second = _launch(state, workspace_name="shared").session.session_id  # type: ignore[attr-defined]

        workspaces = state.workspace_index.list()
        assert len(workspaces) == 1
        assert workspaces[0].session_ids == (second, first), "新会话应前插"

    def test_unnamed_session_stays_ungrouped(self, tmp_path: Path) -> None:
        """未指定项目 → 不建项目（ADR-0025 D6：默认每会话目录不是项目）。"""
        state = _state(tmp_path)
        _launch(state)
        assert state.workspace_index.list() == []

    def test_attach_does_not_touch_session_log(self, tmp_path: Path) -> None:
        """attach 只写账本：会话日志在 attach 前后逐字节相同（AC7 同款约束）。"""
        state = _state(tmp_path)
        result = _launch(state, workspace_name="proj1")
        session_id = result.session.session_id  # type: ignore[attr-defined]
        events_path = tmp_path / "sessions" / session_id / "events.jsonl"
        before = events_path.read_bytes()

        assert asyncio.run(state.workspace_index.attach_session(session_id)) is not None
        assert events_path.read_bytes() == before


class TestForkWiring:
    def test_fork_child_joins_parent_project(self, tmp_path: Path) -> None:
        """fork child 继承父 cwd（#151）→ 应当出现在父的项目里。"""
        state = _state(tmp_path)
        parent_id = _launch(state, workspace_name="proj1").session.session_id  # type: ignore[attr-defined]
        parent = Session.resume(state.store, parent_id)
        parent.append(USER_MESSAGE, {"content": "first"})
        parent.append(RUN_STARTED, {})
        parent.append(RUN_COMPLETED, {})

        boundary = next(
            e.seq for e in state.store.read_events(parent_id) if e.type == USER_MESSAGE
        )
        child_id = asyncio.run(
            SessionService(state).fork(session_id=parent_id, from_seq=boundary)
        )

        workspaces = state.workspace_index.list()
        assert len(workspaces) == 1
        assert set(workspaces[0].session_ids) == {parent_id, child_id}

    def test_fork_of_unnamed_session_stays_ungrouped(self, tmp_path: Path) -> None:
        """父未命名 → 无项目可加入，child 也保持 Ungrouped（与父一致）。"""
        state = _state(tmp_path)
        parent_id = _launch(state).session.session_id  # type: ignore[attr-defined]
        parent = Session.resume(state.store, parent_id)
        parent.append(USER_MESSAGE, {"content": "first"})
        parent.append(RUN_STARTED, {})
        parent.append(RUN_COMPLETED, {})

        boundary = next(
            e.seq for e in state.store.read_events(parent_id) if e.type == USER_MESSAGE
        )
        asyncio.run(SessionService(state).fork(session_id=parent_id, from_seq=boundary))

        assert state.workspace_index.list() == []


class TestStoreBundleWiring:
    def test_recovery_stores_without_headers_has_no_index(self, tmp_path: Path) -> None:
        """可选成员：不接会话 header 时装配出 `None`（大量单测只传一个路径）。"""
        assert recovery_stores(tmp_path / "harness.db").workspace_index is None

    def test_initialize_stores_bootstraps_once(self, tmp_path: Path) -> None:
        """initialize_stores 顺带完成首次 bootstrap，且只发生一次（AC14/AC16）。"""
        store = JsonlSessionStore(tmp_path / "sessions")
        project = tmp_path / "legacy-proj"
        project.mkdir()
        Session.start(store, session_id="old-1", cwd=project)
        Session.start(store, session_id="old-2", cwd=project)

        stores = recovery_stores(tmp_path / "harness.db", workspace_headers=store)
        asyncio.run(initialize_stores(stores))

        index = stores.workspace_index
        assert index is not None
        workspaces = index.list()
        assert [w.title for w in workspaces] == ["legacy-proj"]
        assert set(workspaces[0].session_ids) == {"old-1", "old-2"}

        # 再建一个历史会话后重复初始化：不得被吸收（标记已写，AC16）
        Session.start(store, session_id="late", cwd=project)
        asyncio.run(initialize_stores(stores))
        assert set(index.list()[0].session_ids) == {"old-1", "old-2"}

    def test_initialize_stores_is_idempotent_with_index(self, tmp_path: Path) -> None:
        store = JsonlSessionStore(tmp_path / "sessions")
        stores = recovery_stores(tmp_path / "harness.db", workspace_headers=store)
        asyncio.run(initialize_stores(stores))
        asyncio.run(initialize_stores(stores))  # 二次调用不得抛错


@pytest.mark.parametrize("name", ["proj1", "另一个项目"])
def test_project_title_comes_from_workspace_name(tmp_path: Path, name: str) -> None:
    state = _state(tmp_path)
    _launch(state, workspace_name=name)
    assert state.workspace_index.list()[0].title == name
