"""TickerCapability：Phase 7 Gate 的 demo capability（spec 08 §8 / 14 Gate 1）。

它没有真实业务价值，唯一作用是证明"新增领域能力不改 Agent Core"：
1. descriptor 注册进 CapabilityRegistry（Consumer 可用 optional()/descriptor() 检查）；
2. 以 ContributesTools Protocol（结构化满足，无需 import）贡献 tick 工具 →
   统一 ToolRegistry / ToolExecutor——Permission / Operation Ledger 走既有路径（08 §9）；
3. Agent Loop 对它零感知。

只在 CAPABILITIES 配置显式写明 `{"ticker": {}}` 时才会注册。
"""

from __future__ import annotations

from pydantic import BaseModel

from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission


class TickArgs(BaseModel):
    """tick 无参数；显式空 schema 保持 Contract 完整（模型可见的参数面为零）。"""


class TickerCapability:
    """demo provider：贡献 tick 工具，并记录被 tick 的次数（断言用）。"""

    def __init__(self) -> None:
        self.tick_count = 0

    def contributes_tools(self) -> list[Tool]:
        return [TickTool(self)]


class TickTool(Tool):
    """tick：READ_ONLY demo 工具，返回递增序号。"""

    def __init__(self, owner: TickerCapability) -> None:
        self._owner = owner

    @property
    def name(self) -> str:
        return "tick"

    @property
    def description(self) -> str:
        return "demo 工具：返回一个递增的 tick 序号，用于验证插件链路。无参数。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return TickArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    async def execute(self, args: TickArgs) -> ToolResult:
        self._owner.tick_count += 1
        return ToolResult.success(
            message=f"tick #{self._owner.tick_count}",
            data={"tick": self._owner.tick_count},
        )
