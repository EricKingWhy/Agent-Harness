"""Phase 8 Gate（T6，roadmap 冻结验收）。

Gate 1: Remote MCP Tool 仍经过统一 ToolExecutor——全链路断言：
AgentRuntime → validation → approval（DANGER）→ Scheduler → Executor →
Operation Ledger → ToolResult → SessionEvent 镜像，零旁路。
Gate 2: 不出现双重 retry——SDK/adapter 不自发重试；executor 单一 retry 层；
transport 死亡不隐式重执行。

全部用 in-process fake server（不依赖真实大厂 server）。
"""

import json
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from mcp import types as mcp_types

from agent_harness.agent import AgentRuntime
from agent_harness.capability.base import CapabilityRegistry
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.wiring import wire_capabilities
from agent_harness.config import Settings
from agent_harness.session import (
    MODEL_COMPLETED,
    RUN_COMPLETED,
    TOOL_CALL,
    TOOL_RESULT,
)
from agent_harness.storage import (
    OperationContext,
    OperationState,
    SqliteOperationLedger,
)
from agent_harness.tooling import PermissionPolicy, ToolExecutor, ToolRegistry
from agent_harness.tooling.approval import ApprovalResponse
from tests.conftest import make_session
from tests.mcp_client.fake_server import FakeMCPServer, fake_mcp_session, make_fake_tool
from tests.scripted_model import ScriptedModel


class StubConnection:
    """连接替身：healthy server 正常；down 在 connect 时抛错。"""

    def __init__(self, config, server: FakeMCPServer):
        self.config = config
        self._server = server
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def list_tools(self):
        return list(self._server.tools)

    async def call_tool(self, name, arguments):
        return await self._server._handle_call_tool(None, _Params(name, arguments))

    async def aclose(self) -> None:
        self.connected = False


class _Params:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


def _settings(servers: list[dict], tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        capabilities=json.dumps({
            "mcp": {"provider": "builtin", "enabled": True,
                    "options": {"servers": servers}},
        }),
    )


def _stdio(name: str, **overrides) -> dict:
    base = {"name": name, "transport": "stdio", "command": "npx", "enabled": True}
    base.update(overrides)
    return base


async def _wired_registry(settings: Settings, servers_cfg: list[dict],
                          servers: dict[str, FakeMCPServer]) -> list:
    """wire_capabilities + 连接打桩 → wiring.tools（MCP 工具已包好）。"""

    def factory(config):
        return StubConnection(config, servers[config.name])

    with patch("agent_harness.mcp.capability.MCPServerConnection", factory):
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry,
            parse_capabilities_config(settings.capabilities),
            settings=settings,
        )
    return wiring


@pytest.mark.asyncio
async def test_gate1_remote_mcp_tool_goes_through_unified_executor(tmp_path):
    """Gate 1：MCP 工具经统一链路执行——Ledger 记录 + 审批关卡 + SessionEvent 镜像。"""
    from agent_harness.storage import (
        OnStableBoundary,  # noqa: F401 — wiring 不需要，仅为导入面自检
    )

    echo_server = FakeMCPServer(tools=[make_fake_tool("echo", read_only=True)])
    settings = _settings([_stdio("github")], tmp_path)
    wiring = await _wired_registry(
        settings, [_stdio("github")], {"github": echo_server}
    )
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    # 工具注册进统一 Registry（与其他工具同一条路径）
    from agent_harness.tooling import ToolRegistry as _TR

    tool_registry = _TR()
    for tool in wiring.tools:
        tool_registry.register(tool)
    executor = ToolExecutor(tool_registry, operation_ledger=ledger)

    model = ScriptedModel([
        AIMessage(content="", tool_calls=[
            {"id": "call-mcp", "name": "mcp__github__echo",
             "args": {"text": "hi"}, "type": "tool_call"},
        ]),
        AIMessage(content="done"),
    ])
    runtime = AgentRuntime(model, tool_registry, executor)
    session = make_session(tmp_path / "sessions")
    result = await runtime.run(session, "use the mcp tool")

    assert result.completed
    # Ledger：MCP 调用有 Operation 记录且终态 SUCCEEDED（不变量 #13）
    op = await ledger.get(session.session_id, "call-mcp")
    assert op is not None and op.state == OperationState.SUCCEEDED
    assert op.tool_name == "mcp__github__echo"
    # SessionEvent 镜像：tool/call + tool/result 成对（03 §4 配对语义）
    event_types = [e.type for e in session.events]
    assert MODEL_COMPLETED in event_types
    assert event_types.index(TOOL_CALL) < event_types.index(TOOL_RESULT)
    call_event = next(e for e in session.events if e.type == TOOL_CALL)
    assert call_event.data["tool_call_id"] == "call-mcp"
    assert "done" in str([e.data for e in session.events if e.type == RUN_COMPLETED])


@pytest.mark.asyncio
async def test_gate1_danger_mcp_tool_hits_approval_gate(tmp_path):
    """DANGER 级 MCP 工具（无 readOnlyHint）在非 full-access policy 下被审批
    关卡拦截——MCP 工具零旁路（spec 08 验收）。"""
    danger_server = FakeMCPServer(tools=[make_fake_tool("remote_exec")])  # 无 readOnlyHint → DANGER
    settings = _settings([_stdio("github")], tmp_path)
    wiring = await _wired_registry(
        settings, [_stdio("github")], {"github": danger_server}
    )
    tool_registry = ToolRegistry()
    for tool in wiring.tools:
        tool_registry.register(tool)

    approval_requests: list[str] = []

    async def approval_callback(request):
        approval_requests.append(request.tool_name)
        return ApprovalResponse(approved=False, reason="gate test denies")

    executor = ToolExecutor(tool_registry, policy=PermissionPolicy.WORKSPACE_WRITE,
                            approval_callback=approval_callback)
    model = ScriptedModel([
        AIMessage(content="", tool_calls=[
            {"id": "call-d", "name": "mcp__github__remote_exec",
             "args": {"text": "x"}, "type": "tool_call"},
        ]),
        AIMessage(content="done"),
    ])
    runtime = AgentRuntime(model, tool_registry, executor)
    session = make_session(tmp_path / "sessions")
    await runtime.run(session, "try the danger tool")

    assert approval_requests == ["mcp__github__remote_exec"], (
        "DANGER MCP 工具必须经过审批关卡"
    )
    # 审批拒绝 → 执行从未发生（server 侧零调用）
    assert danger_server.call_count == 0
    denied = next(e for e in session.events if e.type == TOOL_RESULT)
    assert denied.data.get("content") is not None


@pytest.mark.asyncio
async def test_gate2_no_double_retry_on_business_error(tmp_path):
    """Gate 2：MCP isError（业务失败，retryable=False）→ executor 单次尝试，
    server 恰好被调用一次——SDK/adapter/executor 三层都不自发重试。"""
    flaky = FakeMCPServer(
        tools=[make_fake_tool("flaky")],
        call_handler=lambda name, args: mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="boom")],
            is_error=True,
        ),
    )
    settings = _settings([_stdio("github")], tmp_path)
    wiring = await _wired_registry(settings, [_stdio("github")], {"github": flaky})
    tool_registry = ToolRegistry()
    for tool in wiring.tools:
        tool_registry.register(tool)
    # full-access：绕过审批关卡直达执行域（审批拦截由专门的 Gate1 测试覆盖）
    executor = ToolExecutor(tool_registry, policy=PermissionPolicy.DANGER_FULL_ACCESS)

    execution = await executor.execute(
        {"id": "c1", "name": "mcp__github__flaky", "args": {"text": "x"}},
        operation_context=OperationContext(session_id="s", run_id="r"),
    )
    assert execution.result.ok is False
    assert execution.result.retryable is False
    assert execution.result.metadata["attempt"] == 1  # 单一尝试
    assert flaky.call_count == 1, "业务失败被自发重试 = 双重执行"


@pytest.mark.asyncio
async def test_gate2_transport_death_does_not_reexecute(tmp_path):
    """Gate 2：transport 死亡 → 本次调用失败；连接恢复后新调用执行恰好一次
    ——死亡调用不被隐式重放（断线 ≠ 重试）。"""
    calls: list[str] = []

    async def handler(name, args):
        calls.append(name)
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="ok")], is_error=False,
        )

    fake = FakeMCPServer(tools=[make_fake_tool("echo")], call_handler=handler)
    settings = _settings([_stdio("github")], tmp_path)
    wiring = await _wired_registry(settings, [_stdio("github")], {"github": fake})
    tool_registry = ToolRegistry()
    for tool in wiring.tools:
        tool_registry.register(tool)
    executor = ToolExecutor(tool_registry, policy=PermissionPolicy.DANGER_FULL_ACCESS)
    tool = next(t for t in wiring.tools)

    # 第一次调用：session 死亡（连接标记断开，adapter 报失败）
    class _DyingConnection:
        async def call_tool(self, name, arguments):
            from anyio import ClosedResourceError
            raise ClosedResourceError("transport died")

    tool._connection = _DyingConnection()
    execution = await executor.execute(
        {"id": "c1", "name": "mcp__github__echo", "args": {"text": "x"}},
        operation_context=OperationContext(session_id="s", run_id="r"),
    )
    assert execution.result.ok is False
    assert execution.result.retryable is False
    assert calls == [], "死亡调用不得隐式重放"

    # 第二次调用（模型重新发起）：恢复连接后执行恰好一次
    class _LiveConnection:
        async def call_tool(self, name, arguments):
            return await _session_proxy.session.call_tool(name, arguments)

    async with fake_mcp_session(fake) as session:
        _session_proxy = type("P", (), {"session": session})()
        tool._connection = _LiveConnection()
        execution = await executor.execute(
            {"id": "c2", "name": "mcp__github__echo", "args": {"text": "x"}},
            operation_context=OperationContext(session_id="s", run_id="r"),
        )
    assert execution.result.ok is True
    assert calls == ["echo"], "新调用恰好执行一次"


@pytest.mark.asyncio
async def test_gate_schema_validation_fails_before_remote_call(tmp_path):
    """入参 schema 校验在远端调用之前失败（INVALID_ARGUMENT，零远端副作用）。"""
    fake = FakeMCPServer(tools=[make_fake_tool("strict", schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    })])
    settings = _settings([_stdio("github")], tmp_path)
    wiring = await _wired_registry(settings, [_stdio("github")], {"github": fake})
    tool_registry = ToolRegistry()
    for tool in wiring.tools:
        tool_registry.register(tool)
    executor = ToolExecutor(tool_registry, policy=PermissionPolicy.DANGER_FULL_ACCESS)

    execution = await executor.execute(
        {"id": "c1", "name": "mcp__github__strict", "args": {"wrong": 1}},
        operation_context=OperationContext(session_id="s", run_id="r"),
    )
    assert execution.result.ok is False
    assert execution.result.error_code.name == "INVALID_ARGUMENT"
    assert fake.call_count == 0, "校验失败不得触达远端"
