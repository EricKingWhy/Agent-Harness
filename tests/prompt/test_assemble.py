"""T2 组装语义（PRD §10.7）：按 target 分三段互不混装 + R4/R5/R7。

本文件用**本地构造的 registry**，不依赖 `builtin`（T3 才建）。

一处刻意**没有**的测试：票面要求 `test_assemble_duplicate_identity_raises`
（两条同名 identity → `missing_identity`）。该场景在本实现下**结构上不可达**——
`PromptRegistry._sections` 是以 section 名为 key 的 dict，同名 section 连注册都
进不去（R1 已抛 `duplicate_section`），因此 `len(ids)` 永远不会 > 1，R5 的
`!= 1` 实际退化为 `== 0`。写一条"注私表"的假测试只会掩盖这个事实，故改为在
代码处以注释说明（已作为规格观察报告给集成方）。
"""

from __future__ import annotations

import pytest

from agent_harness.prompt import PromptError, PromptRegistry, PromptSection, Target


def _registry(*sections: PromptSection) -> PromptRegistry:
    registry = PromptRegistry()
    for section in sections:
        registry.register(section)
    return registry


def _identity(scope: str, *, order: int = 100, text: str = "identity") -> PromptSection:
    """构造某 profile scope 的 identity section（R5 要求恰好一条）。"""
    return PromptSection(
        name=f"{scope}:identity",
        order=order,
        scopes=frozenset({scope}),
        target=Target.SYSTEM,
        text=text,
    )


def test_assemble_single_section_no_extra_separator() -> None:
    """单 section 时产物 = 原文逐字节，无任何多余前后缀/分隔符。

    这是 T3「逐字节等价搬迁」能成立的前提——多一个 `\\n` 都会让迁移失败。
    """
    product = _registry(_identity("profile:coding", text="你是编码助手。")).assemble(
        "profile:coding"
    )
    assert product.system_text == "你是编码助手。"


def test_assemble_joins_multiple_sections_with_blank_line() -> None:
    product = _registry(
        _identity("profile:coding", order=100, text="A"),
        PromptSection(
            "profile:coding:extra", 200, frozenset({"profile:coding"}), Target.SYSTEM, "B"
        ),
    ).assemble("profile:coding")
    assert product.system_text == "A\n\nB"


def test_assemble_groups_by_target() -> None:
    product = _registry(
        _identity("profile:coding", order=100, text="SYS"),
        PromptSection(
            "profile:coding:note", 200, frozenset({"profile:coding"}), Target.META_USER, "META"
        ),
        PromptSection(
            "profile:coding:frame", 300, frozenset({"profile:coding"}), Target.FRAGMENT, "FRAG"
        ),
    ).assemble("profile:coding")
    assert product.system_text == "SYS"
    assert product.meta_user_text == "META"
    assert product.fragment_text == "FRAG"


def test_assemble_meta_user_empty_when_none() -> None:
    product = _registry(_identity("profile:coding")).assemble("profile:coding")
    assert product.meta_user_text == ""


def test_assemble_fragment_empty_when_none() -> None:
    product = _registry(_identity("profile:coding", text="ID")).assemble("profile:coding")
    assert product.fragment_text == ""
    assert product.system_text == "ID"


def test_assemble_filters_by_scope() -> None:
    registry = _registry(
        _identity("profile:coding", text="C"), _identity("profile:main", text="M")
    )
    assert registry.assemble("profile:coding").system_text == "C"
    assert registry.assemble("profile:main").system_text == "M"


def test_assemble_wildcard_section_always_included() -> None:
    """`*` 覆盖所有 `profile:` scope，但**不**覆盖 `tool:` / `aux:`（PRD §10.5）。"""
    registry = _registry(
        PromptSection(
            "harness:identity", -1000, frozenset({"*"}), Target.SYSTEM, "SHARED"
        ),
        _identity("profile:coding"),
        _identity("profile:main"),
        PromptSection("tool:bash", 2000, frozenset({"tool:bash"}), Target.SYSTEM, "TOOL"),
        PromptSection("aux:demo", 3000, frozenset({"aux:demo"}), Target.SYSTEM, "AUX"),
    )
    assert "SHARED" in registry.assemble("profile:coding").system_text
    assert "SHARED" in registry.assemble("profile:main").system_text
    assert "SHARED" not in registry.assemble("tool:bash").system_text
    assert "SHARED" not in registry.assemble("aux:demo").system_text


def test_assemble_orders_by_order_then_name() -> None:
    product = _registry(
        PromptSection("profile:coding:zzz", 900, frozenset({"profile:coding"}), Target.SYSTEM, "LATE"),
        PromptSection("profile:coding:aaa", 50, frozenset({"profile:coding"}), Target.SYSTEM, "EARLY"),
        _identity("profile:coding", order=100, text="ID"),
    ).assemble("profile:coding")
    assert product.system_text == "EARLY\n\nID\n\nLATE"


def test_assemble_missing_variable_raises() -> None:
    registry = PromptRegistry()
    registry.variable("x")
    registry.register(_identity("profile:coding", text="你好 {{x}}"))
    with pytest.raises(PromptError) as err:
        registry.assemble("profile:coding")
    assert err.value.code == "missing_variable"


def test_assemble_provides_variable() -> None:
    registry = PromptRegistry()
    registry.variable("x")
    registry.register(_identity("profile:coding", text="你好 {{x}}"))
    assert registry.assemble("profile:coding", {"x": "值"}).system_text == "你好 值"


def test_assemble_missing_identity_raises() -> None:
    registry = _registry(
        PromptSection(
            "profile:coding:extra", 200, frozenset({"profile:coding"}), Target.SYSTEM, "E"
        )
    )
    with pytest.raises(PromptError) as err:
        registry.assemble("profile:coding")
    assert err.value.code == "missing_identity"


def test_duplicate_identity_section_cannot_be_registered() -> None:
    """把"R5 的 `len(ids) != 1` 为何只可能是 0"编码成测试，而不是只留一句注释。

    `_sections` 以 section 名为 key，同名 section 连注册都进不去（R1 抛
    `duplicate_section`）——所以"两条 identity"根本构造不出来，票面要求的
    `test_assemble_duplicate_identity_raises` 无法写成行为测试；这里改为锁住
    那条不可达性的**成因**：重名注册必须被拒。
    """
    registry = _registry(_identity("profile:coding"))
    with pytest.raises(PromptError) as err:
        registry.register(_identity("profile:coding", order=999))
    assert err.value.code == "duplicate_section"


def test_assemble_non_profile_scope_needs_no_identity() -> None:
    registry = _registry(
        PromptSection("tool:bash", 2000, frozenset({"tool:bash"}), Target.SYSTEM, "BASH")
    )
    assert registry.assemble("tool:bash").system_text == "BASH"


def test_assemble_empty_scope_raises() -> None:
    with pytest.raises(PromptError) as err:
        _registry().assemble("profile:coding")
    assert err.value.code == "empty_assembly"


def test_assemble_invalid_scope_raises() -> None:
    with pytest.raises(PromptError) as err:
        _registry().assemble("coding")
    assert err.value.code == "invalid_scope"
