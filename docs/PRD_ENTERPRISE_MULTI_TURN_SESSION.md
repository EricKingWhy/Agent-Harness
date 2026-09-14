# PRD: 企业级多轮会话、短期记忆与 CLI/Web 统一续聊

> 状态：决策已收敛（grill-me 23 问全部锁定）
> 日期：2026-09-07
> 作者：ZCode + 用户共同决策
> 依据：
> - `docs/RESEARCH_PI_SESSION_ARCHITECTURE.md`（Pi / oh-my-pi / 当前仓库根因分析）
> - `docs/RESEARCH_DEEPSEEK_HARNESS_WEB.md`（dsh Web/传输/审批/并发设计）
> - `docs/RESEARCH_PI_DSH_MEMORY.md`（Pi/dsh 记忆设计事实核查）
> - `docs/RESEARCH_OHMY_PI_DSH_COMPACTION.md`（oh-my-pi CLI + dsh 压缩精确参数）
> - 工程规格 `goal/Lightweight_Observable_Agent_Harness_Spec/docs/spec/`
> - 架构不变量 #1–#22（见 `AGENTS.md` §7）

---

## 0. 背景与根因

当前产品（CLI `demo/live_agent.py` 与 Web `src/agent_harness/web/app.py`）把**每条用户消息**建模为"创建一个新 Session 并启动一次 run"。底层 `Session`（append-only JSONL）、`AgentRuntime.run_stream`、`ContextBuilder`、`Compactor`、`RunManager`、`MemoryCapability`（LangMem 已实现）全部具备多轮续聊基础，缺口仅在入口层生命周期。

详见 `docs/RESEARCH_PI_SESSION_ARCHITECTURE.md` §3 的根因分析。

本 PRD 不重写底层，只补齐入口层 + 收敛短期记忆参数 + 验证长期记忆在多轮场景下生效。

---

## 1. 目标与非目标

### 目标
1. CLI 和 Web 支持企业级多轮续聊（一个 workspace 一个常驻 current session，普通 prompt 续聊，`/new` 显式新建）。
2. 短期记忆参数对齐 oh-my-pi + dsh 验证过的配置，压缩事件模型改为 replay 确定性的 bracket。
3. 大工具产物外置对象存储，模型只拿摘要 + 引用。
4. Streaming 支持 follow-up（排队）与 steer（立即注入），参考 ZCode / dsh 的体验。
5. 统一 CLI/Web 领域语义，共享同一个 `SessionService`，HTTP 是薄封装。
6. 长期记忆（LangMem，已实现）在多轮场景下验证生效。
7. Tool 审批通过 WS 推送 + HTTP 回传，fail-closed one-shot。
8. 同 session 内模型切换，写 `MODEL_CHANGED` 事件。
9. Fork（从历史点派生新 session 文件），复用已有 `fork.py` / `lineage.py`。
10. 崩溃恢复用 `RUN_INTERRUPTED` closer + Ledger reconcile，不盲重跑 UNKNOWN 工具。
11. 单实例部署优先，多实例预留。
12. Langfuse 多轮 trace 按 session_id 串联。

### 非目标（明确延期）
- Pi `/tree` 同文件内 leaf 移动与树内分支（Q5）。
- `/clone` 复制 session。
- dsh `@session` 跨 session 显式引用（Q19）。
- 多租户 RBAC（本期租户 = workspace，Q7）。
- 多实例 / 分布式 SessionRegistry（Q14，本期单实例优先）。
- 自研长期记忆或换 Mem0 provider（LangMem 作为默认已够用，Mem0 仍是未来可选）。

---

## 2. 已锁定决策（23 项）

| # | 决策点 | 选择 | 关键约束 |
|---|--------|------|---------|
| Q1 | 会话粒度 | 一个 workspace 一个常驻 current session；`/new` 显式新建 | sidebar 按 workspace 分组 |
| Q2 | 活跃 run 行为 | 默认 follow-up 排队；前端"立即"按钮触发 steer | 不静默并发写同一 Session |
| Q3 | CLI/Web 契约 | 共享 `SessionService` 领域层；HTTP 是薄封装 | 不破不变量 #22 |
| Q4 | 短期/长期记忆边界 | 严格分开；短期 = Session 内；长期 = Capability | 不破 #5/#16 |
| Q5 | 分支 | 本期 `/new` + `/fork`；`/tree` 延期 | 复用 fork.py/lineage.py |
| Q6 | 模型切换 | 同 session 内换模型，写 `MODEL_CHANGED` | 不丢上下文 |
| Q7 | 租户 | 本期租户 = workspace | RBAC 延期 |
| Q8 | 传输层 | 迁到 WebSocket 多路复用 + 心跳 + 服务端快照重连 | SSE+after_seq 废弃 |
| Q9 | API 形状 | 混合：资源 CRUD 用 REST，动作类用 action 端点 | 现有 REST 不破坏 |
| Q10 | 短期记忆压缩 | 融合配置（见 §3） | 抄 dsh + oh-my-pi |
| Q11 | CLI slash 命令 | `/new` `/resume` `/fork` `/compact` `/model` `/history` `/cancel` `/help` `/clear` | `/tree` `/clone` 延期 |
| Q12 | SessionRegistry | LRU 缓存（默认 256 hot），冷淘汰写盘 | 单实例优先 |
| Q13 | 排队/steer 持久化 | 进 Session 事件流（新 typed event） | 单一事实源 |
| Q14 | 部署形态 | 单实例优先；多实例预留 session 亲和 | 不背分布式复杂度 |
| Q15 | 审批回传 | 请求走 WS，回传走 HTTP POST | fail-closed one-shot |
| Q16 | 长期记忆 | LangMem（已实现），本期验证多轮场景下生效 | 不重写 |
| Q17 | 摘要 schema | 抄 Pi 六段式（目标/约束/进展/决策/下一步/关键上下文） | 本地化标签 |
| Q18 | 压缩溯源 | 抄 dsh 的 4 事件 bracket + shadowed 原始事件 | replay 确定性 |
| Q19 | `@session` 跨会话引用 | 延期，和长期记忆增强一起下一期 | — |
| Q20 | 崩溃恢复 | `RUN_INTERRUPTED` closer + Ledger reconcile，不盲重跑 | 不破 #12/#13/#14 |
| Q21 | Langfuse 多轮埋点 | 每轮独立 root span + 共享 session_id + turn_index | 复用现有结构 |
| Q22 | 前端 session 列表 | 按 workspace 分组，按 last_active_at 倒序 | 状态/运行指示 |
| Q23 | DoD | 10 条可验证标准（见 §10） | — |

---

## 3. 短期记忆最终配置（融合 oh-my-pi + dsh）

| 参数 | 值 | 来源 |
|------|----|----|
| 触发阈值 | 上下文窗口的 **80%** | dsh `thresholdRatio=0.8` |
| 硬保护 | **90%** | 配合触发留 10% 缓冲 |
| 保留最近 token | **20,000** | oh-my-pi `keepRecentTokens=20000` |
| reserve | `max(15% 窗口, 16384)` | oh-my-pi |
| 切断点 | **绝不在 tool result 中间切断**；沿 tool-balanced 边界回溯 | oh-my-pi + dsh 共识 |
| 大 tool result 外置阈值 | 单条结果 **> 2,048 tokens** 外置 MinIO，session 里留摘要 + artifact ref | 用户设计 + oh-my-pi BlobStore 思路 |
| 压缩事件模型 | dsh 4 事件 bracket：`COMPACTION_START` / `CONTEXT_COMPACTED` / `USER_MESSAGE(replace)` / `COMPACTION_END`；原始事件 shadowed 保留在 JSONL | dsh replay 确定性 |
| 摘要 schema | 六段式 Markdown：`目标 / 约束 / 进展 / 决策 / 下一步 / 关键上下文` | Pi |
| 失败 fallback | 重试 1 次 → 窗口减半再试 → fail-open 保持对话不变；拒绝被截断的摘要 | dsh + oh-my-pi |
| 手动触发 | `/compact` 命令 + `compactNow()` API | dsh |
| shrink 校验 | 摘要必须严格小于被压缩段 | dsh |
| 归一投影 | `derive_messages` 跳过 shadowed 段，用 summary 替代 | dsh |
| KV cache 友好 | 压缩调用保留 prefix，减少 cache miss | dsh |

**关键架构改动**：现有单个 `CONTEXT_COMPACTED` 事件升级为 4 事件 bracket。`derive_messages` 需识别 bracket 边界，跳过被 shadow 的原始 seq 区间。

---

## 4. 架构分层

```text
┌─────────────────────────────────────────────────────────┐
│  CLI (demo/live_agent.py 重构)                          │
│  - slash 命令解析                                        │
│  - REPL 持有 current_session_id                          │
│  - 本地 approval callback                                │
└────────────────┬────────────────────────────────────────┘
                 │ 直接 Python 调用
                 ▼
┌─────────────────────────────────────────────────────────┐
│  SessionService（新增领域层）                            │
│  - resume(id) / send_message(id, content, mode)         │
│  - steer(id, content, run_id)                           │
│  - fork(id, from_seq)                                   │
│  - list(workspace) / cancel(id) / recover(id)           │
│  - switch_model(id, new_model)                          │
│  - compact_now(id)                                      │
└────────┬────────────────────────────────┬──────────────┘
         │                                │
         ▼                                ▼
┌─────────────────────┐         ┌──────────────────────┐
│  Web FastAPI        │         │  现有底层（不改）     │
│  - WS /api/ws       │         │  Session              │
│  - REST 资源 CRUD   │         │  AgentRuntime         │
│  - action 端点      │         │  ContextBuilder       │
│  - approval POST    │         │  Compactor            │
└────────┬────────────┘         │  RunManager           │
         │                      │  ToolExecutor         │
         ▼                      │  MemoryCapability     │
┌─────────────────────┐         │  (LangMem)            │
│  Frontend (Web)     │         │  fork.py/lineage.py   │
│  - WS client        │         └──────────────────────┘
│  - session sidebar  │
│  - composer (续聊)  │
│  - approval modal   │
│  - steer 按钮       │
└─────────────────────┘
```

**关键不变量守护**：
- Session 仍是 append-only typed SessionEvent（#3）。
- Tool 只有 ToolExecutor 一条路径（#7），WS→HTTP 审批链最终汇聚到同一个 callback。
- MemoryCapability 是 Capability + ContextProvider（#16），不进 Session 聚合（#5）。
- LangMem 故障不拖垮 Core（#21），Milvus/embedding 不可用时 graceful degrade。

---

## 5. Web API 契约

### 5.1 WebSocket（所有 streaming / 推送通道）

`GET /api/ws`（upgrade）：
- 单连接多路复用，ping/pong 心跳（2s 默认，30s 超时）。
- 重连：客户端开新 WS，服务端推一份完整快照（session 当前状态 + 在途 run baseline + 已投影消息），之后增量事件。
- 上行消息类型：`subscribe(session_id)` / `send_message` / `steer` / `cancel`。
- 下行事件类型：复用现有 typed SessionEvent + 新增 `APPROVAL_REQUESTED` / `RUN_INTERRUPTED` / `COMPACTION_*` / `MODEL_CHANGED` / `MESSAGE_QUEUED` / `STEER_REQUESTED` / `QUEUE_CANCELLED`。

### 5.2 REST 资源 CRUD（现有接口保持兼容）

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/workspaces/{ws}/sessions` | 列出 workspace 下的 session（按 last_active_at 倒序） |
| POST | `/api/workspaces/{ws}/sessions` | 显式新建 session（等价 `/new`） |
| GET | `/api/sessions/{id}` | 读取 session 元信息 + 事件投影 |
| DELETE | `/api/sessions/{id}` | 删除 session（软删） |

### 5.3 Action 端点（动作类，RPC 风格）

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/sessions/{id}/messages` | 续聊。body: `{content, mode?: "queue"\|"steer"}`，默认 `queue`。idle session 直接起 run；活跃 session 按 mode 排队或注入。 |
| POST | `/api/sessions/{id}/steer` | 显式 steer。body: `{content, run_id}`。 |
| POST | `/api/sessions/{id}/forks` | Fork。body: `{from_seq}`。返回新 session_id。 |
| POST | `/api/sessions/{id}/cancel` | 取消当前 run。 |
| POST | `/api/sessions/{id}/recover` | 触发 Ledger reconcile + 恢复。 |
| POST | `/api/sessions/{id}/model` | 切换模型。body: `{provider, model_id}`。 |
| POST | `/api/sessions/{id}/compact` | 手动触发压缩。 |
| POST | `/api/sessions/{id}/approvals/{call_id}` | 审批回传。body: `{decision: "allow"\|"reject"}`。fail-closed one-shot。 |
| POST | `/api/sessions/{id}/queue/{queue_id}/cancel` | 取消排队项。 |

所有 action 端点的业务逻辑都在 `SessionService`，handler 只做参数校验 + 调用 + 响应。

---

## 6. 新增 Typed SessionEvent

| 事件类型 | 触发 | data 关键字段 |
|---------|------|--------------|
| `MESSAGE_QUEUED` | 活跃 run 时发消息（默认 queue） | `content`, `queue_id`, `created_at` |
| `QUEUE_CANCELLED` | 取消排队项 | `queue_id` |
| `STEER_REQUESTED` | 用户点"立即" | `content`, `run_id`, `steer_id` |
| `STEER_APPLIED` | runtime 把 steer 注入当前 run | `steer_id`, `applied_at` |
| `COMPACTION_START` | 压缩开始 | `source_seq_start`, `source_seq_end` |
| `CONTEXT_COMPACTED` | 摘要写入 | `summary`, `schema="six_section"`, `source_seq_start`, `source_seq_end` |
| `COMPACTION_END` | 压缩结束，shadow 标记完成 | `bracket_id` |
| `MODEL_CHANGED` | 模型切换 | `from_provider`, `from_model`, `to_provider`, `to_model` |
| `RUN_INTERRUPTED` | 崩溃后重启扫描发现无终态 run | `interrupted_seq`, `reason="process_restart"` |
| `ARTIFACT_EXTERNALIZED` | 工具结果外置对象存储 | `artifact_id`, `mime`, `token_count`, `summary`, `ref_uri` |

> **as-built 注（2026-09-09，T7 实现）**：事件类型字符串按仓库既有词汇表约定写作
> **`model/changed`**（`model/*` 族），字段名与跨端契约
> `docs/integration/PRD_PHASE_MULTITURN_TOTAL.md` §2.3 对齐为
> `from_provider` / `from_model_id` / `to_provider` / `to_model_id`（本表旧稿的
> `from_model` / `to_model` 作废）。
>
> **as-built 注（2026-09-09，T8 实现）**：`RUN_INTERRUPTED` 的事件字符串是
> **`run/interrupted`**（`run/*` 族），`run_id` / `step_id` 挂事件信封，`data`
> 只放 `interrupted_seq` + `reason="process_restart"`（见 TOTAL §2.5）。

所有事件 append-only 写入 JSONL，单一事实源。

---

## 7. CLI 设计（以 Pi / oh-my-pi 为榜样）

### 7.1 交互模型
- 进程启动后加载或创建 current session（按 cwd 映射的 workspace）。
- 普通 prompt：直接 `SessionService.send_message(current_id, content)`。
- 不再每次 `_new_session()`。
- 流式输出到终端，支持 Ctrl+C 取消当前 run。

### 7.2 Slash 命令

| 命令 | 行为 |
|------|------|
| `/new` | 显式新建同级 session，切换 current |
| `/resume` (`-r`) | 从历史 session 列表选一个继续 |
| `/fork` | 从当前/指定历史点派生新 session |
| `/compact` | 手动触发压缩 |
| `/model <provider> <model>` | 切换当前 session 模型 |
| `/history` | 列出当前 workspace 的 session |
| `/cancel` | 取消当前在跑的 run |
| `/clear` | 清屏（不删 session） |
| `/help` | 列出所有命令 |

### 7.3 Approval
- 继续使用现有本地 approval callback（auto/ask 模式）。
- `--yolo` 切到 `DANGER_FULL_ACCESS`（保持现有语义）。
- 终端弹提示，用户输入 y/n。

---

## 8. 长期记忆（已实现，本期验证）

LangMem 已完整实现（`src/agent_harness/memory/`，68 测试通过）。本期工作：

1. **验证 session 绑定**：每个 session 绑定一个 `MemoryNamespace`（已有 `ca6fe88` commit），多轮续聊后 namespace 内有足够内容。
2. **验证异步提取**：`MemoryWriteback` 从 outbox 异步提取记忆条目（已有实现），多轮对话后验证提取质量。
3. **验证召回注入**：后续 session 中 `MemoryContextProvider` 按 LangMem 内置的语义检索召回 top-k，注入上下文。
4. **验证 graceful degrade**：Milvus/embedding 不可用时 runtime 不崩（#21）。
5. **不重写、不换 provider**。Mem0 仍是未来可选项（#17）。

**不需要新增能力**——本期是把已实现的长期记忆放到"真的有多轮 session"的场景里验证。

---

## 9. 关键不变量守护对照

| 不变量 | 本 PRD 如何守护 |
|--------|---------------|
| #3 append-only typed SessionEvent | 所有新事件都是 append 类型，不改旧事件；压缩用 bracket + shadow |
| #5 Persistent History ≠ Runtime Context | 短期记忆投影走 derive_messages，不直接注入全部历史 |
| #7 Tool 只有一条执行路径 | WS→HTTP 审批链最终汇聚到 ToolExecutor 同一 callback |
| #11 Sandbox/Permission 是 runtime 边界 | 审批仍是 runtime 强制，不靠 prompt |
| #12 Checkpoint ≠ 副作用恢复 | 崩溃恢复不自动重跑，标记 interrupted 让用户决定 |
| #13 Operation Ledger 必须 reconcile | 崩溃后强制跑 Ledger reconcile |
| #14 UNKNOWN 高风险 Tool 不盲重跑 | reconcile 后 UNKNOWN 工具标记需人工确认 |
| #15 大 Artifact 只给模型 summary+ref | 工具结果 >2k token 外置 MinIO，session 里留摘要+引用 |
| #16 Memory = Capability + ContextProvider | LangMem 走 MemoryCapability + MemoryContextProvider，不进 Session |
| #21 Optional Capability 故障不拖垮 Core | LangMem/Milvus 不可用时 graceful degrade |
| #22 Web UI 不维护第二套 Session 真相 | 所有真相来自 append-only JSONL + SessionService |

---

## 10. 验收标准（Definition of Done）

1. **多轮续聊**：同一 session 连续 10 条消息，全部在同一 session_id 下追加，第 10 条能引用第 1 条内容。
2. **压缩 bracket**：构造超长对话触发压缩，验证 4 事件 bracket 写入、`derive_messages` 正确跳过 shadow 段、replay 后状态一致、shrink 校验通过。
3. **大产物外置**：工具返回 >2k token 时，结果落 MinIO、session 里只剩 `ARTIFACT_EXTERNALIZED` 摘要+ref、模型能通过 `read_artifact` 取回全文。
4. **steer/queue**：run 进行中发消息默认进队列、点"立即"变 steer、run 不被打断、队列项可取消。
5. **CLI/Web 一致性**：CLI 新建的 session 能在 Web 看到、反之亦然；两端走同一个 `SessionService`。
6. **崩溃恢复**：run 进行中 kill 进程，重启后 session 标记 `RUN_INTERRUPTED`、UNKNOWN 工具不盲重跑、用户能看到中断点并选择继续/重发/忽略。
7. **模型切换**：同一 session 中途换模型，`MODEL_CHANGED` 写入、下一轮用新模型、上下文不丢。
8. **fork**：从历史点 fork 出新 session，新 session 独立、原 session 不受影响。
9. **Langfuse 多轮 trace**：连续 3 轮对话在 Langfuse 上按 session_id 串联可见，每轮独立 root span + turn_index。
10. **长期记忆生效**：多轮对话后 LangMem 异步提取记忆、后续新 session 中通过 MemoryContextProvider 召回注入（或 graceful degrade 验证）。
11. **单实例性能**：热会话（LRU 命中）续聊 P95 < 200ms（不含模型调用）。

---

## 11. 实施顺序（建议）

按依赖关系拆分 tracer bullets：

1. **T1 — `SessionService` 领域层**：抽出现有 Web handler 里的 session 逻辑成独立 service，CLI 和 Web 都调它。（无功能变化，纯重构）
2. **T2 — 续聊 action 端点 + WebSocket**：`/api/sessions/{id}/messages`、`/api/ws`、follow-up 排队。
3. **T3 — steer / queue UI 与事件**：`STEER_REQUESTED` 等新事件、前端"立即"按钮。
4. **T4 — CLI 重构**：去掉每条 `_new_session`，加 slash 命令，复用 SessionService。
5. **T5 — 压缩 bracket 升级**：4 事件 bracket + shadow + derive 投影 + 六段式摘要 + shrink 校验。
6. **T6 — 大产物外置**：`ARTIFACT_EXTERNALIZED` + MinIO 存储 + `read_artifact` 工具 + 2k 阈值。
7. **T7 — 审批 WS 推送 + HTTP 回传**：`APPROVAL_REQUESTED` 事件 + modal + `/approvals/{call_id}` 端点。
8. **T8 — 模型切换**：`MODEL_CHANGED` 事件 + `/sessions/{id}/model` 端点 + runtime 读 session 当前模型。
9. **T9 — Fork API + UI/CLI**：`/forks` 端点 + 复用 fork.py。
10. **T10 — 崩溃恢复**：`RUN_INTERRUPTED` 扫描 + Ledger reconcile + UI 提示。
11. **T11 — Langfuse 多轮埋点**：turn_index + session_id 串联 + compaction 子 span。
12. **T12 — 长期记忆多轮验证 + DoD 全量回归**。

每个 T 都带测试 + 不破坏现有不变量。

---

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| WS 迁移影响现有前端 | 保留旧 SSE 一段时间，灰度切换；WS 不可用降级到 SSE+HTTP |
| 压缩 bracket 改动 derive_messages 影响现有测试 | T5 单独成 ticket，先加 bracket 测试再改实现，保留旧 marker 兼容期 |
| 大产物外置依赖 MinIO 可用 | MinIO 不可用时降级为内联截断（head+tail+marker，抄 dsh pruner），不阻塞 run |
| LRU 淘汰导致热会话冷启动延迟 | 可观测：监控 cache miss 率；配置上限可调 |
| 单实例上限 | 文档明确，监控 QPS，触发阈值时启动多实例 + session 亲和方案 |
| LangMem 多轮场景下召回质量 | 先验证"有召回"再优化质量；召回不在本期 critical path |

---

## 13. 引用索引

- Pi session 设计：`C:\Users\王浩宇\AppData\Local\Temp\pi-mono\packages\coding-agent\docs\sessions.md`
- Pi session 格式：`...\docs\session-format.md`
- Pi compaction：`...\docs\compaction.md`
- Pi AgentSession：`...\src\core\agent-session.ts`
- oh-my-pi CLI：`C:\Users\王浩宇\AppData\Local\Temp\oh-my-pi`（详见 `docs/RESEARCH_OHMY_PI_DSH_COMPACTION.md`）
- dsh clone：`C:\Users\王浩宇\AppData\Local\Temp\deepseek-harness`
- 当前仓库根因：`demo/live_agent.py` / `src/agent_harness/web/app.py` / `web/src/hooks/useSession.ts`
- 已实现长期记忆：`src/agent_harness/memory/`（68 测试通过）
- 工程规格：`goal/Lightweight_Observable_Agent_Harness_Spec/docs/spec/`
- 架构不变量：`AGENTS.md` §7
