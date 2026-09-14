"""T1 模板器：严格语法 + **单趟扫描**（不重扫替换值）。

替换值原样写入是硬约束：模板引擎重扫替换值是注入面（用户/模型可控的文本里
带 `{{secret}}` 就会去变量表里取值）。这里用"绝不重扫"从算法上堵死。
"""

from __future__ import annotations

import pytest

from agent_harness.prompt import PromptError, extract_variables, render


def test_render_substitutes_variable() -> None:
    assert render("你好 {{name}}", {"name": "世界"}) == "你好 世界"


def test_render_multiple_variables() -> None:
    assert render("{{a}}-{{b}}", {"a": "1", "b": "2"}) == "1-2"


def test_render_missing_variable_raises() -> None:
    with pytest.raises(PromptError) as err:
        render("{{name}}", {})
    assert err.value.code == "missing_variable"


def test_render_rejects_space_in_braces() -> None:
    with pytest.raises(PromptError) as err:
        render("{{ name }}", {"name": "x"})
    assert err.value.code == "template_syntax"


def test_render_rejects_uppercase_name() -> None:
    with pytest.raises(PromptError) as err:
        render("{{Name}}", {"Name": "x"})
    assert err.value.code == "template_syntax"


def test_render_rejects_empty_braces() -> None:
    with pytest.raises(PromptError) as err:
        render("{{}}", {})
    assert err.value.code == "template_syntax"


def test_render_rejects_triple_brace() -> None:
    with pytest.raises(PromptError) as err:
        render("{{{name}}}", {"name": "x"})
    assert err.value.code == "template_syntax"


def test_render_rejects_unclosed() -> None:
    with pytest.raises(PromptError) as err:
        render("{{name", {})
    assert err.value.code == "template_syntax"


def test_render_rejects_orphan_close() -> None:
    with pytest.raises(PromptError) as err:
        render("name}}", {})
    assert err.value.code == "template_syntax"


def test_render_rejects_orphan_close_before_a_variable() -> None:
    """孤立 `}}` 出现在 `{{` **之前**也要拦——那是与尾部检查不同的另一条分支。"""
    with pytest.raises(PromptError) as err:
        render("}} {{a}}", {"a": "x"})
    assert err.value.code == "template_syntax"


def test_render_does_not_rescan_substituted_value() -> None:
    """替换值里的 `{{b}}` 原样输出——不展开、不报错（不重扫）。"""
    assert render("{{a}}", {"a": "{{b}}"}) == "{{b}}"


def test_extract_variables_returns_names() -> None:
    assert extract_variables("{{a}} 和 {{b}}") == frozenset({"a", "b"})


def test_extract_variables_raises_on_bad_syntax() -> None:
    with pytest.raises(PromptError) as err:
        extract_variables("{{ Bad }}")
    assert err.value.code == "template_syntax"
