"""WorkspaceRegistry 契约测试：LocalSubprocessSandbox 后端。

验证 Session ↔ Sandbox 映射的持久化和 workspace 恢复。
进程重启模拟：构造新的 WorkspaceRegistry 实例指向同一个 root。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.sandbox.registry import WorkspaceRegistry


@pytest.fixture
def registry(tmp_path: Path) -> WorkspaceRegistry:
    return WorkspaceRegistry(root=tmp_path, backend="local")


class TestCreate:
    def test_returns_ensure_started_sandbox(self, registry: WorkspaceRegistry):
        """create → 返回已 ensure_started 的 Sandbox（LocalSubprocess 是 no-op）。"""
        sandbox = registry.create("sess_1")
        assert sandbox is not None
        assert isinstance(sandbox, LocalSubprocessSandbox)

    def test_workspace_root_exists(self, registry: WorkspaceRegistry, tmp_path: Path):
        """create → workspace_root 目录被创建。"""
        sandbox = registry.create("sess_1")
        assert Path(sandbox.workspace_root).exists()
        assert Path(sandbox.workspace_root).is_dir()

    def test_mapping_json_written(self, registry: WorkspaceRegistry, tmp_path: Path):
        """create → 映射 JSON 文件存在且包含正确字段。"""
        registry.create("sess_1")

        mapping_file = tmp_path / "workspaces" / "sess_1.json"
        assert mapping_file.exists()

        import json

        mapping = json.loads(mapping_file.read_text())
        assert mapping["session_id"] == "sess_1"
        assert mapping["backend"] == "local"
        assert "workspace_root" in mapping
        assert mapping["container_name"] is None
        assert mapping["volume_name"] is None
        assert "created_at" in mapping


class TestGet:
    def test_same_instance_from_cache(self, registry: WorkspaceRegistry):
        """get（同 Registry 实例）→ 返回缓存中的同一个 Sandbox。"""
        sandbox1 = registry.create("sess_1")
        sandbox2 = registry.get("sess_1")

        assert sandbox1 is sandbox2

    def test_rebuild_after_simulated_restart(
        self, registry: WorkspaceRegistry, tmp_path: Path
    ):
        """get（新 Registry 实例，模拟进程重启）→ 重建 Sandbox，workspace_root 一致。"""
        sandbox1 = registry.create("sess_1")
        original_root = sandbox1.workspace_root

        # 模拟进程重启：新 Registry 实例，同一个 root
        new_registry = WorkspaceRegistry(root=tmp_path, backend="local")
        sandbox2 = new_registry.get("sess_1")

        assert isinstance(sandbox2, LocalSubprocessSandbox)
        assert Path(sandbox2.workspace_root) == Path(original_root)

    def test_nonexistent_raises(self, registry: WorkspaceRegistry):
        """get 不存在的 session → KeyError。"""
        with pytest.raises(KeyError):
            registry.get("sess_nonexistent")


class TestWorkspaceRecovery:
    def test_workspace_files_persist_across_restart(
        self, registry: WorkspaceRegistry, tmp_path: Path
    ):
        """workspace 恢复：create → write 文件 → 新 Registry get → 文件还在。"""
        sandbox1 = registry.create("sess_1")
        sandbox1.write_text("important.py", "print('hello')")

        # 模拟进程重启
        new_registry = WorkspaceRegistry(root=tmp_path, backend="local")
        sandbox2 = new_registry.get("sess_1")

        content = sandbox2.read_text("important.py")
        assert content == "print('hello')"

    def test_workspace_files_from_multiple_sessions(
        self, registry: WorkspaceRegistry, tmp_path: Path
    ):
        """多 session 的 workspace 互不干扰。"""
        sa = registry.create("sess_a")
        sb = registry.create("sess_b")
        sa.write_text("a.txt", "from_a")
        sb.write_text("b.txt", "from_b")

        new_registry = WorkspaceRegistry(root=tmp_path, backend="local")
        recovered_a = new_registry.get("sess_a")
        recovered_b = new_registry.get("sess_b")

        assert recovered_a.read_text("a.txt") == "from_a"
        assert recovered_b.read_text("b.txt") == "from_b"
        assert Path(recovered_a.workspace_root) != Path(recovered_b.workspace_root)


class TestExists:
    def test_nonexistent_returns_false(self, registry: WorkspaceRegistry):
        assert registry.exists("sess_no") is False

    def test_existing_returns_true(self, registry: WorkspaceRegistry):
        registry.create("sess_1")
        assert registry.exists("sess_1") is True


class TestStopAndDelete:
    def test_stop_is_idempotent(self, registry: WorkspaceRegistry):
        """stop 多次不报错（LocalSubprocess 的 stop 是 no-op）。"""
        registry.create("sess_1")
        registry.stop("sess_1")
        registry.stop("sess_1")  # 不报错

    def test_stop_nonexistent_is_idempotent(self, registry: WorkspaceRegistry):
        """stop 不存在的 session 也不报错。"""
        registry.stop("sess_nonexistent")

    def test_delete_removes_mapping(self, registry: WorkspaceRegistry, tmp_path: Path):
        """delete → 映射文件删除。"""
        registry.create("sess_1")
        assert registry.exists("sess_1")

        registry.delete("sess_1")

        assert not registry.exists("sess_1")
        assert not (tmp_path / "workspaces" / "sess_1.json").exists()

    def test_delete_is_idempotent(self, registry: WorkspaceRegistry):
        """delete 多次不报错。"""
        registry.create("sess_1")
        registry.delete("sess_1")
        registry.delete("sess_1")  # 不报错


class TestCrossProcessLifecycle:
    """跨进程的 stop/delete：Registry 实例 cache 为空时，仍能从 JSON 重建并操作。"""

    def test_stop_after_simulated_restart(self, tmp_path: Path):
        """create → 新 Registry 实例（模拟重启）→ stop 不报错且清空 cache。"""
        registry1 = WorkspaceRegistry(root=tmp_path, backend="local")
        registry1.create("sess_x")
        assert registry1.exists("sess_x")

        # 模拟进程重启
        registry2 = WorkspaceRegistry(root=tmp_path, backend="local")
        assert "sess_x" not in registry2._cache  # cache 为空

        # 跨进程 stop：应从 JSON 重建 Sandbox 再 stop，不报错
        registry2.stop("sess_x")
        assert "sess_x" not in registry2._cache

    def test_delete_after_simulated_restart_removes_everything(
        self, tmp_path: Path
    ):
        """create → 新 Registry → delete 应彻底清理映射 + workspace 目录。"""
        registry1 = WorkspaceRegistry(root=tmp_path, backend="local")
        sandbox = registry1.create("sess_y")
        sandbox.write_text("data.txt", "persistent")

        workspace_dir = Path(sandbox.workspace_root)
        assert workspace_dir.exists()

        # 模拟进程重启
        registry2 = WorkspaceRegistry(root=tmp_path, backend="local")
        assert "sess_y" not in registry2._cache

        registry2.delete("sess_y")

        # 映射 + workspace 目录都被清理
        assert not registry2.exists("sess_y")
        assert not workspace_dir.exists()

    def test_delete_orphan_workspace_dir_without_mapping(self, tmp_path: Path):
        """映射文件不存在但 workspace 目录残留 → delete 应清孤儿目录，幂等。"""
        registry = WorkspaceRegistry(root=tmp_path, backend="local")
        orphan = tmp_path / "workspaces" / "sess_orphan"
        orphan.mkdir(parents=True)
        (orphan / "junk.txt").write_text("junk")

        registry.delete("sess_orphan")  # 不报错

        assert not orphan.exists()


# ── B 组加固（R8-6）：delete 谎报成功防线 ──


def test_delete_keeps_mapping_when_workspace_locked(tmp_path, monkeypatch):
    """workspace 目录删除失败（文件被锁等）时不得删映射谎报成功。

    此前 rmtree(ignore_errors=True) 失败后映射照样被 unlink——孤儿目录留在
    磁盘且注册表无记录，永远无法再清理。现在：删除未完成 → 保留映射并抛错。
    """
    import shutil as _shutil

    import pytest as _pytest

    from agent_harness.sandbox.registry import WorkspaceRegistry

    registry = WorkspaceRegistry(root=tmp_path / "ws", backend="local")
    registry.create("sess-del")
    workspace = tmp_path / "ws" / "workspaces" / "sess-del"
    assert workspace.exists()

    real_rmtree = _shutil.rmtree

    def locked_rmtree(path, *args, **kwargs):
        real_rmtree(path, *args, **kwargs)
        # 模拟 rmtree 部分失败：目录被重建且残留一个"锁死"的文件
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "locked.bin").write_bytes(b"x")

    monkeypatch.setattr(_shutil, "rmtree", locked_rmtree)
    with _pytest.raises(RuntimeError, match="sess-del"):
        registry.delete("sess-del")
    # 映射保留：下次可以重试清理
    assert registry._mapping_path("sess-del").exists()
    monkeypatch.undo()
    registry.delete("sess-del")  # 重试成功
    assert not registry._mapping_path("sess-del").exists()
