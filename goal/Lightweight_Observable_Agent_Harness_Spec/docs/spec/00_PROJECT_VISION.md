# 00 — Project Vision / 项目宪法

## 1. 项目定位

本项目 MUST 是一个 **通用、轻量、可观察、可恢复、可扩展的 Agent Harness**，而不是 Coding Agent、RAG 应用、Research Agent 或 Multi-Agent Framework 本身。

默认可以提供 Coding / Knowledge / Research 三类能力，但它们均 MUST 通过 Capability / Tool / Provider 接入。未来新增 Finance、AIOps、Browser、Data Analysis 等领域能力时，原则上只增加插件，不修改 Core Agent Loop。

## 2. 五个核心卖点

### 2.1 Lightweight

- Agent Core MUST 保持小而清晰。
- LangGraph、Langfuse、Milvus、MinIO、LangMem、MCP、Web Search、FastAPI、前端均 MUST NOT 成为 Core 的必要前置。
- 不为了“架构高级”引入不必要的 Scheduler、Service Mesh、复杂工作流引擎或分布式基础设施。

### 2.2 Observable

一次运行应能追踪：

`Session → Run → Agent → Step → Model → Tool → Validation → Permission → Retry → Operation → Checkpoint → Artifact → Context → Recovery`

- Durable Session Event 与 Diagnostic Log MUST 分层。
- JSONL MUST 保留。
- Langfuse SHOULD 作为可选 Trace/Span UI Adapter。
- Observability 故障 MUST NOT 使核心 Agent 不可用。

### 2.3 Recoverable

恢复不是“重新跑一遍”。

系统 MUST 区分：

- Session/Message/Graph 等**状态恢复**；
- 外部 Tool 的**副作用恢复**。

必须支持：
- Resume
- Replay
- Fork
- Checkpoint
- Operation Ledger
- Reconcile
- Session-scoped Sandbox Restore

当 Tool 状态无法确定时 MUST 进入 `NEED_RECONCILE` / 人工决策，不允许盲目重放高风险副作用。

### 2.4 Extensible

业务能力通过 Capability / Provider / Consumer 边界扩展。

Core MUST NOT 出现：

```python
if task_type == "finance":
    ...
elif task_type == "rag":
    ...
```

新增 Finance 等能力时，优先增加：

```text
Capability Interface
→ Provider
→ Tool / Context Provider / AgentProfile
```

### 2.5 Reuse First

最高级工程原则：

> **Reuse First, Build Second.**

每个模块实现前 MUST 先检查成熟开源设计、官方 SDK、稳定库。

实现策略只能明确选择：
- `REUSE`：直接依赖成熟库/SDK。
- `ADAPT`：用薄 Adapter 接入本项目 Contract。
- `PORT DESIGN`：借鉴成熟架构/协议思想，用 Python 实现。
- `BUILD`：现有方案不满足核心边界时才自研。
- `DEFER`：当前版本没有必要实现。

禁止为了展示能力而重造：
- MCP wire protocol
- Provider HTTP/SSE Adapter
- Langfuse SDK
- MinIO SDK
- Milvus Client
- LangMem 内部 Memory 算法
- Pydantic Schema 机制
- FastAPI/SSE 基础设施

## 3. 最高级架构原则

以下原则为冻结项：

1. **Python + Async-first**。
2. **Core Runtime 自己掌控**；任何框架都不能成为 Agent Loop 的主人。
3. **Session Event-sourced / append-only**。
4. **Model-visible input 必须可追溯**。
5. **Event ≠ Log**。
6. **Persistent History ≠ Runtime Context**。
7. **完整保存 ≠ 完整注入**。
8. **Recovery before Retry**：恢复场景优先对账，不盲重试。
9. **Operation Ledger 独立于 SessionEvent**。
10. **Tool 只有一条统一执行路径**。
11. **Tool Retry 只有 ToolExecutor 一个责任域**。
12. **Model Fallback 与 Tool Retry 分离**。
13. **Dependency-aware Concurrency**，不是“读全并行、写全串行”的简单规则。
14. **Permission / Risk Policy 是 Runtime 边界，不是 Prompt 提醒**。
15. **Capability Provider 可替换**。
16. **Memory MUST 暴露为 Capability / Context Provider**，不得把 LangMem 写死进 Core。
17. **Artifact 优先于 Context Pollution**。
18. **SubAgent 必须复用现有 AgentRuntime**，不能重造第二套 Loop。
19. **LangGraph 只可作为可选 orchestration layer**。
20. **Optional subsystem failure 不得拖垮 Core**。
21. **No hidden second path**：MCP Tool、Knowledge Tool、Coding Tool 都必须进入统一 Tool Runtime。
22. **AI Coding Agent 在编码前先阅读复用矩阵**。

## 4. V1 产品形态

V1 MUST 同时具备：

- CLI 交互；
- FastAPI SSE；
- 最轻量 Web Session Inspector；
- Single-Agent 完整 Runtime；
- Tool Runtime；
- Docker Sandbox；
- Coding Tools；
- SessionEvent / JSONL；
- Resume / Replay / Fork；
- Operation Ledger + Reconcile；
- Artifact Store（Local + MinIO Provider）；
- Context Compaction；
- Memory Capability（默认 LangMem Adapter）；
- MCP Client Tool Adapter；
- Skills；
- Knowledge/RAG Capability；
- Web Search Tool；
- Multi-Agent Supervisor + 默认三个 AgentProfile；
- 动态创建 SubAgent 的 AgentFactory；
- Langfuse Adapter；
- 项目自有 Golden Eval + EvalScope Adapter。

## 5. 明确非目标

V1 MUST NOT：

- 自研 LLM Provider HTTP 协议栈；
- 自研 MCP 协议；
- 自动 Git commit / push；
- 默认直接修改 Host 真实目录；
- 无限动态生成 Python Agent 类；
- 将所有 Agent 全量 Context 互相倾倒；
- 让 LangGraph 替代 Tool Runtime / Operation Ledger；
- 让 Langfuse 成为唯一日志；
- 让 Memory 绑定 LangMem；
- 让 Milvus 绑定 Knowledge 接口；
- 做复杂多查询 CRAG / 学术式 Evidence Grader；
- 做多写 Agent 无约束并发；
- 做分布式锁/集群 Scheduler；
- 为了“看起来生产级”引入 Redis/Kafka/K8s 等无实际必要的基础设施。

## 6. Definition of Done

整个项目完成的判断标准不是“功能文件都存在”，而是：

- 能从真实 SessionEvent 还原模型可见历史；
- 能完整查看一次 Agent Run 链路；
- Tool 参数错误能回模型自修正；
- Tool transient failure 只在正确责任域重试；
- 大输出不撑爆 Context；
- Session crash 后能恢复；
- Tool 副作用不因恢复被错误重复；
- UNKNOWN 副作用会进入 reconcile；
- Sandbox 能恢复原 workspace；
- Memory Provider 可以替换而不修改 Agent Core；
- MCP / Knowledge / Coding Tool 共享统一 Runtime；
- 多 Agent 能结构化委派并收敛；
- Langfuse 不可用时 Agent 仍正常；
- Golden deterministic Gate 能跑通；
- Full E2E 至少包含一次 Kill / Resume / Reconcile。
