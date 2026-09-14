# Backend Audit — Observable Agent Workspace

> Phase 0 交付物。基于 `feat/backend-c`（起步基线 `main` `6335066`）。
> 审计范围：现有 Backend 能否真实支撑 SDD `03_RUNTIME_EVENT_CONTRACT.md`，
> 而非重新设计产品语义。结论先行：**当前 Backend 已经是一个成熟的可观察 Agent Harness，绝大多数 Contract 能力已真实存在；真实缺口集中在「权限交互化」「Run 能力声明」「元数据富化」三块，全部可通过最小必要改动闭环，不需要重构领域模型。**

---

## 1. 结论 TL;DR

| 维度 | 状态 |
| --- | --- |
| 领域模型（Session / Run / SessionEvent） | ✅ 已存在且干净映射 Contract，**不需要新建 Run/Turn 表** |
| Append-only 事件日志（JSONL） | ✅ 已是单一事实源，seq 严格递增、词汇表校验、监听器广播 |
| Agent Loop（run / run_stream） | ✅ 双入口共享同一 `_drive`，事件事实源已落 JSONL |
| 流式传输（SSE） | ✅ 稳定，**保持 SSE 不迁移**；已有 live + 重放 + 断连续传 |
| 持久化与恢复（Ledger / Checkpoint / Recovery） | ✅ 完整，Ledger-first 8 步恢复已实现 |
| 工具运行时（校验/超时/单 Retry Layer/批次/审批关卡） | ✅ 成熟；权限**策略**真实存在 |
| 取消 / 中断 | ✅ detached-run + POST /cancel + 孤儿回收，run/failed.reason 区分来源 |
| 大 Tool Result → Artifact | ✅ OverflowHandler + content-hash 寻址 + inspect 切片 |
| 权限**交互化**（permission.requested/resolved + 等待态） | ❌ **最大真实缺口**——当前是同步 callback + 默认 auto-approve |
| Contract 事件命名对齐 | 🟡 词汇不同（`tool/call` vs `tool.started`），**不需要改名**——SDD 明确允许沿用现有命名，只需映射表 |
| Contract 信封字段（schema_version / durability / status） | 🟡 缺，**纯加法**，可低成本补齐 |
| 能力清单 / 模型元数据富化 / Run 能力声明 / Artifact Web 面 / Context usage | ❌ 缺，全是**新增只读端点**，不动核心 |
| checkpoint.created / recovery.* 事件 | ⚠️ 故意不进 SessionEvent（既有不变量），需通过**独立只读端点**暴露元数据 |

**关键判断**：这次不是「重构 Backend」，而是「在不破坏既有不变量的前提下，把已存在的能力按 Contract 对齐暴露，并补齐权限交互这一块真实能力」。

---

## 2. 现有领域模型（不要为它新增表）

### 2.1 Session 聚合根 — `src/agent_harness/session/session.py`

- `Session` 持有 `session_id` + 内存事件缓存 + `_next_seq` 增量计数器 + `_listeners`。
- 构造入口：`Session.start()` / `Session.resume()`（resume 会校验 seq 严格递增、修复 dangling tool_call、append `session/resumed`）。
- 核心 `append()`：分配 seq → 同步写 JSONL → 更新内存 → 推进计数器 → 触发监听器。**词汇表校验**：只有 `EVENT_TYPES` 内类型可持久化；`STREAM_ONLY_TYPES`（`model/started` / `model/delta`）被显式拒绝（不变量 #4：Event ≠ Diagnostic Log）。
- Run 边界：`begin_run()` 生成 run_id + append `run/started`；`end_run()` append `run/completed | run/failed`，data 带 `usage_total` / `trace_id` / `trace_url` / `reason`。
- `mark()` / `since()` 给 runtime 增量取「这轮新追加的事件」。

### 2.2 SessionEvent — `src/agent_harness/session/event.py`

`@dataclass(frozen=True)`，字段：`event_id` / `seq` / `time`(ISO-8601 ms) / `type` / `session_id` / `run_id?` / `agent_id?` / `step_id?` / `block_id?` / `data` / `source_event_ids?`。

durable 词汇表（`EVENT_TYPES`）：`session/{started,resumed,forked}`、`run/{started,completed,failed}`、`user/message`、`model/{completed,failed,fallback}`、`tool/{call,result,output_delta}`、`text/delta`、`reasoning/{started,delta,completed,interrupted}`、`artifact/created`、`context/compacted`、`memory/degraded`、`tool/failure-guard`、`agent/{delegation-started,delegation-finished}`、`operation/reconcile-required`。

stream-only：`model/started` / `model/delta`（保留词汇，运行时不再发射后者，由 `text/delta` 承接）。

### 2.3 Run / Turn 的真实形态

- **Run = `run_id` 字段 + 一对 `run/started` / `run/completed|failed` 事件**，不是独立 ORM 表。事件流自然表达 Run 的所有事实。
- **Turn 不存在**。本项目里一轮「user → agent 回合」就是「一段从 `user/message` 到 `run/completed|failed` 的事件序列」。引入 Turn 表只会制造与 Run 同义的第二个真相源（违反 §22 不变量）。
- SDD `03` §2 与 `05` §2 都明确说：**先审计、不要为了名词建表**。审计结论：**保留现状**。

### 2.4 领域映射表（对 Contract）

| Contract 概念 | Backend 现状 | 动作 |
| --- | --- | --- |
| Session | `Session` 聚合根 + JSONL | keep |
| Turn | 不存在；一轮 run 即一个 turn | **不引入**（按 SDD §2.2 决策 23/24） |
| Run | `run_id` + `run/started`…`run/completed\|failed` 事件边界 | keep（无需建表） |
| RuntimeEvent | `SessionEvent`（durable）+ `AgentEvent`（含 stream-only 镜像） | keep，补信封字段 |
| Artifact | `Artifact`（content-hash id）+ `ArtifactStore` + `artifact/created` 事件 | keep，补 Web 面 |
| Checkpoint | `Checkpoint` + `CheckpointStore` + `CheckpointPolicy`（**不进事件流**，ADR-0004 不变量） | keep，补只读元数据端点 |

---

## 3. 现有 Runtime 生命周期与调用链

`AgentRuntime`（`src/agent_harness/agent/runtime.py`）双入口共享 `_drive`：

```
run() / run_stream()
   └─ _drive(session, user_input, stream=…)
        ├─ append user/message → to_agent_event 镜像 yield
        ├─ save_checkpoint(USER_ACCEPTED)
        ├─ begin_run() → run/started；RunTracer.run_started（如启用）
        ├─ BlockStreamer.begin_run（合帧记账）
        ├─ while True:
        │    ├─ context_builder.build(session)   ← 模型可见投影唯一入口
        │    ├─ ModelFallbackCoordinator.astream / ainvoke
        │    │     （含 stall 看门狗 + 进程级并发闸 + 两级 fallback）
        │    ├─ BlockStreamer 合帧：reasoning/* + text/delta（durable）
        │    ├─ append model/completed（带 usage/model/tool_calls）
        │    ├─ steps += 1
        │    ├─ 无 tool_calls → end_run(completed) + write_memories + return
        │    ├─ 撞 max_steps → end_run(failed, max_steps_exceeded)
        │    ├─ 预持久化 tool/call（执行前，§4.1）
        │    ├─ executor.execute_batch(calls, OperationContext, session)
        │    │     （每条经 lookup→validate→approval gate→Ledger→timeout→retry→output stream→overflow）
        │    ├─ emit_pending_events（artifact/created 等延迟事件）
        │    ├─ emit_result_event（tool/result）
        │    ├─ save_checkpoint(TOOL_BATCH_COMPLETED)
        │    └─ RepeatedToolFailureGuard：软熔断注入纠正消息 / 硬熔断 end_run(failed)
        ├─ except (CancelledError, GeneratorExit):  取消臂
        │     streamer.interrupt → model/failed(cancelled) → run/failed(reason=cancelled|orphaned)
        ├─ except Exception:  异常臂
        │     streamer.interrupt → model/failed → run/failed
        └─ finally: run_context_var.reset（嵌套运行恢复）
```

关键不变量已在代码里钉住：
- **单终态**：`_RunFinalizer` 是终态簿记唯一 owner（取消臂/异常臂/成功臂都经它收口）。
- **失败兜底**：任何异常都不会让 JSONL 停在悬空 `run/started` 上。
- **取消语义分离**（02 §17）：`reason` ∈ {`cancelled`（用户 POST /cancel）, `orphaned`（孤儿回收）, 故障类型名（异常臂）, `identical_tool_failure_loop`（硬熔断）, `max_steps_exceeded`, `context_window_exceeded`}。
- **usage 如实**：`_usage_from_response` 只接 `int >= 0`，缺数据返 None，绝不伪造；run 级 `usage_total` 聚合但不分主备。
- **trace_id / trace_url 并列**下发到 `run/completed|failed.data`（机器可读 + 人类可点击，不互替）。

---

## 4. 现有流式架构（保持 SSE，不迁移）

- Transport：**SSE**（`sse_starlette.EventSourceResponse`）。决策 22 明确「保持当前稳定 SSE/WS，无谓不迁移」——审计结论：**SSE 稳定且已生产级加固，保持**。
- 端点（`src/agent_harness/web/app.py`）：
  - `POST /api/sessions` —— 起新 session，**detached-run** 驱动，SSE 返回 live `AgentEvent`。
  - `GET /api/sessions/{id}/stream?after_seq=N` —— **重连续传**：重放 durable 事件（`after_seq < seq ≤ replay_upto`）→ 接 live 流；客户端按 seq 幂等合并两条通道的帧（同形 payload）。backlog 超 `STREAM_REPLAY_MAX_EVENTS=1000` → 单帧 `stream/truncated` 控制事件，客户端走 `GET /events` 全量重建后重连。
  - `GET /api/sessions/{id}/events` —— 全量历史事件（刷新重建视图用）。
  - `POST /api/sessions/{id}/cancel` —— 显式取消。
  - `POST /api/sessions/{id}/recover` —— RecoveryCoordinator 入口（修 dangling + Ledger reconcile；RUNNING/UNKNOWN 返 409 等人工裁决）。
  - `GET /api/sessions` / `GET /api/models` / `GET /api/sessions/{id}/lineage`。
- RunManager（`web/runmanager.py`）：detached `asyncio.Task` 驱动 `run_stream`，SSE 只是订阅者；断连只 unsubscribe；孤儿宽限计时回收；seq 幂等合并（listener 通道 vs run_stream 镜像通道），队列有界满时丢最旧（seq gap 触发客户端重连自愈）。
- 已有不变量对齐 SDD §19：单调序 ✅、event_id/seq 去重 ✅、reconnect cursor ✅、cancellation 走 HTTP 端点 ✅。
- **性能**：诊断日志走独立 JSONL（不阻塞模型流）；token chunk 经 BlockStreamer 合帧（不每个 token 一行）；durable 写是同步 JSONL append（薄层）；SSE 帧渲染在端点侧（runmanager 不反向依赖 web.app）。

---

## 5. 现有持久化与恢复

- **SessionEvent JSONL**（`JsonlSessionStore`）：append-only、崩溃安全（tmp + replace）、seq 校验、dangling 修复。
- **Operation Ledger**（SQLite）：每个 tool_call 的 PENDING→RUNNING→{SUCCEEDED|FAILED|CANCELLED|UNKNOWN|NEED_RECONCILE}；崩溃后 Ledger 永远比 SessionEvent 更完整（Ledger-first）。
- **Checkpoint**（SQLite + `CheckpointPolicy`）：4 个稳定边界（`USER_ACCEPTED` / `MODEL_COMPLETED` / `TOOL_BATCH_COMPLETED` / `FINAL_COMPLETED`）。**关键不变量**：`checkpoint/saved` 永远不进 SessionEvent（它是存储层恢复辅助，不是对话事实）。这意味着 SDD `checkpoint.created` 事件**不能直接照搬进事件流**——需通过独立只读端点暴露元数据（见 §7）。
- **RecoveryCoordinator**：8 步恢复（07 §9），UNKNOWN 永不自动验证/自动重跑（不变量 #14），NEED_RECONCILE 走 ReconcileCallback 人工裁决。
- **ArtifactStore**（S3 兼容 / Fake）：content-hash 寻址，`save` / `load` / `inspect`（按行/关键词切片，防大行灌爆 context）。大 Tool Result 经 `OverflowHandler` 溢出，模型只拿截断摘要 + `artifact_ref`。
- **SessionMetaStore**（SQLite）：session 元信息 + lineage（fork 父子）。

---

## 6. 现有工具与权限（策略真实，交互缺位）

- `ToolRegistry`（静态路由）+ `ToolExecutor`（执行域）：validation-first 三阶段 + 阶段 2.5 审批关卡 + timeout 边界 + **唯一 Retry Layer**（`retryable` 位驱动，`MAX_ATTEMPTS=3`）+ 批次调度（全 READ_ONLY 并发 / 任一 MUTATING 串行，严格保序）+ 输出流（`tool/output_delta`）+ OverflowHandler。
- **权限策略已存在**：
  - `PermissionPolicy` ∈ {`read-only`, `workspace-write`, `danger-full-access`}（Session 级）。
  - `ToolPermission` ∈ {`read-only`, `workspace-write`, `danger`}（Tool 级）。
  - `needs_approval()` 精确判定超级别；无 callback → **安全拒绝**（绝不静默放行 DANGER）。
  - per-call scoping：每次 execute 独立检查，不存「已批准」状态。
- **真实缺口**：
  - 审批是**同步 `ApprovalCallback`**（`ApprovalResponse = callback(ApprovalRequest)`），不是 async、不能 yield 事件、不能让 Run 进入「等待态」。
  - Web 层 `auto_approve=True` 默认，`POST /approve` 是预留 seam（返 202「V1 uses auto-approve」）。
  - 没有 `permission.requested` / `permission.resolved` 事件；没有 Run 等待态。
  - 这正是 SDD `05` §9 与 PRD §15 的硬需求：「如果后端缺权限执行能力，Backend AI 必须实现真实支持，前端绝不能 ship 一个什么都不做的假选择器」。

---

## 7. 对照 `03_RUNTIME_EVENT_CONTRACT.md` 的 Gap Analysis

### 7.1 事件命名（**不需要改名**）

SDD `03` §4：「Exact naming may adapt to existing backend conventions, but semantic coverage should include…」。映射：

| Contract | Backend 现状 | 说明 |
| --- | --- | --- |
| `session.created` | `session/started` | 同义 |
| `session.updated` | `session/resumed` / `session/forked` | 同义 |
| `run.started` / `run.completed` / `run.failed` | 同名 ✅ | 直接对齐 |
| `run.interrupted` | `run/failed` + `data.reason=cancelled\|orphaned` | **语义已覆盖**，无需独立事件（避免双终结） |
| `assistant.chunk`（transient） | `text/delta`（durable）/ `model/delta`（stream-only, legacy） | 同义；**注意**：backend 把合帧 text/delta 当 durable，SDD 也允许 |
| `assistant.message.settled` | `model/completed` | 同义 |
| `reasoning.summary` | `reasoning/{started,delta,completed,interrupted}` | 更细粒度，覆盖 |
| `llm.started` / `llm.completed` / `llm.failed` | `model/started`(stream-only) / `model/completed` / `model/failed` | 同义 |
| `tool.started` / `tool.completed` / `tool.failed` | `tool/call` / `tool/result`(+`output_delta`) | call 含 args，result 含完整 ToolResult JSON（含 error） |
| `permission.requested` / `permission.resolved` | ❌ **缺** | 见 §6，最大缺口 |
| `retry.scheduled` / `retry.started` | ⚠️ 只进诊断日志（`retry` log event），不进 SessionEvent | SDD 不强制 durable；可保持现状或加 transient 事件 |
| `checkpoint.created` | ❌ **故意不进事件流** | 用独立只读端点暴露（见下） |
| `recovery.started` / `recovery.completed` | ❌ RecoveryCoordinator 不发事件 | 同上，端点级表达即可 |
| `artifact.created` / `artifact.updated` | `artifact/created` ✅ | updated 缺（当前只有 created） |
| `change.created/updated` | ❌ 无 Git change 事件 | Coding capability 才需要；当前无 coding capability 装配 |
| `context.compacted` | `context/compacted` ✅ | 直接对齐 |

### 7.2 事件信封字段（`RuntimeEvent<T>`，SDD `03` §3）

| 字段 | Backend `SessionEvent` | 动作 |
| --- | --- | --- |
| `schema_version` | ❌ 缺 | **加常量**（如 `"runtime_event/v1"`），SSE 帧 + JSONL 行同源 |
| `event_id` | ✅ `event_id` | — |
| `session_id` | ✅ | — |
| `turn_id` | ❌（无 Turn 概念） | **不加**（按 §2.3 决策） |
| `run_id` | ✅ | — |
| `sequence` | ✅ `seq` | — |
| `timestamp` | ✅ `time` | — |
| `type` | ✅ | — |
| `status` | ❌（隐含在 type 里） | **可选加**（便于前端投影；低优先级） |
| `trace_id` | 在 `data` 里（`run/completed\|failed.data.trace_id`） | **保持**（不强行抬到信封） |
| `parent_event_id` | ❌（有 `source_event_ids`） | **不加**（source_event_ids 更通用） |
| `capability` | ❌ | **加**（用于 capability-aware 投影；从 assembly 注入） |
| `durability` | ❌（靠 `EVENT_TYPES` vs `STREAM_ONLY_TYPES` 分类） | **加分类字段**（durable|transient），SSE 帧标注 |
| `visibility` | ❌ | **可选加**（default|detailed|raw；用于 Timeline 密度） |

**结论**：信封字段是**纯加法**，对既有持久化零破坏。`schema_version` + `capability` + `durability` 是必加三项，其余按前端需要再加。

### 7.3 Run 状态机（SDD `03` §5）

Backend 当前能 event-derived 出的状态：`idle`（无在途 run）→ `running`（run/started 后）→ {`thinking`（reasoning/started）/ `calling_model`（model/started stream-only）/ `running_tool`（tool/call 后）/ `retrying`（retry log）/ `recovering`（recover 端点）} → `completed` / `failed` / `interrupted`（run/failed.reason）。

**缺**：
- `waiting_approval` —— 需要权限交互化后由 `permission.requested` 派生。
- `checkpointing` —— checkpoint 是后台静默保存，不阻塞 run，**不应**作为用户可见状态（保持现状）。

### 7.4 其他 Contract 子节

| Contract 子节 | 现状 | 缺口 |
| --- | --- | --- |
| §6 LLM payload（provider/model/tokens/latency/cost/finish_reason） | `model/completed.data` 带 content/model/usage；**latency 在诊断日志不在事件**；cost 不伪造（费率表未定义） | 可选把 `latency_ms` 抬进 data；cost 保持 None（不伪造，符合 §15） |
| §7 Reasoning | `reasoning/*` 事件族 ✅，仅在 provider 真吐时发射 | 无缺口 |
| §8 Tool payload（preview/summary/size/artifact_id/truncated） | `tool/result.data.content` 是完整 ToolResult JSON（含 message/error/artifact_ref）；**preview/summary/size 不在事件顶层** | 加派生字段或前端从 content 解析（见 §9 性能） |
| §9 Permission contract | ❌ 见 §6 | **最大缺口** |
| §10 Permission modes | ❌ 没有列 mode 的端点 | **加 `GET /api/permission-modes`**（返回后端能真实执行的 modes） |
| §11 Stop/cancel | ✅ POST /cancel + cooperative + `Stopping…` 可由 `run/failed.reason=cancelled` 与 task 状态派生 | 可选加 `run/interrupting` 中间事件（前端「Stopping」体验更顺） |
| §12 Retry/Resume + `RunActions` | ✅ retry 工具域已实现；❌ **没有 `can_stop/can_retry/can_resume/latest_checkpoint_id` 端点** | **加 `GET /api/sessions/{id}/run-actions`** 或并入 session detail |
| §13 Checkpoint payload | ✅ 存储层有完整 Checkpoint；❌ 无 Web 面 | **加 `GET /api/sessions/{id}/checkpoints`**（只读元数据，不进事件流） |
| §14 Artifact model | ✅ 存储层完整；❌ 无 Web 面 | **加 `GET /api/sessions/{id}/artifacts` + `GET /api/artifacts/{id}` + `GET /api/artifacts/{id}/inspect`** |
| §15 Change model | ❌ 无 coding capability 装配 | capability 到位后再做（不在本轮核心） |
| §16 Model metadata | ⚠️ `GET /api/models` 只返 name/provider/model/default | **富化**：context_window / speed_tier / supports_tools / supports_vision / supports_reasoning_summary / is_available（从 ModelCatalogEntry + provider 预设，**不猜**） |
| §17 Capability manifest | ❌ 无 `GET /api/capabilities` | **加**：从 CapabilityRegistry + CapabilityWiring 派生 surfaces/actions |
| §18 Context usage | ❌ 无端点 | **加** `GET /api/sessions/{id}/context-usage`（返 used/max/percentage/**source=provider|backend_estimate|unknown**/compacted）；tiktoken 估算已在 `context/tokens.py` |
| §19 Streaming/reconnect | ✅ 见 §4 | 无缺口（可选加 SSE `Last-Event-ID` 头支持，当前用 `after_seq` 查询参数等效） |
| §21 Search | ❌ 无 search 端点 | 按 SDD `06` Phase 7 后置；本轮**不做**（除非显式要求） |
| §23 Security/redaction | ⚠️ 部分（memory writeback 脱敏、tracer redacted 模式）；**SSE/事件层无系统化 redaction** | **加事件序列化层的 redaction 策略点**（API key / auth header / 已知敏感字段），在 `_event_to_sse_dict` 边界统一 |

---

## 8. 最小必要迁移计划（按 SDD `06` Phase 编排）

> 原则：**Preserve what already works. Add only what the contract actually needs. No fake capability. No architecture astronautics.**

### Phase 0（本审计）— 已完成
交付本文档 + SDD 入版本控制（`docs/spec/Observable_Agent_Workspace_SDD/`）。

### Phase 2 — Composer 后端支撑（只读端点，零核心改动）
1. `GET /api/models` 富化（context_window / speed_tier / supports_* / is_available）。来源：provider 预设 + `ModelCatalogEntry`，**未知字段省略不猜**。
2. `GET /api/permission-modes` —— 返回后端能真实执行的 mode 列表 + 描述。
3. `GET /api/capabilities`（v1 骨架）—— 从 `CapabilityRegistry` 派生 `CapabilityManifest`（surfaces/actions）。即使装配为空也要诚实返回（前端据此隐藏 Changes/Terminal）。
4. **事件信封加字段**：`schema_version` + `durability`（+ 可选 `visibility`）。改 `_event_to_sse_dict` / `_session_event_to_sse_dict`，JSONL 行可选带（向后兼容）。加测试。

### Phase 3 — 共享运行时事件基础（**大部分已存在**，只做对齐验证）
- 已有：append-only、seq、durable/transient、replay/reconnect、LLM/tool 生命周期、settled assistant、reasoning。
- 补：`status` 信封字段（可选）、把 `latency_ms` 抬进 `model/completed.data`（已在诊断日志，抬到事件低成本）。
- 写 **契约对齐测试**（不是改实现）：seq 单调、reconnect 无重复、断连中段恢复、settled 后可重建 Chat/Timeline。

### Phase 4 — Timeline + Inspector 后端支撑
1. `tool/result` 顶层加 `result_preview` / `result_summary` / `result_size_bytes` / `truncated`（从 ToolResult 派生；完整 content 仍在，前端可按密度选）。
2. `GET /api/sessions/{id}/artifacts` + `GET /api/artifacts/{id}` + `GET /api/artifacts/{id}/inspect`（lazy load）。
3. `GET /api/sessions/{id}/context-usage`（带 `source` 标签）。

### Phase 5 — Permission + Stop + Retry/Resume（**本轮真正的核心工作**）
> 这是唯一触及核心 Runtime 行为的 Phase。其余都是加端点/加字段。

1. **权限交互化**（最大缺口，需新设计但不动既有审批关卡语义）：
   - 把 `ApprovalCallback` 从同步扩展为 **async + 可暂停**：ToolExecutor 命中审批关卡时：
     - append `permission.requested` 事件（带 `permission_id` / `action_type` / `tool_call_id` / `arguments_preview` / `risk` / `allowed_decisions`）；
     - Run 进入 **等待态**（Run Pulse = `Waiting approval`）；
     - 经 RunManager 把 pending approval 暴露给订阅者；
     - `POST /api/sessions/{id}/approve` 真实回传决策；
     - 后端校验 `allowed_decisions`、执行决策（放行/拒绝）、append `permission.resolved`；
     - Run 恢复或按决策拒绝（`tool/result` PERMISSION_DENIED）。
   - **必须**：后端强制；前端控件不是安全边界（既有铁律一保留）。
   - **必须**：决策审计 trail（permission.requested/resolved 事件是 audit）。
2. **Stop 语义增强**：可选加 `run/interrupting` 中间事件（POST /cancel 后立即发），让前端「Stopping」体验真实；终态仍是 `run/failed.reason=cancelled`。
3. **RunActions 端点**：`GET /api/sessions/{id}/run-actions` 返回 `{can_stop, can_retry, can_resume, latest_checkpoint_id}`。
   - `can_stop` = 有在途 run；
   - `can_retry` = 末次 run 终态为 failed/interrupted（本轮实现「新建相关 run」语义）；
   - `can_resume` = 有 resumable checkpoint（Checkpoint.resumable 标志——当前 Checkpoint 模型无此字段，需加；默认 false = 诚实「不能确定性 resume」）。

### Phase 6 — Capability-aware surfaces
- finalize `GET /api/capabilities`（Phase 2 骨架已建）。
- coding capability 装配到位后：加 `GET /api/sessions/{id}/changes`（真实 Git diff，不解析终端输出）。
- terminal：当前无终端后端 → manifest 诚实返 `terminal:false`，前端隐藏。

### Phase 7 — Search（后置，本轮不做除非显式要求）

### Phase 8 — 性能/安全加固
- 事件序列化层统一 redaction 策略点（§23）。
- 长 Timeline 的 `GET /events` 分页/窗口化（当前全量返回；超长会话需加 `?after_seq=` 或 `?limit=`）。
- payload 大小审查（tool/result preview 字段化后，事件体应更小）。

### Phase 9 — 集成验收
- 契约对齐测试 + E2E（start → model → tool → permission → stop/retry → refresh → artifact）。
- 视觉 QA 由前端负责。
- 合并前对照 `03_RUNTIME_EVENT_CONTRACT.md` 做 diff review。

---

## 9. Frontend 依赖（前端需要 backend 提供什么）

按 SDD `04_FRONTEND_SDD.md` 的真实需求倒推（前端 SDD 非必读，但从 Contract 反推）：

| 前端能力 | 依赖后端 | 当前可用？ |
| --- | --- | --- |
| Session 列表 + Run Pulse | `GET /api/sessions`（已有 summary） | ✅（Run Pulse 可从是否存在在途 run 派生，但当前 list_sessions 不返 in_run 标志——**可加**） |
| Timeline（事件驱动） | `GET /stream` + `GET /events` + `POST /api/sessions` SSE | ✅ |
| Chat（流式回答） | `text/delta` + `model/completed` | ✅ |
| 重连重建 | `GET /stream?after_seq=` | ✅ |
| Composer 模型选择 | `GET /api/models`（需富化） | 🟡 Phase 2 |
| Composer 权限模式 | `GET /api/permission-modes` + 真实执行 | ❌ Phase 2 + 5 |
| 能力感知 tab 显隐 | `GET /api/capabilities` | ❌ Phase 2/6 |
| Inspector（Run/Tool/Context/Permission/Artifact/Checkpoint/Trace） | run-actions / context-usage / artifacts / checkpoints 端点 + 事件字段富化 | 🟡 Phase 4/5 |
| 权限审批 surface | `permission.requested/resolved` 事件 + `POST /approve` 真实 | ❌ Phase 5 |
| Stop / Stopping / Interrupted | POST /cancel + run/failed.reason | ✅（可选加 interrupting 中间事件） |
| Retry / Resume 按钮 | run-actions.can_retry/can_resume + retry 端点 | ❌ Phase 5 |
| 大 Tool Result lazy load | artifact 端点 | ❌ Phase 4 |
| Changes（coding） | changes 端点 + capability | ⬜ coding capability 到位后 |
| Terminal | capability manifest terminal:false | ✅（诚实隐藏） |

---

## 10. 数据迁移需求

**无破坏性数据迁移**。所有改动都是：
- 加事件信封字段（旧 JSONL 行缺字段 → 读时默认值，向后兼容）。
- 加新事件类型（`permission.requested/resolved` 进 `EVENT_TYPES`）。
- 加新只读端点（不动既有存储 schema）。
- Checkpoint 模型加 `resumable: bool` 字段（SQLite 加列，默认 false，幂等）。

唯一需要小心的 schema 变更：`Checkpoint` 加 `resumable` 字段。当前 SQLite 实现需确认是否需要 ALTER TABLE（见 `storage/sqlite.py`，按现有模式加列即可）。

---

## 11. 不做的事（Scope Lock）

- 不新建 Run/Turn 表（领域映射证明不需要）。
- 不把 checkpoint/recovery 进事件流（违反既有不变量）。
- 不重命名 `tool/call` → `tool.started` 等（SDD 明确允许沿用现有命名）。
- 不迁移 SSE → WebSocket（决策 22）。
- 不引入 Kafka / Event Sourcing 框架（轻量原则）。
- 不为搜索（Phase 7）提前工程化。
- 不动既有审批关卡的安全语义（铁律一：执行域失败永远返回 ToolExecution；铁律二：唯一 Retry Layer）。

---

## 12. 下一步建议

按 SDD `06` Phase 序列，**Phase 2（只读端点 + 信封字段）** 是最低风险开局：
- 零核心改动、纯加法、前端 Composer 立即可消费真实模型/权限/能力元数据。
- 同步把 SDD 提交进版本控制（本审计一并提交）。

**Phase 5（权限交互化）** 是本轮唯一真正触及核心 Runtime 的设计工作，建议单独立 ADR（沿用 ADR-0004 风格），明确：
- async approval 的暂停/恢复机制（经 RunManager 暴露 pending approval）；
- 等待态的取消语义（用户在等待审批时按 Stop）；
- 决策的审计 trail 与既有 `permission` 日志的分层。

其余 Phase（3/4/6）均可在不破坏既有不变量的前提下增量推进。
