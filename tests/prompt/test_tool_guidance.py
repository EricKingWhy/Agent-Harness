"""T6 工具 guidance 归集（ADR-0023 D11）。

覆盖：guidance → `tool:<name>` section 的映射规则、child 路径的拼接顺序、
父/子两条路径的顺序一致性（漂移守卫）、以及 prompt 包不得反向依赖 tooling 包。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from agent_harness.prompt import (
    SECTION_ORDERS,
    PersonaConfig,
    PromptError,
    Target,
    apply_persona,
    build_registry,
    compose_agent_prompt,
    join_guidance,
    tool_guidance_sections,
)
from agent_harness.tooling import Tool, ToolResult


#: 结构类型替身——`tool_guidance_sections` 只看 `.name` / `.prompt_guidance`。
@dataclass
class FakeTool:
    name: str
    guidance: str | None = None

    @property
    def prompt_guidance(self) -> str | None:
        return self.guidance


class _NoArgs(BaseModel):
    pass


class _MinimalTool(Tool):
    """最小具体 Tool：证明新增 `prompt_guidance` 不要求既有工具改实现。"""

    @property
    def name(self) -> str:
        return "minimal"

    @property
    def description(self) -> str:
        return "minimal tool"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _NoArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        return ToolResult.success("ok")


# —— section 映射规则 ——

def test_guidance_none_produces_no_section():
    assert tool_guidance_sections([FakeTool("t")]) == []


def test_whitespace_guidance_produces_no_section():
    assert tool_guidance_sections([FakeTool("t", "   \n ")]) == []


def test_guidance_produces_tool_section():
    sections = tool_guidance_sections([FakeTool("bash", "G")])

    assert len(sections) == 2  # guidance + BUG-013 澄清句
    section = sections[0]
    assert section.name == "tool:bash"
    assert section.order == SECTION_ORDERS["tool"] == 2000
    assert section.scopes == frozenset({"*"})
    assert section.target is Target.SYSTEM
    assert section.text == "G"


def test_disclaimer_appended_after_guidance():
    """BUG-013：澄清句在全部工具 guidance 之后，仅当有 guidance 时出现。"""
    from agent_harness.prompt.tool_sections import TOOL_USE_DISCLAIMER

    assert tool_guidance_sections([FakeTool("t")]) == []  # 无 guidance → 无澄清句
    sections = tool_guidance_sections([FakeTool("a", "A"), FakeTool("b", "B")])
    assert [s.name for s in sections] == ["tool:a", "tool:b", "frame:tool_disclaimer"]
    assert sections[-1].text == TOOL_USE_DISCLAIMER


def test_multiple_tools_produce_multiple_sections():
    sections = tool_guidance_sections(
        [FakeTool("a", "A"), FakeTool("b"), FakeTool("c", "C")],
    )
    assert [s.name for s in sections] == ["tool:a", "tool:c", "frame:tool_disclaimer"]


def test_tool_default_prompt_guidance_is_none():
    """AC：`prompt_guidance` 是可选 property（默认 None），既有工具无需改动。"""
    assert _MinimalTool().prompt_guidance is None


# —— child 路径拼接 ——

def test_join_guidance_sorted_by_name():
    """order 相同 → 按 section 名排序，与注册表 `(order, name)` 一致。"""
    assert join_guidance([FakeTool("bash", "B"), FakeTool("apply_patch", "A")]) \
        == "A\n\nB\n\n以上工具按需调用即可；简单问答、对话与写作类任务直接回答，无需调用工具。"


def test_join_guidance_returns_none_when_empty():
    assert join_guidance([]) is None
    assert join_guidance([FakeTool("t")]) is None


def test_join_guidance_uses_double_newline():
    text = join_guidance([FakeTool("a", "A"), FakeTool("b", "B")])
    assert text is not None
    assert "A\n\nB" in text
    # 分隔符仍是 "\n\n"（澄清句也用同一分隔符拼接）
    assert "\n\n\n" not in text


# —— 父路径组装 ——

def test_tool_section_enters_profile_scope():
    registry = build_registry(tool_sections=tool_guidance_sections([FakeTool("bash", "G")]))
    text = registry.assemble("profile:coding").system_text

    identity = build_registry().assemble("profile:coding").system_text
    assert "G" in text
    assert text.index(identity) < text.index("G")  # guidance 在身份文本之后


def test_tool_section_does_not_enter_aux_scope():
    """`*` 只匹配 profile scope → 工具 section（含澄清句）不得污染 aux prompt。"""
    registry = build_registry(tool_sections=tool_guidance_sections([FakeTool("bash", "G")]))

    for scope in ("aux:compaction", "aux:memory_extraction"):
        assembled = registry.assemble(scope).system_text
        assert "按需调用即可" not in assembled  # 澄清句也不进 aux
        assert assembled == build_registry().assemble(scope).system_text


def test_tool_section_order_is_2000():
    persona = PersonaConfig(prefix="P", suffix="S")
    registry = build_registry(
        persona, tool_sections=tool_guidance_sections([FakeTool("t", "G")]),
    )
    text = registry.assemble("profile:coding").system_text

    identity = build_registry().assemble("profile:coding").system_text
    disclaimer = "以上工具按需调用即可；简单问答、对话与写作类任务直接回答，无需调用工具。"
    assert text.index("P") < text.index(identity) < text.index("G") < text.index(disclaimer) < text.index("S")
    assert text == f"P\n\n{identity}\n\nG\n\n{disclaimer}\n\nS"


def test_unregistered_tool_has_no_guidance():
    assert tool_guidance_sections([]) == []
    text = build_registry().assemble("profile:coding").system_text
    assert "delegate" not in text  # 工具缺席 → 说明缺席


# —— 命名与模板约束在注册期响亮失败 ——

def test_tool_name_must_be_section_safe():
    """工具名带连字符 → section 名非法。这是期望行为：命名约束被显式暴露。"""
    with pytest.raises(PromptError) as excinfo:
        build_registry(tool_sections=tool_guidance_sections([FakeTool("my-tool", "G")]))
    assert excinfo.value.code == "invalid_section_name"


def test_guidance_with_template_placeholder_raises():
    """工具 guidance 无变量声明处 → 含 `{{x}}` 在注册期抛 undefined_variable。"""
    with pytest.raises(PromptError) as excinfo:
        build_registry(tool_sections=tool_guidance_sections([FakeTool("bash", "{{x}}")]))
    assert excinfo.value.code == "undefined_variable"


# —— 漂移守卫 ——

def test_compose_matches_registry_order():
    """child 文本包裹的四段顺序必须与父路径注册表组装逐字节一致。"""
    base = build_registry().assemble("profile:coding").system_text
    persona = PersonaConfig(prefix="P", suffix="S")
    sections = tool_guidance_sections([FakeTool("t", "G")])
    disclaimer = "以上工具按需调用即可；简单问答、对话与写作类任务直接回答，无需调用工具。"

    # child 路径的 join_guidance 含澄清句（与父路径同源）——两边都含才不漂移。
    assert compose_agent_prompt(base, persona, f"G\n\n{disclaimer}") == (
        build_registry(persona, tool_sections=sections).assemble("profile:coding").system_text
    )


def test_compose_guidance_goes_before_suffix():
    assert compose_agent_prompt("B", PersonaConfig(suffix="S"), "G") == "B\n\nG\n\nS"


def test_compose_without_guidance_equals_apply_persona():
    """T5 的签名与语义未被破坏。"""
    persona = PersonaConfig(prefix="P", suffix="S")
    assert compose_agent_prompt("B", persona, None) == apply_persona("B", persona)
    assert compose_agent_prompt(None, None, None) is None
    assert apply_persona(None, None) is None


# —— 结构性边界 ——

def test_tool_sections_does_not_import_tooling():
    """prompt 包不得反向依赖 tooling 包（层序与环）。"""
    module = pathlib.Path(__file__).resolve().parents[2] / "src/agent_harness/prompt/tool_sections.py"
    source = module.read_text(encoding="utf-8")
    assert "import agent_harness.tooling" not in source
    assert "from agent_harness.tooling" not in source
