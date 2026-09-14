# ADR-0004: Storage 分层 — SessionEvent 留 JSONL，Ledger/Checkpoint 用 SQLite

**Status**: Accepted  
**Date**: 2026-09-03  
**Phase**: 4 (Storage + Operation Ledger + Recovery)

## Context

Phase 4 交付物要求 "SQLite default" + "Operation Ledger" + "Checkpoint" + "reconcile"。
Phase 1 已稳定 `JsonlSessionStore`（append-only JSONL，line-atomic write，通过崩溃测试）。
03 §9 警告"禁止双主事实源"，但 SessionEvent 和 Operation Ledger 是**不同种类的事实**
（前者是"对话历史发生了什么"，后者是"每次 Tool 调用现在什么状态"），不是同一事实的两份副本。

三个候选方案：
- A. 全部迁 SQLite（SessionEvent + Ledger + Checkpoint 同库）
- B. SessionEvent 留 JSONL + Ledger/Checkpoint 新建 SQLite
- C. 全部继续 JSONL（SQLite 只定义接口不实装）

## Decision

**Option B**：SessionEvent 保持 JSONL，Operation Ledger + Checkpoint 用 SQLite。

三个分离的 Store 接口，物理上共享同一个 SQLite 文件：
- `SessionStore`（已有 `JsonlSessionStore`）——SessionEvent 的薄 IO 层
- `OperationLedger`——Operation 状态账本
- `CheckpointStore`——稳定边界快照

恢复顺序按 07 §9 冻结：load SessionEvent → load Session-Sandbox mapping → ensure Sandbox →
load Operation Ledger → reconcile unresolved ops → restore tool result consistency →
rebuild Runtime Context → resume。

## Rationale

- **不迁移已稳定代码**：`JsonlSessionStore` 通过 Phase 1 崩溃测试 + 135 个测试验证。
  迁移到 SQLite 是高风险大 Scope 动作，违反 §8 Scope Lock 和 §9.3 Surgical Changes。
- **不是双主事实源**：SessionEvent 和 Ledger 记录的是不同种类的事实（对话历史 vs 操作状态），
  通过固定恢复顺序协调，不存在"同一事实两份副本需要对账"的问题。
- **SQLite 给 Ledger 的天然适配**：Ledger 的核心操作是"按 operation_id 查状态 / 更新状态"，
  SQL 比 JSONL 行扫描高效且天然支持索引/事务。
- **接口分离镜像规格的五层逻辑分离**（07 §2）：每个接口单一职责，独立演化。

## Consequences

- 需要引入 SQLite 依赖（`aiosqlite` 或同步 `sqlite3`，后者是 stdlib）。
- `SessionStore` 接口保持不变——未来如果 SessionEvent 也要迁 SQLite，替换实现即可。
- Checkpoint + 对应 SessionEvent 的"事务化提交"跨两个存储引擎，需要应用层协调
  （先写 Ledger/Checkpoint，再 append SessionEvent；或反之，取决于崩溃语义）。
  这是 Round 2 的逼问对象。

## Round 2 决策补充

以下决策在 grill-with-docs Round 2 中确认，作为本 ADR 的补充：

### 崩溃写顺序：Ledger-first（Q4 → A）

顺序：`Ledger PENDING → Ledger RUNNING → tool.execute() → Ledger SUCCEEDED/FAILED → append tool/call + tool/result SessionEvent`。

Ledger 永远比 SessionEvent 更完整。崩溃时 Ledger 有 SUCCEEDED 但 SessionEvent 缺配对 →
reconcile 合成 Recovery ToolResult 注入。这正是 reconcile 的本职工作。
Phase 1 的 dangling 检测（合成"结果未知"ToolMessage）被 Phase 4 的 Ledger 驱动 reconcile 升级替代。

### Checkpoint 触发：AgentRuntime + CheckpointPolicy seam（Q5 → B）

AgentRuntime 是唯一知道全部 4 个稳定边界的组件。通过薄 seam `CheckpointPolicy` 注入：
Runtime 在每个边界调 `checkpoint_policy.maybe_save(session, boundary_type)`。
默认实现 `OnStableBoundary`；测试可用 `NoCheckpoint` / `EveryStep`。

### kill-test 注入：kill_hook 可选回调（Q6 → A）

`ToolExecutor.execute()` 关键位置插可选 `kill_hook: Callable[[str], None] | None`。
测试传入在指定点 `os._exit(1)` 的 hook。SQLite WAL 模式下已 commit 的事务持久化，
未 commit 的丢失——精确模拟真实崩溃语义。`@pytest.mark.integration` 标注。

### NEED_RECONCILE 升级：独立 ReconcileCallback（Q7 → B）

与 Phase 3 的 `ApprovalCallback` 平行而非复用——Approval 是事前授权（"可以跑吗"），
Reconcile 是事后裁决（"它跑了吗"）。用户拿到 Operation 全上下文（args、Ledger 状态、
Tool 的 reconcile_hint）返回裁决（确认成功 / 确认失败 / 手动重跑 / 放弃）。
两者都注入 AgentRuntime / resume 路径。

## Round 3 决策补充

以下决策在 grill-with-docs Round 3 中确认：

### SQLite schema：三张表（Q8 → B）

共享同一个 `.db` 文件，三张表镜像 07 §2 五层逻辑分离：
- `operations`——Operation Ledger 全字段（07 §4 冻结最小集）
- `checkpoints`——稳定边界快照（session_id / boundary_type / event_seq / payload_json / created_at）
- `session_meta`——Metadata Store 薄索引（session_id / created_at / agent_id / last_checkpoint_seq 等）

SessionEvent 不进 SQLite（留 JSONL）。checkpoint 必须独立表——有些边界（USER_ACCEPTED）没有关联 operation。

### Tool 层新增方法：reconcile_hint()（Q9 → A）

Tool ABC 新增可选方法 `reconcile_hint(args, ledger_state) -> ReconcileHint`。
默认实现返回 `ReconcileHint(verifiable=False)`——安全默认即 NEED_RECONCILE。
只有可验证的工具（read/write/edit/glob/grep/git_status/git_diff）覆写。
ReconcileHint 含建议验证动作 + 可验证性标记（verifiable / unverifiable）。
不加 `critical_side_effects`——它是调试用中间产物，不直接服务 reconcile 决策。

### ToolExecutor ↔ Ledger 接线：execute() retry_loop 外层（Q10 → B）

Ledger 记录 operation 级状态流转，不关心 attempt 级 retry 细节：
`execute() 入口写 PENDING → retry_loop 前写 RUNNING → retry_loop 结束后写 SUCCEEDED/FAILED`。
retry 之间的失败走 Diagnostic Log（已有 `log_event("retry")`），不进 Ledger。
Ledger 记录数 = operation 数，不因 retry 爆炸。

### SQLite 驱动：异步 aiosqlite（Q11 → B）

Ledger 写入走 `aiosqlite`，不阻塞 event loop。增加 aiosqlite 依赖。
Ledger 接口定义为 async（`async def append()` / `async def update_state()` 等），
SessionStore 保持同步 JSONL（Phase 1 已验证同步文件 IO 在 async 路径中可接受）。

## Round 4 决策补充

以下决策在 grill-with-docs Round 4 中确认：

### Resume 编排：独立 RecoveryCoordinator（Q12 → B）

新类 `RecoveryCoordinator`，注入 `SessionStore` + `WorkspaceRegistry` + `OperationLedger`
+ `ReconcileCallback`，暴露 `recover(session_id) -> Session`，按 07 §9 冻结顺序编排 8 步。
`Session.resume()` 保持现状（只管 events），`AgentRuntime` 只需调 `coordinator.recover(session_id)` 一行。

### Reconcile 精确步骤（Q13 → a3 + b2）

PENDING 操作：注入 `PendingPolicy` 默认 skip（合成 skipped ToolResult）。Ledger-first 顺序下
PENDING 极罕见（微秒级窗口），默认 skip 最安全，未来需要可改 retry。

UNKNOWN + verifiable：一律走 ReconcileCallback 交用户。即使 Tool 的 `reconcile_hint` 标记
`verifiable=True`，也不自动执行验证——`hint.verifiable=True` 的意义是给用户提供验证建议
（callback UI 显示"可检查文件 X 确认"），而非授权自动验证。保守优先（不变量 #14）。

### PostgreSQL seam：Store 接口层 ABC（Q14 → A）

三个 Store 各自 ABC 化：`OperationLedger` / `CheckpointStore` / `SessionMetaStore`。
今天实装 SQLite 版，未来实装 Postgres 版。Roadmap 只要 "boundary"——ABC 定义边界，
Postgres 实现留空等真正需要时再加。不做统一 Backend 接口（三 Store 访问模式差异大）。

### kill-test 组织：分层（Q15 → C）

- 底层单元测试（`tests/tooling/test_ledger_wiring.py`）：mock ledger，验证 PENDING/RUNNING/
  SUCCEEDED 在 execute() 正确位置被调。快、精确、不需要真崩溃。
- 顶层 kill-test 集成测试（`tests/recovery/test_kill_scenarios.py`，`@pytest.mark.integration`）：
  每场景一个独立测试（非参数化），用 kill_hook + 子进程 resume，覆盖 5 个 Gate 场景：
  1. Tool success → crash before result event
  2. UNKNOWN bash 不盲重跑
  3. dangling tool_call = 0
  4. duplicate side effect = 0
  5. PENDING 未启动操作被正确跳过

## Round 5 决策补充（收尾轮）

以下决策在 grill-with-docs Round 5 中确认，覆盖设计树剩余 7 个分支：

### 新增 SessionEvent 发射方与时序（Q16 → a2 + b1）

- `checkpoint/saved`：**不进 SessionEvent**。checkpoint 是存储层恢复辅助，不是对话事实，
  derive_messages 不需要它。
- `operation/reconcile-required`：**进 SessionEvent**。reconcile 决策是对话事实的一部分——
  模型在 resume 后应看到"上次有个 operation 进了 NEED_RECONCILE"，否则对话有隐形缺口。
  由 RecoveryCoordinator 在进入 NEED_RECONCILE 时 append。
- `artifact/created`：Phase 5 延期，Phase 4 不处理。

### operation_id 生成归属（Q17 → A）

`operation_id = tool_call_id`。Ledger 表主键直接是 `tool_call_id`（VARCHAR）。
即使 batch 并行调 N 个工具，每个 tool call 有唯一 tool_call_id（OpenAI / Anthropic API 契约），
不存在碰撞。1:1 关系，无额外身份层（YAGNI；retry 是 ToolExecutor 内部细节，Ledger 只记最终态）。

### Ledger retention（Q18 a → a2）

不加自动 TTL，但加 `session_meta.archived BOOLEAN DEFAULT 0` 标记 + 可选 `cleanup(session_id)`
方法。不自动执行——手动/运维触发。未来需要时再接策略。

### RecoveryCoordinator 自身失败（Q18 b → b1）

Recovery 抛异常 + 不写任何中间状态。Recovery 是幂等的（每次从头读 Ledger），失败就重试。
不做部分恢复、不记"recovered to step N"中间态。

### artifact_ref 列（Q18 c → c1）

`operations` 表现在就加 nullable `artifact_ref TEXT` 列。Phase 4 不写但 schema 先留位，
比 Phase 5 加 migration 风险更低（一行 nullable 列几乎零成本）。

### 并发恢复锁（Q18 d → d2）

两个进程同时 recover 同一个 session 时，用数据库锁保护。SQLite 下用
`BEGIN EXCLUSIVE TRANSACTION`（ pessimistic）锁定 `session_meta` 行——
第二个 RecoveryCoordinator 阻塞直到第一个完成或超时。未来 PostgreSQL 用 `SELECT FOR UPDATE`。

### execute_batch 事务粒度 + 失败级联（Q18 e → e1 + 级联语义）

事务粒度：**每个 tool 独立事务**（N 个 operations = N 次 commit），与单 execute() 行为一致。

失败级联（新增语义）：
- **Serial 批次**（含 MUTATING）里任一工具永久失败（retry 耗尽，Ledger FAILED）→ 中止剩余工具，
  它们在 Ledger 记 CANCELLED。安全默认：不确定依赖关系时停止比继续更安全。
- **Parallel 批次**（全 READ_ONLY）→ 单个失败不影响其他（读操作天然独立）。
- 模型看到 FAILED + CANCELLED 结果后自主决策下一步。
