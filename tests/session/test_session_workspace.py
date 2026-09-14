"""Session ↔ WorkspaceRegistry 集成测试。

验证 Session.start/resume 通过 workspace_registry 绑定 Sandbox，
以及不传 registry 时的向后兼容性。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.sandbox.registry import WorkspaceRegistry
from agent_harness.session.session import Session
from agent_harness.session.store import JsonlSessionStore


@pytest.fixture
def store_and_registry(tmp_path: Path):
    """返回 (JsonlSessionStore root, WorkspaceRegistry) 共享同一 root 目录。"""
    store = JsonlSessionStore(root=tmp_path)
    registry = WorkspaceRegistry(root=tmp_path, backend="local")
    return store, registry


class TestStartWithRegistry:
    def test_start_binds_sandbox(self, store_and_registry):
        """Session.start(registry) → session.sandbox 不是 None。"""
        store, registry = store_and_registry
        session = Session.start(store, workspace_registry=registry)

        assert session.sandbox is not None
        assert isinstance(session.sandbox, LocalSubprocessSandbox)
        assert Path(session.sandbox.workspace_root).exists()

    def test_start_without_registry_sandbox_is_none(self, tmp_path: Path):
        """不传 registry → session.sandbox 是 None（向后兼容）。"""
        store = JsonlSessionStore(root=tmp_path)
        session = Session.start(store)

        assert session.sandbox is None


class TestResumeWithRegistry:
    def test_resume_restores_sandbox(self, store_and_registry):
        """Session.resume(registry) → session.sandbox 恢复，workspace 文件还在。"""
        store, registry = store_and_registry

        # start → 写文件 → resume
        session1 = Session.start(store, workspace_registry=registry)
        session1.sandbox.write_text("data.txt", "important")
        session_id = session1.session_id

        # resume：新 Session 实例，同一 registry
        session2 = Session.resume(store, session_id, workspace_registry=registry)

        assert session2.sandbox is not None
        assert session2.sandbox.read_text("data.txt") == "important"

    def test_resume_without_registry_sandbox_is_none(
        self, store_and_registry, tmp_path: Path
    ):
        """resume 不传 registry → sandbox 是 None（向后兼容）。"""
        store, registry = store_and_registry
        session1 = Session.start(store, workspace_registry=registry)
        session_id = session1.session_id

        session2 = Session.resume(store, session_id)
        assert session2.sandbox is None

    def test_resume_across_simulated_restart(self, store_and_registry):
        """Session.resume 在模拟进程重启后（新 Registry 实例）仍能恢复 workspace。"""
        store, registry = store_and_registry

        session1 = Session.start(store, workspace_registry=registry)
        session1.sandbox.write_text("persist.py", "x = 42")
        session_id = session1.session_id

        # 模拟进程重启：新 Registry 实例指向同一个 root
        new_registry = WorkspaceRegistry(root=registry._root, backend="local")
        session2 = Session.resume(store, session_id, workspace_registry=new_registry)

        assert session2.sandbox is not None
        assert session2.sandbox.read_text("persist.py") == "x = 42"


class TestExistingBehaviorUnchanged:
    def test_start_without_registry_works_as_before(self, tmp_path: Path):
        """不传 registry 时 Session.start 行为完全不变。"""
        store = JsonlSessionStore(root=tmp_path)
        session = Session.start(store)

        assert session.sandbox is None
        assert len(session.events) >= 1  # session/started 事件已追加

    def test_resume_without_registry_works_as_before(self, tmp_path: Path):
        """不传 registry 时 Session.resume 行为完全不变。"""
        store = JsonlSessionStore(root=tmp_path)
        session1 = Session.start(store)
        session_id = session1.session_id

        session2 = Session.resume(store, session_id)
        assert session2.sandbox is None
        # session/resumed 事件已追加
        assert any(e.type == "session/resumed" for e in session2.events)
