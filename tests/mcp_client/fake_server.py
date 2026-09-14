"""in-process 脚本化 MCP server（T1 测试基建，ADR-0012 决策 12）。

官方 SDK 内存通路（create_client_server_memory_streams + lowlevel Server）。
全部 Phase 8 测试用它做确定性替身——Gate 测试不依赖真实大厂 server。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, types
from mcp.client.session import ClientSession as _ClientSession
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_client_server_memory_streams


@dataclass
class MCPCallRecord:
    """一次 tools/call 的记录（断言用）。"""

    name: str
    arguments: dict[str, Any]


@dataclass
class FakeMCPServer:
    """脚本化 server：tools 固定、call 行为可注入、调用可观察。"""

    tools: list[types.Tool]
    # 自定义 call 行为；缺省回显。抛异常 = server 端错误。
    call_handler: Any = None
    calls: list[MCPCallRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._server = Server("fake-mcp")
        self._server.add_request_handler(
            "tools/list", types.PaginatedRequestParams, self._handle_list_tools
        )
        self._server.add_request_handler(
            "tools/call", types.CallToolRequestParams, self._handle_call_tool
        )

    async def _handle_list_tools(self, ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=list(self.tools))

    async def _handle_call_tool(self, ctx: Any, params: Any) -> types.CallToolResult:
        self.calls.append(MCPCallRecord(name=params.name, arguments=dict(params.arguments or {})))
        if self.call_handler is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"echo:{params.name}")],
                is_error=False,
            )
        try:
            return await self.call_handler(params.name, dict(params.arguments or {}))
        except Exception as error:  # noqa: BLE001 — 测试替身：handler 任意异常都转 isError
            # MCP 语义：工具执行错误 = isError 结果（不是协议错误）——
            # 与真实 server 行为一致，供 client 侧 isError 断言。
            return types.CallToolResult(
                content=[types.TextContent(type="text",
                                           text=f"{type(error).__name__}: {error}")],
                is_error=True,
            )

    @property
    def call_count(self) -> int:
        return len(self.calls)


@asynccontextmanager
async def fake_mcp_session(
    server: FakeMCPServer,
) -> AsyncIterator[ClientSession]:
    """把 FakeMCPServer 与 ClientSession 在内存里接通；yield 已初始化的 session。"""
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        run_task = asyncio.create_task(
            server._server.run(
                server_read, server_write,
                server._server.create_initialization_options(),
                raise_exceptions=True,
            )
        )
        try:
            async with _ClientSession(client_read, client_write) as session:
                await session.initialize()
                yield session
        finally:
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass


def make_fake_tool(name: str = "echo", *, read_only: bool | None = None,
                   schema: dict | None = None) -> types.Tool:
    """造一个 MCP Tool 描述。read_only: None=无注解（MCP 默认非只读）、
    True/False=显式 readOnlyHint 注解。"""
    return types.Tool(
        name=name,
        description=f"fake tool {name}",
        inputSchema=schema or {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        annotations=(
            types.ToolAnnotations(read_only_hint=read_only)
            if read_only is not None
            else None
        ),
    )
