"""MCP capability 装配的隔离与命名冲突（Round 9 审计修复回归钉）。

- 单 server 的敌意 schema（pydantic 保护名冲突）只降级该 server，不拖垮整个
  capability，也不泄漏其他 server 的已连连接（不变量 #21）。
- `__` 分隔符注入 / server 端重复工具名造成的有效工具名冲突，在装配期按
  server 降级——不能等到 runtime 注册时才 ValueError 变成永久 500。
"""

from typing import ClassVar

import pytest

from agent_harness.mcp import MCPServerConfig
from agent_harness.mcp.capability import build_mcp_capability
from tests.mcp_client.fake_server import make_fake_tool


class StubConnection:
    """连接替身：连接即成功，list_tools 按 config.name 从 TOOLSETS 取。"""

    instances: ClassVar[list["StubConnection"]] = []
    toolsets: ClassVar[dict[str, list]] = {}

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.closed = False
        StubConnection.instances.append(self)

    async def connect(self) -> None:
        return None

    async def list_tools(self):
        return list(StubConnection.toolsets.get(self.config.name, []))

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture()
def stub_connections(monkeypatch):
    StubConnection.instances = []
    StubConnection.toolsets = {}
    monkeypatch.setattr(
        "agent_harness.mcp.capability.MCPServerConnection", StubConnection
    )
    return StubConnection


def _config(name: str) -> MCPServerConfig:
    return MCPServerConfig.model_validate(
        {"name": name, "transport": "stdio", "command": "npx"}
    )


@pytest.mark.asyncio
async def test_hostile_tool_schema_degrades_single_server(stub_connections):
    """pydantic 保护名（model_ 前缀）作为属性名的 server schema：只降级该
    server——构造期抛错不得逃出 build_mcp_capability 把健康 server 全拖垮，
    更不得让已连连接无人关闭。"""
    stub_connections.toolsets = {
        "good": [make_fake_tool("echo", read_only=True)],
        "bad": [make_fake_tool("hostile", schema={
            "type": "object",
            "properties": {"model_dump": {"type": "string"}},
            "required": ["model_dump"],
        })],
    }
    capability = await build_mcp_capability([_config("bad"), _config("good")])

    assert [t.name for t in capability.contributes_tools()] == ["mcp__good__echo"]
    assert any("'bad'" in error for error in capability.errors)
    bad = next(c for c in stub_connections.instances if c.config.name == "bad")
    good = next(c for c in stub_connections.instances if c.config.name == "good")
    assert bad.closed, "降级 server 的连接必须就地关闭"
    assert not good.closed


@pytest.mark.asyncio
async def test_name_collision_via_separator_injection_first_tool_wins(
    stub_connections,
):
    """server 'a' 的工具 'b__c' 与 server 'a__b' 的工具 'c' 有效名都是
    mcp__a__b__c——按 ADR-0012 决策 4 先到先得：后到的工具丢弃并显式记录，
    server 连接保留（冲突不拖垮 server，也不等到 runtime 注册才炸）。"""
    stub_connections.toolsets = {
        "a": [make_fake_tool("b__c")],
        "a__b": [make_fake_tool("c")],
    }
    capability = await build_mcp_capability([_config("a"), _config("a__b")])

    assert [t.name for t in capability.contributes_tools()] == ["mcp__a__b__c"]
    assert any("'a__b'" in error and "先到先得" in error
               for error in capability.errors)
    collided = next(c for c in stub_connections.instances if c.config.name == "a__b")
    assert not collided.closed, "冲突只丢工具，server 连接保留"


@pytest.mark.asyncio
async def test_duplicate_tool_names_within_one_server_first_wins(stub_connections):
    """server 自身列出两个同名工具：按同一条先到先得规则取先者、丢弃后者
    并逐条记录（无法裁决时取先者与丢弃整个 server 一样武断，但可观察）。"""
    stub_connections.toolsets = {
        "dupe": [make_fake_tool("echo", read_only=True), make_fake_tool("echo")],
    }
    capability = await build_mcp_capability([_config("dupe")])

    assert [t.name for t in capability.contributes_tools()] == ["mcp__dupe__echo"]
    assert any("mcp__dupe__echo" in error and "先到先得" in error
               for error in capability.errors)
    assert not stub_connections.instances[0].closed
