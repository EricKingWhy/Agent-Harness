"""T3 的裁判：三条 profile 文本与迁移前**逐字节相同**（零行为变化）。

`LEGACY_SYSTEM_PROMPTS` 是从迁移前的 `agent/profiles.py` 用 `repr()` 取回的原文，
**不是手抄**——手抄漏一个空格或把 `——` 写成 `-`，这份基线就会把错误固化成"正确"。

本文件一律用 `build_registry()`（无参、确定性，不读环境）。本 Agent 在此**修正过
一处自己的错误说法**：曾以为 T5 会让 `DEFAULT_REGISTRY` 带上 persona，但交接文档
§4.4 明确 `DEFAULT_REGISTRY = build_registry()` **永不读环境**，persona 由装配点
`build_registry(persona=…)` 注入——所以 `_builtin_prompt`（读 `DEFAULT_REGISTRY`）
拿到的永远是**不含 persona 的 base 文本**，本文件的断言在 T5 之后依然成立。
"""

from __future__ import annotations

import pytest

from agent_harness.agent.profiles import BUILTIN_PROFILES
from agent_harness.prompt.builtin import build_registry

#: 迁移前 `BUILTIN_PROFILES[name].system_prompt` 的 repr 原文（迁移基线）。
LEGACY_SYSTEM_PROMPTS = {
    "main": (
        "你是主协调 agent。简单任务直接完成；需要并行/专项深入时用 delegate "
        "工具把 scoped task 派给合适的子代理（coding=写代码，research_review="
        "调研与审查），并综合它们的结构化结果。委派时给出完整自洽的任务描述"
        "——子代理看不到你们的对话历史。"
    ),
    "coding": (
        "你是编码 agent，在给定 workspace 内完成 scoped task：读写文件、运行命令、"
        "验证结果。结束时给出简明总结：做了什么、改了哪些文件、验证结果，以及"
        "任何未解决事项。"
    ),
    "research_review": (
        "你是调研审查 agent，只读地收集证据（本地文件、知识语料、网络）并给出"
        "带引用的结论。结束时给出简明总结：结论、引用（citation）、以及任何未"
        "解决事项。你没有写权限。"
    ),
}

NAMES = sorted(LEGACY_SYSTEM_PROMPTS)


@pytest.mark.parametrize("name", NAMES)
def test_profile_prompt_byte_identical(name: str) -> None:
    """注册表组装出的文本 == 迁移前内联原文，逐字节。"""
    assert (
        build_registry().assemble(f"profile:{name}").system_text
        == LEGACY_SYSTEM_PROMPTS[name]
    )


@pytest.mark.parametrize("name", NAMES)
def test_builtin_profiles_come_from_registry(name: str) -> None:
    """`BUILTIN_PROFILES` 确实取自注册表——串错档（coding 拿到 main 的文案）会红。"""
    assert (
        BUILTIN_PROFILES[name].system_prompt
        == build_registry().assemble(f"profile:{name}").system_text
    )


def test_profiles_are_scope_isolated() -> None:
    coding = build_registry().assemble("profile:coding").system_text
    assert "编码 agent" in coding
    assert "主协调" not in coding
    assert "调研审查" not in coding

    main = build_registry().assemble("profile:main").system_text
    assert "主协调" in main
    assert "编码 agent" not in main


def test_assemble_returns_no_meta_user_for_profiles() -> None:
    assert build_registry().assemble("profile:main").meta_user_text == ""


def test_wildcard_sections_absent_in_p0() -> None:
    """P0 只有三条 profile；首个 `*` section 是 T5 的 persona。"""
    assert [s.name for s in build_registry().available() if "*" in s.scopes] == []
