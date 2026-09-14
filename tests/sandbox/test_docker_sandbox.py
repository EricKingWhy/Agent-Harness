"""DockerSandbox contract tests."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from uuid import uuid4

import pytest

from agent_harness.sandbox import ExecResult


def _docker_available() -> bool:
    try:
        docker = importlib.import_module("docker")
        client = docker.from_env(use_context=False)
        client.ping()
        client.close()
    except Exception:  # noqa: BLE001 — probe: any failure means Docker unavailable
        return False
    return True


docker_required = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker SDK or daemon is unavailable",
)


@pytest.fixture
def docker_sandbox() -> Iterator[object]:
    from agent_harness.sandbox.docker import DockerSandbox

    suffix = uuid4().hex
    volume_name = f"agent-harness-test-{suffix}"
    sandbox = DockerSandbox(
        container_name=f"agent-harness-test-{suffix}",
        volume_name=volume_name,
    )
    try:
        yield sandbox
    finally:
        sandbox.delete()


def test_constructor_reports_missing_docker_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """The optional Docker SDK is loaded only when the backend is constructed."""
    real_import_module = importlib.import_module

    def import_without_docker(name: str, package: str | None = None):
        if name == "docker":
            raise ModuleNotFoundError("No module named 'docker'")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", import_without_docker)

    from agent_harness.sandbox.docker import DockerSandbox

    with pytest.raises(RuntimeError, match="DockerSandbox 需要 pip install docker"):
        DockerSandbox()


@docker_required
def test_exec_runs_in_workspace_and_stop_is_idempotent(docker_sandbox: object) -> None:
    result = docker_sandbox.exec("printf hello")

    assert isinstance(result, ExecResult)
    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert result.stderr == ""
    assert result.duration_ms >= 0

    docker_sandbox.stop()
    docker_sandbox.stop()


@docker_required
def test_write_then_read_nested_file(docker_sandbox: object) -> None:
    docker_sandbox.write_text("nested/note.txt", "你好, Docker")

    assert docker_sandbox.read_text("nested/note.txt") == "你好, Docker"


@docker_required
@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "..\\..\\etc\\passwd"])
def test_workspace_path_escape_is_denied(docker_sandbox: object, path: str) -> None:
    with pytest.raises(PermissionError):
        docker_sandbox.read_text(path)


@docker_required
def test_copy_in_imports_host_file(
    docker_sandbox: object,
    tmp_path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("from Host", encoding="utf-8")

    docker_sandbox.copy_in(source, "imports/copied.txt")

    assert docker_sandbox.read_text("imports/copied.txt") == "from Host"
