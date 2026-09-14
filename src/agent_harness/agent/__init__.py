"""Agent 模块：透明最小 Agent Loop + 流式事件。

对外暴露：AgentRuntime（驱动循环）、AgentRunResult（运行结果）、AgentEvent（流式信封）。
"""

from agent_harness.agent.runtime import AgentRuntime
from agent_harness.agent.types import (
    STATUS_COMPLETED,
    STATUS_CONTEXT_WINDOW_EXCEEDED,
    STATUS_MAX_STEPS_EXCEEDED,
    AgentEvent,
    AgentRunResult,
    to_agent_event,
)

__all__ = [
    "STATUS_COMPLETED",
    "STATUS_CONTEXT_WINDOW_EXCEEDED",
    "STATUS_MAX_STEPS_EXCEEDED",
    "AgentEvent",
    "AgentRunResult",
    "AgentRuntime",
    "to_agent_event",
]
