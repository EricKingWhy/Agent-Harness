"""真实七牛端到端 Gate，显式运行 pytest -m qiniu。"""

import pytest

from agent_harness.config import Settings
from agent_harness.storage.s3_artifact import S3ArtifactStore
from tests.conftest import make_session
from tests.phase5_scenario import ARTIFACT_ID, run_phase5_scenario


@pytest.mark.qiniu
@pytest.mark.asyncio
async def test_phase5_real_qiniu_gate(tmp_path):
    settings = Settings()
    if not all((settings.artifact_store_endpoint, settings.artifact_store_bucket,
                settings.artifact_store_access_key, settings.artifact_store_secret_key,
                settings.artifact_store_region)):
        pytest.skip("Configure artifact_store_* for the real Phase 5 Gate")
    sdk = pytest.importorskip("aioboto3")
    session = make_session(tmp_path / "sessions")
    store = S3ArtifactStore(settings, session_id=session.session_id)
    try:
        await run_phase5_scenario(tmp_path, session, store)
        # 独立 Provider 实例仍可按同一 Session 命名空间找回细节。
        restored = S3ArtifactStore(settings, session_id=session.session_id)
        assert (await restored.inspect(ARTIFACT_ID, start_line=2501, end_line=2501)).lines == [
            {"line_number": 2501, "text": "output 2500"},
        ]
    finally:
        # 只清理本测试随机 Session 下的已知 key，不枚举或删除其他对象。
        async with sdk.Session().client(
            "s3", endpoint_url=settings.artifact_store_endpoint,
            region_name=settings.artifact_store_region,
            aws_access_key_id=settings.artifact_store_access_key.get_secret_value(),
            aws_secret_access_key=settings.artifact_store_secret_key.get_secret_value(),
        ) as client:
            await client.delete_object(Bucket=settings.artifact_store_bucket,
                                       Key=f"{session.session_id}/{ARTIFACT_ID}")
