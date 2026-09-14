"""Prompt Registry：集中登记 prompt section，按 scope 组装。

`builtin.py` 是内置 section 正文的唯一集散地（改文案只开那一个文件）。
"""

from __future__ import annotations

from agent_harness.prompt.builtin import DEFAULT_REGISTRY, build_registry
from agent_harness.prompt.errors import PromptError
from agent_harness.prompt.persona import (
    PersonaConfig,
    apply_persona,
    compose_agent_prompt,
    parse_persona_config,
    persona_sections,
)
from agent_harness.prompt.registry import (
    AssembledPrompt,
    PromptRegistry,
    run_self_check,
)
from agent_harness.prompt.section import SECTION_ORDERS, PromptSection, Target
from agent_harness.prompt.template import extract_variables, render
from agent_harness.prompt.tool_sections import join_guidance, tool_guidance_sections

__all__ = [
    "DEFAULT_REGISTRY",
    "SECTION_ORDERS",
    "AssembledPrompt",
    "PersonaConfig",
    "PromptError",
    "PromptRegistry",
    "PromptSection",
    "Target",
    "apply_persona",
    "build_registry",
    "compose_agent_prompt",
    "extract_variables",
    "join_guidance",
    "parse_persona_config",
    "persona_sections",
    "render",
    "run_self_check",
    "tool_guidance_sections",
]
