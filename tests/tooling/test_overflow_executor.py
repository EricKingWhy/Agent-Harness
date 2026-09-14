"""真实 BashTool 经 Executor 溢出，Ledger 与 Artifact 保持一致。"""

from unittest.mock import Mock

import pytest

from agent_harness.sandbox.base import ExecResult, Sandbox
from agent_harness.storage import (
    OperationContext,
    OperationState,
    SqliteOperationLedger,
)
from agent_harness.storage.artifact import FakeArtifactStore
from agent_harness.tooling import PermissionPolicy, ToolExecutor, ToolRegistry
from agent_harness.tooling.overflow import ArtifactOverflowHandler
from agent_harness.tools import BashTool
from tests.conftest import make_session


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_bash_overflow_is_outside_retry_and_before_ledger_terminal(tmp_path, failure):
    class Store(FakeArtifactStore):
        async def save(self, *args, **kwargs):
            assert (await ledger.get(session.session_id, "call")).state == OperationState.RUNNING
            if failure:
                raise ConnectionError("storage offline")
            return await super().save(*args, **kwargs)

    session = make_session(tmp_path / "sessions")
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    store = Store()
    raw = "\n".join(f"output {i}" for i in range(5000))
    sandbox = Mock(spec=Sandbox)
    sandbox.exec.return_value = ExecResult(exit_code=1, stdout=raw, stderr="")
    registry = ToolRegistry()
    registry.register(BashTool(sandbox))
    executor = ToolExecutor(
        registry, policy=PermissionPolicy.DANGER_FULL_ACCESS, operation_ledger=ledger,
        overflow_handler=ArtifactOverflowHandler(store),
    )
    call = {"id": "call", "name": "bash", "args": {"command": "run-tests"}}
    context = OperationContext(session_id=session.session_id)
    if failure:
        # T5 (#135): fail-open — store unavailable → raw result kept.
        executions = await executor.execute_batch(
            [call], session=session, operation_context=context,
        )
        result = executions[0].result
        assert result.artifact_ref is None
        assert not any(e.type == "artifact/externalized" for e in session.events)
    else:
        executions = await executor.execute_batch(
            [call], session=session, operation_context=context,
        )
        result = executions[0].result
        persisted = await ledger.get(session.session_id, "call")
        assert persisted.state == OperationState.SUCCEEDED
        assert persisted.result_json == result.model_dump_json()
        assert persisted.artifact_ref == result.artifact_ref
        assert (await store.load(result.artifact_ref)).content == raw
        assert result.ok and result.data["exit_code"] == 1
        assert len(result.data["stdout"]) < 2000
    sandbox.exec.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_session", [True, False])
async def test_invalid_session_configuration_fails_before_side_effect(tmp_path, missing_session):
    session = make_session(tmp_path)
    sandbox = Mock(spec=Sandbox)
    registry = ToolRegistry()
    registry.register(BashTool(sandbox))
    executor = ToolExecutor(
        registry, policy=PermissionPolicy.DANGER_FULL_ACCESS,
        overflow_handler=ArtifactOverflowHandler(FakeArtifactStore()),
    )
    with pytest.raises(ValueError, match="session"):
        await executor.execute(
            {"id": "call", "name": "bash", "args": {"command": "run"}},
            session=None if missing_session else session,
            operation_context=OperationContext(session_id="different-session"),
        )
    sandbox.exec.assert_not_called()
