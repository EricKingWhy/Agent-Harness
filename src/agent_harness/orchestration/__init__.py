"""可选编排层接缝（Phase 13 T11, #92, ADR-0015 决策 1；不变量 #20）。

OrchestrationAdapter 是 LangGraph 等图编排器的挂点——V1 只定义协议位，
不实现、不依赖。Core（AgentRuntime/ToolExecutor/Session）零 import
langgraph（由 test_orchestration_seam 的 import 边界测试钉死）；
「langgraph 未安装时 Single Agent Core 仍可运行」是 spec §13 验收。
"""

from agent_harness.orchestration.adapter import OrchestrationAdapter

__all__ = ["OrchestrationAdapter"]
