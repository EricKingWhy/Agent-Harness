"""T6 工具 guidance 的装配点集成（ADR-0023 D11）。

用**真实 DelegateTool**做端到端（multiagent capability 开/关驱动），不注入假工具——
注入假工具需要改生产代码，成本更高、证据更弱。

核心性质：guidance 的出现与否**严格跟随工具是否注册**。这由 registry 在
`build_runtime` 里被 `profile_spec.tool_scope` 收窄决定，所以同一份代码下面：
main + multiagent 开 → 有委派须知；multiagent 关 → 无；coding → 无（tool_scope 不含）。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessageChunk

from agent_harness.agent.profiles import BUILTIN_PROFILES
from agent_harness.assembly import build_runtime, initialize_stores, recovery_stores
from agent_harness.capability.base import CapabilityRegistry
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.wiring import CapabilityWiring, wire_capabilities
from agent_harness.config import Settings
from agent_harness.sandbox import WorkspaceRegistry
from agent_harness.session.store import JsonlSessionStore

GUIDANCE_MARKER = "委派须知"
PREFIX_MARKER = "PREFIX_MARKER"
SUFFIX_MARKER = "SUFFIX_MARKER"


class ScriptedModelFactory:
    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        yield AIMessageChunk(content="ok")


def _settings(tmp_path, *, multiagent: bool, persona: str = "") -> Settings:
    caps = {"multiagent": {"provider": "builtin", "enabled": multiagent, "options": {}}}
    return Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        capabilities=json.dumps(caps),
        agent_persona=persona,
    )


async def _build_runtime(
    tmp_path: Path, *, agent_profile: str | None, multiagent: bool = True,
    persona: str = "",
):
    settings = _settings(tmp_path, multiagent=multiagent, persona=persona)
    if multiagent:
        wiring = await wire_capabilities(
            CapabilityRegistry(), parse_capabilities_config(settings.capabilities),
            settings=settings,
        )
    else:
        wiring = CapabilityWiring()
    stores = recovery_stores(tmp_path / "harness.db")
    await initialize_stores(stores)
    store = JsonlSessionStore(tmp_path / "sessions")

    with patch("agent_harness.assembly.create_chat_model",
               return_value=ScriptedModelFactory()):
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=WorkspaceRegistry(root=tmp_path, backend="local"),
            session_id="sess-guidance",
            workspace=tmp_path / "workspaces" / "sess-guidance",
            max_steps=10, auto_approve=True, session_store=store,
            agent_profile=agent_profile,
        )
    return runtime


@pytest.mark.asyncio
async def test_parent_prompt_includes_tool_guidance(tmp_path):
    runtime = await _build_runtime(tmp_path, agent_profile="main")
    prompt = runtime._context_builder.system_prompt

    assert prompt is not None
    assert GUIDANCE_MARKER in prompt
    assert not prompt.startswith(GUIDANCE_MARKER)  # 在 profile 身份文本之后


@pytest.mark.asyncio
async def test_parent_prompt_order_is_prefix_identity_guidance_suffix(tmp_path):
    persona = json.dumps({"prefix": PREFIX_MARKER, "suffix": SUFFIX_MARKER})
    runtime = await _build_runtime(tmp_path, agent_profile="main", persona=persona)
    prompt = runtime._context_builder.system_prompt

    assert prompt is not None
    identity = BUILTIN_PROFILES["main"].system_prompt
    # 断相对位置，不断绝对偏移
    assert (
        prompt.index(PREFIX_MARKER)
        < prompt.index(identity)
        < prompt.index(GUIDANCE_MARKER)
        < prompt.index(SUFFIX_MARKER)
    )


@pytest.mark.asyncio
async def test_tool_absent_no_guidance(tmp_path):
    """本票的核心价值断言：工具缺席 → 说明缺席。"""
    runtime = await _build_runtime(tmp_path, agent_profile="main", multiagent=False)
    prompt = runtime._context_builder.system_prompt

    assert prompt is not None
    assert GUIDANCE_MARKER not in prompt


@pytest.mark.asyncio
async def test_guidance_absent_keeps_prompt_byte_identical(tmp_path):
    """P2 不回归 P0/P1：无 guidance 且无 persona → 逐字节等于 T3~T5 的产物。"""
    runtime = await _build_runtime(tmp_path, agent_profile="main", multiagent=False)
    assert runtime._context_builder.system_prompt == BUILTIN_PROFILES["main"].system_prompt


@pytest.mark.asyncio
async def test_coding_profile_excludes_delegate_guidance(tmp_path):
    """proof：内容来自**收窄后**的 registry，不是全量。"""
    runtime = await _build_runtime(tmp_path, agent_profile="coding")
    assert "delegate" not in {t.name for t in runtime.registry.list()}

    prompt = runtime._context_builder.system_prompt
    assert prompt is not None
    assert GUIDANCE_MARKER not in prompt
    assert prompt == BUILTIN_PROFILES["coding"].system_prompt


@pytest.mark.asyncio
async def test_none_profile_gets_guidance_without_identity(tmp_path):
    runtime = await _build_runtime(tmp_path, agent_profile=None)
    prompt = runtime._context_builder.system_prompt

    assert prompt is not None
    assert GUIDANCE_MARKER in prompt
    assert BUILTIN_PROFILES["main"].system_prompt not in prompt  # 默认档无身份段


@pytest.mark.asyncio
async def test_none_profile_no_guidance_no_persona_stays_none(tmp_path):
    """C4 逐字保持。"""
    runtime = await _build_runtime(tmp_path, agent_profile=None, multiagent=False)
    assert runtime._context_builder.system_prompt is None
