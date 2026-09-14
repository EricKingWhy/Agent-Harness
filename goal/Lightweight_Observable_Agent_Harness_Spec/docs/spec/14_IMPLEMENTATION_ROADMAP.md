# 14 — Implementation Roadmap

## 1. 原则

此 Roadmap 按**依赖关系**组织，不按 Day/学习时间组织。

每个阶段只有达到 Gate 才进入依赖它的下一阶段。可独立模块允许并行，但不能以牺牲 Contract 稳定性为代价。

## Phase 0 — Repository Foundation

交付：
- Python 3.11+
- Async-first project structure
- config
- Pydantic contracts
- test harness
- JSONL diagnostic logger skeleton
- basic CI

Gate：
- async unit test 可运行；
- config/provider injection 可测试；
- 不引入业务框架绑死 Core。

## Phase 1 — SessionEvent + Model + Minimal Agent Loop

交付：
- Session/Run/Step IDs
- append-only SessionEvent
- JSONL Session persistence
- derive_messages
- ModelProvider
- streaming + complete AIMessage
- minimal AgentRuntime
- max_steps

Gate：
- 简单对话重启后可恢复历史；
- streaming 不破坏结构化 tool_calls（先可用 FakeModel 测）。

## Phase 2 — Tool Runtime

交付：
- Tool Contract
- Registry
- ToolResult
- Validation
- Permission interface
- ToolExecutor
- single retry layer
- dependency metadata
- first scheduler
- tool call/result events

Gate：
- INVALID_ARGUMENT 不重试；
- transient 可重试；
- Tool pair consistency=100%。

## Phase 3 — Docker Sandbox + Coding Tools

交付：
- Session-scoped Sandbox
- persistent workspace
- read/write/edit/bash/grep/glob/apply_patch/git_status/git_diff
- path guard
- approval
- workspace resource locks

Gate：
- Toy project `read → edit → pytest fail → fix → pass`；
- Host 目录隔离；
- edit ambiguous 失败。

## Phase 4 — Storage + Operation Ledger + Recovery

交付：
- Storage abstractions
- SQLite default
- PostgreSQL adapter boundary
- Checkpoint
- Operation Ledger
- reconcile
- kill/resume
- ToolResult recovery

Gate：
- `Tool success → crash before result event` 可恢复；
- UNKNOWN bash 不盲重跑；
- dangling tool call=0。

## Phase 5 — Artifact + MinIO + Context Compaction

交付：
- ArtifactStore
- LocalProvider
- MinIOProvider
- inspect_artifact
- ContextBuilder
- token budget
- auto/hard thresholds
- structured compaction + fallback

Gate：
- 超大 stdout 不进入完整 Context；
- raw data 可找回；
- compaction 不删除 SessionEvent。

## Phase 6 — Memory Capability / Context Provider

交付：
- MemoryCapability
- MemoryProvider Protocol
- MemoryContextProvider
- LangMemProvider
- scope/relevance/recency/importance budget
- graceful degradation

Gate：
- 使用 LangMem 正常 recall；
- 切换 Fake Provider 不改 Core；
- Memory 挂掉基础 Agent 仍运行。

## Phase 7 — Capability / Plugin Foundation + Skills

交付：
- capability registry
- provider descriptors
- plugin config
- SKILL.md discovery
- progressive disclosure
- Context injection

Gate：
- 新增 demo capability 不改 Agent Loop；
- Skill 全文不默认永久进 Context。

## Phase 8 — MCP

交付：
- MCP Python client
- discovery
- MCPToolAdapter
- permission/side-effect mapping

Gate：
- Remote MCP Tool 仍经过统一 ToolExecutor；
- 不出现双重 retry。

## Phase 9 — Streaming Surfaces

交付：
- AgentEvent stream
- CLI Renderer
- FastAPI SSE
- disconnect cleanup
- Session query API

Gate：
- ModelDelta/Tool events 实时；
- SSE 断连无 queue/task 泄漏。

## Phase 10 — Lightweight Web Session Inspector

交付：
- Sessions/Runs/Fork Tree
- Conversation/Agent activity
- Step detail
- Resume/Replay/Fork
- Approval
- Artifact inspect

Gate：
- 刷新后由持久 Event 重建；
- 前端不维护第二套不可对账状态。

## Phase 11 — Knowledge / RAG

交付：
- VectorStore abstraction
- MilvusProvider
- ingestion
- chunk/metadata
- incremental index
- retrieve_knowledge
- citation
- sufficient

Gate：
- restart 后 persistent search；
- 证据不足明确 false；
- Citation 可追溯。

## Phase 12 — Web Search / Reliability

交付：
- WebSearchProvider
- independent web_search Tool
- retrieval fallback
- repeated tool guard
- Model Fallback

Gate：
- KB 足够不联网；
- 不足才 fallback；
- provider transient 有 fallback reason。

## Phase 13 — Multi-Agent

交付：
- AgentProfile/AgentSpec
- AgentFactory
- Supervisor
- default main/coding/research_review
- Dynamic SubAgent
- structured result
- max_delegations/depth
- optional LangGraph orchestration

Gate：
- 动态创建第四个 Agent；
- tool/context permission 收窄；
- child 不倾倒完整历史；
- Single Agent 不依赖 LangGraph。

## Phase 14 — Resume / Replay / Fork 完整化

基础 Resume 在前面已实现；此阶段完成产品级能力：
- replay projector
- fork boundary
- lineage tree
- child session seed
- UI/CLI commands
- artifact/workspace fork policy

Gate：
- replay 无副作用；
- fork 不改变父 Session；
- lineage 可视化正确。

## Phase 15 — Observability + Evaluation

交付：
- diagnostic structured log schema
- Langfuse Adapter
- Golden Cases
- deterministic assertions
- EvalScope Adapter
- regression metadata

Gate：
- Langfuse 不可用时 Core 正常；
- P0 deterministic cases 通过；
- recovery/citation/permission 指标可报告。

## Phase 16 — Final Full E2E

必须跑完整场景：

```text
historical session
→ research
→ KB insufficient
→ web
→ citation
→ coding
→ edit/test failure
→ retry strategy by agent
→ mutating tool running
→ kill
→ restart
→ sandbox restore
→ operation reconcile
→ continue
→ tests pass
→ review
→ final
→ replay
→ fork
→ Langfuse trace
→ Eval report
```

最终 Gate：
- duplicate confirmed side effect = 0
- dangling tool call = 0
- core recovery = 100%
- citation validity = 100%
- permission violation = 0
- Full E2E reproducible

## 2. AI Coding Agent 执行规则

每开始一个 Phase：

1. 读取 `00_PROJECT_VISION.md`；
2. 读取本 Phase 对应模块规格；
3. 读取 `13_OPEN_SOURCE_REUSE_MATRIX.md`；
4. 检查当前代码状态；
5. 先输出最小实现计划与“复用/自研”决策；
6. 只实现当前 Phase 的 Contract，不提前跨层堆功能；
7. 完成 Acceptance Tests；
8. 更新 ADR/实现差异；
9. Gate 失败不得声称 Phase 完成。
