"""build_runtime context_providers 运行时筛选（ADR-0020b，RUNTIME 子批次）。

覆盖五条契约：
  F1：context_providers=None（默认）→ wiring 全量注入（向后兼容）；
  F2：context_providers=[] → 不注入任何 provider（显式零，区别于 None）；
  F3：context_providers=["memory"] + wiring=[memory, skills] → 只注入 memory；
  F4：context_providers=["nonexistent"] → 空注入（fail-open，不抛错）；
  F5：context_providers=["memory", "ghost"] → 只留 memory（已知保留、未知跳过）。

另含一条单元测试直接覆盖 _select_context_providers helper（不经 build_runtime）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessageChunk

from agent_harness.assembly import (
    _select_context_providers,
    build_runtime,
    initialize_stores,
    recovery_stores,
)
from agent_harness.capability.wiring import CapabilityWiring
from agent_harness.config import Settings
from agent_harness.sandbox import WorkspaceRegistry


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test")


class _NamedProvider:
    """最小 ContextProvider stand-in：只带 name，用于测试筛选层。"""

    def __init__(self, name: str) -> None:
        self.name = name

    async def select(self, session, token_budget):
        return []


class _ScriptedModel:
    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        yield AIMessageChunk(content="ok")


async def _build_runtime(tmp_path: Path, wiring: CapabilityWiring, context_providers):
    settings = _settings(tmp_path)
    stores = recovery_stores(tmp_path / "harness.db")
    await initialize_stores(stores)
    workspace_registry = WorkspaceRegistry(root=tmp_path, backend="local")

    with patch("agent_harness.assembly.create_chat_model", return_value=_ScriptedModel()):
        runtime = await build_runtime(
            settings=settings, wiring=wiring, stores=stores,
            workspace_registry=workspace_registry,
            session_id="sess-cp",
            workspace=tmp_path / "workspaces" / "sess-cp",
            max_steps=10,
            context_providers=context_providers,
        )
    return runtime


@pytest.mark.asyncio
async def test_build_runtime_none_request_keeps_all_providers(tmp_path):
    """F1：context_providers=None → wiring 全量注入（默认行为，向后兼容）。"""
    wiring = CapabilityWiring(context_providers=[_NamedProvider("memory"), _NamedProvider("skills")])
    runtime = await _build_runtime(tmp_path, wiring, context_providers=None)
    names = [getattr(p, "name", None) for p in runtime._context_builder.context_providers]
    assert names == ["memory", "skills"]


@pytest.mark.asyncio
async def test_build_runtime_empty_list_injects_no_providers(tmp_path):
    """F2：context_providers=[] → 不注入任何 provider（显式零）。"""
    wiring = CapabilityWiring(context_providers=[_NamedProvider("memory"), _NamedProvider("skills")])
    runtime = await _build_runtime(tmp_path, wiring, context_providers=[])
    assert runtime._context_builder.context_providers == []


@pytest.mark.asyncio
async def test_build_runtime_subset_filters_to_named(tmp_path):
    """F3：context_providers=["memory"] + wiring=[memory, skills] → 只注入 memory。"""
    wiring = CapabilityWiring(context_providers=[_NamedProvider("memory"), _NamedProvider("skills")])
    runtime = await _build_runtime(tmp_path, wiring, context_providers=["memory"])
    names = [getattr(p, "name", None) for p in runtime._context_builder.context_providers]
    assert names == ["memory"]


@pytest.mark.asyncio
async def test_build_runtime_unknown_name_silently_skipped(tmp_path):
    """F4：context_providers=["nonexistent"] → 空注入（fail-open，不抛错）。"""
    wiring = CapabilityWiring(context_providers=[_NamedProvider("memory"), _NamedProvider("skills")])
    runtime = await _build_runtime(tmp_path, wiring, context_providers=["nonexistent"])
    assert runtime._context_builder.context_providers == []


@pytest.mark.asyncio
async def test_build_runtime_unknown_plus_known_keeps_known(tmp_path):
    """F5：context_providers=["memory", "ghost"] → 只留 memory（未知 fail-open）。"""
    wiring = CapabilityWiring(context_providers=[_NamedProvider("memory"), _NamedProvider("skills")])
    runtime = await _build_runtime(tmp_path, wiring, context_providers=["memory", "ghost"])
    names = [getattr(p, "name", None) for p in runtime._context_builder.context_providers]
    assert names == ["memory"]


# ── _select_context_providers 单元测试 ──


def test_select_helper_none_returns_full_copy():
    """helper：None → 返回全量副本（不是原列表引用，避免下游 mutate 污染 wiring）。"""
    wired = [_NamedProvider("memory"), _NamedProvider("skills")]
    out = _select_context_providers(wired, None)
    assert [getattr(p, "name", None) for p in out] == ["memory", "skills"]
    assert out is not wired  # 副本，非原引用


def test_select_helper_empty_returns_empty():
    """helper：[] → 空列表。"""
    wired = [_NamedProvider("memory")]
    assert _select_context_providers(wired, []) == []


def test_select_helper_unnamed_provider_never_matched():
    """helper：未声明 name 的 provider 经 getattr 容错为 None，不被任何请求命中。"""
    class Anon:
        async def select(self, session, token_budget):
            return []
    wired = [Anon(), _NamedProvider("memory")]
    out = _select_context_providers(wired, ["anon", "memory"])
    assert [getattr(p, "name", None) for p in out] == ["memory"]
