"""WorkspaceRegistry Docker 后端集成测试。

确定性命名 + workspace 恢复（volume 持久性）验证。
默认 skip（需要 Docker daemon）。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _docker_available() -> bool:
    try:
        docker = importlib.import_module("docker")
        client = docker.from_env(use_context=False)
        client.ping()
        client.close()
    except Exception:  # noqa: BLE001 — probe
        return False
    return True


docker_required = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker SDK or daemon is unavailable",
)

SESSION_ID = "test-registry-docker-session"


@pytest.fixture
def registry(tmp_path: Path):
    from agent_harness.sandbox.registry import WorkspaceRegistry

    reg = WorkspaceRegistry(root=tmp_path, backend="docker")
    yield reg
    # 清理：删除测试容器和 volume
    try:
        reg.delete(SESSION_ID)
    except Exception:  # noqa: BLE001, S110 — best-effort cleanup
        pass
    try:
        import docker

        client = docker.from_env(use_context=False)
        for vol_suffix in [SESSION_ID]:
            try:
                client.volumes.get(f"agent-harness-{vol_suffix}").remove(force=True)
            except Exception:  # noqa: BLE001, S110
                pass
        client.close()
    except Exception:  # noqa: BLE001, S110
        pass


@docker_required
class TestDockerRegistryDeterministicNaming:
    def test_container_name_is_deterministic(self, registry, tmp_path: Path):
        """同一 session_id 产生的容器名确定性。"""
        import json

        _sandbox = registry.create(SESSION_ID)

        mapping_file = tmp_path / "workspaces" / f"{SESSION_ID}.json"
        mapping = json.loads(mapping_file.read_text())
        assert mapping["container_name"] == f"agent-harness-{SESSION_ID}"
        assert mapping["volume_name"] == f"agent-harness-{SESSION_ID}"


@docker_required
class TestDockerWorkspaceRecovery:
    def test_workspace_files_persist_across_restart(self, registry):
        """workspace 恢复：create → write → 新 Registry get → 文件还在。

        Docker volume 持久：容器停了但 volume 在，resume 时重启容器即可。
        """
        sandbox1 = registry.create(SESSION_ID)
        sandbox1.write_text("persistent.py", "print('survived restart')")

        # 模拟进程重启：stop 容器（不删 volume），新 Registry get 重启容器
        registry.stop(SESSION_ID)

        from agent_harness.sandbox.registry import WorkspaceRegistry

        new_registry = WorkspaceRegistry(
            root=registry._root, backend="docker"
        )
        sandbox2 = new_registry.get(SESSION_ID)

        content = sandbox2.read_text("persistent.py")
        assert content == "print('survived restart')"
