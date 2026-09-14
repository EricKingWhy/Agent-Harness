"""T5 装配点集成：persona 只在装配点注入，且不污染零配置基线。

形制照抄 `test_assembly_agent_profile.py` 的 `_settings` / `_build_runtime`，
但本文件**不修改**那份契约测试的任何断言（PRD §10.9）。

已知前提：本文件与 `test_assembly_agent_profile.py` 都依赖测试环境**未导出**
`AGENT_PERSONA`（`Settings(_env_file=None)` 仍会读真实环境变量）。
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
from agent_harness.prompt import PromptError
from agent_harness.prompt.builtin import build_registry
from agent_harness.sandbox import WorkspaceRegistry
from tests.conftest import make_session


class ScriptedModelFactory:
    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        yield AIMessageChunk(content="ok")


async def _build_runtime(
    tmp_path: Path, *, agent_profile: str | None, agent_persona: str | None = None
):
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        **({} if agent_persona is None else {"agent_persona": agent_persona}),
    )
    stores = recovery_stores(tmp_path / "harness.db")
    await initialize_stores(stores)
    with patch("agent_harness.assembly.create_chat_model", return_value=ScriptedModelFactory()):
        return await build_runtime(
            settings=settings,
            wiring=CapabilityWiring(),
            stores=stores,
            workspace_registry=WorkspaceRegistry(root=tmp_path, backend="local"),
            session_id="sess-persona",
            workspace=tmp_path / "workspaces" / "sess-persona",
            max_steps=5,
            agent_profile=agent_profile,
        )


@pytest.mark.asyncio
async def test_persona_unset_preserves_exact_prompt(tmp_path: Path) -> None:
    """persona 未设 → 与 C5 等价式逐字节相同（证明单 section 组装无多余字符）。"""
    runtime = await _build_runtime(tmp_path, agent_profile="coding")
    assert (
        runtime._context_builder.system_prompt
        == BUILTIN_PROFILES["coding"].system_prompt
    )


@pytest.mark.asyncio
async def test_persona_prefix_injected_for_coding(tmp_path: Path) -> None:
    runtime = await _build_runtime(
        tmp_path, agent_profile="coding", agent_persona='{"prefix":"P"}'
    )
    assert runtime._context_builder.system_prompt == (
        "P\n\n" + BUILTIN_PROFILES["coding"].system_prompt
    )


@pytest.mark.asyncio
async def test_persona_suffix_injected_for_main(tmp_path: Path) -> None:
    runtime = await _build_runtime(
        tmp_path, agent_profile="main", agent_persona='{"suffix":"S"}'
    )
    assert runtime._context_builder.system_prompt is not None
    assert runtime._context_builder.system_prompt.endswith("\n\nS")


@pytest.mark.asyncio
async def test_persona_both_sides_wrap_the_base(tmp_path: Path) -> None:
    """前后缀把 base **包住**，不是都堆在前面。"""
    runtime = await _build_runtime(
        tmp_path, agent_profile="coding", agent_persona='{"prefix":"P","suffix":"S"}'
    )
    base = BUILTIN_PROFILES["coding"].system_prompt
    assert runtime._context_builder.system_prompt == f"P\n\n{base}\n\nS"


@pytest.mark.asyncio
async def test_persona_none_profile_stays_none_when_unset(tmp_path: Path) -> None:
    runtime = await _build_runtime(tmp_path, agent_profile=None)
    assert runtime._context_builder.system_prompt is None


@pytest.mark.asyncio
async def test_persona_creates_prompt_when_no_profile(tmp_path: Path) -> None:
    runtime = await _build_runtime(
        tmp_path, agent_profile=None, agent_persona='{"prefix":"P","suffix":"S"}'
    )
    assert runtime._context_builder.system_prompt == "P\n\nS"


@pytest.mark.asyncio
async def test_persona_is_counted_in_token_budget(tmp_path: Path) -> None:
    """persona 不是白送的预算——它会进 ContextBuilder 的 token 估算（ADR-0020a）。"""
    plain = await _build_runtime(tmp_path / "plain", agent_profile="coding")
    wrapped = await _build_runtime(
        tmp_path / "wrapped", agent_profile="coding", agent_persona='{"prefix":"%s"}' % ("长" * 200)
    )
    session = make_session(tmp_path)
    await plain._context_builder.build(session)
    await wrapped._context_builder.build(session)
    assert (
        wrapped._context_builder._system_prompt_tokens
        > plain._context_builder._system_prompt_tokens
    )


@pytest.mark.asyncio
async def test_invalid_persona_fails_loud(tmp_path: Path) -> None:
    """坏配置不降级、不忽略——装配期就响亮失败。"""
    with pytest.raises(PromptError) as err:
        await _build_runtime(
            tmp_path, agent_profile="coding", agent_persona='{"prefx":"x"}'
        )
    assert err.value.code == "invalid_persona_config"


@pytest.mark.asyncio
async def test_persona_does_not_affect_aux_prompts_end_to_end(tmp_path: Path) -> None:
    """端到端重复一遍 §4.1 红线：装配出的 runtime 带上了 persona，而辅助 prompt 一字不变。

    前半段让 runtime 真正承重（否则这条只是单元测试的副本，白建一次 runtime）；
    后半段覆盖两个 target（system + meta_user），不只看 system 通道。
    """
    runtime = await _build_runtime(
        tmp_path, agent_profile="coding", agent_persona='{"prefix":"P","suffix":"S"}'
    )
    assert runtime._context_builder.system_prompt is not None
    assert runtime._context_builder.system_prompt.startswith("P\n\n")

    persona = _persona()
    for scope in ("aux:compaction", "aux:memory_extraction"):
        assert (
            build_registry(persona).assemble(scope).system_text
            == build_registry().assemble(scope).system_text
        )
    assert build_registry(persona).assemble("aux:fork_tail", {"tail_text": "T"}).meta_user_text == (
        build_registry().assemble("aux:fork_tail", {"tail_text": "T"}).meta_user_text
    )


def _persona():
    from agent_harness.prompt import PersonaConfig

    return PersonaConfig(prefix="P", suffix="S")
