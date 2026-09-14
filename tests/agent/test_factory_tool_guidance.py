"""T6 child 路径的工具 guidance（ADR-0023 D11）。

B2 契约（`tests/agent/test_system_prompt_wiring.py`）断言
`child.system_prompt == spec.system_prompt`。本票靠 **默认关闭** 的显式开关保持它绿，
而不是靠"`ReadTool` 恰好没有 guidance"——那样一旦有人给 ReadTool 加 guidance，
B2 会莫名变红。本文件的第一个用例把这条理由固化下来。
"""

from __future__ import annotations

from pydantic import BaseModel

from agent_harness.agent.factory import AgentFactory
from agent_harness.agent.profiles import AgentSpec
from agent_harness.prompt import PersonaConfig
from agent_harness.tooling import Tool, ToolRegistry, ToolResult
from tests.scripted_model import ScriptedModel


class _NoArgs(BaseModel):
    pass


class FakeTool(Tool):
    """带 guidance 的工具替身（`prompt_guidance` 可配）。"""

    def __init__(self, name: str, guidance: str | None = None) -> None:
        self._name = name
        self._guidance = guidance

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} tool"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _NoArgs

    @property
    def prompt_guidance(self) -> str | None:
        return self._guidance

    async def execute(self, args: BaseModel) -> ToolResult:
        return ToolResult.success("ok")


def _spec(tool_scope: frozenset[str], *, name: str = "coding") -> AgentSpec:
    return AgentSpec(
        name=name,
        description="子代理",
        system_prompt="你是编码 agent。",
        tool_scope=tool_scope,
    )


def test_factory_without_flag_appends_nothing():
    """B2 的成立与工具数据无关：工具**有** guidance，默认仍逐字节等于 spec。"""
    registry = ToolRegistry()
    registry.register(FakeTool("probe", "P"))
    spec = _spec(frozenset({"probe"}))

    child = AgentFactory(model=ScriptedModel([])).create(spec, source_registry=registry)

    assert child._context_builder.system_prompt == spec.system_prompt


def test_factory_with_flag_appends_guidance():
    registry = ToolRegistry()
    registry.register(FakeTool("probe", "P"))
    spec = _spec(frozenset({"probe"}))

    child = AgentFactory(
        model=ScriptedModel([]), include_tool_guidance=True,
    ).create(spec, source_registry=registry)

    # BUG-013：join_guidance 现在带澄清句（与父路径同源）。
    from agent_harness.prompt.tool_sections import TOOL_USE_DISCLAIMER

    assert child._context_builder.system_prompt == (
        f"{spec.system_prompt}\n\nP\n\n{TOOL_USE_DISCLAIMER}"
    )


def test_factory_guidance_comes_from_child_registry():
    """child 只应看到自己可用工具的 guidance（越权信息不泄漏）。"""
    registry = ToolRegistry()
    registry.register(FakeTool("in_scope", "IN"))
    registry.register(FakeTool("out_of_scope", "OUT"))
    spec = _spec(frozenset({"in_scope"}))

    child = AgentFactory(
        model=ScriptedModel([]), include_tool_guidance=True,
    ).create(spec, source_registry=registry)

    prompt = child._context_builder.system_prompt
    assert prompt is not None
    assert "IN" in prompt
    assert "OUT" not in prompt


def test_factory_child_guidance_respects_persona_order():
    registry = ToolRegistry()
    registry.register(FakeTool("probe", "G"))
    spec = _spec(frozenset({"probe"}))

    child = AgentFactory(
        model=ScriptedModel([]), include_tool_guidance=True,
        persona=PersonaConfig(suffix="S"),
    ).create(spec, source_registry=registry)

    # BUG-013：join_guidance 含澄清句（与父路径同源），五段顺序不漂移。
    from agent_harness.prompt.tool_sections import TOOL_USE_DISCLAIMER

    assert child._context_builder.system_prompt == (
        f"{spec.system_prompt}\n\nG\n\n{TOOL_USE_DISCLAIMER}\n\nS"
    )


def test_factory_flag_on_without_guidance_appends_nothing():
    """开关打开但工具**没有** guidance → 仍逐字节等于 spec（不 append 空段落）。"""
    registry = ToolRegistry()
    registry.register(FakeTool("probe"))
    spec = _spec(frozenset({"probe"}))

    child = AgentFactory(
        model=ScriptedModel([]), include_tool_guidance=True,
    ).create(spec, source_registry=registry)

    assert child._context_builder.system_prompt == spec.system_prompt
