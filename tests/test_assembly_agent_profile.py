"""build_runtime agent_profile 运行时消费（ADR-0020a，RUNTIME 子批次）。

覆盖五条契约：
  C1：agent_profile="coding" → registry 只含 _CODING_TOOLS（收窄）；
  C2：agent_profile="research_review" → registry 只含 _RESEARCH_TOOLS；
  C3：agent_profile="main" → registry 全量（不过滤，向后兼容）；
  C4：agent_profile=None（默认）→ registry 全量 + 无 system_prompt（向后兼容）；
  C5：任何非 None profile → ContextBuilder.system_prompt == profile 文本。

测试沿用 test_assembly.py 的装配模式：patch create_chat_model + 最小 CapabilityWiring。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessageChunk

from agent_harness.agent.profiles import BUILTIN_PROFILES
from agent_harness.assembly import build_runtime, initialize_stores, recovery_stores
from agent_harness.capability.wiring import CapabilityWiring
from agent_harness.config import Settings
from agent_harness.sandbox import WorkspaceRegistry


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test")


class ScriptedModelFactory:
    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        yield AIMessageChunk(content="ok")


async def _build_runtime(tmp_path: Path, agent_profile: str | None):
    """装配一个 runtime（最小 wiring），返回 runtime 供断言 registry/system_prompt。"""
    settings = _settings(tmp_path)
    wiring = CapabilityWiring()
    stores = recovery_stores(tmp_path / "harness.db")
    await initialize_stores(stores)
    workspace_registry = WorkspaceRegistry(root=tmp_path, backend="local")

    with patch("agent_harness.assembly.create_chat_model", return_value=ScriptedModelFactory()):
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=workspace_registry,
            session_id="sess-profile",
            workspace=tmp_path / "workspaces" / "sess-profile",
            max_steps=10,
            agent_profile=agent_profile,
        )
    return runtime


@pytest.mark.asyncio
async def test_build_runtime_coding_profile_filters_registry(tmp_path):
    """C1：agent_profile="coding" → registry 只含 _CODING_TOOLS（无 delegate、无 research-only）。"""
    runtime = await _build_runtime(tmp_path, agent_profile="coding")
    tool_names = {tool.name for tool in runtime.registry.list()}

    coding_scope = BUILTIN_PROFILES["coding"].tool_scope
    assert tool_names == (coding_scope & tool_names), (
        f"coding profile registry 应只含 _CODING_TOOLS，实际：{tool_names}"
    )
    # 关键工具在
    assert {"read", "write", "bash", "edit", "apply_patch"} <= tool_names
    # delegate 不在（coding 不能委派）
    assert "delegate" not in tool_names


@pytest.mark.asyncio
async def test_build_runtime_research_profile_filters_registry(tmp_path):
    """C2：agent_profile="research_review" → registry 只含 _RESEARCH_TOOLS（无 write/bash）。"""
    runtime = await _build_runtime(tmp_path, agent_profile="research_review")
    tool_names = {tool.name for tool in runtime.registry.list()}

    research_scope = BUILTIN_PROFILES["research_review"].tool_scope
    assert tool_names == (research_scope & tool_names), (
        f"research_review profile registry 应只含 _RESEARCH_TOOLS，实际：{tool_names}"
    )
    # 只读工具在
    assert {"read", "grep", "glob"} <= tool_names
    # 写/执行工具不在（research 是只读角色）
    assert "write" not in tool_names
    assert "bash" not in tool_names


@pytest.mark.asyncio
async def test_build_runtime_main_profile_keeps_full_registry(tmp_path):
    """C3：agent_profile="main" → registry 含全量 coding 工具（不过滤）。"""
    runtime = await _build_runtime(tmp_path, agent_profile="main")
    tool_names = {tool.name for tool in runtime.registry.list()}

    # main 的 _MAIN_TOOLS 含全部 coding + research + delegate + inspect_artifact；
    # 无 capability 配置时实际注册的是 9 个 coding 工具（research/delegate 靠 wiring 注入）
    assert {"read", "write", "bash", "edit", "apply_patch",
            "grep", "glob", "git_status", "git_diff"} <= tool_names


@pytest.mark.asyncio
async def test_build_runtime_none_profile_keeps_full_registry(tmp_path):
    """C4：agent_profile=None（默认）→ registry 全量（向后兼容，不过滤）。"""
    runtime = await _build_runtime(tmp_path, agent_profile=None)
    tool_names = {tool.name for tool in runtime.registry.list()}

    # 默认行为不变：全部 coding 工具在册
    assert {"read", "write", "bash", "edit", "apply_patch",
            "grep", "glob", "git_status", "git_diff"} <= tool_names


@pytest.mark.asyncio
async def test_build_runtime_coding_profile_injects_system_prompt(tmp_path):
    """C5：agent_profile="coding" → runtime 的 ContextBuilder.system_prompt == coding 文本。"""
    runtime = await _build_runtime(tmp_path, agent_profile="coding")
    assert runtime._context_builder.system_prompt == BUILTIN_PROFILES["coding"].system_prompt


@pytest.mark.asyncio
async def test_build_runtime_none_profile_no_system_prompt(tmp_path):
    """agent_profile=None → ContextBuilder.system_prompt 是 None（向后兼容）。"""
    runtime = await _build_runtime(tmp_path, agent_profile=None)
    assert runtime._context_builder.system_prompt is None


@pytest.mark.asyncio
async def test_build_runtime_main_profile_injects_system_prompt(tmp_path):
    """agent_profile="main" → 注入 main system_prompt（显式选 main 有角色提示）。"""
    runtime = await _build_runtime(tmp_path, agent_profile="main")
    assert runtime._context_builder.system_prompt == BUILTIN_PROFILES["main"].system_prompt
