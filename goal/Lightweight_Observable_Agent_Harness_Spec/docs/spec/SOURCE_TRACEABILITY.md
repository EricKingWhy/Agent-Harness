# Source Traceability

本套规格由以下用户提供的旧教学 Source Plan 去教学化、去重复并重组：

- 04_Day04_ToolRuntime_SourcePlan
- 05_Day05_DockerSandbox_CodingTools_SourcePlan
- 06_Day06_RAG_Foundation_AgenticRAG_SourcePlan
- 07_Day07_Checkpoint_CrashRecovery_SourcePlan
- 08_Day08_Context_Artifact_Compaction_SourcePlan
- 09_Day09_Streaming_SSE_MCP_Skills_SourcePlan
- 10_Day10_LangGraph_Core_SourcePlan
- 11_Day11_MultiAgent_Supervisor_SourcePlan
- 12_Day12_Subgraph_SessionSandbox_Recovery_SourcePlan
- 13_Day13_WebResearch_CRAG_Reliability_SourcePlan
- 14_Day14_Langfuse_EvalScope_FinalE2E_SourcePlan

保留的源内容类型：
- 工程目标与主链
- Contract / Runtime 边界
- Failure / Debug 场景
- Scope Lock
- Completion Gate
- E2E 验收链路

删除/转换的源内容类型：
- Day/学习时间
- 今天必须亲手完成
- CORE_LEARNING / AI_CODING_PRACTICE 教学标签
- 用户必须学会/会讲
- Micro Change
- 课程式 Task 粒度

另外根据需求澄清新增/升级：
- Event-sourced Session
- Resume / Replay / Fork
- Dynamic AgentProfile / AgentFactory
- Dependency-aware Tool Scheduler
- Approval / Permission Policy
- MinIO Artifact Store
- Memory Capability / Context Provider（LangMem 默认 Adapter，可换 Mem0/自研）
- 最轻量 Web Session Inspector
- Open-source Reuse Matrix

外部设计参考以实现时实时核查上游仓库为准：
- Pi: https://github.com/badlogic/pi-mono
- DeepSeek Harness: https://github.com/deepseek-ai/deepseek-harness
