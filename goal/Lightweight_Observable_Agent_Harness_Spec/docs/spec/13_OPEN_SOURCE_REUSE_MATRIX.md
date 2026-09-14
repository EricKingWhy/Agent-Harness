# 13 — Open-source Reuse Matrix

## 1. 强制流程

每个模块编码前，AI Coding Agent MUST：

1. 查本矩阵；
2. 检查对应上游当前版本/文档；
3. 确认 License；
4. 选择 `REUSE / ADAPT / PORT DESIGN / BUILD / DEFER`；
5. 若实质复制/移植代码，保留许可证与版权信息；
6. 在 PR/commit note 中记录来源与差异。

本项目不追求“全自研”。

## 2. Pi

Pi 当前核心价值适合借鉴：
- minimal terminal coding harness；
- extension/skill/package；
- Session resume/tree/fork/clone；
- JSONL full history；
- compaction；
- progressive Skill disclosure。

### 决策

| 能力 | 策略 | 本项目用法 |
|---|---|---|
| Minimal Agent philosophy | PORT DESIGN | 保持 Core 小 |
| Session Tree / Fork | PORT DESIGN | Python Session lineage |
| Resume / JSONL | PORT DESIGN | 与 Event-sourced Session 融合 |
| Compaction | PORT DESIGN | 历史不删除、Runtime Context summary |
| Skills / SKILL.md | PORT DESIGN | progressive disclosure |
| Extensions | PORT DESIGN | Capability/Plugin 体系参考 |
| Pi TypeScript runtime | DEFER | 不直接嵌入 Python Core |

## 3. DeepSeek Harness

重点借鉴其当前设计：
- append-only typed SessionEvent；
- event-sourced Session / derive messages；
- capability seams；
- subagent provider registry；
- spill/oversized output 思路；
- sandbox policy；
- UI 消费 session/event；
- tool execution pipeline。

### 决策

| 能力 | 策略 | 本项目用法 |
|---|---|---|
| Event-sourced Session | PORT DESIGN | SessionEvent 主事实源 |
| deriveMessages 思想 | PORT DESIGN | Python event projection |
| Capability seam | PORT DESIGN | Interface/Provider/Consumer |
| SubAgent provider seam | PORT DESIGN | AgentFactory + provider registry |
| spawn/fork child | PORT DESIGN | Dynamic agent |
| Tool execution pipeline | PORT DESIGN | Permission→Scheduler→Executor→Result |
| Oversized output spill | PORT DESIGN | ArtifactStore/MinIO |
| Sandbox policy | PORT DESIGN | read-only/workspace-write/approval |
| DSH TypeScript/Cordis | DEFER | 不引入为 Python Core runtime |

## 4. 直接 REUSE 的库/SDK

### Pydantic
`REUSE`
- Tool Args
- DTO
- Config
- Validation

### FastAPI
`REUSE`
- API
- SSE integration

### LangChain / official provider clients
`ADAPT`
- 只承担 Model Provider compatibility
- 不使用 prebuilt agent 隐藏自己的 Agent Loop

### MCP Python SDK
`REUSE + ADAPT`
- transport/protocol
- Tool discovery
- 本项目自己做 MCPToolAdapter

### LangMem
`REUSE + ADAPT`
- 默认 MemoryProvider
- 必须经 `MemoryCapability / MemoryContextProvider`
- Core 禁止 import LangMem concrete class

### Milvus SDK
`REUSE + ADAPT`
- 默认 VectorStoreProvider

### MinIO SDK
`REUSE + ADAPT`
- 默认 ObjectArtifactProvider
- Artifact contract 不绑定 MinIO

### Langfuse SDK
`REUSE + ADAPT`
- optional observability

### EvalScope
`ADAPT`
- thin evaluation adapter
- 项目自有 Runner 是事实入口

### LangGraph
`ADAPT / OPTIONAL`
- Multi-Agent orchestration
- 不能重写 Agent Runtime

## 5. 什么时候允许 BUILD

只有以下情况才自研：
- 核心 Contract 是本项目差异化卖点；
- 上游会隐藏 Agent 执行链；
- 上游无法满足 recovery/operation semantics；
- 上游强绑定不需要的框架；
- 复用成本高于最小实现；
- 必须保证 provider-neutral。

明确需要 BUILD 的部分：
- 最小 Agent Loop；
- Tool Runtime Contract/Executor glue；
- Operation Ledger + reconcile policy；
- SessionEvent Python domain model；
- ContextBuilder integration；
- AgentFactory/AgentProfile domain contract；
- dependency-aware scheduler glue；
- project-owned Eval Runner。

## 6. 禁止直接复制的方式

- 不整仓 fork Pi/DSH 后“翻译成 Python”；
- 不复制 Cordis 等与本项目语言/架构强绑定的基础设施；
- 不把上游私有内部类当稳定 API；
- 不删除来源 License；
- 不因“上游做了”就无脑搬全部功能。

## 7. 上游核查链接

实现时优先核对官方仓库：
- Pi: `https://github.com/badlogic/pi-mono`
- DeepSeek Harness: `https://github.com/deepseek-ai/deepseek-harness`

重点文档：
- Pi coding-agent README / sessions / extensions / skills
- DSH `docs/subsystems/session.md`
- DSH `docs/capability-seams.md`
- DSH `docs/subsystems/subagent.md`
- DSH `docs/architecture.md`

注意：上游实现会变化。AI Coding Agent MUST 在真正 Port 前重新检查当前版本，不只依赖本规格中的摘要。
