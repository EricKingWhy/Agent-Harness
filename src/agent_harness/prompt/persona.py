"""Persona 配置：`AGENT_PERSONA`（env JSON）→ 前后缀 section + 文本包裹（T5 / ADR-0023 D10）。

定位（PRD §10.4）：persona 是"所有 agent profile"共享的前后缀，所以 section 的
`scopes = {"*"}`——而 `"*"` **只匹配 `profile:<name>`** scope（PRD §10.5），因此
persona **结构性地不会**进入 `aux:*` 辅助 prompt（摘要器 / 抽取器）。那不是靠调用点
自觉传参，而是靠 scope 前缀判定。

解析形制照抄 `capability/config.py::parse_capabilities_config`：显式失败，
绝不静默吞。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from agent_harness.prompt.errors import PromptError
from agent_harness.prompt.section import SECTION_ORDERS, PromptSection, Target

__all__ = [
    "PersonaConfig",
    "apply_persona",
    "compose_agent_prompt",
    "parse_persona_config",
    "persona_sections",
]

#: 单侧上限。persona 会进入每一次 agent prompt 并计入 token 预算（ADR-0020a）；
#: 2000 字符 ≈ 1000 token，够写一段人格描述，又不至于把预算吃穿。
_MAX_PERSONA_CHARS = 2000

#: persona 的前后缀分隔符。必须与 `PromptRegistry.assemble` 一致（T2 固定为
#: `"\n\n"`）——两套机制的顺序一致性由漂移守卫测试绑定。
_SEPARATOR = "\n\n"


class PersonaConfig(BaseModel):
    """persona 覆盖（`AGENT_PERSONA`）。

    `strict`：拒绝隐式强转（数字转 str 之类）。
    `extra="forbid"`：未知键必须报错——`"prefx"` 这种拼错若被静默忽略，用户会以为
    配置生效了，实际什么都没发生。
    """

    model_config = {"strict": True, "extra": "forbid"}

    prefix: str = Field(default="", max_length=_MAX_PERSONA_CHARS)
    suffix: str = Field(default="", max_length=_MAX_PERSONA_CHARS)

    @property
    def is_empty(self) -> bool:
        """两侧都只有空白 = 无 persona（等价于未配置）。"""
        return not (self.prefix.strip() or self.suffix.strip())


def parse_persona_config(raw: str | None) -> PersonaConfig:
    """解析 env `AGENT_PERSONA`（JSON 字符串）；空值 = 无 persona = 零行为变化。

    形状或内容非法抛 `PromptError("invalid_persona_config")`——显式失败，绝不静默吞。
    错误消息带上**首条具体的字段名**，用户才知道是哪个键写错了。
    """
    if raw is None or not raw.strip():
        return PersonaConfig()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as error:
        raise PromptError(
            f"AGENT_PERSONA is not valid JSON: {error}",
            code="invalid_persona_config",
        ) from None
    try:
        return PersonaConfig.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(loc) for loc in first.get("loc", [])) or "<root>"
        raise PromptError(
            f"AGENT_PERSONA is invalid: {error.error_count()} validation error(s); "
            f"first: {location}: {first.get('msg')}",
            code="invalid_persona_config",
        ) from None


def persona_sections(persona: PersonaConfig) -> list[PromptSection]:
    """非空侧才产出 section——空串不入注册表，否则 join 会多出空段落。

    正文**原样**（不 strip）：用户排版是自己的事。空判定只看 `strip()` 后是否为空。
    """
    sections: list[PromptSection] = []
    if persona.prefix.strip():
        sections.append(
            PromptSection(
                name="persona:prefix",
                order=SECTION_ORDERS["persona:prefix"],
                scopes=frozenset({"*"}),
                target=Target.SYSTEM,
                text=persona.prefix,
                description="用户配置的 agent persona 前缀（AGENT_PERSONA.prefix）",
            )
        )
    if persona.suffix.strip():
        sections.append(
            PromptSection(
                name="persona:suffix",
                order=SECTION_ORDERS["persona:suffix"],
                scopes=frozenset({"*"}),
                target=Target.SYSTEM,
                text=persona.suffix,
                description="用户配置的 agent persona 后缀（AGENT_PERSONA.suffix）",
            )
        )
    return sections


def compose_agent_prompt(
    base: str | None,
    persona: PersonaConfig | None,
    guidance_text: str | None = None,
) -> str | None:
    """按 order 顺序拼 agent prompt：persona 前缀 → base → tool guidance → persona 后缀。

    对应注册表 order：`persona:prefix` 0、`profile:identity` 100、`tool` 2000、
    `persona:suffix` 10200。父路径走 `build_registry(persona,
    tool_sections=…).assemble(f"profile:{name}")`（有 profile 时）；child 路径与
    **无 profile 的父路径**走本函数——两条路径的产物由
    `test_compose_matches_registry_order` 固定一致，child 与父不漂移。

    guidance 插在**后缀之前**：后缀是用户声明的"最终落点"，永远在最后。

    - `base=None` 且 persona 空且无 guidance → `None`（保持"无 system prompt"语义）
    - 单侧为空时**不 append 空串**，否则产物会变成 `"\\n\\nBASE"`，破坏逐字节相等
    """
    parts: list[str] = []
    if persona is not None and persona.prefix.strip():
        parts.append(persona.prefix)
    if base is not None:
        parts.append(base)
    if guidance_text is not None and guidance_text.strip():
        parts.append(guidance_text)
    if persona is not None and persona.suffix.strip():
        parts.append(persona.suffix)
    return _SEPARATOR.join(parts) if parts else None


def apply_persona(base: str | None, persona: PersonaConfig | None) -> str | None:
    """T5 的等价形式（无 guidance）——保留为薄封装，T5 的签名与语义不变。

    与 `build_registry(persona).assemble("profile:…")` 的产物顺序一致
    （prefix 0 → profile identity 100 → suffix 10200），一致性由
    `test_apply_persona_matches_registry_order` 固定——child 与父不漂移。

    - `base=None` 且 persona 空 → `None`（保持"无 system prompt"语义）
    - `base=None` 且 persona 非空 → 只有前后缀（用户显式配置就该生效）
    - 单侧为空时**不 append 空串**，否则产物会变成 `"\\n\\nBASE"`，破坏逐字节相等
    """
    return compose_agent_prompt(base, persona)
