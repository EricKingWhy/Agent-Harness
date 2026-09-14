"""Prompt 注册表（T1：注册 / 查询侧；`assemble` 由 T2 加）。

校验规则 R1/R2/R3 的判据全部是 PRD §10.5 的三条正则——集中在这里，不散到调用点。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from agent_harness.prompt.errors import PromptError
from agent_harness.prompt.section import PromptSection, Target
from agent_harness.prompt.template import extract_variables, render

__all__ = ["AssembledPrompt", "PromptRegistry", "run_self_check"]

#: section 名：至少两段（`^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$`）
_SECTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$")
#: scope 名：`<段>:<段>`；字面量 `*` 另判
_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")
#: 变量名
_VARIABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: `*` 只覆盖 agent profile——见 `PromptRegistry._matches`。
_WILDCARD = "*"
_PROFILE_PREFIX = "profile:"


def _require_valid_scope(scope: str, *, context: str) -> None:
    """scope 判据的**唯一落点**（PRD §10.5）：`<段>:<段>` 或字面量 `*`。

    注册期校验各 section 的 scopes、查询期校验 `sections(scope)` 的参数，用的是
    同一条规则——分两处写迟早漂移，所以只留这一个函数。
    """
    if scope != _WILDCARD and not _SCOPE_RE.match(scope):
        raise PromptError(
            f"{context}（需 `<段>:<段>` 或 `*`）：{scope!r}", code="invalid_scope"
        )


@dataclass(frozen=True)
class AssembledPrompt:
    """组装产物三段。

    FRAGMENT 单列而非并入 META_USER：它不是消息，若混进 user-role 文本就会被
    当成模型输入持久化 / 参与记忆抽取，污染边界当场失守。
    """

    system_text: str
    meta_user_text: str
    fragment_text: str


class PromptRegistry:
    """section 与变量的集中登记处。同名重复注册**抛错**，绝不静默覆盖。"""

    def __init__(self) -> None:
        self._sections: dict[str, PromptSection] = {}
        self._variables: dict[str, str] = {}

    def register(self, section: PromptSection) -> None:
        """登记一条 section；依次跑 R1 / R2 / R3，任一步失败即抛 `PromptError`。"""
        # R1 —— 名字合法 + 不重名
        if not _SECTION_NAME_RE.match(section.name):
            raise PromptError(
                f"section 名非法（需至少两段小写标识符，如 profile:coding:identity）："
                f"{section.name!r}",
                code="invalid_section_name",
            )
        if section.name in self._sections:
            raise PromptError(
                f"section {section.name!r} 已注册；重复注册被拒绝，不静默覆盖",
                code="duplicate_section",
            )
        # R2 —— scope 合法（含"不能为空"：永不注入的 section 是无意义的配置错误）
        if not section.scopes:
            raise PromptError(
                f"section {section.name!r} 的 scopes 为空——永不注入的 section 是无意义的配置错误",
                code="invalid_scope",
            )
        for scope in sorted(section.scopes):
            _require_valid_scope(scope, context=f"section {section.name!r} 的 scope 非法")
        # R3a —— 模板语法（坏模板在注册期拦下，不留到运行时）
        required = extract_variables(section.text)
        # R3b —— 引用到的变量必须已声明
        missing = required - self.declared_variables()
        if missing:
            raise PromptError(
                f"section {section.name!r} 引用了未声明的变量：{sorted(missing)}"
                f"（先调用 variable(name) 声明）",
                code="undefined_variable",
            )
        self._sections[section.name] = section

    def variable(self, name: str, *, description: str = "") -> None:
        """声明一个可用变量。

        重复声明同名**允许且幂等**，描述以最后一次为准——变量表是"可提供值的
        名字空间"，同一变量被多处重复声明是正常写法，没必要当成冲突。
        """
        if not _VARIABLE_NAME_RE.match(name):
            raise PromptError(
                f"变量名非法（需 ^[a-z][a-z0-9_]*$）：{name!r}",
                code="invalid_variable_name",
            )
        self._variables[name] = description

    def sections(self, scope: str) -> list[PromptSection]:
        """该 scope 命中的 section，按 `(order, name)` 稳定排序。"""
        _require_valid_scope(scope, context="scope 非法")
        included = [s for s in self._sections.values() if self._matches(s, scope)]
        return sorted(included, key=lambda s: (s.order, s.name))

    def available(self) -> list[PromptSection]:
        """全量 section（"一处看全貌"的视图），同样按 `(order, name)` 排序。"""
        return sorted(self._sections.values(), key=lambda s: (s.order, s.name))

    def assemble(
        self, scope: str, variables: Mapping[str, str] | None = None
    ) -> AssembledPrompt:
        """组装一个 scope 的 prompt（PRD §10.7）。

        拼接分隔符固定 `"\\n\\n"`；scope 只命中一条 section 时产物 = 该 section
        原文逐字节（无多余前后缀）——这是 T3「逐字节等价搬迁」成立的前提。

        三个 target **各自独立分区**，绝不混装：FRAGMENT 若被并进 `system_text`，
        调用方会把"以下内容是语料数据"这类片段当系统提示装错位置。
        """
        variables = dict(variables or {})
        included = self.sections(scope)  # 筛选 + 按 (order, name) 排序，不在此重复实现
        if not included:  # R7
            raise PromptError(
                f"scope '{scope}' 组装产物为空（无任何 section 被纳入）",
                code="empty_assembly",
            )
        if scope.startswith(_PROFILE_PREFIX):  # R5：只对 profile scope 要求 identity
            identity_name = f"{scope}:identity"
            ids = [s for s in included if s.name == identity_name]
            # `!= 1` 而非 `== 0`：`_sections` 以 name 为 key，同名 section 注册期就被
            # R1 拒了，所以 >1 结构上不可达；保留 `!= 1` 是为了与 PRD §10.7 一致，
            # 也防止将来换成分层注册时静默放行。
            if len(ids) != 1:
                raise PromptError(
                    f"scope '{scope}' 需要恰好一条 '{identity_name}'，实际 {len(ids)} 条",
                    code="missing_identity",
                )
        # R4 不在这里重复实现：render 已对未提供值的变量抛 missing_variable。
        return AssembledPrompt(
            system_text="\n\n".join(
                render(s.text, variables) for s in included if s.target is Target.SYSTEM
            ),
            meta_user_text="\n\n".join(
                render(s.text, variables) for s in included if s.target is Target.META_USER
            ),
            fragment_text="\n\n".join(
                render(s.text, variables) for s in included if s.target is Target.FRAGMENT
            ),
        )

    def declared_variables(self) -> frozenset[str]:
        return frozenset(self._variables)

    @staticmethod
    def _matches(section: PromptSection, scope: str) -> bool:
        """scope 命中判据（PRD §10.5）。

        `*` **只**覆盖 `profile:<name>`：它表达的是"所有 agent 身份"。`aux:*` 是
        辅助 LLM 的一次性指令（摘要器 / 抽取器），把 persona 注进去会直接污染其
        指令语义——所以这里是结构性前缀判定，不靠各 aux 调用点自觉传参。
        """
        if scope in section.scopes:
            return True
        return _WILDCARD in section.scopes and scope.startswith(_PROFILE_PREFIX)


def run_self_check(registry: PromptRegistry, scopes: Iterable[str]) -> None:
    """对每个 scope 跑一次组装，配置错误在进程启动时 fail-fast（PRD §10.8）。

    变量用**空字符串占位**（取自各 section 自动推导的 `requires`），因此本函数只验证
    **结构完整性**——section 名 / scope 合法性、identity 唯一性、产物非空、模板语法——
    **不验证变量是否会被调用方真正提供**（静态不可判定）。

    为什么是"自动填空串"而不是传 `{}`：含变量的 scope（如 `aux:fork_tail` 的
    `{{tail_text}}`）在 `{}` 下会抛 `missing_variable`，那是**误报**，会让人以为
    配置坏了。自动填充让「注册表里出现的每个 scope 都必须能组装成功」成为一句
    无例外的规则，新增 section 不需要维护自检豁免名单。

    不捕获任何异常：`PromptError` 直接上抛，让 import / 启动失败——吞掉就等于没做。
    """
    for scope in scopes:
        names = {name for section in registry.sections(scope) for name in section.requires}
        registry.assemble(scope, dict.fromkeys(names, ""))
