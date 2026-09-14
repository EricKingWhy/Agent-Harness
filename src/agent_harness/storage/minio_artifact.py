"""MinIO-backed ArtifactStore for externalized large tool results.

Phase Multiturn T5 (#135): when a tool result exceeds the overflow threshold,
the raw content is externalized to MinIO (S3-compatible). The session keeps
only a truncated summary + artifact_ref. The model can read back local slices
via the ``read_artifact`` tool.

Design notes:
- Content-addressable: ``artifact_id = sha256(content)[:16]``.
- Session-scoped namespace: S3 key = ``{session_id}/{artifact_id}``.
- Verification on load: recomputes the hash and compares.
- Graceful degradation: if MinIO is unreachable during ``save``, the handler
  falls back to keeping the original (untruncated) tool result in-session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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


class MinioArtifactStore(ArtifactStore):
    """S3-compatible store backed by MinIO for externalized large tool results.

    Unlike the generic ``S3ArtifactStore``, this store is purpose-built for
    the T5 overflow path: it stores raw tool output under a session-scoped
    key and verifies content integrity on load.
    """

    def __init__(self, settings: Settings, *, session_id: str) -> None:
        # 键段形态与 S3/Local 共用一份定义（`storage/artifact.py`）：三个 Provider 的键
        # 都是 `{session_id}/{artifact_id}`，"同一条规则"不该有一处不校验（#192 批 1 审查）。
        if not SESSION_KEY_PATTERN.fullmatch(session_id):
            raise ValueError("session_id must be a single safe key segment")
        access_key = settings.minio_access_key.get_secret_value()
        secret_key = settings.minio_secret_key.get_secret_value()
        if not all(
            (
                settings.minio_endpoint,
                settings.minio_bucket,
                access_key,
                secret_key,
            )
        ):
            raise ValueError("MinioArtifactStore requires minio_* configuration")
        try:
            sdk = __import__("aioboto3")
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "MinioArtifactStore requires pip install 'intelligence-agent[artifact]'"
            ) from error
        self._sdk_session = sdk.Session()
        self._client_error = __import__(
            "botocore.exceptions", fromlist=["ClientError"]
        ).ClientError
        config_type = __import__("botocore.config", fromlist=["Config"]).Config
        self._session_id = session_id
        self._bucket = settings.minio_bucket
        self._client_kwargs: dict[str, Any] = {
            "endpoint_url": settings.minio_endpoint,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "config": config_type(
                signature_version="s3v4", s3={"addressing_style": "path"}
            ),
        }

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
        async with self._sdk_session.client("s3", **self._client_kwargs) as client:
            await client.put_object(
                Bucket=self._bucket,
                Key=f"{session_id}/{artifact.artifact_id}",
                Body=body,
                ContentType=mime_type,
            )
        return artifact

    async def load(self, artifact_id: str) -> Artifact:
        # 形态校验必须与 S3ArtifactStore 一致（#185 AC3）：此前这里直接拿 id 拼 key
        # 去请求对象存储，畸形 id 会以 SDK 异常的形状外泄——错误契约不统一。
        # 与 S3 一致地先判形态，再走网络，统一以 KeyError 表示"不存在/不可读"。
        if not ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
            raise KeyError(f"Artifact '{artifact_id}' does not exist")
        async with self._sdk_session.client("s3", **self._client_kwargs) as client:
            try:
                response = await client.get_object(
                    Bucket=self._bucket,
                    Key=f"{self._session_id}/{artifact_id}",
                )
            except self._client_error as error:
                # 与 S3ArtifactStore 一致：对象不存在是**契约内的 not-found**，统一成
                # KeyError；否则它会以 SDK 异常的形状漏到 HTTP 层变成 500（#185 审查 P1）。
                if error.response.get("Error", {}).get("Code") == "NoSuchKey":
                    raise KeyError(f"Artifact '{artifact_id}' does not exist") from error
                raise
            async with response["Body"] as stream:
                body = await stream.read()
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError as error:
            # 与 S3 同口径：损坏/截断的对象不得以 UnicodeDecodeError 外泄（会变 500），
            # 也不得静默当成合法内容——统一 KeyError → 404。
            raise KeyError(
                f"Artifact '{artifact_id}' is not valid UTF-8 "
                "(object modified or corrupted out-of-band)"
            ) from error
        # Content-addressable verification: artifact_id is sha256(content)[:16].
        if compute_artifact_id(content) != artifact_id:
            raise KeyError(
                f"Artifact '{artifact_id}' content hash mismatch "
                "(object modified or corrupted out-of-band)"
            )
        return Artifact(
            artifact_id=artifact_id,
            session_id=self._session_id,
            size=len(body),
            mime_type=response.get("ContentType", "application/octet-stream"),
            # save 未持久化这三项（对象上只有内容和 ContentType），所以 load 无法恢复：
            # 如实给 None，而不是伪造 ""（#185 AC4）。
            source_tool=None,
            tool_call_id=None,
            created_at=None,
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
