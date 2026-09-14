"""AgentRuntime ordering contract for Ledger-first Tool execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from agent_harness.agent import AgentRuntime
from agent_harness.session import (
    MODEL_COMPLETED,
    TOOL_CALL,
    TOOL_RESULT,
    JsonlSessionStore,
    Session,
)
from agent_harness.storage import OperationState, SqliteOperationLedger
from agent_harness.tooling import Tool, ToolExecutor, ToolRegistry, ToolResult
from tests.scripted_model import ScriptedModel


class _NoArgs(BaseModel):
    pass


class _OrderingTool(Tool):
    def __init__(
        self,
        ledger: SqliteOperationLedger,
        session: Session,
        call_id: str,
    ) -> None:
        self._ledger = ledger
        self._session = session
        self._call_id = call_id
        self.state_during_execute: OperationState | None = None
        self.event_types_during_execute: list[str] = []

    @property
    def name(self) -> str:
        return "observe_order"

    @property
    def description(self) -> str:
        return "Observe durable state at the side-effect boundary."

    @property
    def args_schema(self) -> type[BaseModel]:
        return _NoArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        operation = await self._ledger.get(self._session.session_id, self._call_id)
        assert operation is not None
        self.state_during_execute = operation.state
        self.event_types_during_execute = [event.type for event in self._session.events]
        return ToolResult.success("done")


class _LegacyOrderingTool(Tool):
    def __init__(self, session: Session) -> None:
        self._session = session
        self.event_types_during_execute: list[str] = []

    @property
    def name(self) -> str:
        return "legacy_order"

    @property
    def description(self) -> str:
        return "Observe event ordering without durable Operation tracking."

    @property
    def args_schema(self) -> type[BaseModel]:
        return _NoArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        self.event_types_during_execute = [event.type for event in self._session.events]
        return ToolResult.success("done")


@pytest.mark.asyncio
async def test_runtime_persists_ledger_before_tool_conversation_events(
    tmp_path: Path,
) -> None:
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    session = Session.start(JsonlSessionStore(tmp_path / "sessions"))
    tool = _OrderingTool(ledger, session, "call-order")
    registry = ToolRegistry()
    registry.register(tool)
    model = ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call-order", "name": "observe_order", "args": {}}
                ],
            ),
            AIMessage(content="complete"),
        ]
    )
    runtime = AgentRuntime(
        model,
        registry,
        ToolExecutor(registry, operation_ledger=ledger),
    )

    await runtime.run(session, "run the tool")

    operation = await ledger.get(session.session_id, "call-order")
    assert tool.state_during_execute is OperationState.RUNNING
    assert MODEL_COMPLETED not in tool.event_types_during_execute
    assert operation is not None
    assert operation.state is OperationState.SUCCEEDED
    event_types = [event.type for event in session.events]
    # ADR-0016 §4.1：TOOL_CALL 由 runtime 预持久化（先于延迟写入的
    # model/completed），不变量收敛为 call < result 的会话配对 + Ledger
    # RUNNING 先于 execute（上方 state_during_execute 断言）。
    assert event_types.index(TOOL_CALL) < event_types.index(TOOL_RESULT)


@pytest.mark.asyncio
async def test_runtime_preserves_eager_events_without_operation_ledger(
    tmp_path: Path,
) -> None:
    session = Session.start(JsonlSessionStore(tmp_path / "sessions"))
    tool = _LegacyOrderingTool(session)
    registry = ToolRegistry()
    registry.register(tool)
    model = ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call-legacy", "name": "legacy_order", "args": {}}
                ],
            ),
            AIMessage(content="complete"),
        ]
    )
    runtime = AgentRuntime(model, registry, ToolExecutor(registry))

    await runtime.run(session, "run the tool")

    assert MODEL_COMPLETED in tool.event_types_during_execute
