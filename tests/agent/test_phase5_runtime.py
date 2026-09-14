"""离线回归证据；真实七牛 Gate 另见 tests/integration/test_phase5_qiniu.py。"""

import pytest

from agent_harness.storage.artifact import FakeArtifactStore
from tests.conftest import make_session
from tests.phase5_scenario import run_phase5_scenario


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_phase5_runtime_offline(tmp_path, stream):
    session = make_session(tmp_path / "sessions")
    await run_phase5_scenario(tmp_path, session, FakeArtifactStore(), stream=stream)
