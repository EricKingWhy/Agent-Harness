"""T5：persona（`AGENT_PERSONA` env JSON）——解析严格性 + 组装顺序一致性。

两条最关键的断言：
- `apply_persona(base, None)` / `apply_persona(base, PersonaConfig())` **逐字节**返回
  `base`——这是 C4/C5/C7 与 B2 契约保持绿的前提（persona 未设 = 零行为变化）。
- `test_apply_persona_matches_registry_order`：父路径走注册表组装、child 路径走
  `apply_persona` 文本包裹，两套机制必须产出同一顺序（prefix → base → suffix）。
  这条漂移守卫是本票不可省的。
"""

from __future__ import annotations

import pytest

from agent_harness.prompt import (
    PersonaConfig,
    PromptError,
    apply_persona,
    parse_persona_config,
)
from agent_harness.prompt.builtin import _declared_scopes, build_registry
from agent_harness.prompt.persona import _MAX_PERSONA_CHARS, persona_sections
from agent_harness.prompt.registry import run_self_check
from agent_harness.prompt.section import Target


def _code(excinfo: pytest.ExceptionInfo[PromptError]) -> str:
    return excinfo.value.code


def test_parse_empty_returns_no_persona() -> None:
    for raw in ("", None, "   "):
        assert parse_persona_config(raw).is_empty


def test_parse_valid_json() -> None:
    persona = parse_persona_config('{"prefix":"P","suffix":"S"}')
    assert persona.prefix == "P"
    assert persona.suffix == "S"
    assert not persona.is_empty


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(PromptError) as err:
        parse_persona_config('{"prefix":')
    assert _code(err) == "invalid_persona_config"


def test_parse_unknown_key_raises() -> None:
    """拼错的键必须点名——静默忽略会让用户以为配置生效了。"""
    with pytest.raises(PromptError) as err:
        parse_persona_config('{"prefx":"x"}')
    assert _code(err) == "invalid_persona_config"
    assert "prefx" in str(err.value)


def test_parse_wrong_type_raises() -> None:
    with pytest.raises(PromptError) as err:
        parse_persona_config('{"prefix":123}')
    assert _code(err) == "invalid_persona_config"


@pytest.mark.parametrize("raw", ['[1,2]', '"x"', "42"])
def test_parse_non_object_raises(raw: str) -> None:
    with pytest.raises(PromptError) as err:
        parse_persona_config(raw)
    assert _code(err) == "invalid_persona_config"


def test_parse_overlong_raises() -> None:
    with pytest.raises(PromptError) as err:
        parse_persona_config('{"prefix":"%s"}' % ("x" * (_MAX_PERSONA_CHARS + 1)))
    assert _code(err) == "invalid_persona_config"


def test_parse_at_limit_ok() -> None:
    persona = parse_persona_config('{"prefix":"%s"}' % ("x" * _MAX_PERSONA_CHARS))
    assert len(persona.prefix) == _MAX_PERSONA_CHARS


def test_sections_only_for_nonempty_sides() -> None:
    assert [s.name for s in persona_sections(PersonaConfig(prefix="P"))] == ["persona:prefix"]
    assert [s.name for s in persona_sections(PersonaConfig(suffix="S"))] == ["persona:suffix"]
    assert persona_sections(PersonaConfig()) == []
    assert persona_sections(PersonaConfig(prefix="   ", suffix="  ")) == []


def test_section_scopes_is_wildcard() -> None:
    sections = persona_sections(PersonaConfig(prefix="P", suffix="S"))
    assert [s.name for s in sections] == ["persona:prefix", "persona:suffix"]
    for section in sections:
        assert section.scopes == frozenset({"*"})
        assert section.target is Target.SYSTEM


def test_apply_persona_prefix_only() -> None:
    assert apply_persona("BASE", PersonaConfig(prefix="P")) == "P\n\nBASE"


def test_apply_persona_suffix_only() -> None:
    assert apply_persona("BASE", PersonaConfig(suffix="S")) == "BASE\n\nS"


def test_apply_persona_both() -> None:
    assert apply_persona("BASE", PersonaConfig(prefix="P", suffix="S")) == "P\n\nBASE\n\nS"


def test_apply_persona_empty_persona_is_byte_identical() -> None:
    assert apply_persona("BASE", PersonaConfig()) == "BASE"


def test_apply_persona_none_persona_is_byte_identical() -> None:
    assert apply_persona("BASE", None) == "BASE"


def test_apply_persona_base_none_empty_persona() -> None:
    """C4 的关键前提：无 profile + 无 persona → 仍然没有 system prompt。"""
    assert apply_persona(None, PersonaConfig()) is None
    assert apply_persona(None, None) is None


def test_apply_persona_base_none_with_persona() -> None:
    assert apply_persona(None, PersonaConfig(prefix="P", suffix="S")) == "P\n\nS"


def test_apply_persona_matches_registry_order() -> None:
    """漂移守卫：父路径（注册表组装）与 child 路径（文本包裹）顺序必须一致。"""
    base = build_registry().assemble("profile:coding").system_text
    persona = PersonaConfig(prefix="P", suffix="S")
    assert apply_persona(base, persona) == build_registry(persona).assemble(
        "profile:coding"
    ).system_text


def test_persona_sections_do_not_touch_aux_scopes() -> None:
    """`*` 只覆盖 `profile:`——persona 不得进入摘要器/抽取器的一次性指令。"""
    persona = PersonaConfig(prefix="P")
    assert build_registry(persona).assemble("aux:compaction").system_text == (
        build_registry().assemble("aux:compaction").system_text
    )


def test_persona_applies_to_all_profiles() -> None:
    persona = PersonaConfig(prefix="P")
    for name in ("main", "coding", "research_review"):
        assert build_registry(persona).assemble(f"profile:{name}").system_text.startswith(
            "P\n\n"
        )


def test_persona_registry_self_check_passes() -> None:
    """persona 引入 `*` section 后，自检仍覆盖全部非 `*` scope。"""
    registry = build_registry(PersonaConfig(prefix="P", suffix="S"))
    run_self_check(registry, _declared_scopes(registry))


def test_persona_text_with_undeclared_variable_raises() -> None:
    """坏配置响亮失败，不静默渲染成空串（R3b）。"""
    with pytest.raises(PromptError) as err:
        build_registry(PersonaConfig(prefix="{{nope}}"))
    assert _code(err) == "undefined_variable"
