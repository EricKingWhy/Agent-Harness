# 07 — Storage / Persistence / Recovery

## 1. Storage 不是一个数据库

逻辑分层：

```text
Session/Event Persistence
Metadata Store
Operation Ledger
Artifact/Object Store
Vector Store
```

默认实现：

```text
Session/Metadata/Operation:
  SQLite (local default)
  PostgreSQL (production adapter)

Artifact:
  Local
  MinIO

Vector:
  Milvus default
  future providers
```

## 2. Session / Run / Checkpoint / Operation

必须区分：

- Session：长期容器；
- Run：一次 user request 的 Agent 执行；
- Checkpoint：已经持久化成功、可以恢复的稳定状态事实；
- Operation：真实外部操作执行到了哪里。

## 3. Checkpoint

建议稳定边界：

```text
USER_ACCEPTED
MODEL_COMPLETED
TOOL_BATCH_COMPLETED
FINAL_COMPLETED
```

Checkpoint 代表“可恢复事实”，不是“代码执行到某一行”。

同一稳定边界的 Message/Event + Checkpoint SHOULD 尽可能事务化提交。

## 4. Operation Ledger

状态建议：

```text
PENDING
→ RUNNING
→ SUCCEEDED / FAILED / CANCELLED

crash:
RUNNING → UNKNOWN / NEED_RECONCILE
```

字段至少：
- operation_id
- session_id
- run_id
- agent_id
- tool_call_id
- tool_name
- args_hash / critical args
- state
- result_json/ref
- started_at
- finished_at
- reconcile metadata

## 5. 为什么 Checkpoint 不够

场景：

```text
bash("migration")
→ external world actually changed
→ process crash
→ ToolResult not appended
```

若只根据旧 Checkpoint 重跑，可能发生重复迁移、重复部署、重复删除、重复支付等。

因此恢复 MUST 查 Operation Ledger。

## 6. Reconcile

### SUCCEEDED + ToolResult 缺失
从 `result_json/artifact_ref` 生成 Recovery ToolResult，使用原 `tool_call_id`。

### FAILED
补失败结果，让 Agent 继续。

### CANCELLED
补明确 CANCELLED。

### PENDING
证明 Tool 尚未真正启动，可按策略重执行。

### RUNNING / UNKNOWN
进入 Tool-specific reconcile。

## 7. Tool-specific Recovery

### read / retrieve_knowledge
通常可安全重读，但仍遵守成本和一致性策略。

### write / edit
检查目标状态是否已经达到预期：
- 已达到 → 标记成功并补结果；
- 未达到且确认未执行 → 可重试；
- 不确定 → NEED_RECONCILE。

### bash
默认最保守。
`pytest`、`pip install`、`curl POST`、`migration` 的副作用完全不同，不允许统一假装可安全重跑。

UNKNOWN bash：
- 能验证实际状态 → reconcile；
- 无法验证 → 交用户处理。

## 8. Message/Event Consistency

恢复后检查：

```text
tool/call(tool_call_id)
↔ tool/result(tool_call_id)
```

不能留下 dangling call。

## 9. Resume 顺序

```text
load SessionEvent / optional Graph checkpoint
→ load Session-Sandbox mapping
→ ensure Sandbox started
→ load Operation Ledger
→ reconcile unresolved operations
→ restore tool result/message consistency
→ rebuild Runtime Context
→ resume Agent/Graph
```

## 10. Acceptance Criteria

必须有真实 Kill 测试：

- Tool 尚未开始时 Kill；
- Tool 已成功但结果未写时 Kill；
- Tool RUNNING 状态 Kill；
- Artifact 已存但 message 未写时 Kill；
- Multi-Agent Coding Tool 执行中 Kill。

Gate：
- 已确认副作用不重复；
- UNKNOWN 进入人工 reconcile；
- dangling tool call=0；
- Session Workspace 正确恢复；
- Recovery 过程有完整事件和日志。
