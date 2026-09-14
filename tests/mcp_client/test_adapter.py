"""MCPToolAdapter（T4）：命名/权限映射/schema 转换/执行/预算。"""

from contextlib import asynccontextmanager

import pytest
from mcp import types as mcp_types
from pydantic import ValidationError

from agent_harness.mcp import ConfigError, MCPServerConfig, parse_mcp_servers
from agent_harness.mcp.adapter import (
    MCPTool,
    _pydantic_model_from_json_schema,
    mcp_tool_name,
)
from agent_harness.tooling import ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.result import ErrorCode
from tests.mcp_client.fake_server import FakeMCPServer, fake_mcp_session, make_fake_tool


def _config(**overrides) -> MCPServerConfig:
    base = {"name": "github", "transport": "stdio", "command": "npx"}
    base.update(overrides)
    return MCPServerConfig.model_validate(base)


class _FakeConnection:
    """用 fake session 直接构造的最小 connection 替身（仅 call_tool）。"""

    def __init__(self, session):
        self._session = session

    async def call_tool(self, name, arguments):
        return await self._session.call_tool(name, arguments)


@asynccontextmanager
async def _built_tools(config: MCPServerConfig, server: FakeMCPServer):
    """discovery → adapter 工具；在 session 存活期间 yield（执行要在连接内）。"""
    async with fake_mcp_session(server) as session:
        discovered = (await session.list_tools()).tools
        connection = _FakeConnection(session)
        yield [MCPTool(connection, config, remote) for remote in discovered]


def test_naming_namespaces_server_and_tool():
    assert mcp_tool_name("github", "create_issue") == "mcp__github__create_issue"


@pytest.mark.asyncio
async def test_permission_defaults_hint_and_override():
    """无注解 → DANGER/MUTATING（最严默认）；readOnlyHint → READ_ONLY/READ_ONLY；
    server 配置覆写优先于注解。"""
    server = FakeMCPServer(tools=[
        make_fake_tool("no_annot"),
        make_fake_tool("ro_tool", read_only=True),
    ])
    config = _config(tool_permissions={"ro_tool": "workspace-write"})
    async with _built_tools(config, server) as tools:
        built = {t.remote_name: t for t in tools}
        assert built["no_annot"].permission == ToolPermission.DANGER
        assert built["no_annot"].side_effect == ToolSideEffect.MUTATING
        assert built["ro_tool"].permission == ToolPermission.WORKSPACE_WRITE, (
            "server 配置覆写优先于 readOnlyHint"
        )
        assert built["ro_tool"].side_effect == ToolSideEffect.READ_ONLY


def test_pydantic_model_from_schema_types_and_required():
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
            "tags": {"type": "array"},
            "meta": {"type": "object"},
        },
        "required": ["title"],
    }
    model = _pydantic_model_from_json_schema(schema, "M")
    inst = model(title="t")
    dumped = inst.model_dump()
    assert dumped["title"] == "t" and dumped["count"] is None
    full = model(title="t", count=2, ratio=0.5, flag=True, tags=["a"], meta={"k": 1})
    assert full.model_dump()["meta"] == {"k": 1}
    with pytest.raises(ValidationError):
        model()  # required title 缺失


def test_pydantic_model_fallback_for_unknown_schema_shape():
    model = _pydantic_model_from_json_schema({"type": "weird"}, "M")
    assert model.model_validate({"anything": 1}).model_dump() == {"anything": 1}


@pytest.mark.asyncio
async def test_execute_success_routes_content_and_records_call():
    config = _config()
    fake = FakeMCPServer(tools=[make_fake_tool("echo")])
    async with _built_tools(config, fake) as tools:
        assert tools[0].name == "mcp__github__echo"
        result = await tools[0].execute(tools[0].args_schema.model_validate({"text": "hi"}))
    assert result.ok is True
    assert result.data["output"] == "echo:echo"
    assert fake.calls[0].name == "echo"  # 远端收到的是 bare name，不是 mangle 后的
    assert fake.calls[0].arguments == {"text": "hi"}


@pytest.mark.asyncio
async def test_execute_maps_is_error_to_failure_without_retry():
    async def handler(name, args):
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="boom detail")],
            is_error=True,
        )

    fake = FakeMCPServer(tools=[make_fake_tool("bad")], call_handler=handler)
    config = _config()
    async with _built_tools(config, fake) as tools:
        result = await tools[0].execute(tools[0].args_schema.model_validate({"text": "x"}))
    assert result.ok is False
    assert result.error_code == ErrorCode.TOOL_EXECUTION_ERROR
    assert result.retryable is False
    assert "boom detail" in result.message


@pytest.mark.asyncio
async def test_output_budget_caps_long_results():
    async def handler(name, args):
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="z" * 80_000)],
            is_error=False,
        )

    fake = FakeMCPServer(tools=[make_fake_tool("huge")], call_handler=handler)
    config = _config()
    async with _built_tools(config, fake) as tools:
        result = await tools[0].execute(tools[0].args_schema.model_validate({"text": "x"}))
    output = result.data["output"]
    assert len(output) <= 50_000 + 50, "输出预算未生效"
    assert "truncated" in output
    assert "z" * 80_000 not in output


@pytest.mark.asyncio
async def test_description_declares_budget_and_server():
    server = FakeMCPServer(tools=[make_fake_tool("echo")])
    async with _built_tools(_config(), server) as tools:
        assert "MCP server: github" in tools[0].description
        assert "50" in tools[0].description
        assert tools[0].timeout_seconds == 30.0


def test_config_tool_permissions_invalid_value_rejected():
    """非法权限值经 parse 层转 ConfigError（响亮失败）。"""
    with pytest.raises(ConfigError, match="local"):
        parse_mcp_servers({"servers": [
            {"name": "local", "transport": "stdio", "command": "npx",
             "tool_permissions": {"x": "root"}},
        ]})
