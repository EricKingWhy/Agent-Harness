# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/) 格式，版本号采用 [Semantic Versioning](https://semver.org/)。

---

## [1.0.0] — 2026-09-07

**首个正式版本——冻结 Roadmap 全部交付。**

这是 `intelligence-agent` 项目 `14_IMPLEMENTATION_ROADMAP.md` 上所有 Phase（1–16）全部完成后的首个稳定版本。Lightweight Observable Agent Harness 的核心能力全部落地：Async-first Agent Runtime、append-only SessionEvent 真相源、统一 ToolExecutor、持久化 Operation Ledger、Sandbox/Permission Runtime 边界、可观察 Langfuse 旁路、评测骨架、完整 Recovery / Replay / Fork 链路。

### Phase 进度（详见 `docs/PHASE_STATUS.md`）

| Phase | 主题 | 状态 |
| ----- | ---- | ---- |
| 1–3 | Foundation（项目骨架 / Agent Runtime 核心 / SessionEvent 模型） | ✅ |
| 4 | Tool Runtime + Operation Ledger + Recovery | ✅ |
| 5 | Sandbox / Coding Tools（本地 + Docker） | ✅ |
| 6 | Context / Artifact / Memory（Capability + ContextProvider 抽象） | ✅ |
| 7 | Storage / Persistence / Recovery（Checkpoint + Ledger reconcile） | ✅ |
| 8 | Plugin / Capability 系统 | ✅ |
| 9 | MCP / Skills / Knowledge / Web（Capability 化的工具生态） | ✅ |
| 10 | Multi-Agent / Dynamic SubAgent（同一 AgentRuntime 复用） | ✅ |
| 11 | Knowledge / Agentic RAG（检索即工具，citation 可追溯） | ✅ |
| 12 | Web Search / Reliability（熔断 + Model Fallback） | ✅ |
| 13 | Multi-Agent（AgentProfile + delegate + 预算/熔断/并行/取消） | ✅ |
| S-UI | Streaming UI 生产级改造（detached-run / reasoning / 工具输出流 / 重连 / 多模型） | ✅ |
| 14 | Resume / Replay / Fork 完整化（file-per-lineage + copy-on-fork） | ✅ |
| 15 | Observability + Evaluation（Langfuse 旁路 + 评测骨架 + 真云 Gate） | ✅ |
| 16 | Final Full E2E（场景链全链验证 + Gate 6/6） | ✅ |

### 新增（相对于项目起点）

- **Agent Runtime**：Async-first Loop（`AgentRuntime`），统一 ModelProvider，Model Fallback 协调器。
- **Session 模型**：append-only typed `SessionEvent`（Event ≠ Diagnostic Log），`JsonlSessionStore`，Resume / Replay / Fork。
- **Tool Runtime**：统一 `ToolExecutor`（Validation-first 三阶段 + Timeout + 唯一 Retry Layer + Permission Gate），并发调度基于显式依赖。
- **Operation Ledger**：`SqliteOperationLedger`（PENDING/RUNNING/SUCCEEDED/FAILED/NEED_RECONCILE），`RecoveryCoordinator` 八步恢复（kill → restart → reconcile → continue）。
- **Sandbox**：`LocalSubprocessSandbox` + `DockerSandbox`（确定性容器命名 + 跨进程恢复）。
- **Coding Tools**：Bash / Read / Write / Edit / ApplyPatch / Glob / Grep / Git 工具。
- **Knowledge / RAG**：Agentic RAG（检索即工具），Milvus 向量库，`KnowledgeService` + `FakeKnowledgeVectorStore`，citation `kb:<source>#<chunk>`。
- **Web Search**：`TavilyWebSearchProvider`（手写 httpx），`RepeatedToolFailureGuard` 熔断。
- **Multi-Agent**：`AgentProfile` / `AgentFactory` / delegate 工具，预算三旋钮 + 重复熔断 + 并行 + 取消恢复。
- **Capability 系统**：一切皆可插件（`Capability` + `ContextProvider`），Memory = Capability + Provider（LangMem 默认可替换）。
- **Observability**：`LangfuseSink`（旁路骨架 + 故障隔离 + 熔断器，key 空 = 零 import 完全缺席），`RunTracer`（trace=run + generation + tool span + SubAgent 嵌套），`trace_url` 契约。
- **Evaluation**：`evaluation/` 骨架（datasets 真相源 + P0 金标 cases + 真实模型 smoke）。
- **Streaming UI**：`AgentRuntime.run_stream`（text/delta 合帧 + reasoning + 工具输出流 + detached-run + after_seq 重连 + 多模型）。
- **Web Session Inspector**：三栏单帧 + Trace Ladder + 五档密度 + WCAG 无障碍。

### 修复（集成后验证期发现并修复）

- `DockerSandbox.read_text` 的 `docker.errors.NotFound` 未映射成 `FileNotFoundError`——`WriteTool.execute` 读 before 内容时未捕获，导致 Docker 路径首次写操作失败。修复：`read_text` 把 `NotFound` 映射成 `FileNotFoundError`（`7a2b8db`）。

### 已知遗留（非阻断）

- `docker` Python SDK 未在 `pyproject.toml` `[project.optional-dependencies]` 声明——建议后续加 `sandbox = ["docker>=7"]` extras 组。
- 真实模型 smoke 已跑一次（senseaudio 网关），上游网关间歇 500 时需复跑（Phase 14 probe-gated 登记法）。
- 前端真实端到端抽查（场景 E + C6）建议后续手动过一次。

### 测试基线（1.0.0 发版）

- 全量离线回归：**1222 passed / 1 skipped / 39 deselected**，ruff clean。
- Phase 16 Final Full E2E Gate：**12/12 passed**（含 Docker 容器恢复），wall clock 8.25s。
- 真实模型 smoke：Langfuse jp 区 trace 结构与 Gate 断言一致（root `agent-run` + 3× generation + 3× context-build + metadata `session_id`/`run_id`/`agent_id`）。

---

## 版本约定

- **主版本号（1.x.x）**：Roadmap 级别的里程碑（新的大特性集）。
- **次版本号（x.1.x）**：新 Phase / 新 Capability。
- **修订号（x.x.1）**：bug 修复 + 文档 + 集成验证闭合。
