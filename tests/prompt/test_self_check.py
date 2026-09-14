"""T2 启动自检（PRD §10.8）：每个 scope 都能组装 → 配置错误在进程启动暴露。

自检的变量用**空串占位**（取自各 section 自动推导的 requires），所以它只验证结构
完整性，不验证调用方是否会真的提供变量值（静态不可判定）。
"""

from __future__ import annotations

import pytest

from agent_harness.prompt import (
    PromptError,
    PromptRegistry,
    PromptSection,
    Target,
    run_self_check,
)


def _registry(*sections: PromptSection) -> PromptRegistry:
    registry = PromptRegistry()
    for section in sections:
        registry.register(section)
    return registry


def _identity(scope: str) -> PromptSection:
    return PromptSection(
        f"{scope}:identity", 100, frozenset({scope}), Target.SYSTEM, "identity"
    )


def test_self_check_passes_on_valid_registry() -> None:
    run_self_check(_registry(_identity("profile:coding")), ["profile:coding"])


def test_self_check_raises_on_missing_identity() -> None:
    registry = _registry(
        PromptSection("profile:bad:extra", 200, frozenset({"profile:bad"}), Target.SYSTEM, "E")
    )
    with pytest.raises(PromptError) as err:
        run_self_check(registry, ["profile:bad"])
    assert err.value.code == "missing_identity"


def test_self_check_raises_on_empty_scope() -> None:
    with pytest.raises(PromptError) as err:
        run_self_check(_registry(), ["tool:none"])
    assert err.value.code == "empty_assembly"


def test_self_check_checks_every_scope() -> None:
    """遍历必须走到第二个 scope——只看第一个就返回等于没做自检。"""
    registry = _registry(_identity("profile:coding"))
    with pytest.raises(PromptError) as err:
        run_self_check(registry, ["profile:coding", "tool:none"])
    assert err.value.code == "empty_assembly"


def test_self_check_fills_declared_variables() -> None:
    """含变量的 scope 也要能被自检覆盖——自动填空串，而不是传 `{}`。

    传 `{}` 会让带 `{{foo}}` 的 scope 在 import 期抛 `missing_variable`，
    那是误报（不是配置错误）。这条对照断言锁住"确实填了占位值"。
    """
    registry = PromptRegistry()
    registry.variable("foo")
    registry.register(
        PromptSection("aux:demo", 3000, frozenset({"aux:demo"}), Target.SYSTEM, "带 {{foo}} 的正文")
    )
    run_self_check(registry, ["aux:demo"])  # 不抛

    with pytest.raises(PromptError) as err:
        registry.assemble("aux:demo")  # 对照：不传值 → 真的会抛
    assert err.value.code == "missing_variable"


def test_bad_template_rejected_at_registration() -> None:
    """非法模板在**注册期**就被拦下（R3a），所以自检不可能把它"吞掉"。

    断言因此落在 `register` 上：`{{Bad}}`（大写）非法 → `template_syntax`，
    根本进不了 `_sections`。若哪天 register 不再做语法校验，这条会红，
    提醒必须把该职责补回自检（§10.8 把"模板语法"列为自检职责，实际由 register
    承担——T3 的 builtin 必须走 `register` 才能吃到这道校验）。
    """
    registry = PromptRegistry()
    with pytest.raises(PromptError) as err:
        registry.register(
            PromptSection("aux:demo", 3000, frozenset({"aux:demo"}), Target.SYSTEM, "{{Bad}}")
        )
    assert err.value.code == "template_syntax"
