"""工具 guidance 归集为 prompt section（ADR-0023 D11）。

本模块只依赖 `prompt` 包内部：工具对象以**结构类型**（`GuidanceSource`）接收，
因此不需要 import `agent_harness.tooling`——避免 prompt 包反向依赖 tooling 包。
由测试 `test_tool_sections_does_not_import_tooling` 固定这条边界。

归集的"内容边界"由**喂进来的 registry** 决定，不由本模块决定：调用方传的是
已按 `tool_scope` 收窄过的 registry，所以 `profile:coding` 拿不到 `delegate`
的 guidance（工具缺席 → 说明缺席）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from agent_harness.prompt.section import SECTION_ORDERS, PromptSection, Target

__all__ = [
    "TOOL_USE_DISCLAIMER",
    "GuidanceSource",
    "join_guidance",
    "tool_guidance_sections",
]


#: BUG-013：工具澄清句——「有工具」不等于「任何任务都要用工具」。真机实测：
#: 快照紧贴用户消息列出工具时，模型会把「写作文」误判为需要写作工具的任务，
#: 进而拒认自己刚写过的内容。澄清句与工具 guidance 同源（本模块产出）：
#: 只有 registry 里**确实存在**贡献 guidance 的工具时才出现——无工具的 agent
#: prompt 不出现（与"工具缺席 → 说明缺席"同一边界）。
TOOL_USE_DISCLAIMER = (
    "以上工具按需调用即可；简单问答、对话与写作类任务直接回答，无需调用工具。"
)


class GuidanceSource(Protocol):
    """结构类型：任何有 `name` / `prompt_guidance` 的对象（`Tool` 即满足）。"""

    @property
    def name(self) -> str: ...

    @property
    def prompt_guidance(self) -> str | None: ...


def tool_guidance_sections(tools: Iterable[GuidanceSource]) -> list[PromptSection]:
    """把有 guidance 的工具转成 `tool:<name>` section（父路径注册表用）。

    scope 是 `{"*"}` 而非具体 profile：它表达"所有 agent 身份"，**具体哪些工具
    存在**由调用方喂进来的 registry 决定（PRD §10.5 的结构性边界——`*` 只匹配
    `profile:<name>`，所以工具 guidance 不会进入 `aux:*` 辅助 prompt）。

    纯空白 guidance 视同无 guidance（不产出 section），否则 join 会多出空段落。
    """
    sections: list[PromptSection] = []
    for tool in tools:
        guidance = tool.prompt_guidance
        if guidance is None or not guidance.strip():
            continue
        sections.append(
            PromptSection(
                name=f"tool:{tool.name}",
                order=SECTION_ORDERS["tool"],
                scopes=frozenset({"*"}),
                target=Target.SYSTEM,
                text=guidance,
                description=f"{tool.name} 工具的使用指引",
            )
        )
    # BUG-013：澄清句追加在全部工具 guidance 之后。它**不是**某个工具的 guidance
    # ——独立 frame（order 2100 > tool 2000），名不占 `tool:<name>` 命名空间；
    # 只有至少一个工具贡献了 guidance 才加——无工具（join 为空）时不出现。
    if sections:
        sections.append(
            PromptSection(
                name="frame:tool_disclaimer",
                order=SECTION_ORDERS["frame:tool_disclaimer"],
                scopes=frozenset({"*"}),
                target=Target.SYSTEM,
                text=TOOL_USE_DISCLAIMER,
                description="工具使用澄清（按需调用，简单任务直接回答）",
            )
        )
    return sections


def join_guidance(tools: Iterable[GuidanceSource]) -> str | None:
    """child 路径用：按 `(order, name)` 同序把 guidance 拼成一段文本。

    分隔符沿用 §10.7 的 `"\\n\\n"`；无 guidance 时返回 `None`（**不是空串**——
    空串会让 `compose_agent_prompt` 多出一个空段落，破坏逐字节断言）。
    """
    texts = [
        section.text
        for section in sorted(tool_guidance_sections(tools), key=lambda s: (s.order, s.name))
    ]
    return "\n\n".join(texts) if texts else None
