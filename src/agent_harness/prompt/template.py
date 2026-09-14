"""严格模板器（PRD §10.6）：**单趟扫描 + 增量拼接**。

绝不整体 `re.sub`，也绝不对替换结果重扫——替换值原样写入。这把"模型/用户可控
文本里含 `{{x}}` 会在渲染期被再次展开"这条注入路径从算法上堵死，而不是靠调用方
自觉转义。

扫描逻辑由 `_scan` 单独承载，`render` 与 `extract_variables` 共用同一趟：否则
"渲染时合法的模板"与"注册期校验认为合法的模板"会漂移。
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping

from agent_harness.prompt.errors import PromptError

__all__ = ["extract_variables", "render"]

#: `[a-z]` 开头天然排除大写与数字开头；紧贴花括号，故 `{{ name }}` 不匹配。
_VAR = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


def _syntax(detail: str) -> PromptError:
    return PromptError(f"模板语法非法：{detail}", code="template_syntax")


def _scan(text: str) -> Iterator[tuple[bool, str]]:
    """单趟扫描，逐段产出 `(是否变量, 值)`。语法非法即抛 `template_syntax`。

    变量段产出变量名；文本段产出字面文本。空文本段不产出（无意义）。
    """
    i = 0
    length = len(text)
    while i < length:
        start = text.find("{{", i)
        if start == -1:
            tail = text[i:]
            if "}}" in tail:  # 孤立 }}：没有配对的 {{
                raise _syntax(f"孤立的 }}}} 没有配对的 {{{{：{tail!r}")
            yield False, tail
            return
        before = text[i:start]
        if "}}" in before:  # 孤立 }}：夹在两段 {{ 之间
            raise _syntax(f"孤立的 }}}} 没有配对的 {{{{：{before!r}")
        if before:
            yield False, before
        match = _VAR.match(text, start)
        if match is None:  # {{ 未闭合 / 含空格 / 大写 / 空 / 三花括号
            raise _syntax(f"{{{{ 未闭合或变量名非法：{text[start : start + 24]!r}")
        yield True, match.group(1)
        i = match.end()


def render(text: str, variables: Mapping[str, str]) -> str:
    """把 `{{name}}` 替换为 `variables[name]`，替换值原样写入不再扫描。"""
    out: list[str] = []
    for is_variable, value in _scan(text):
        if is_variable:
            if value not in variables:
                raise PromptError(f"变量 {value!r} 未提供值", code="missing_variable")
            out.append(variables[value])
        else:
            out.append(value)
    return "".join(out)


def extract_variables(text: str) -> frozenset[str]:
    """扫描 text 引用到的变量名集合。

    语法非法同样抛 `template_syntax`——让坏模板在**注册期**就被拦住，而不是等到
    运行时渲染才炸。
    """
    return frozenset(value for is_variable, value in _scan(text) if is_variable)
