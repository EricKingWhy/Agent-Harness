"""Multi-Agent 编排能力（Phase 13, ADR-0015）——可装卸插件。

multiagent 是 CAPABILITIES 显式 opt-in 的 capability：贡献 delegate 工具 +
SubagentProvider（spawn 执行器）+ child 运行注册表。禁用 = 单代理零感知；
换实现 = 换 SubagentProvider。AgentProfile/AgentSpec 是核心域对象（agent/
包），不进插件。
"""

from agent_harness.multiagent.provider import (
    InProcessSubagentProvider,
    SubagentProvider,
    SubAgentResult,
)
from agent_harness.multiagent.tools import DelegateTool

__all__ = [
    "DelegateTool",
    "InProcessSubagentProvider",
    "SubAgentResult",
    "SubagentProvider",
]
