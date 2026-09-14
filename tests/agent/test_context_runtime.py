"""Runtime 消费 ContextBuilder 并镜像压缩事实。"""

import asyncio
import json
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from agent_harness.agent import AgentRuntime
from agent_harness.context.builder import ContextBuilder
from agent_harness.sandbox.base import (
    ExecResult,
    Sandbox,
    ShellEnvironment,
    ShellFamily,
)
from agent_harness.session import MODEL_COMPLETED, USER_MESSAGE
from agent_harness.storage.artifact import FakeArtifactStore
from agent_harness.tooling import (
    PermissionPolicy,
    ToolExecutor,
    ToolRegistry,
    ToolSideEffect,
)
from agent_harness.tooling.overflow import ArtifactOverflowHandler
from agent_harness.tools import BashTool
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_runtime_stops_before_model_request_when_context_exceeds_guard(tmp_path, stream):
    model = ScriptedModel([])
    registry = ToolRegistry()
    runtime = AgentRuntime(model, registry, ToolExecutor(registry),
                           context_builder=ContextBuilder(model, max_context_tokens=100))
    session = make_session(tmp_path)
    if stream:
        events = [event async for event in runtime.run_stream(session, "huge " * 200)]
        assert events[-1].type == "run/failed"
        assert events[-1].data["reason"] == "context_window_exceeded"
    else:
        result = await runtime.run(session, "huge " * 200)
        assert result.status == "context_window_exceeded"
        assert result.steps == 0 and not result.completed
    assert model.snapshots == []
    assert session.events[-1].type == "run/failed"


@pytest.mark.asyncio
async def test_compaction_event_stream_matches_persistence_and_model_sees_summary(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "old " * 8000})
    session.append(MODEL_COMPLETED, {"content": "done"})
    before = session.events
    summary = {key: [] for key in ("facts", "decisions", "constraints", "failed_attempts",
                                   "unresolved", "artifact_refs", "citations", "tool_outcomes")}
    model = ScriptedModel([AIMessage(content=json.dumps(summary)), AIMessage(content="answer")])
    registry = ToolRegistry()
    runtime = AgentRuntime(model, registry, ToolExecutor(registry),
                           context_builder=ContextBuilder(model, max_context_tokens=10000))
    emitted = [e async for e in runtime.run_stream(session, "current")]
    persisted = session.events[len(before):]
    assert [(e.type, e.seq, e.data) for e in emitted if e.is_durable] == [
        (e.type, e.seq, e.data) for e in persisted
    ]
    assert any(e.type == "context/compacted" for e in emitted)
    assert isinstance(model.snapshots[-1].messages[0], SystemMessage)
    assert session.events[:len(before)] == before


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_partial_batch_failure_still_emits_committed_artifact(tmp_path, parallel):
    class Store(FakeArtifactStore):
        async def save(self, *args, **kwargs):
            if kwargs["tool_call_id"] == "second":
                raise ConnectionError("storage offline")
            if parallel:
                await asyncio.sleep(0.01)
            return await super().save(*args, **kwargs)

    class TestTool(BashTool):
        @property
        def side_effect(self):
            return ToolSideEffect.READ_ONLY if parallel else ToolSideEffect.MUTATING

    session = make_session(tmp_path)
    before = len(session.events)
    sandbox = Mock(spec=Sandbox)
    sandbox.exec.return_value = ExecResult(exit_code=0, stdout="long " * 1000, stderr="")
    # BashTool.description 现在按 Sandbox 声明真实解释器（OBS-012）；spec'd Mock 的
    # property 会返回 Mock，故显式声明，让本用例与 shell 无关。
    sandbox.shell_environment = ShellEnvironment("sh", ShellFamily.POSIX_SH)
    registry = ToolRegistry()
    registry.register(TestTool(sandbox))
    model = ScriptedModel([AIMessage(content="", tool_calls=[
        {"id": name, "name": "bash", "args": {"command": "test"}}
        for name in ("first", "second")
    ])])
    runtime = AgentRuntime(model, registry, ToolExecutor(
        registry, policy=PermissionPolicy.DANGER_FULL_ACCESS,
        overflow_handler=ArtifactOverflowHandler(Store()),
    ))
    emitted = []
    # FIX 1 契约：执行器 / 存储异常不再让流半途断掉——Runtime 补 run/failed
    # 终结帧后正常收流（异常不再向上抛，ConnectionError 只进日志与终结事件）。
    async for event in runtime.run_stream(session, "run"):
        emitted.append(event)
    if parallel:
        await asyncio.sleep(0.02)
    assert [(e.type, e.seq) for e in emitted if e.is_durable] == [
        (e.type, e.seq) for e in session.events[before:]
    ]
    # 部分批失败的核心不变量不变：first 的 artifact/created 仍已提交并被镜像；
    # 变化的是收尾方式——流以 run/failed 终结，而不是以异常截断。
    assert emitted[-1].type == "run/failed"
    assert "artifact/externalized" in [e.type for e in emitted]
    assert sandbox.exec.call_count == 2


# ── B 组加固（R6-8）：双入口注入不得重复执行 provider ──


@pytest.mark.asyncio
async def test_context_providers_not_duplicated_when_builder_given(tmp_path):
    """同时传 context_builder 和 context_providers 时，provider 不得被注入两次。

    此前直接 extend——同一 provider 每 build 跑两次（重复注入内容 + 双倍
    内存搜索/超时风险）。按身份去重：已在 builder 列表里的实例跳过。
    """
    model = ScriptedModel([AIMessage(content="done")])
    session = make_session(tmp_path)

    class _CountingProvider:
        def __init__(self):
            self.calls = 0

        async def select(self, session, token_budget):
            self.calls += 1
            return []

    provider = _CountingProvider()
    builder = ContextBuilder(model, context_providers=[provider])
    runtime = AgentRuntime(model, ToolRegistry(), ToolExecutor(ToolRegistry()),
                           context_builder=builder, context_providers=[provider])
    await runtime.run(session, "hi")
    assert provider.calls == 1, f"provider 被执行了 {provider.calls} 次"


# ── B 组加固（R6-7）：artifact/created 落在 tool/call 之后 ──


@pytest.mark.asyncio
async def test_artifact_created_lands_after_tool_call(tmp_path):
    """事件顺序契约：tool/call → artifact/created → tool/result。

    OverflowHandler 在 execute_batch 内保存 artifact，但事件必须延迟到
    tool/call 落盘之后追加——否则事件日志里 artifact 引用一个尚未存在的
    tool_call（前向引用），消费者按 tool_call_id 对账会扑空。
    """
    from typing import Annotated

    from pydantic import BaseModel as _BaseModel
    from pydantic import Field as _Field

    from agent_harness.storage.artifact import FakeArtifactStore
    from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
    from agent_harness.tooling.overflow import ArtifactOverflowHandler

    class _Args(_BaseModel):
        size: Annotated[int, _Field(ge=1)]

    class BigOutput(Tool):
        @property
        def name(self) -> str:
            return "big_output"

        @property
        def description(self) -> str:
            return "产出超预算输出的只读工具。"

        @property
        def args_schema(self) -> type[_BaseModel]:
            return _Args

        @property
        def side_effect(self) -> ToolSideEffect:
            return ToolSideEffect.READ_ONLY

        async def execute(self, args: _Args) -> ToolResult:
            return ToolResult.success("ok", data={"output": "x" * args.size})

    session = make_session(tmp_path)
    registry = ToolRegistry()
    registry.register(BigOutput())
    runtime = AgentRuntime(
        ScriptedModel([
            AIMessage(content="", tool_calls=[
                {"id": "c1", "name": "big_output",
                 "args": {"size": 5000}, "type": "tool_call"},
            ]),
            AIMessage(content="done"),
        ]),
        registry,
        ToolExecutor(registry, overflow_handler=ArtifactOverflowHandler(FakeArtifactStore())),
    )
    await runtime.run(session, "run")

    types = [e.type for e in session.events]
    assert types.index("tool/call") < types.index("artifact/externalized") < types.index("tool/result"), types
