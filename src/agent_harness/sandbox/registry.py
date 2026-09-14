"""WorkspaceRegistry：Session ↔ Sandbox 映射表的持久化管理。

05_SANDBOX_CODING_TOOLS.md §2 + 07_STORAGE_PERSISTENCE_RECOVERY.md §9 要求的恢复顺序
（load Session → load sandbox mapping → ensure sandbox started → ... → resume）在
第二步需要一张持久化的 session_id → sandbox 映射表。WorkspaceRegistry 就是这张表。

映射存为 JSON 文件（与 SessionStore 的 JSONL 同级技术，不引入 SQLite/Postgres）：
  <root>/workspaces/<session_id>.json

LocalSubprocessSandbox 后端：workspace 是真实目录，天然持久——进程重启后目录还在。
DockerSandbox 后端（Ticket D）：容器名/volume 名基于 session_id 确定性生成，
volume 持久，resume 时用确定性名字重启容器即可恢复 workspace。

本模块只负责映射管理和 Sandbox 实例重建，不改 Sandbox 路径边界（ADR-0001 不变）。
"""

from __future__ import annotations

import json
import os
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_harness.sandbox.base import Sandbox
from agent_harness.sandbox.local import LocalSubprocessSandbox
from agent_harness.sandbox.paths import canonical_workspace_path


class WorkspaceRegistry:
    """Session ↔ Sandbox 映射表的持久化管理器。"""

    def __init__(self, root: Path, backend: str = "local") -> None:
        """root 是映射表和 workspace 的根目录。backend='local'|'docker'。"""
        self._root = Path(root).resolve()
        self._backend = backend
        self._workspaces_dir = self._root / "workspaces"
        self._workspaces_dir.mkdir(parents=True, exist_ok=True)
        #: 进程内缓存：session_id → Sandbox 实例（避免重复重建）。
        self._cache: dict[str, Sandbox] = {}

    def create(self, session_id: str, *, workspace_root: Path | None = None) -> Sandbox:
        """为新 session 创建 Sandbox，持久化映射，返回已 ensure_started 的 Sandbox。

        如果映射已存在（同 session_id 再次 create），直接从缓存或重建返回已有 Sandbox。
        workspace_root 允许调用方指定实际工作目录（web 层的命名 workspace）；
        缺省用 <root>/workspaces/<session_id>。映射里记录真实目录——
        RecoveryCoordinator 据此恢复（R8-1）。

        映射里的路径是**规范化后**的（`canonical_workspace_path`，WS-1 AC5）：
        先 mkdir 是这里原本的行为（确保 workspace 目录存在），随后按 `fs.realpath`
        语义规范化，所以已存在的链接会被解析到目标。会话侧 `session/started` 的
        `cwd` 走同一个函数，故"日志里的路径"与"映射里的路径"对同一物理目录必然
        逐字符相等。
        """
        if session_id in self._cache:
            return self._cache[session_id]

        mapping = self._build_mapping(session_id)
        requested = (
            Path(workspace_root) if workspace_root is not None
            else Path(mapping["workspace_root"])
        )
        requested.mkdir(parents=True, exist_ok=True)
        workspace_root = Path(canonical_workspace_path(requested))
        workspace_root.mkdir(parents=True, exist_ok=True)
        mapping["workspace_root"] = str(workspace_root)

        sandbox = self._instantiate_sandbox(mapping)
        sandbox.ensure_started()

        self._write_mapping(session_id, mapping)
        self._cache[session_id] = sandbox
        return sandbox

    def get(self, session_id: str) -> Sandbox:
        """查回 session 的 Sandbox 实例（必要时从 JSON 重建并 ensure_started）。"""
        if session_id in self._cache:
            return self._cache[session_id]

        mapping = self._read_mapping(session_id)
        if mapping is None:
            raise KeyError(
                f"Session '{session_id}' 没有对应的 workspace 映射记录。"
            )

        sandbox = self._instantiate_sandbox(mapping)
        sandbox.ensure_started()

        self._cache[session_id] = sandbox
        return sandbox

    def exists(self, session_id: str) -> bool:
        """检查 session 是否有映射记录。"""
        return self._mapping_path(session_id).exists()

    def stop(self, session_id: str) -> None:
        """停止 session 的 Sandbox（保留 Volume/workspace 以便 resume）。幂等。

        跨进程安全：即使本进程没缓存该 Sandbox，也会从映射记录重建实例并停掉它。
        """
        sandbox = self._cache.get(session_id)
        if sandbox is None:
            # 跨进程恢复：进程重启后 cache 为空，但容器可能还在跑。
            mapping = self._read_mapping(session_id)
            if mapping is None:
                return  # 没有映射记录，幂等 no-op
            sandbox = self._instantiate_sandbox(mapping)
        sandbox.stop()
        self._cache.pop(session_id, None)

    def delete(self, session_id: str) -> None:
        """彻底清理 session 的 Sandbox 资源和映射（容器 + Volume + workspace 目录）。幂等。

        跨进程安全：即使本进程没缓存该 Sandbox，也会从映射记录重建实例再彻底销毁。
        """
        sandbox = self._cache.get(session_id)
        if sandbox is None:
            mapping = self._read_mapping(session_id)
            if mapping is None:
                # 没有映射记录——清理可能残留的孤儿 workspace 目录后返回。
                workspace_dir = self._workspaces_dir / session_id
                if workspace_dir.exists():
                    shutil.rmtree(workspace_dir, ignore_errors=True)
                return
            sandbox = self._instantiate_sandbox(mapping)
        sandbox.delete()
        self._cache.pop(session_id, None)
        mapping_file = self._mapping_path(session_id)
        if mapping_file.exists():
            mapping_file.unlink()

    def discard_session_artifacts(self, session_id: str) -> None:
        """硬删会话时丢弃 harness 自己造的两样沙箱工件。**绝不解引用映射**。幂等。

        只删本注册表用 `root + session_id` 自己拼出来的路径：

        - `<root>/workspaces/<session_id>.json`（映射记录）
        - `<root>/workspaces/<session_id>/`（默认形态的会话工作区）

        第二条为什么不需要再判"确实是默认形态"（#172 的原话）：这个路径**就是**默认形态
        的定义——它由本注册表用 root 与 session_id 拼成，只有 harness 会往里写（
        `create` 的默认分支、`resume_and_launch` 的无条件 mkdir 都写在同一个位置），
        用户自己的目录永远不在这个前缀下。判定因此是"写死的构造规则"，不是"读映射再
        决定删什么"——后者才会删到用户仓库。

        **为什么不用 `delete()`**（ADR-0029 D2）：`delete()` 走 `Sandbox.delete()`，
        本地后端是 `shutil.rmtree(self._workspace_root)`；而 ADR-0027 之后
        `workspace_root` 可能是**用户的真实目录**（cwd 会话），映射里就写着
        `D:\\some\\repo`。任何用它做硬删的路径都会删掉用户的仓库——所以那条路径
        今天不能有生产调用方（`docs/PHASE_STATUS.md` 已登记），本方法就是它的安全替代。

        映射指向别处时，只删映射文件本身，**不碰 `workspace_root`**（这是刻意的：
        用户目录不归 harness 处置）。
        """
        mapping_file = self._mapping_path(session_id)
        if mapping_file.exists():
            mapping_file.unlink()
        default_workspace = self._workspaces_dir / session_id
        if default_workspace.is_dir():
            shutil.rmtree(default_workspace, ignore_errors=True)
        self._cache.pop(session_id, None)

    # —— 内部方法 ——

    def _build_mapping(self, session_id: str) -> dict:
        """构造新 session 的映射字典。"""
        workspace_root = self._workspaces_dir / session_id
        mapping = {
            "session_id": session_id,
            "backend": self._backend,
            "workspace_root": str(workspace_root),
            "container_name": None,
            "volume_name": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if self._backend == "docker":
            # 确定性命名：基于 session_id，进程重启后能按名字找回容器/volume。
            mapping["container_name"] = f"agent-harness-{session_id}"
            mapping["volume_name"] = f"agent-harness-{session_id}"
        return mapping

    def _instantiate_sandbox(self, mapping: dict) -> Sandbox:
        """根据映射字典重建 Sandbox 实例。"""
        backend = mapping.get("backend", "local")
        workspace_root = Path(mapping["workspace_root"])

        if backend == "local":
            return LocalSubprocessSandbox(workspace_root=workspace_root)

        if backend == "docker":
            from agent_harness.sandbox.docker import DockerSandbox

            container_name = mapping.get("container_name") or None
            volume_name = mapping.get("volume_name") or None
            return DockerSandbox(
                container_name=container_name,
                volume_name=volume_name,
            )

        raise ValueError(f"未知的 Sandbox 后端: {backend}")

    def _mapping_path(self, session_id: str) -> Path:
        return self._workspaces_dir / f"{session_id}.json"

    def _write_mapping(self, session_id: str, mapping: dict) -> None:
        # temp + os.replace 原子落盘：truncate-in-place 写到一半崩溃会留下损坏
        # JSON，get()/stop()/delete() 从此对该 session 永久 JSONDecodeError
        # （resume 与清理双断，且不自愈）。同目录 rename 在两种平台都原子。
        path = self._mapping_path(session_id)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex[:8]}.tmp")
        try:
            tmp.write_text(
                json.dumps(mapping, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        finally:
            with suppress(OSError):
                tmp.unlink()

    def _read_mapping(self, session_id: str) -> dict | None:
        path = self._mapping_path(session_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
