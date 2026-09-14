"""显式运行：uv run --extra artifact python -X utf8 -m pytest -m qiniu。"""

from uuid import uuid4

import pytest

from agent_harness.config import Settings
from agent_harness.storage.s3_artifact import S3ArtifactStore


@pytest.mark.qiniu
@pytest.mark.asyncio
async def test_qiniu_save_load_inspect():
    settings = Settings()
    if not all((settings.artifact_store_endpoint, settings.artifact_store_bucket,
                settings.artifact_store_access_key, settings.artifact_store_secret_key,
                settings.artifact_store_region)):
        pytest.skip("Configure artifact_store_* credentials to run Qiniu integration")
    sdk = pytest.importorskip("aioboto3")
    session_id = f"artifact-test-{uuid4().hex}"
    store = S3ArtifactStore(settings, session_id=session_id)
    artifact_id = None
    try:
        saved = await store.save(session_id, "第一行\nneedle\nlast", mime_type="text/plain",
                                 source_tool="integration", tool_call_id="test-call")
        artifact_id = saved.artifact_id
        # 用新实例验证无进程内索引依赖。
        restored = S3ArtifactStore(settings, session_id=session_id)
        assert (await restored.load(artifact_id)).content == "第一行\nneedle\nlast"
        assert (await restored.inspect(artifact_id, keyword="needle")).lines == [
            {"line_number": 2, "text": "needle"},
        ]
    finally:
        if artifact_id is not None:
            async with sdk.Session().client(
                "s3", endpoint_url=settings.artifact_store_endpoint,
                region_name=settings.artifact_store_region,
                aws_access_key_id=settings.artifact_store_access_key.get_secret_value(),
                aws_secret_access_key=settings.artifact_store_secret_key.get_secret_value(),
            ) as client:
                await client.delete_object(
                    Bucket=settings.artifact_store_bucket, Key=f"{session_id}/{artifact_id}",
                )
