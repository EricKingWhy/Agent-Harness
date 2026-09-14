"""Phase 7 Gate 集成测试（spec 14 Gate 两条 + spec 08 §7/§8/§9）。

Gate 1：新增 demo capability（TickerCapability，纯 config 注册）不改 Agent Loop——
        工具经 wire_capabilities 收集 → ToolRegistry → 统一 ToolExecutor，
        AgentRuntime 用 ScriptedModel 闭环跑通（Agent Loop 零特判）。
Gate 2：Skill 全文不默认进 Context——模型请求边界（ScriptedModel snapshots）里
        只有目录行（name/description/when_to_use），全文只在显式 load_skill 后出现。

降级实证（08 §7）：factory 构造失败 → OPTIONAL 降级跳过 → 基础 Agent 照常运行。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agent_harness.agent import AgentRuntime
from agent_harness.agent.types import STATUS_COMPLETED
from agent_harness.capability.base import CapabilityRegistry, Degradation
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.wiring import wire_capabilities
from agent_harness.config import Settings
from agent_harness.tooling import ToolCall, ToolExecutor, ToolRegistry
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel

TICK_CALL_ID = "call_ticker_0001"
LOAD_CALL_ID = "call_load_skill_0001"

#: 技能正文里的唯一标记：Gate 2 用它证明"全文没进默认上下文"。
BODY_MARKER = "BODY_ONLY_TOKEN_正文独有"


def _settings(tmp_path: Path) -> Settings:
    """隔离环境：skill 全局目录指向不存在的 tmp 路径，防真实 home 目录泄漏进目录。"""
    return Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        skill_global_dir=str(tmp_path / "no-such-global"),
    )


def _make_skill(project_root: Path) -> Path:
    """在 workspace/skills 下放一个带 when_to_use 的 SKILL.md（spec 09 §2 + ADR-0011 Q6）。"""
    skill_dir = project_root / "skills" / "pdf-export"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: pdf-export\n"
        "description: 导出 PDF 报告的标准流程\n"
        "when_to_use: 需要导出 PDF 时\n"
        "---\n"
        f"\n# PDF 导出流程\n\n第一步……{BODY_MARKER}……完。\n",
        encoding="utf-8",
    )
    return skill_dir


class TestTickerCapabilityDemo:
    """demo capability：只在 config 显式启用时注册（spec 08 §6/§8）。"""

    @pytest.mark.asyncio
    async def test_registered_only_via_explicit_config(self, tmp_path):
        # 默认 config：无 ticker，零行为变化。
        empty = await wire_capabilities(
            CapabilityRegistry(), parse_capabilities_config(None), settings=_settings(tmp_path),
        )
        assert empty.tools == []

        # 显式配置：注册 descriptor + 贡献 tick 工具。
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry, parse_capabilities_config('{"ticker": {}}'), settings=_settings(tmp_path),
        )
        descriptor = registry.descriptor("ticker")
        assert descriptor.degradation is Degradation.OPTIONAL_RUNTIME
        assert descriptor.supports("tick")
        assert [tool.name for tool in wiring.tools] == ["tick"]

    @pytest.mark.asyncio
    async def test_disabled_entry_skipped(self, tmp_path):
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry, parse_capabilities_config('{"ticker": {"enabled": false}}'),
            settings=_settings(tmp_path),
        )
        assert registry.available() == []
        assert wiring.tools == []

    @pytest.mark.asyncio
    async def test_tick_is_read_only_through_unified_executor(self, tmp_path):
        """tick 走统一 ToolExecutor（08 §9：插件不绕过 Permission/Ledger），READ_ONLY。"""
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry, parse_capabilities_config('{"ticker": {}}'), settings=_settings(tmp_path),
        )
        tool_registry = ToolRegistry()
        for tool in wiring.tools:
            tool_registry.register(tool)

        executor = ToolExecutor(tool_registry)
        execution = await executor.execute(ToolCall(id="c1", name="tick", args={}))
        assert execution.result.error_code is None

        from agent_harness.tooling.contract import ToolPermission, ToolSideEffect
        tick = wiring.tools[0]
        assert tick.side_effect is ToolSideEffect.READ_ONLY
        assert tick.permission is ToolPermission.READ_ONLY

    @pytest.mark.asyncio
    async def test_closed_loop_through_agent_runtime(self, tmp_path):
        """Gate 1 闭环：config → wiring → ToolRegistry → Executor → 回填 → 第二轮收敛。

        AgentRuntime 只吃 Registry/Executor/Context 标准接缝，对 ticker 零感知——
        这是"新增 capability 不改 Agent Loop"（08 §8）的行为证明。
        """
        cap_registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            cap_registry, parse_capabilities_config('{"ticker": {}}'), settings=_settings(tmp_path),
        )
        tool_registry = ToolRegistry()
        for tool in wiring.tools:
            tool_registry.register(tool)

        model = ScriptedModel([
            AIMessage(content="", tool_calls=[
                {"name": "tick", "args": {}, "id": TICK_CALL_ID, "type": "tool_call"},
            ]),
            AIMessage(content="已完成一次 tick。"),
        ])
        runtime = AgentRuntime(
            model=model, registry=tool_registry, executor=ToolExecutor(tool_registry),
        )
        session = make_session(tmp_path)
        result = await runtime.run(session, "请 tick 一下")

        assert result.status == STATUS_COMPLETED
        assert result.final_text == "已完成一次 tick。"
        # 第二轮请求里拿到了 tick 的执行结果（回填成功，配对正确）。
        second_round = model.snapshots[1].messages
        tool_messages = [m for m in second_round if m.type == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == TICK_CALL_ID
        assert "tick #1" in tool_messages[0].content


class TestWebWiringCoexistence:
    @pytest.mark.asyncio
    async def test_memory_skills_ticker_coexist(self, tmp_path, monkeypatch):
        """Web 装配场景：三能力共存——memory（fake）+ skills + ticker 一套 config 装配。"""

        class _FakeMemory:
            async def initialize(self): pass
            async def close(self): pass
            capability = object()
            writeback = object()

        monkeypatch.setattr(
            "agent_harness.capability.factories.build_memory_components",
            lambda settings, *, provider="builtin": _FakeMemory(),
        )
        _make_skill(tmp_path)

        config = parse_capabilities_config(
            '{"memory": {"provider": "langmem"}, "skills": {}, "ticker": {}}'
        )
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(registry, config, settings=_settings(tmp_path))

        assert [d.name for d in registry.available()] == ["memory", "skills", "ticker"]
        assert wiring.memory_writer is not None
        assert len(wiring.context_providers) == 2  # MemoryContextProvider + SkillCatalogContextProvider
        # #159 起 memory 经契约贡献遗忘工具（收集循环的第二来源）——这个共存网关必须看见它，
        # 否则"记忆工具真的接进了统一 ToolRegistry"就没有证据。断言**集合**而不是顺序：收集
        # 顺序是实现细节，不是这个网关要守的行为。
        assert {tool.name for tool in wiring.tools} == {"load_skill", "tick", "forget_memory"}


class TestGate2SkillsProgressiveDisclosure:
    """Gate 2 在模型请求边界实证：目录行进系统注入，全文只在显式 load 后出现。"""

    async def _build_runtime(self, tmp_path: Path, responses: list[AIMessage]) -> tuple[AgentRuntime, ScriptedModel]:
        _make_skill(tmp_path)
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry, parse_capabilities_config('{"skills": {}}'), settings=_settings(tmp_path),
        )  # type: ignore[arg-type]
        tool_registry = ToolRegistry()
        for tool in wiring.tools:
            tool_registry.register(tool)
        model = ScriptedModel(responses)
        runtime = AgentRuntime(
            model=model, registry=tool_registry, executor=ToolExecutor(tool_registry),
            context_providers=list(wiring.context_providers),
        )
        return runtime, model

    @pytest.mark.asyncio
    async def test_catalog_line_in_context_full_text_absent(self, tmp_path):
        runtime, model = await self._build_runtime(
            tmp_path, [AIMessage(content="好的，我看到了技能目录。")],
        )
        session = make_session(tmp_path)
        result = await runtime.run(session, "你好")
        assert result.status == STATUS_COMPLETED

        # 请求边界（snapshots）：目录行在场（含 when_to_use 注入），全文标记绝不在场。
        first_request = "\n".join(str(m.content) for m in model.snapshots[0].messages)
        assert "pdf-export: 导出 PDF 报告的标准流程" in first_request
        assert "何时用：需要导出 PDF 时" in first_request
        assert BODY_MARKER not in first_request

    @pytest.mark.asyncio
    async def test_load_skill_brings_full_text_on_demand(self, tmp_path):
        runtime, model = await self._build_runtime(tmp_path, [
            AIMessage(content="", tool_calls=[
                {"name": "load_skill", "args": {"name": "pdf-export"}, "id": LOAD_CALL_ID,
                 "type": "tool_call"},
            ]),
            AIMessage(content="已按技能全文执行导出流程。"),
        ])
        session = make_session(tmp_path)
        result = await runtime.run(session, "请按技能导出 PDF")
        assert result.status == STATUS_COMPLETED

        second_request = "\n".join(str(m.content) for m in model.snapshots[1].messages)
        assert BODY_MARKER in second_request  # 显式按需加载后才到达模型
        assert "不是运行时指令" in second_request  # 数据非指令前缀在场（防注入框架）


class TestDegradation:
    @pytest.mark.asyncio
    async def test_factory_failure_degrades_and_base_agent_still_runs(self, tmp_path, monkeypatch):
        """OPTIONAL provider 构造失败 → 装配跳过（optional() None）→ 基础 Agent 照常运行。"""

        def _boom(settings, *, provider="builtin"):
            raise RuntimeError("simulated milvus outage")

        monkeypatch.setattr(
            "agent_harness.capability.factories.build_memory_components", _boom,
        )
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry, parse_capabilities_config('{"memory": {}}'), settings=_settings(tmp_path),
        )
        assert registry.available() == []  # 未注册 → registry.optional("memory") is None
        assert registry.optional("memory") is None
        assert wiring.memory_writer is None and wiring.memory is None
        assert wiring.context_providers == []

        # 降级后基础 Agent 照常运行（08 §7：OPTIONAL_RUNTIME 缺失不影响 Agent 可运行）。
        model = ScriptedModel([AIMessage(content="纯 Runtime 回答")])
        runtime = AgentRuntime(
            model=model, registry=ToolRegistry(), executor=ToolExecutor(ToolRegistry()),
        )
        result = await runtime.run(make_session(tmp_path), "在吗")
        assert result.status == STATUS_COMPLETED
        assert result.final_text == "纯 Runtime 回答"
