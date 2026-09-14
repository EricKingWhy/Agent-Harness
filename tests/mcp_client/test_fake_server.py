"""fake server 基建验收（T1）：in-process MCP server 可列工具、可调用、可观察。"""

import pytest

from agent_harness.mcp import MAX_OUTPUT_CHARS
from tests.mcp_client.fake_server import (
    FakeMCPServer,
    fake_mcp_session,
    make_fake_tool,
)


@pytest.mark.asyncio
async def test_fake_session_lists_tools_and_calls():
    server = FakeMCPServer(tools=[make_fake_tool("echo", read_only=True)])
    async with fake_mcp_session(server) as session:
        tools = await session.list_tools()
        assert [t.name for t in tools.tools] == ["echo"]
        assert tools.tools[0].annotations.read_only_hint is True

        result = await session.call_tool("echo", {"text": "hi"})
        assert result.is_error is False
        assert [c.text for c in result.content if hasattr(c, "text")] == ["echo:echo"]

    assert server.call_count == 1
    assert server.calls[0].arguments == {"text": "hi"}


@pytest.mark.asyncio
async def test_fake_session_supports_error_results_and_multiple_tools():
    from mcp import types as _t

    async def handler(name: str, args: dict):
        if name == "boom_tool":
            raise RuntimeError("server-side crash")
        return _t.CallToolResult(
            content=[_t.TextContent(type="text", text="ok")], is_error=False
        )

    server = FakeMCPServer(
        tools=[make_fake_tool("ok_tool"), make_fake_tool("boom_tool")],
        call_handler=handler,
    )
    async with fake_mcp_session(server) as session:
        ok = await session.call_tool("ok_tool", {})
        assert ok.is_error is False
        boom = await session.call_tool("boom_tool", {})
        assert boom.is_error is True, "server 端异常应映射为 isError 结果"
        assert "server-side crash" in boom.content[0].text
    assert server.call_count == 2


def test_output_budget_constant_matches_adr():
    assert MAX_OUTPUT_CHARS == 50_000
