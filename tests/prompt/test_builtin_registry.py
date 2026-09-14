"""T3 默认注册表的完整性与启动自检。

区分 `build_registry()` 与 `DEFAULT_REGISTRY`：前者无参、确定性；后者是"按当前
环境构建的结果"（T5 起含 persona）。断言组成必须用前者。
"""

from __future__ import annotations

from agent_harness.prompt import DEFAULT_REGISTRY, PersonaConfig, run_self_check
from agent_harness.prompt.builtin import _declared_scopes, build_registry

_PROFILE_SCOPES = ["profile:coding", "profile:main", "profile:research_review"]


def test_builtin_registry_has_three_profile_sections() -> None:
    """只统计 `profile:` 前缀 scope 的 section——`aux:*`（T4 起）不计入。

    刻意**不**断言"总数 == N"：每加一条辅助/框架 prompt 都要改这个数字，那是
    无意义的摩擦。总数另有 `test_aux_prompts.py` 的当票断言管。
    """
    profile_sections = [
        s
        for s in build_registry().available()
        if any(scope.startswith("profile:") for scope in s.scopes)
    ]
    assert [s.name for s in profile_sections] == [
        "profile:coding:identity",
        "profile:main:identity",
        "profile:research_review:identity",
    ]


def test_builtin_registry_self_check_passed() -> None:
    """import 成功本身已证明自检通过；这里再做一次显式断言防回归。"""
    run_self_check(build_registry(), _PROFILE_SCOPES)


def test_builtin_registry_sections_sorted() -> None:
    sections = build_registry().available()
    keys = [(s.order, s.name) for s in sections]
    assert keys == sorted(keys)


def test_build_registry_is_deterministic() -> None:
    """两次构建结果逐字段相等——证明它不依赖 env / 全局可变状态。"""
    first = [(s.name, s.order, s.text) for s in build_registry().available()]
    second = [(s.name, s.order, s.text) for s in build_registry().available()]
    assert first == second


def test_default_registry_is_zero_config_baseline() -> None:
    """`DEFAULT_REGISTRY` 必须等于一次**全新零配置构建**——即它不读环境。

    交接文档 §4.4：`DEFAULT_REGISTRY = build_registry()`，**永不读环境变量**；
    persona 由装配点 `build_registry(persona=…)` 注入，不在默认注册表上变形。
    这条断言就是那条不变量的机器化表达——两半缺一不可：
    ① 与零配置构建相等（谁把 env 派生 section 塞进 DEFAULT_REGISTRY，这里红）；
    ② 与带 persona 的构建**不**相等（证明 persona 确实只在装配点注入）。
    """
    baseline = [(s.name, s.order, s.text) for s in build_registry().available()]
    assert [(s.name, s.order, s.text) for s in DEFAULT_REGISTRY.available()] == baseline
    assert baseline != [
        (s.name, s.order, s.text)
        for s in build_registry(PersonaConfig(prefix="P")).available()
    ]


def test_declared_variables_are_exactly_the_six_used() -> None:
    """T4 `tail_text`；T7 快照三值（BUG-013 瘦身后 model/tools 已删）；T8 两值。

    断言**精确集合**而不是 `"tail_text" in ...`：多声明一个没人用的变量说明
    `_DECLARED_VARIABLES` 被写脏了，值得红。BUG-013 删除快照的 model/tools 后，
    也不得残留这两个声明（防回归复活）。
    """
    assert build_registry().declared_variables() == frozenset(
        {"tail_text", "cwd", "os", "date", "tool_name", "consecutive_failures"}
    )


def test_declared_scopes_covers_every_non_wildcard_scope() -> None:
    """自检 scope 集 = 注册表里所有非 `*` 的 scope（T4 `aux:*`，T7 快照，T8 框架/纠偏）。"""
    assert _declared_scopes(build_registry()) == [
        "aux:compaction",
        "aux:fork_tail",
        "aux:memory_extraction",
        "corrective:tool_failure_guard",
        "frame:recovery_skipped",
        "frame:untrusted_knowledge",
        "frame:untrusted_websearch",
        "profile:coding",
        "profile:main",
        "profile:research_review",
        "runtime:context_snapshot",
    ]
