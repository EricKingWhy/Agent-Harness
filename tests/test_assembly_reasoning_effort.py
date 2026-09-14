"""build_runtime reasoning_effort 透传（RUNTIME 子批次）。

覆盖两条契约：
  B1：reasoning_effort="deep" → create_chat_model 收到 reasoning_effort="deep"；
  B2：reasoning_effort=None（默认）→ create_chat_model 收到 reasoning_effort=None。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessageChunk

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


async def _build_runtime(
    tmp_path: Path,
    reasoning_effort: str | None,
    captured_calls: list,
) -> None:
    """装配 runtime，捕获 create_chat_model 调用参数。"""
    settings = _settings(tmp_path)
    wiring = CapabilityWiring()
    stores = recovery_stores(tmp_path / "harness.db")
    await initialize_stores(stores)
    workspace_registry = WorkspaceRegistry(root=tmp_path, backend="local")

    def _spy_create(config, *, reasoning_effort=None):
        captured_calls.append({"reasoning_effort": reasoning_effort})
        return ScriptedModelFactory()

    with patch("agent_harness.assembly.create_chat_model", side_effect=_spy_create):
        await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=workspace_registry,
            session_id="sess-effort",
            workspace=tmp_path / "workspaces" / "sess-effort",
            max_steps=10,
            reasoning_effort=reasoning_effort,
        )


@pytest.mark.asyncio
async def test_build_runtime_passes_reasoning_effort_to_model(tmp_path):
    """B1：reasoning_effort="deep" → create_chat_model 收到 reasoning_effort="deep"。"""
    captured: list[dict] = []
    await _build_runtime(tmp_path, reasoning_effort="deep", captured_calls=captured)

    # primary 模型构造调用应该收到 reasoning_effort="deep"
    assert any(c["reasoning_effort"] == "deep" for c in captured), (
        f"create_chat_model 应收到 reasoning_effort='deep'，实际调用：{captured}"
    )


@pytest.mark.asyncio
async def test_build_runtime_none_reasoning_effort_no_injection(tmp_path):
    """B2：reasoning_effort=None → create_chat_model 收到 reasoning_effort=None。"""
    captured: list[dict] = []
    await _build_runtime(tmp_path, reasoning_effort=None, captured_calls=captured)

    # 所有 create_chat_model 调用都应收到 reasoning_effort=None
    assert all(c["reasoning_effort"] is None for c in captured), (
        f"reasoning_effort=None 时不应注入，实际调用：{captured}"
    )
