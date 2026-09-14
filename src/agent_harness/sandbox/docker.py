"""Docker-backed Sandbox with an optional, lazily loaded SDK dependency."""

from __future__ import annotations

import fnmatch
import importlib
import io
import posixpath
import tarfile
from pathlib import Path, PurePosixPath
from time import perf_counter
from uuid import uuid4

from agent_harness.sandbox.base import (
    ExecResult,
    Sandbox,
    ShellEnvironment,
    ShellFamily,
)
from agent_harness.sandbox.local import DEFAULT_EXEC_TIMEOUT


def _glob_match_posix(rel_path: str, pattern: str) -> bool:
    """对容器内相对路径做 glob 匹配，支持 ** 递归（与 LocalSubprocessSandbox._glob_match 同语义）。"""
    if pattern in ("", "*"):
        return True
    if "**" in pattern:
        normalized = pattern.replace("**/", "").replace("**", "*")
        return fnmatch.fnmatch(rel_path, normalized) or fnmatch.fnmatch(
            PurePosixPath(rel_path).name, normalized
        )
    return fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(
        PurePosixPath(rel_path).name, pattern
    )


class DockerSandbox(Sandbox):
    """Run Coding Tools inside an isolated Docker container."""

    def __init__(
        self,
        *,
        image: str = "python:3-slim",
        container_name: str | None = None,
        volume_name: str | None = None,
    ) -> None:
        try:
            docker = importlib.import_module("docker")
        except ModuleNotFoundError as error:
            raise RuntimeError("DockerSandbox 需要 pip install docker") from error
        self._client = docker.from_env(use_context=False)
        suffix = uuid4().hex
        self._image = image
        self._container_name = container_name or f"agent-harness-{suffix}"
        self._volume_name = volume_name or f"agent-harness-{suffix}"
        self._container = None

    @property
    def workspace_root(self) -> PurePosixPath:
        return PurePosixPath("/workspace")

    @property
    def shell_environment(self) -> ShellEnvironment:
        """容器内固定用 `/bin/sh -lc`（见 exec）——OBS-012：是 sh，不是 bash。"""
        return ShellEnvironment(name="/bin/sh", family=ShellFamily.POSIX_SH)

    def ensure_started(self) -> None:
        if self._container is not None:
            self._container.reload()
            if self._container.status == "running":
                return
            self._container.start()
            return

        # 跨进程恢复：按确定性 container_name 查找已存在的容器。
        # 进程重启后 self._container 为 None，但容器可能还在（停止状态）。
        # 如果找到，重启它；找不到才创建新容器。
        docker = importlib.import_module("docker")
        try:
            existing = self._client.containers.get(self._container_name)
        except docker.errors.NotFound:
            existing = None
        if existing is not None:
            if existing.status != "running":
                existing.start()
            self._container = existing
            return

        self._container = self._client.containers.run(
            self._image,
            ["sleep", "infinity"],
            name=self._container_name,
            detach=True,
            working_dir=str(self.workspace_root),
            volumes={
                self._volume_name: {
                    "bind": str(self.workspace_root),
                    "mode": "rw",
                }
            },
        )

    def exec(self, command: str, *, timeout: float | None = None,
             cancel_event=None, on_output=None) -> ExecResult:
        """在容器内执行命令；timeout 到点返回 exit_code=-1 的超时结果（D10 契约）。

        docker SDK 的 exec_run 没有超时参数且是阻塞读——实现上把调用放进
        daemon 线程等待，到点放弃等待返回超时结果（容器内进程随容器生命周期
        收敛）。调用方（tool 边界）已把本方法卸载到工作线程，event loop 不阻塞。

        V1 限制（诚实声明）：cancel_event 被接受但忽略——容器内进程的协作取消
        需要 docker exec kill 链路，V1 不实现；容器内命令会跑完自身生命周期。
        on_output（ADR-0016 §4.2）同样接受但忽略：exec_run 一次性返回 demux
        结果，无逐段读取窗口；容器后端的输出流式留待 demux 迭代器改造。
        """
        import threading

        self.ensure_started()
        effective_timeout = timeout if timeout is not None else DEFAULT_EXEC_TIMEOUT
        started = perf_counter()
        container = self._container
        holder: dict = {}

        def _run() -> None:
            try:
                holder["result"] = container.exec_run(
                    ["/bin/sh", "-lc", command],
                    demux=True,
                    workdir=str(self.workspace_root),
                )
            except Exception as error:  # noqa: BLE001 — 交给调用方统一处理
                holder["error"] = error

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(effective_timeout)
        if worker.is_alive():
            return ExecResult(
                exit_code=-1,
                stdout="",
                stderr=f"命令超时（上限 {effective_timeout} 秒）",
                duration_ms=round((perf_counter() - started) * 1000, 1),
            )
        if "error" in holder:
            raise holder["error"]
        result = holder["result"]
        stdout_bytes, stderr_bytes = result.output
        # 这里**刻意**保持固定 UTF-8（与 LocalSubprocessSandbox 的 StreamDecoder 不同）：
        # 产出方是 Linux 容器内的进程，不是宿主控制台——宿主代码页（中文 Windows=GBK）
        # 与容器输出编码无关，套用只会引入错误。OBS-011 的宿主乱码不适用于本后端。
        return ExecResult(
            exit_code=result.exit_code,
            stdout=(stdout_bytes or b"").decode("utf-8", errors="replace"),
            stderr=(stderr_bytes or b"").decode("utf-8", errors="replace"),
            duration_ms=round((perf_counter() - started) * 1000, 1),
        )

    def list_files(self, pattern: str) -> list[str]:
        """枚举容器 workspace 内匹配 glob 模式的文件，返回相对 /workspace 路径（排序）。

        用 exec("find . -type f -printf '%P\n'") 拿文件列表后 Python 侧 fnmatch 过滤。
        """
        effective = pattern if pattern else "*"
        result = self.exec("find . -type f -printf '%P\n'")
        if result.exit_code != 0:
            return []
        candidates = [line for line in result.stdout.splitlines() if line.strip()]
        matched = [
            rel
            for rel in candidates
            if _glob_match_posix(rel, effective)
        ]
        matched.sort()
        return matched

    def read_text(self, path: str) -> str:
        target = self.resolve_within_workspace(path)
        self.ensure_started()
        docker = importlib.import_module("docker")
        try:
            stream, _ = self._container.get_archive(str(target))
        except docker.errors.NotFound as exc:
            # Docker 的 get_archive 对不存在的文件抛 NotFound（OSError 子类，
            # 不是 FileNotFoundError）。统一映射成 FileNotFoundError，
            # 让调用方（如 WriteTool 读 before）能按预期捕获。
            raise FileNotFoundError(path) from exc
        with tarfile.open(fileobj=io.BytesIO(b"".join(stream)), mode="r:") as archive:
            member = next((item for item in archive.getmembers() if item.isfile()), None)
            if member is None:
                raise FileNotFoundError(path)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise FileNotFoundError(path)
            return extracted.read().decode("utf-8")

    def write_text(self, path: str, content: str) -> None:
        target = self.resolve_within_workspace(path)
        self.ensure_started()
        mkdir_result = self._container.exec_run(["mkdir", "-p", str(target.parent)])
        if mkdir_result.exit_code != 0:
            raise RuntimeError(f"无法创建 Workspace 目录 '{target.parent}'")

        payload = content.encode("utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            member = tarfile.TarInfo(name=target.name)
            member.size = len(payload)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(payload))
        if not self._container.put_archive(str(target.parent), buffer.getvalue()):
            raise RuntimeError(f"无法写入 Workspace 文件 '{target}'")

    def copy_in(self, host_path: Path, workspace_path: str) -> None:
        target = self.resolve_within_workspace(workspace_path)
        source = Path(host_path)
        if not source.exists():
            raise FileNotFoundError(source)

        self.ensure_started()
        mkdir_result = self._container.exec_run(["mkdir", "-p", str(target.parent)])
        if mkdir_result.exit_code != 0:
            raise RuntimeError(f"无法创建 Workspace 目录 '{target.parent}'")

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", dereference=False) as archive:
            archive.add(source, arcname=target.name, recursive=True)
        if not self._container.put_archive(str(target.parent), buffer.getvalue()):
            raise RuntimeError(f"无法导入 Host 路径 '{source}'")

    def resolve_within_workspace(self, path: str) -> PurePosixPath:
        """Resolve a model-supplied path with container-native POSIX semantics."""
        root = self.workspace_root
        raw = PurePosixPath(path.replace("\\", "/"))
        candidate = raw if raw.is_absolute() else root / raw
        resolved = PurePosixPath(posixpath.normpath(str(candidate)))
        if resolved != root and root not in resolved.parents:
            raise PermissionError(
                f"路径 '{path}' 解析为 '{resolved}'，越出 workspace '{root}' 边界，拒绝访问"
            )
        return resolved

    def stop(self) -> None:
        """停容器（保留 Volume 以便 resume）。幂等。"""
        if self._container is None:
            return
        docker = importlib.import_module("docker")
        try:
            self._container.reload()
            if self._container.status == "running":
                self._container.stop()
        except docker.errors.NotFound:
            pass
        finally:
            self._container = None

    def delete(self) -> None:
        """彻底清理：移除容器 + 删除 Volume。幂等。"""
        docker = importlib.import_module("docker")
        if self._container is not None:
            try:
                self._container.remove(force=True)
            except docker.errors.NotFound:
                pass
            finally:
                self._container = None
        else:
            # 跨进程：容器可能还在，按确定性名字查回再删。
            try:
                existing = self._client.containers.get(self._container_name)
            except docker.errors.NotFound:
                existing = None
            if existing is not None:
                existing.remove(force=True)
        try:
            self._client.volumes.get(self._volume_name).remove(force=True)
        except docker.errors.NotFound:
            pass
