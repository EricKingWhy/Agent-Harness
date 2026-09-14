"""delegation 事件 + lineage + Ledger agent_id（Phase 13 T3, #84, ADR-0015 决策 6）。

契约：
- 两个新持久化事件 agent/delegation-started / agent/delegation-finished
  （过词表、非 stream-only、gen_event_types 同步）；
- delegate 工具经 ToolResult.pending_events（exclude 出模型可见 JSON）产生
  两条事件：started {target, task, child_session_id}、finished {target,
  child_session_id, status, summary}；executor 落盘顺序 tool/call → 两条
  delegation 事件 → tool/result；
- lineage：child_session_id 可定位 child JSONL；
- child runtime 的 run/started 与 Ledger 归因 agent_id = profile 名（不再
  全是 "default"）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from agent_harness.agent.factory import AgentFactory
from agent_harness.multiagent.provider import InProcessSubagentProvider
from agent_harness.multiagent.tools import DelegateTool
from agent_harness.sandbox import WorkspaceRegistry
from agent_harness.session import SESSION_STARTED, USER_MESSAGE, Session
from agent_harness.session.event import (
    EVENT_TYPES,
    STREAM_ONLY_TYPES,
)
from agent_harness.session.store import JsonlSessionStore
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.scripted_model import ScriptedModel


class _EchoArgs(BaseModel):
    text: str = Field(default="x", description="回显")


class EchoTool:
    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return "read"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EchoArgs

    async def execute(self, args: _EchoArgs) -> object:
        from agent_harness.tooling import ToolResult

        return ToolResult.success(message=args.text)


def _activated_tool(tmp_path: Path, child_model=None):
    store = JsonlSessionStore(tmp_path / "sessions")
    workspace_registry = WorkspaceRegistry(root=tmp_path / "workspaces")
    workspace_registry.create("parent-0001", workspace_root=tmp_path / "ws")

    provider = InProcessSubagentProvider()
    tool = DelegateTool(provider)
    factory = AgentFactory(
        model=child_model or ScriptedModel([AIMessage(content="child 完成")]),
        primary_model_name="main-model",
    )
    source_registry = ToolRegistry()
    source_registry.register(EchoTool())
    source_registry.register(tool)
    provider.activate(
        factory=factory, source_registry=source_registry,
        session_store=store, workspace_registry=workspace_registry,
        parent_session_id="parent-0001",
    )
    return tool, provider


def _args(target: str, task: str) -> object:
    return type("_Args", (), {"target": target, "task": task,
                              "constraints": []})()


class TestDelegationEventVocabulary:
    def test_both_events_in_event_types_not_stream_only(self):
        from agent_harness.session.event import (
            AGENT_DELEGATION_FINISHED,
            AGENT_DELEGATION_STARTED,
        )

        assert AGENT_DELEGATION_STARTED == "agent/delegation-started"
        assert AGENT_DELEGATION_FINISHED == "agent/delegation-finished"
        assert AGENT_DELEGATION_STARTED in EVENT_TYPES
        assert AGENT_DELEGATION_FINISHED in EVENT_TYPES
        assert not ({AGENT_DELEGATION_STARTED, AGENT_DELEGATION_FINISHED}
                    & STREAM_ONLY_TYPES)


class TestDelegatePendingEvents:
    @pytest.mark.asyncio
    async def test_delegate_carries_started_and_finished(self, tmp_path):
        tool, provider = _activated_tool(tmp_path)

        result = await tool.execute(_args("coding", "实现一个函数"))

        child = provider.last_child_sessions[-1]
        assert result.pending_events == [
            ("agent/delegation-started", {
                "target": "coding", "task": "实现一个函数",
                "child_session_id": child.session_id,
            }),
            ("agent/delegation-finished", {
                "target": "coding", "child_session_id": child.session_id,
                "status": "completed", "summary": "child 完成",
            }),
        ]

    @pytest.mark.asyncio
    async def test_pending_events_excluded_from_model_visible_json(self, tmp_path):
        """pending_events 是 durable 事件通道，不是模型可见内容——必须 exclude。"""
        tool, _ = _activated_tool(tmp_path)
        result = await tool.execute(_args("coding", "x"))
        assert "pending_events" not in result.model_dump_json()

    @pytest.mark.asyncio
    async def test_executor_persists_events_in_order(self, tmp_path):
        """executor 落盘顺序：tool/call → delegation-started → finished → tool/result。"""
        store = JsonlSessionStore(tmp_path / "sessions")
        workspace_registry = WorkspaceRegistry(root=tmp_path / "workspaces")
        workspace_registry.create("p1", workspace_root=tmp_path / "ws")
        provider = InProcessSubagentProvider()
        tool = DelegateTool(provider)
        source_registry = ToolRegistry()
        source_registry.register(tool)
        provider.activate(
            factory=AgentFactory(model=ScriptedModel([AIMessage(content="done")])),
            source_registry=source_registry,
            session_store=store, workspace_registry=workspace_registry,
            parent_session_id="p1",
        )
        registry = ToolRegistry()
        registry.register(tool)

        session = Session(
            session_id="sess-exec", store=JsonlSessionStore(tmp_path / "s2"),
            sandbox=workspace_registry.get("p1"),
        )
        session.append(SESSION_STARTED, {})
        session.append(USER_MESSAGE, {"content": "派活"})
        executor = ToolExecutor(registry)

        from agent_harness.storage import OperationContext
        from agent_harness.tooling import ToolCall

        executions = await executor.execute_batch(
            [ToolCall.normalize({"id": "call_0001", "name": "delegate",
                                 "args": {"target": "coding", "task": "做"}})],
            session=session,
            operation_context=OperationContext(
                session_id="sess-exec", run_id="r1", agent_id="main",
            ),
        )
        # ADR-0016 §4.1：TOOL_CALL 由 runtime 预持久化，pending 事件走
        # emit_pending_events（tool/call 之后、tool/result 之前）。
        executor.emit_call_event(
            session, tool_call_id=executions[0].tool_call_id,
            tool_name="delegate", args={"target": "coding", "task": "做"},
            run_id="r1", step_id=1,
        )
        executor.emit_pending_events(
            session, pending_events=executions[0].pending_events,
            run_id="r1", step_id=1,
        )
        types = [e.type for e in session._events]
        assert "agent/delegation-started" in types
        assert "agent/delegation-finished" in types
        started_idx = types.index("agent/delegation-started")
        finished_idx = types.index("agent/delegation-finished")
        assert started_idx < finished_idx
        started = session._events[started_idx]
        assert started.data["target"] == "coding"
        assert started.data["child_session_id"]


class TestChildAgentIdAttribution:
    @pytest.mark.asyncio
    async def test_child_run_started_carries_profile_name(self, tmp_path):
        """child 的 run/started 归因 agent_id=coding（不再全是 default）。"""
        store = JsonlSessionStore(tmp_path / "sessions")
        workspace_registry = WorkspaceRegistry(root=tmp_path / "workspaces")
        workspace_registry.create("p1", workspace_root=tmp_path / "ws")
        provider = InProcessSubagentProvider()
        tool = DelegateTool(provider)
        source_registry = ToolRegistry()
        source_registry.register(tool)
        provider.activate(
            factory=AgentFactory(model=ScriptedModel([AIMessage(content="done")]),
                                 primary_model_name="m"),
            source_registry=source_registry,
            session_store=store, workspace_registry=workspace_registry,
            parent_session_id="p1",
        )

        await tool.execute(_args("coding", "做"))

        child = provider.last_child_sessions[-1]
        run_started = next(e for e in child._events if e.type == "run/started")
        assert run_started.agent_id == "coding"

    def test_runtime_agent_id_param_wired(self):
        from agent_harness.agent.runtime import AgentRuntime

        runtime = AgentRuntime(model=ScriptedModel([]), registry=ToolRegistry(),
                               executor=ToolExecutor(ToolRegistry()),
                               agent_id="coding")
        assert runtime._agent_id == "coding"
        # 缺省保持 "default"（向后兼容）
        runtime2 = AgentRuntime(model=ScriptedModel([]), registry=ToolRegistry(),
                                executor=ToolExecutor(ToolRegistry()))
        assert runtime2._agent_id == "default"

    def test_factory_passes_profile_name_as_agent_id(self, tmp_path):
        source = ToolRegistry()
        factory = AgentFactory(model=ScriptedModel([AIMessage(content="x")]))
        spec = next(iter(__import__("agent_harness.agent.profiles",
                                    fromlist=["BUILTIN_PROFILES"]).BUILTIN_PROFILES.values()))
        runtime = factory.create(spec, source_registry=source)
        assert runtime._agent_id == spec.name
