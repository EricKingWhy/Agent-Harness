"""Session-scoped S3 ArtifactStore；SDK 仅在构造 Provider 时加载。"""

import importlib
import json
from datetime import UTC, datetime

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


class S3ArtifactStore(ArtifactStore):
    """绑定 Session 命名空间，无需内存索引即可恢复 artifact_id 的 S3 key。"""

    def __init__(self, settings: Settings, *, session_id: str) -> None:
        # 键段形态用共享定义（`storage/artifact.py`）：这条规则三个 Provider 与
        # session 层共用一份，各写一个正则字面量迟早漂移（#192 审查发现这里曾是第二份）。
        if not SESSION_KEY_PATTERN.fullmatch(session_id):
            raise ValueError("session_id must be a single safe key segment")
        # SecretStr('') 为 falsy（truthiness 基于密钥值长度）："是否已配置"
        # 判断可直接用字段本身（与 str 时代语义一致）。
        access_key = settings.artifact_store_access_key.get_secret_value()
        secret_key = settings.artifact_store_secret_key.get_secret_value()
        if not all((settings.artifact_store_endpoint, settings.artifact_store_bucket,
                    access_key, secret_key,
                    settings.artifact_store_region)):
            raise ValueError("S3ArtifactStore requires artifact_store_* configuration")
        try:
            sdk = importlib.import_module("aioboto3")
        except ModuleNotFoundError as error:
            raise RuntimeError("S3ArtifactStore requires pip install 'intelligence-agent[artifact]'") from error
        self._sdk_session = sdk.Session()
        self._client_error = importlib.import_module("botocore.exceptions").ClientError
        config_type = importlib.import_module("botocore.config").Config
        self._session_id = session_id
        self._bucket = settings.artifact_store_bucket
        self._client_kwargs = {
            "endpoint_url": settings.artifact_store_endpoint,
            "region_name": settings.artifact_store_region,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "config": config_type(signature_version="s3v4", s3={"addressing_style": "path"}),
        }

    async def save(
        self, session_id: str, content: str, *, mime_type: str,
        source_tool: str, tool_call_id: str,
    ) -> Artifact:
        if session_id != self._session_id:
            raise ValueError("save session_id must match the store namespace")
        body = content.encode("utf-8")
        artifact = Artifact(
            artifact_id=compute_artifact_id(content), session_id=session_id,
            size=len(body), mime_type=mime_type, source_tool=source_tool,
            tool_call_id=tool_call_id,
            created_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
        )
        async with self._sdk_session.client("s3", **self._client_kwargs) as client:
            await client.put_object(
                Bucket=self._bucket, Key=f"{session_id}/{artifact.artifact_id}",
                Body=body, ContentType=mime_type,
                Metadata={"artifact": json.dumps(artifact.model_dump(exclude={"content"}),
                                                  ensure_ascii=True)},
            )
        return artifact

    async def load(self, artifact_id: str) -> Artifact:
        if not ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
            raise KeyError(f"Artifact '{artifact_id}' does not exist")
        async with self._sdk_session.client("s3", **self._client_kwargs) as client:
            try:
                response = await client.get_object(
                    Bucket=self._bucket, Key=f"{self._session_id}/{artifact_id}",
                )
            except self._client_error as error:
                if error.response.get("Error", {}).get("Code") == "NoSuchKey":
                    raise KeyError(f"Artifact '{artifact_id}' does not exist") from error
                raise
            async with response["Body"] as stream:
                body = await stream.read()
        # 先验哈希后解码：损坏对象可能在 decode 前就被识破（UnicodeDecodeError
        # 不外泄——错误契约统一是 KeyError，与 id 非法/对象缺失一致）。
        artifact = Artifact.model_validate_json(response["Metadata"]["artifact"])
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KeyError(
                f"Artifact '{artifact_id}' is not valid UTF-8 "
                "(object modified or corrupted out-of-band)"
            ) from error
        # 内容寻址自验证：artifact_id 就是 sha256(content)[:16]，读回时重算比对。
        # S3 对象可能被带外覆盖/截断——静默把错误内容当 artifact 交给模型违背
        # "内容寻址 = id 可验证"的承诺（不验证的 hash 只是摆设）。
        if compute_artifact_id(content) != artifact_id:
            raise KeyError(
                f"Artifact '{artifact_id}' content hash mismatch "
                "(object modified or corrupted out-of-band)"
            )
        return artifact.model_copy(update={"content": content})

    async def inspect(
        self, artifact_id: str, *, start_line: int | None = None,
        end_line: int | None = None, keyword: str | None = None, max_lines: int = 200,
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
