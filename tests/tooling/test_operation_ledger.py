"""Operation Ledger integration at the public Tool and ToolExecutor seams."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from agent_harness.storage import (
    OperationContext,
    OperationState,
    SqliteOperationLedger,
)
from agent_harness.tooling import (
    ErrorCode,
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
)


class _Args(BaseModel):
    label: str
    count: int


class _IdentityTool(Tool):
    @property
    def name(self) -> str:
        return "identity"

    @property
    def description(self) -> str:
        return "Return validated arguments."

    @property
    def args_schema(self) -> type[BaseModel]:
        return _Args

    async def execute(self, args: BaseModel) -> ToolResult:
        return ToolResult.success("ok", data=args.model_dump())


class _LedgerObservingTool(_IdentityTool):
    def __init__(self, ledger: SqliteOperationLedger, call_id: str,
                 session_id: str = "session-1") -> None:
        self._ledger = ledger
        self._call_id = call_id
        self._session_id = session_id
        self.observed_states: list[OperationState] = []

    async def execute(self, args: BaseModel) -> ToolResult:
        operation = await self._ledger.get(self._session_id, self._call_id)
        assert operation is not None
        self.observed_states.append(operation.state)
        return await super().execute(args)


class _FlakyLedgerObservingTool(_LedgerObservingTool):
    async def execute(self, args: BaseModel) -> ToolResult:
        operation = await self._ledger.get(self._session_id, self._call_id)
        assert operation is not None
        self.observed_states.append(operation.state)
        if len(self.observed_states) < 3:
            return ToolResult.failure(
                "temporary",
                error_code=ErrorCode.TRANSIENT_ERROR,
                retryable=True,
            )
        return ToolResult.success("recovered")


class _BlockingTool(_IdentityTool):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def execute(self, args: BaseModel) -> ToolResult:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _FailingTool(_IdentityTool):
    async def execute(self, args: BaseModel) -> ToolResult:
        return ToolResult.failure(
            "deterministic failure",
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            retryable=False,
        )


def test_default_args_identity_is_stable_and_preserves_unicode() -> None:
    tool = _IdentityTool()

    first = tool.args_identity({"label": "中文", "count": 2})
    second = tool.args_identity({"count": 2, "label": "中文"})

    assert first == second
    assert first == '{"count": 2, "label": "中文"}'


@pytest.mark.asyncio
async def test_tool_execution_is_durable_before_and_after_side_effect(
    tmp_path: Path,
) -> None:
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    tool = _LedgerObservingTool(ledger, "call-1")
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(registry, operation_ledger=ledger)

    execution = await executor.execute(
        {"id": "call-1", "name": "identity", "args": {"label": "中文", "count": 2}},
        operation_context=OperationContext(
            session_id="session-1", run_id="run-1", agent_id="agent-1"
        ),
    )

    persisted = await ledger.get("session-1", "call-1")
    assert execution.result.ok is True
    assert tool.observed_states == [OperationState.RUNNING]
    assert persisted is not None
    assert persisted.state is OperationState.SUCCEEDED
    assert persisted.session_id == "session-1"
    assert persisted.run_id == "run-1"
    assert persisted.agent_id == "agent-1"
    assert persisted.args_identity == '{"count": 2, "label": "中文"}'
    assert persisted.result_json == execution.result.model_dump_json()


@pytest.mark.asyncio
async def test_retries_share_one_operation(tmp_path: Path) -> None:
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    tool = _FlakyLedgerObservingTool(ledger, "call-retry")
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(registry, operation_ledger=ledger)
    context = OperationContext(session_id="session-1", run_id="run-1")

    execution = await executor.execute(
        {"id": "call-retry", "name": "identity", "args": {"label": "x", "count": 1}},
        operation_context=context,
    )

    operations = await ledger.list_for_session("session-1")
    assert execution.result.ok is True
    assert execution.result.metadata["attempt"] == 3
    assert tool.observed_states == [OperationState.RUNNING] * 3
    assert len(operations) == 1
    assert operations[0].state is OperationState.SUCCEEDED


@pytest.mark.asyncio
async def test_cancelled_execution_is_recorded_as_cancelled(tmp_path: Path) -> None:
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    tool = _BlockingTool()
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(registry, operation_ledger=ledger)

    task = asyncio.create_task(
        executor.execute(
            {"id": "call-cancel", "name": "identity", "args": {"label": "x", "count": 1}},
            operation_context=OperationContext(session_id="session-1"),
        )
    )
    await tool.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    operation = await ledger.get("session-1", "call-cancel")
    assert operation is not None
    assert operation.state is OperationState.CANCELLED
    assert operation.finished_at is not None


@pytest.mark.asyncio
async def test_failed_execution_persists_failure_result(tmp_path: Path) -> None:
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    registry = ToolRegistry()
    registry.register(_FailingTool())
    executor = ToolExecutor(registry, operation_ledger=ledger)

    execution = await executor.execute(
        {"id": "call-fail", "name": "identity", "args": {"label": "x", "count": 1}},
        operation_context=OperationContext(session_id="session-1"),
    )

    operation = await ledger.get("session-1", "call-fail")
    assert execution.result.ok is False
    assert operation is not None
    assert operation.state is OperationState.FAILED
    assert operation.result_json == execution.result.model_dump_json()
