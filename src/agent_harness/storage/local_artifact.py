"""LocalArtifactStore：artifact 的本地文件系统 Provider（spec 06 §3 的**默认** Provider）。

规范原文（06 §3）："默认 Provider：Local filesystem：开发/小型部署；MinIO：正式大文件、
大量对象。" 本模块补上这句话里从未实现的那一半——此前只有 S3 / MinIO（远端）与 Fake
（内存），于是任何**没有**配置对象存储的部署都外置不出任何 artifact：溢出处理器
（`tooling/overflow.py`）是生产里唯一写入者，而它只在 S3 分支被创建
（`assembly.py`）——结果是读取接口（#185）永远回 503，界面（#186）看不到内容。

落盘形态
--------
    <artifact_dir>/<session_id>/<artifact_id>        内容（UTF-8）
    <artifact_dir>/<session_id>/<artifact_id>.json   元数据（旁挂，可缺）

三个 Key 决定：

1. **与对象存储的 key 约定逐段同构**（`{session_id}/{artifact_id}`）：三个 Provider
   因此同形，#185 的读取接口与 `web/artifacts.py` 的 store 选择保持 Provider 无关。
2. **session 段必须是单个名字段**（`SESSION_KEY_PATTERN`）：它会被拼进文件系统路径，
   不校验时 `..` / 反斜杠段能越出 artifact 根目录。与 session 层同一条规则。
3. **元数据旁挂而可缺**：对象存储上只存得下内容与 ContentType（所以 S3/MinIO 的 load
   只能如实返回 `None`）；本地没有这个限制，就把四项元数据存下来。但旁挂文件缺失时
   **不报错**——内容还在、id 自证，元数据如实为 `None`（#185 AC4 的"缺失即 None"）。
   旁挂文件是**内容之后**写的，所以崩溃只会留下"有内容、没元数据"，不会留下
   "有元数据、没内容"的假记录。

为什么不放 workspace 底下：ADR-0027 之后 workspace 可能指向**用户的真实仓库**，
artifact 绝不能落进去——那条路径会话硬删时不许碰（ADR-0029 D2）。
"""

from __future__ import annotations

import json
import os
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_harness.config import Settings
from agent_harness.storage.artifact import (
    ARTIFACT_ID_PATTERN,
    SESSION_KEY_PATTERN,
    Artifact,
    ArtifactSlice,
    ArtifactStore,
    compute_artifact_id,
    slice_artifact,
)

#: 旁挂元数据的后缀。用后缀而不是把元数据塞进内容头部：内容必须**逐字节**等于
#: 模型当初产出的大输出（`compute_artifact_id` 要对得上），塞头部就会改变内容。
_META_SUFFIX = ".json"


class LocalArtifactStore(ArtifactStore):
    """本地文件系统上的 ArtifactStore（默认 Provider，零外部依赖）。"""

    def __init__(self, settings: Settings, *, session_id: str) -> None:
        root = settings.artifact_dir.strip()
        if not root:
            raise ValueError("LocalArtifactStore requires artifact_dir")
        if not SESSION_KEY_PATTERN.fullmatch(session_id):
            # 不构造带越界段的实例：错误越早、越靠近来源越好（与 path 边界同一纪律）。
            raise ValueError(
                f"session_id must be a single safe name segment: {session_id!r}"
            )
        # resolve() 不要求路径存在（strict=False 默认）：根目录在 save 时才创建。
        self._root = Path(root).resolve()
        self._session_id = session_id
        self._dir = self._root / session_id

    async def save(
        self,
        session_id: str,
        content: str,
        *,
        mime_type: str,
        source_tool: str,
        tool_call_id: str,
    ) -> Artifact:
        if session_id != self._session_id:
            raise ValueError("save session_id must match the store namespace")
        body = content.encode("utf-8")
        artifact = Artifact(
            artifact_id=compute_artifact_id(content),
            session_id=session_id,
            size=len(body),
            mime_type=mime_type,
            source_tool=source_tool,
            tool_call_id=tool_call_id,
            created_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
        )
        # 内容与元数据都是 temp + os.replace 原子落盘（与 SessionStore / 映射表同纪律）：
        # 半写的文件会被 `load` 的 hash 校验判成损坏 → 一个正常写入的 artifact 变成
        # 永久不可读（不自愈）。同目录 rename 在两种平台都原子。
        self._dir.mkdir(parents=True, exist_ok=True)
        self._write_atomic(self._content_path(artifact.artifact_id), body)
        # 元数据直接由 `Artifact` 序列化（去掉 content）：手抄一份字段表会在 `Artifact`
        # 加字段时静默漂移（#192 批 1 审查）。
        meta = artifact.model_dump(exclude={"content"})
        self._write_atomic(
            self._meta_path(artifact.artifact_id),
            json.dumps(meta, ensure_ascii=False).encode("utf-8"),
        )
        return artifact

    async def load(self, artifact_id: str) -> Artifact:
        # 形态校验先做（与 S3/MinIO 一致，#185 AC3）：畸形 id 不得进入路径拼接。
        if not ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
            raise KeyError(f"Artifact '{artifact_id}' does not exist")
        path = self._content_path(artifact_id)
        try:
            body = path.read_bytes()
        except FileNotFoundError as error:
            # not-found 是契约内的结果，不是异常路径：统一 KeyError（三实现同契约）。
            # 只接 not-found——与远端 Provider 同形状（那里也只把 NoSuchKey 映射成
            # KeyError，其余 SDK 异常照常外泄成 500）。把 PermissionError 之类也吞成
            # 404 会把"服务端异常"谎报成"不存在"。
            raise KeyError(f"Artifact '{artifact_id}' does not exist") from error
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError as error:
            # 与 S3/MinIO 同口径：损坏/被外部改动的内容不得以 UnicodeDecodeError 外泄
            # （会变 500），也不得当成合法内容——统一 KeyError → 404。
            raise KeyError(
                f"Artifact '{artifact_id}' is not valid UTF-8 "
                "(file modified or corrupted out-of-band)"
            ) from error
        # content-addressable 自证：id 就是 sha256(content)[:16]，所以"内容是否还是
        # 当初那份"不需要额外校验字段。
        if compute_artifact_id(content) != artifact_id:
            raise KeyError(
                f"Artifact '{artifact_id}' content hash mismatch "
                "(file modified or corrupted out-of-band)"
            )
        meta = self._read_meta(artifact_id)
        return Artifact(
            artifact_id=artifact_id,
            session_id=self._session_id,
            size=len(body),
            mime_type=meta.get("mime_type") or "application/octet-stream",
            # 旁挂元数据可缺（崩溃窗口 / 外部清理）：如实给 None，不伪造 ""（#185 AC4）。
            source_tool=_optional_str(meta.get("source_tool")),
            tool_call_id=_optional_str(meta.get("tool_call_id")),
            created_at=_optional_str(meta.get("created_at")),
            content=content,
        )

    async def inspect(
        self,
        artifact_id: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        keyword: str | None = None,
        max_lines: int = 200,
        max_chars_per_line: int = 2000,
    ) -> ArtifactSlice:
        artifact = await self.load(artifact_id)
        assert artifact.content is not None
        return slice_artifact(
            artifact_id,
            artifact.content,
            start_line=start_line,
            end_line=end_line,
            keyword=keyword,
            max_lines=max_lines,
            max_chars_per_line=max_chars_per_line,
        )

    # —— 内部方法 ——

    def _content_path(self, artifact_id: str) -> Path:
        return self._dir / artifact_id

    def _meta_path(self, artifact_id: str) -> Path:
        return self._dir / f"{artifact_id}{_META_SUFFIX}"

    def _read_meta(self, artifact_id: str) -> dict:
        """读旁挂元数据；缺失或损坏都返回 `{}`（内容才是事实，元数据是便利）。"""
        path = self._meta_path(artifact_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _write_atomic(path: Path, body: bytes) -> None:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex[:8]}.tmp")
        try:
            tmp.write_bytes(body)
            os.replace(tmp, path)
        finally:
            with suppress(OSError):
                tmp.unlink()


def _optional_str(value: object) -> str | None:
    """元数据字段 → `str | None`：非字符串一律 None（不把类型错误伪装成空串）。"""
    return value if isinstance(value, str) and value else None


def discard_local_artifacts(settings: Settings, session_id: str) -> None:
    """会话硬删时丢弃该会话的**本地** artifact 目录。幂等。

    窄方法，沿用 `WorkspaceRegistry.discard_session_artifacts` 的既有模式
    （ADR-0029 D2）：**不读映射**、只删"用 setting + session_id 自己拼出来的路径"。
    这里的路径完全由 `settings.artifact_dir` 与 session_id 拼成，只有 harness 会往里写，
    所以删除判定是"写死的构造规则"，碰不到用户目录——这正是 ADR-0029 D2 要求的安全形状。

    **两条刻意不做的**（记录在案，不在本票范围）：
    - 配置了 S3/MinIO 时**远端对象不删**（那些 Provider 没有 delete）；
    - 不做任何自动 TTL / 体积清理（ADR-0004 明确不做自动 TTL；ADR-0029 Non-Goals 同款）。
      于是 artifact 的生命周期 = 会话生命周期：只要会话还在，它的引用就必然可解析。
    """
    root = settings.artifact_dir.strip()
    if not root:
        return
    if not SESSION_KEY_PATTERN.fullmatch(session_id):
        # 硬删入口已校验过 id 形态（422），这里再挡一次：本函数只允许删自己拼得出的路径。
        return
    target = Path(root).resolve() / session_id
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
