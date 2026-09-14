"""T1 注册表：校验规则 R1/R2/R3 + scope 筛选。

最容易做错的一条：`*` **只匹配 `profile:<name>`**，不覆盖 `aux:*`——否则设了
AGENT_PERSONA 就会改掉压缩/抽取这类辅助 LLM 的一次性指令（T4 文本等价搬迁
当场破产）。这里的 `test_sections_excludes_wildcard_for_aux_scope` 就是那道闸。
"""

from __future__ import annotations

import pytest

from agent_harness.prompt import PromptError, PromptRegistry, PromptSection, Target


def _section(
    name: str,
    *,
    order: int = 100,
    scopes: frozenset[str] = frozenset({"profile:coding"}),
    target: Target = Target.SYSTEM,
    text: str = "正文",
) -> PromptSection:
    return PromptSection(
        name=name, order=order, scopes=scopes, target=target, text=text
    )


def test_register_and_available() -> None:
    registry = PromptRegistry()
    registry.register(_section("profile:coding:extra", order=200))
    registry.register(_section("profile:coding:identity", order=100))
    assert [s.name for s in registry.available()] == [
        "profile:coding:identity",
        "profile:coding:extra",
    ]


def test_duplicate_section_name_raises() -> None:
    registry = PromptRegistry()
    registry.register(_section("profile:coding:identity"))
    with pytest.raises(PromptError) as err:
        registry.register(_section("profile:coding:identity"))
    assert err.value.code == "duplicate_section"


def test_invalid_section_name_raises() -> None:
    registry = PromptRegistry()
    with pytest.raises(PromptError) as err:
        registry.register(_section("bash"))
    assert err.value.code == "invalid_section_name"


def test_invalid_scope_raises() -> None:
    registry = PromptRegistry()
    with pytest.raises(PromptError) as err:
        registry.register(_section("profile:coding:identity", scopes=frozenset({"coding"})))
    assert err.value.code == "invalid_scope"


def test_empty_scopes_raises() -> None:
    registry = PromptRegistry()
    with pytest.raises(PromptError) as err:
        registry.register(_section("profile:coding:identity", scopes=frozenset()))
    assert err.value.code == "invalid_scope"


def test_wildcard_scope_accepted() -> None:
    registry = PromptRegistry()
    registry.register(_section("harness:identity", scopes=frozenset({"*"})))
    assert [s.name for s in registry.available()] == ["harness:identity"]


def test_undefined_variable_raises() -> None:
    registry = PromptRegistry()
    with pytest.raises(PromptError) as err:
        registry.register(_section("profile:coding:identity", text="你好 {{x}}"))
    assert err.value.code == "undefined_variable"
    assert "x" in str(err.value)


def test_declared_variable_allows_registration() -> None:
    registry = PromptRegistry()
    registry.variable("x", description="测试变量")
    registry.register(_section("profile:coding:identity", text="你好 {{x}}"))
    assert registry.declared_variables() == frozenset({"x"})


def test_invalid_variable_name_raises() -> None:
    registry = PromptRegistry()
    with pytest.raises(PromptError) as err:
        registry.variable("Bad-Name")
    assert err.value.code == "invalid_variable_name"


def test_sections_filters_by_scope() -> None:
    registry = PromptRegistry()
    registry.register(_section("profile:coding:identity", scopes=frozenset({"profile:coding"})))
    registry.register(_section("profile:main:identity", scopes=frozenset({"profile:main"})))
    assert [s.name for s in registry.sections("profile:coding")] == [
        "profile:coding:identity"
    ]


def test_sections_includes_wildcard_for_profile_scope() -> None:
    registry = PromptRegistry()
    registry.register(_section("harness:identity", order=-1000, scopes=frozenset({"*"})))
    assert [s.name for s in registry.sections("profile:coding")] == ["harness:identity"]


def test_sections_excludes_wildcard_for_aux_scope() -> None:
    """`*` 不覆盖 `aux:*`（PRD §10.5 的结构性边界）。"""
    registry = PromptRegistry()
    registry.register(_section("harness:identity", scopes=frozenset({"*"})))
    assert registry.sections("aux:compaction") == []


def test_sections_sorted_by_order_then_name() -> None:
    """同 order 必须按 name 稳定排序——否则同 order 的注入顺序不确定（R6）。"""
    registry = PromptRegistry()
    registry.register(_section("tool:bash", order=2000, scopes=frozenset({"profile:coding"})))
    registry.register(_section("tool:edit", order=2000, scopes=frozenset({"profile:coding"})))
    assert [s.name for s in registry.sections("profile:coding")] == ["tool:bash", "tool:edit"]


def test_requires_derived_from_text() -> None:
    registry = PromptRegistry()
    registry.variable("a")
    registry.variable("b")
    section = _section("profile:coding:identity", text="{{a}}{{b}}")
    registry.register(section)
    assert section.requires == frozenset({"a", "b"})
