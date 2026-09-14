"""Web Search Capability 接线测试（T4/T6, #79/#81, ADR-0014 决策 8/10）。

TavilyWebSearchProvider 打桩（config→provider 是唯一注入缝）；验证：
- TAVILY_API_KEY 配置齐全 → web_search 工具进统一 registry（不变量 #7）
- TAVILY_API_KEY 未配置 → OPTIONAL_RUNTIME 降级缺席（警告可观察）
- enabled=false → 显式 opt-out
- 接线出的工具端到端可执行（identity 上下文内，不触网）
"""

import json
from typing import ClassVar

import pytest

from agent_harness.capability.base import CapabilityRegistry
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.wiring import wire_capabilities
from agent_harness.config import Settings
from agent_harness.websearch.protocol import WebHit


class StubTavilyProvider:
    """构造替身：签名与真实 provider 一致（无状态，per-request client）。"""

    instances: ClassVar[list["StubTavilyProvider"]] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        StubTavilyProvider.instances.append(self)

    async def search(self, query: str, *, k: int = 5, freshness=None):
        return []


@pytest.fixture()
def stub_tavily(monkeypatch):
    StubTavilyProvider.instances = []
    monkeypatch.setattr(
        "agent_harness.websearch.tavily.TavilyWebSearchProvider",
        StubTavilyProvider,
    )
    return StubTavilyProvider


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        capabilities=json.dumps({
            "websearch": {"provider": "builtin", "enabled": True, "options": {}},
        }),
        **overrides,
    )


async def _wire(settings: Settings):
    registry = CapabilityRegistry()
    return await wire_capabilities(
        registry, parse_capabilities_config(settings.capabilities),
        settings=settings,
    )


@pytest.mark.asyncio
async def test_websearch_wiring_registers_tool(tmp_path, stub_tavily):
    """TAVILY_API_KEY 齐全 → web_search 进统一 registry（零旁路）。"""
    wiring = await _wire(_settings(tmp_path, tavily_api_key="tvly-test"))
    names = [tool.name for tool in wiring.tools]
    assert names == ["web_search"]
    assert stub_tavily.instances, "Tavily provider 被构造"


@pytest.mark.asyncio
async def test_websearch_absent_when_key_unconfigured(tmp_path, stub_tavily, caplog):
    """TAVILY_API_KEY 未配置 → OPTIONAL_RUNTIME 降级缺席，不注册不报错。"""
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        capabilities=json.dumps({
            "websearch": {"provider": "builtin", "enabled": True, "options": {}},
        }),
    )
    wiring = await _wire(settings)
    assert wiring.tools == []
    assert not StubTavilyProvider.instances
    assert any("TAVILY_API_KEY" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_websearch_disabled_in_config(tmp_path, stub_tavily):
    """enabled=false → 不接线（显式 opt-out，与其它 capability 一致）。"""
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        tavily_api_key="tvly-test",
        capabilities=json.dumps({
            "websearch": {"provider": "builtin", "enabled": False, "options": {}},
        }),
    )
    wiring = await _wire(settings)
    assert wiring.tools == []


@pytest.mark.asyncio
async def test_websearch_wired_tool_executes_end_to_end(tmp_path, stub_tavily, monkeypatch):
    """接线出的 web_search 工具真实可执行（identity 上下文内，不触网）。"""
    wiring = await _wire(_settings(tmp_path, tavily_api_key="tvly-test"))
    tool = wiring.tools[0]

    class _Args:
        query = "python testing"
        recency = None
        k = 5

    async def fake_search(self, query, *, k=5, freshness=None):
        return [WebHit(title="t", url="https://example.test/a",
                       snippet="s", score=0.9, raw_content=None)]

    monkeypatch.setattr(StubTavilyProvider, "search", fake_search)
    from agent_harness.identity import IdentityContext, identity_context_var

    token = identity_context_var.set(
        IdentityContext(tenant_id="t", user_id="u", scopes=["user"])
    )
    try:
        result = await tool.execute(_Args())
    finally:
        identity_context_var.reset(token)
    assert result.ok
    import json as _json

    output = _json.loads(result.data["output"])
    assert output["hits"][0]["citation"] == "web:https://example.test/a"
