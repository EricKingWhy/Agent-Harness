"""multiagent capability 接线测试（Phase 13 T2, #83, ADR-0015 决策 2）。

- CAPABILITIES 配 multiagent → wiring 携带 delegate 工具 + provider（激活后可用）
- 未配 / enabled=false → 零 delegate（单代理零感知）
- build_runtime 激活链：session_store 缺席 → delegate 降级缺席（不注册不炸）
"""

import json

import pytest

from agent_harness.assembly import (
    build_runtime,
    initialize_stores,
    recovery_stores,
)
from agent_harness.capability.base import CapabilityRegistry
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.wiring import wire_capabilities
from agent_harness.config import Settings
from agent_harness.multiagent.provider import InProcessSubagentProvider
from agent_harness.multiagent.tools import DelegateTool
from agent_harness.sandbox import WorkspaceRegistry
from agent_harness.session.store import JsonlSessionStore


def _settings(tmp_path, *, multiagent: bool = True) -> Settings:
    caps = {"multiagent": {"provider": "builtin", "enabled": multiagent, "options": {}}}
    return Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        capabilities=json.dumps(caps),
    )


@pytest.mark.asyncio
async def test_multiagent_wiring_carries_delegate(tmp_path):
    registry = CapabilityRegistry()
    wiring = await wire_capabilities(
        registry, parse_capabilities_config(_settings(tmp_path).capabilities),
        settings=_settings(tmp_path),
    )
    assert any(isinstance(t, DelegateTool) for t in wiring.tools)
    assert isinstance(wiring.multiagent_provider, InProcessSubagentProvider)


@pytest.mark.asyncio
async def test_multiagent_disabled_no_delegate(tmp_path):
    registry = CapabilityRegistry()
    wiring = await wire_capabilities(
        registry,
        parse_capabilities_config(_settings(tmp_path, multiagent=False).capabilities),
        settings=_settings(tmp_path, multiagent=False),
    )
    assert not any(isinstance(t, DelegateTool) for t in wiring.tools)
    assert wiring.multiagent_provider is None


@pytest.mark.asyncio
async def test_build_runtime_activates_provider(tmp_path):
    """端到端：capability 配置 → build_runtime → delegate 进 registry 且
    provider 已激活（可真实派 child，ScriptedModel 替身）。"""
    from unittest.mock import patch

    from tests.test_assembly import ScriptedModelFactory

    settings = _settings(tmp_path)
    stores = recovery_stores(tmp_path / "harness.db")
    await initialize_stores(stores)
    wiring = await wire_capabilities(
        CapabilityRegistry(), parse_capabilities_config(settings.capabilities),
        settings=settings,
    )
    store = JsonlSessionStore(tmp_path / "sessions")

    with patch("agent_harness.assembly.create_chat_model",
               return_value=ScriptedModelFactory()):
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=WorkspaceRegistry(root=tmp_path),
            session_id="sess-ma", workspace=tmp_path / "w",
            max_steps=5, auto_approve=True, session_store=store,
        )

    assert "delegate" in [t.name for t in runtime.registry.list()]
    provider = runtime.registry.get("delegate")._provider
    assert isinstance(provider, InProcessSubagentProvider)
    assert provider._activated


@pytest.mark.asyncio
async def test_build_runtime_without_session_store_degrades_delegate(tmp_path, caplog):
    """multiagent 启用但 session_store 缺席 → delegate 降级缺席（不注册不炸）。"""
    from unittest.mock import patch

    from tests.test_assembly import ScriptedModelFactory

    settings = _settings(tmp_path)
    stores = recovery_stores(tmp_path / "harness.db")
    await initialize_stores(stores)
    wiring = await wire_capabilities(
        CapabilityRegistry(), parse_capabilities_config(settings.capabilities),
        settings=settings,
    )

    with patch("agent_harness.assembly.create_chat_model",
               return_value=ScriptedModelFactory()):
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=WorkspaceRegistry(root=tmp_path),
            session_id="s", workspace=tmp_path / "w",
            max_steps=5, auto_approve=True, session_store=None,
        )

    assert "delegate" not in [t.name for t in runtime.registry.list()]
    assert any("session_store" in rec.message for rec in caplog.records)
