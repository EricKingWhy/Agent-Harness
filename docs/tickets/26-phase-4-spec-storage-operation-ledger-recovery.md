# #26 — Phase 4 Spec: Storage + Operation Ledger + Recovery

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T15:50:10Z
- **Closed**: 2026-09-03T19:50:37Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/26

---

## Problem Statement

当 Agent 执行到一半进程崩溃时（如执行了一个 `write` 或 `bash` 后、把结果写回 SessionEvent 之前），重启后系统无法判断那个 Tool 到底执行成功了没有——副作用可能已经发生（文件已写、命令已跑），但 SessionEvent 序列里只有 `tool/call` 没有配对的 `tool/result`。当前 Phase 1 的 dangling 检测只能注入"结果未知"占位，模型被迫盲猜，可能导致重复执行已成功的副作用（文件写两遍、命令跑两次）或跳过本该完成的操作。

用户（开发者）需要一个能从崩溃中精确恢复的 Harness：知道每个 Tool 调用到底到了哪一步，据此合成正确的恢复结果，而不是盲猜或重复执行。

## Solution

引入 **Operation Ledger**（独立于 SessionEvent 的操作状态账本）+ **Checkpoint**（稳定边界快照）+ **RecoveryCoordinator**（恢复编排器），实现崩溃后的精确恢复：

- 每次 Tool 执行前，状态写入 Ledger（PENDING→RUNNING）；执行后写入终态（SUCCEEDED/FAILED/CANCELLED）。
- Ledger 先于 SessionEvent 写入（Ledger-first 顺序），保证 Ledger 永远比 SessionEvent 更完整。
- 崩溃后 resume 时，RecoveryCoordinator 读 Ledger 查每个未终止 Operation 的真实结局，按终态语义合成 Recovery ToolResult 注入 SessionEvent（而非注入"结果未知"占位）。
- UNKNOWN（崩溃时处于 RUNNING）的 Operation 不盲重跑，走 ReconcileCallback 交用户裁决。

## User Stories

### Storage 架构

1. As a developer, I want SessionEvent 保持 JSONL 存储不变, so that Phase 1 已稳定的崩溃安全写入不需要迁移
2. As a developer, I want Operation Ledger 和 Checkpoint 用 SQLite 存储, so that 操作状态查询有索引支持且事务语义清晰
3. As a developer, I want 三个 Store 接口分离（SessionStore / OperationLedger / CheckpointStore / SessionMetaStore）, so that 逻辑职责清晰且各自独立演化
4. As a developer, I want 三个 Store 物理上共享同一个 SQLite 文件, so that 文件管理简单且跨表查询方便
5. As a developer, I want Store 接口 ABC 化（SQLite 版今天实装，PostgreSQL 版留空）, so that 未来切换数据库只需替换实现
6. As a developer, I want Ledger 使用 aiosqlite 异步驱动, so that 不阻塞 event loop

### Operation Ledger

7. As a developer, I want 每次 Tool 执行在 execute() 入口写 PENDING, so that Ledger 记录"即将执行"
8. As a developer, I want 进入 retry_loop 前写 RUNNING, so that Ledger 记录"正在执行"
9. As a developer, I want retry_loop 结束后写 SUCCEEDED/FAILED/CANCELLED, so that Ledger 记录 operation 最终态
10. As a developer, I want Ledger 不记录 retry 中间的失败, so that Ledger 记录数 = operation 数（retry 走 Diagnostic Log）
11. As a developer, I want operation_id = tool_call_id（1:1）, so that batch 并行调用也能唯一定位每个 operation
12. As a developer, I want Ledger 表含 07 §4 冻结的最小字段集 + artifact_ref nullable 列, so that Phase 5 不需要 schema migration

### Checkpoint

13. As a developer, I want AgentRuntime 在 4 个稳定边界（USER_ACCEPTED / MODEL_COMPLETED / TOOL_BATCH_COMPLETED / FINAL_COMPLETED）写 Checkpoint, so that 系统知道安全恢复点
14. As a developer, I want Checkpoint 通过 CheckpointPolicy 薄 seam 注入, so that 测试可换 NoCheckpoint / EveryStep 策略
15. As a developer, I want checkpoint/saved 不进 SessionEvent, so that SessionEvent 只记对话事实不记存储动作

### Reconcile

16. As a developer, I want 崩溃后 resume 时 RecoveryCoordinator 读 Ledger 查未终止 Operation, so that 系统知道每个 Tool 到底到了哪一步
17. As a developer, I want SUCCEEDED + 缺 ToolResult 的 Operation 从 Ledger 合成 Recovery ToolResult（复用原始 tool_call_id）, so that derive_messages 能配对 dangling tool_call
18. As a developer, I want FAILED 的 Operation 合成失败 ToolResult, so that 模型看到失败可以自主决策
19. As a developer, I want CANCELLED 的 Operation 合成显式取消 ToolResult, so that 模型知道这个操作被取消了
20. As a developer, I want PENDING 的 Operation 按 PendingPolicy 处理（默认 skip 合成 skipped 结果）, so that 未启动的操作不被误重跑
21. As a developer, I want UNKNOWN 的 Operation 不盲重跑, so that 不违反不变量 #14（高风险 Tool 不盲重跑）
22. As a developer, I want UNKNOWN 的 Operation 走 ReconcileCallback 交用户裁决, so that 用户拿到 Tool 全上下文做出 informed decision
23. As a developer, I want ReconcileCallback 与 ApprovalCallback 平行（不共用）, so that 事前授权和事后裁决语义不混淆
24. As a developer, I want RecoveryCoordinator 进入 NEED_RECONCILE 时 append operation/reconcile-required SessionEvent, so that 模型在 resume 后能看到"上次有 operation 需要人工裁决"

### Tool 层扩展

25. As a developer, I want Tool ABC 新增 args_identity(args) 方法（默认全 args hash）, so that Ledger 的 args_hash 字段有统一来源
26. As a developer, I want Tool ABC 新增 reconcile_hint(args, ledger_state) 方法（默认 verifiable=False）, so that ReconcileCallback 拿到 Tool 提供的验证建议
27. As a developer, I want 可验证工具（read/write/edit/glob/grep/git_status/git_diff）覆写 reconcile_hint, so that 这些工具能提供"检查文件是否存在"等验证路径
28. As a developer, I want bash 不覆写 reconcile_hint（默认 verifiable=False）, so that UNKNOWN bash 一律交用户

### Resume 编排

29. As a developer, I want RecoveryCoordinator 按 07 §9 冻结的 8 步顺序编排恢复, so that 恢复流程确定性
30. As a developer, I want RecoveryCoordinator 注入 SessionStore + WorkspaceRegistry + OperationLedger + ReconcileCallback, so that 恢复所需组件全部可注入可测试
31. As a developer, I want RecoveryCoordinator 暴露 recover(session_id) -> Session 单一方法, so that AgentRuntime 只需调一行
32. As a developer, I want RecoveryCoordinator 自身失败时抛异常不写中间态, so that recovery 幂等可重试

### 并发与失败

33. As a developer, I want 两个进程同时 recover 同一 session 时用 pessimistic 锁保护, so that 不会产生双重恢复
34. As a developer, I want Serial 批次里任一工具永久失败时中止剩余工具（记 CANCELLED）, so that 不在失败的副作用上叠加新副作用
35. As a developer, I want Parallel 批次（全 READ_ONLY）单个失败不影响其他, so that 读操作天然独立
36. As a developer, I want 每个工具独立事务（N 个 operations = N 次 commit）, so that 与单 execute() 行为一致

### 运维

37. As a developer, I want session_meta 表有 archived 标记 + 可选 cleanup(session_id) 方法, so that 已完成 session 可手动清理（不自动执行）

## Implementation Decisions

### 存储架构

- **SessionEvent 保持 JSONL**：`JsonlSessionStore` 不迁移。Phase 1 已验证崩溃安全 + 135 测试覆盖。
- **Operation Ledger + Checkpoint + SessionMeta 用 SQLite**：共享同一 `.db` 文件，三张表。
- **驱动**：aiosqlite（异步）。Ledger 接口定义为 async。
- **三 Store ABC 化**：`OperationLedger`（ABC）→ `SqliteOperationLedger`（实现）；`CheckpointStore`（ABC）→ `SqliteCheckpointStore`；`SessionMetaStore`（ABC）→ `SqliteSessionMetaStore`。PostgreSQL 实现留空（Phase 4 只需 boundary）。

### SQLite Schema（三张表）

**`operations` 表**（Operation Ledger，按 07 §4 最小字段集）：
```
tool_call_id TEXT PRIMARY KEY,       -- = operation_id，1:1
session_id   TEXT NOT NULL,
run_id       TEXT,
agent_id     TEXT,
tool_name    TEXT NOT NULL,
args_identity TEXT NOT NULL,         -- Tool.args_identity() 输出
state        TEXT NOT NULL,          -- PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED/UNKNOWN/NEED_RECONCILE
result_json  TEXT,                    -- 终态时写入 ToolResult 的 JSON
artifact_ref TEXT,                    -- nullable，Phase 4 不写先留位
started_at   TEXT,
finished_at  TEXT,
reconcile_meta TEXT                   -- reconcile 裁决记录
```

**`checkpoints` 表**：
```
session_id     TEXT NOT NULL,
boundary_type  TEXT NOT NULL,         -- USER_ACCEPTED/MODEL_COMPLETED/TOOL_BATCH_COMPLETED/FINAL_COMPLETED
event_seq      INTEGER NOT NULL,      -- 对应的 SessionEvent 序号
payload_json   TEXT,
created_at     TEXT NOT NULL,
PRIMARY KEY (session_id, boundary_type, event_seq)
```

**`session_meta` 表**：
```
session_id          TEXT PRIMARY KEY,
created_at          TEXT NOT NULL,
agent_id            TEXT,
last_checkpoint_seq INTEGER,
archived            BOOLEAN DEFAULT 0
```

### Ledger-first 崩溃写顺序

```
execute() 入口 → Ledger.PENDING
进入 retry_loop → Ledger.RUNNING
tool.execute(args) + retry（不写 Ledger，走 Diagnostic Log）
retry_loop 结束 → Ledger.SUCCEEDED / FAILED / CANCELLED
→ append tool/call + tool/result SessionEvent
```

崩溃时 Ledger 比 SessionEvent 更完整 → reconcile 合成缺失的 ToolResult。

### Operation 状态机（07 §4 冻结）

```
PENDING → RUNNING → SUCCEEDED
                  → FAILED
                  → CANCELLED
崩溃时 RUNNING → UNKNOWN → NEED_RECONCILE
```

### Reconcile 流程（RecoveryCoordinator 第 5 步）

```
for op in ledger.list_unresolved(session_id):
    if op.state == SUCCEEDED:    → 合成 Recovery ToolResult（用 result_json）
    elif op.state == FAILED:     → 合成失败 ToolResult
    elif op.state == CANCELLED:  → 合成取消 ToolResult
    elif op.state == PENDING:    → PendingPolicy.skip（合成 skipped ToolResult）
    elif op.state in (UNKNOWN, NEED_RECONCILE):
        hint = tool.reconcile_hint(op.args, op.state)
        → 一律走 ReconcileCallback 交用户（即使 hint.verifiable=True）
        → append operation/reconcile-required SessionEvent
    所有合成结果复用原始 tool_call_id → session.append(tool/result event)
```

### CheckpointPolicy seam

```
class CheckpointPolicy(ABC):
    def maybe_save(self, session, boundary_type): ...

class OnStableBoundary(CheckpointPolicy):  # 默认
    # 只在 4 个稳定边界写 CheckpointStore

class NoCheckpoint(CheckpointPolicy):      # 测试用
class EveryStep(CheckpointPolicy):         # 测试用
```

AgentRuntime 在每个边界调 `self._checkpoint_policy.maybe_save(session, boundary_type)`。

### ReconcileCallback

```
class ReconcileCallback(ABC):
    def __call__(self, operation: Operation, hint: ReconcileHint) -> ReconcileVerdict: ...
    # ReconcileVerdict: CONFIRM_SUCCESS / CONFIRM_FAILURE / RETRY / ABANDON

class ReconcileHint:
    verifiable: bool
    hint: str
    # Tool ABC 默认 verifiable=False
```

与 Phase 3 ApprovalCallback 平行——事前授权 vs 事后裁决。默认 None → 拒绝（安全默认，与 Approval 相同姿态）。

### RecoveryCoordinator

```
class RecoveryCoordinator:
    def __init__(self, session_store, workspace_registry, operation_ledger,
                 reconcile_callback=None, pending_policy=None, checkpoint_policy=None): ...

    async def recover(self, session_id: str) -> Session:
        # 07 §9 冻结 8 步：
        # 1. load SessionEvent → Session
        # 2. load Session-Sandbox mapping → WorkspaceRegistry.get()
        # 3. ensure Sandbox started
        # 4. load Operation Ledger → list unresolved
        # 5. reconcile unresolved ops（上面的流程）
        # 6. restore tool result / message consistency → session.append 合成 events
        # 7. rebuild Runtime Context
        # 8. return Session，交给 AgentRuntime 继续
        # 自身失败 → 抛异常，不写中间态（幂等重试）
        # 并发 → BEGIN EXCLUSIVE 锁 session_meta 行
```

### Tool 层扩展

```
class Tool(ABC):
    # 现有属性省略
    def args_identity(self, args: dict) -> str:
        """默认：json.dumps(args, sort_keys=True)。Tool 按需覆写。"""
        return json.dumps(args, sort_keys=True, ensure_ascii=False)

    def reconcile_hint(self, args: dict, ledger_state: str) -> ReconcileHint:
        """默认：ReconcileHint(verifiable=False)。可验证工具覆写。"""
        return ReconcileHint(verifiable=False, hint="无法自动验证")
```

### execute_batch 失败级联

- Serial 批次（含 MUTATING）里任一工具永久失败（retry 耗尽，Ledger FAILED）→ 中止剩余，记 CANCELLED。
- Parallel 批次（全 READ_ONLY）→ 单个失败不影响其他。

### 新增 SessionEvent 类型

- `operation/reconcile-required`：RecoveryCoordinator 进 NEED_RECONCILE 时 append。
- `checkpoint/saved`：不进 SessionEvent。
- `artifact/created`：Phase 5。

## Testing Decisions

### 测试 seam

**主 seam**：`RecoveryCoordinator.recover(session_id) -> Session`——用户视角的"崩溃后能恢复吗"单一入口。
**辅助 seam**：`ToolExecutor.execute()` Ledger 接线（单元测试 mock ledger 验证写顺序）。

### 分层测试

**底层单元测试**（`tests/tooling/test_ledger_wiring.py`）：
- mock ledger，验证 execute() 在正确位置调 PENDING / RUNNING / SUCCEEDED / FAILED。
- 验证 retry 中间失败不写 Ledger。
- 验证 batch 并行/串行下每个 tool 都有自己的 operation 记录。

**Store 单元测试**（`tests/storage/test_sqlite_ledger.py` 等）：
- CRUD 验证：insert pending → update running → update succeeded → query unresolved。
- 并发：两个连接同时写同一 operation → pessimistic 锁生效。
- schema：三张表字段完整、artifact_ref nullable。

**Tool 扩展测试**：
- `args_identity()` 默认 vs 覆写。
- `reconcile_hint()` 默认 vs 可验证工具覆写。

**顶层 kill-test 集成测试**（`tests/recovery/test_kill_scenarios.py`，`@pytest.mark.integration`）：
每个场景一个独立测试（非参数化），用 kill_hook + 子进程 resume，覆盖 5 个 Gate 场景：

1. **`test_tool_success_crash_before_result_event`**：Tool 执行成功 → Ledger SUCCEEDED → kill_hook 在 append SessionEvent 前 `os._exit(1)` → 新进程 RecoveryCoordinator.recover() → 验证 Recovery ToolResult 合成正确、dangling=0、duplicate side effect=0。
2. **`test_unknown_bash_not_blind_rerun`**：bash 执行中 → Ledger RUNNING → kill → resume → Ledger 显示 UNKNOWN → 验证不自动重跑、走 ReconcileCallback。
3. **`test_dangling_tool_call_zero_after_reconcile`**：多 Tool 部分完成 → kill → resume → 验证 derive_messages 后 dangling=0。
4. **`test_duplicate_side_effect_zero`**：write 成功 → kill → resume → 验证文件只写了一遍（不重复执行 SUCCEEDED operation）。
5. **`test_pending_operation_skipped`**：Ledger PENDING → kill → resume → 验证合成 skipped ToolResult、不重跑。

### Prior art

- Phase 1 `test_resume_session.py`：已有的 resume 集成测试模式（进程重启 + JSONL 恢复）。
- Phase 2 `test_coding_tools.py`：batch 调度 + side_effect 分流测试。
- Phase 3 `test_approval_gate.py`：callback 注入测试模式（可复用于 ReconcileCallback）。

## Out of Scope

- **PostgreSQL 实装**：只定义 ABC boundary，不实现 PostgresLedger / PostgresCheckpointStore。
- **Artifact Store / MinIO**：Phase 5。Phase 4 只在 `operations` 表留 `artifact_ref` nullable 列。
- **Ledger 自动 TTL / retention**：只加 `session_meta.archived` 标记 + `cleanup(session_id)` 方法，不自动执行。
- **Checkpoint 内容压缩 / 增量**：Phase 4 的 checkpoint 只存 event_seq + payload_json，不做增量快照。
- **Vector Store**：不在 Phase 4。
- **SessionEvent 迁移到 SQLite**：保持 JSONL。
- `artifact/created` SessionEvent 类型：Phase 5。

## Further Notes

### 规格冻结 vs 本 spec 新决策

**规格已冻结（07_STORAGE_PERSISTENCE_RECOVERY.md 等）**：Ledger 状态机、reconcile 终态语义、恢复 8 步顺序、4 个 Checkpoint 边界、不变量 #12-14。本 spec 不重新审视这些。

**本 spec 新决策**：存储架构（JSONL + SQLite 分层）、三 Store ABC、Ledger-first 写顺序、CheckpointPolicy seam、ReconcileCallback 独立、aiosqlite、operation_id=tool_call_id、PendingPolicy skip、串行批次失败级联、pessimistic 锁等。详见 ADR-0004。

### 与 Phase 3 的衔接

- Phase 3 的 `WorkspaceRegistry` 已实现恢复顺序第 2-3 步（load mapping → ensure sandbox）。
- Phase 3 的 `ApprovalCallback` 与本 spec 的 `ReconcileCallback` 平行但不共用。
- Phase 3 的 `ToolExecutor.execute()` 是 Ledger 接线的注入点。

### 与 Phase 1 的衔接

- Phase 1 的 dangling 检测（合成"结果未知"ToolMessage）在 Phase 4 被 Ledger 驱动的 reconcile 升级替代——RecoveryCoordinator 合成的是有数据的 Recovery ToolResult，不是"结果未知"占位。
- Phase 1 的 `SessionEvent` 类型需新增 `operation/reconcile-required`。

### 依赖

- 新增依赖：`aiosqlite`（PyPI）。
- stdlib：`sqlite3`（aiosqlite 底层用）。

### ADR 引用

- ADR-0004：Storage 分层 — SessionEvent 留 JSONL，Ledger/Checkpoint 用 SQLite（本 spec 的架构决策来源）。
- ADR-0001：Sandbox 路径边界（Phase 4 不改）。
- ADR-0002：bash 非零 exit_code = Tool success（Phase 4 不改）。
- ADR-0003：SessionEvent append-only 事件日志（Phase 4 在其上加新 event 类型）。

