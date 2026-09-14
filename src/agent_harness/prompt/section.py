"""Section 数据模型 + 集中 order 表（PRD §10.4）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_harness.prompt.template import extract_variables

__all__ = ["SECTION_ORDERS", "PromptSection", "Target"]


class Target(str, Enum):
    """section 产物的落点。

    判据只有一个：**这条 section 的产物要装进哪里**，与"是否持久化"无关
    （持久化纪律是具体 section 的要求，比如 runtime 上下文快照，不是 META_USER
    的定义）。
    """

    SYSTEM = "system"  # 装进 system-role 消息（SystemMessage）
    META_USER = "meta_user"  # 装进 user-role 消息（HumanMessage）
    FRAGMENT = "fragment"  # 非消息文本片段：嵌入位置由调用方决定


#: 集中 order 表：**一处看清全部 prompt 的最终顺序**，避免顺序散落在各调用点。
#: 逐字照抄 PRD §10.4（含 T8 才会消费的 `frame:recovery_skipped`）——照抄全量而非
#: "只抄当前用得到的"，后续票就不必回头改这张表。
SECTION_ORDERS: dict[str, int] = {
    "harness:identity": -1000,
    "persona:prefix": 0,
    "profile:identity": 100,  # profile:<name>:identity 用此值
    "profile:extra": 200,  # profile:<name>:<其他> 用此值
    "output:summary": 1000,
    "tool": 2000,  # 工具 guidance 的基准；同 order 内按 section 名排序
    "frame:tool_disclaimer": 2100,  # BUG-013：工具澄清句，恒在全部工具 guidance 之后
    "aux:compaction": 3000,
    "aux:memory_extraction": 3100,
    "aux:fork_tail": 3200,
    "frame:untrusted_data": 9000,  # 槽位：knowledge / websearch 两条 frame section 共用
    "corrective:tool_failure_guard": 9100,
    "frame:recovery_skipped": 9200,  # 恢复期"未启动即跳过"的合成 ToolResult 文案
    "runtime:context_snapshot": 9500,
    "persona:suffix": 10200,
}


@dataclass(frozen=True)
class PromptSection:
    """一条 prompt section。

    `requires` 是 **property 而非字段**：从 `text` 扫描推导，不手写、无状态、不会
    与 `text` 失配（手写字段在改文案时必然漂移）。
    """

    name: str
    order: int
    #: 显式 scope 名；`"*"` = 所有 `profile:<name>` scope（**不含** `aux:*`，见 §10.5）
    scopes: frozenset[str]
    target: Target
    text: str
    description: str = ""

    @property
    def requires(self) -> frozenset[str]:
        return extract_variables(self.text)
