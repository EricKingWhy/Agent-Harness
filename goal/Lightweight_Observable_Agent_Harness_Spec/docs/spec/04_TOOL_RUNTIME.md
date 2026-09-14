# 04 — Tool Runtime

## 1. 目标

所有 Tool 共用一个统一 Runtime：

```text
LLM Tool Call
→ Tool Contract
→ ToolRegistry
→ Pydantic Validation
→ Permission/Risk Policy
→ Dependency-aware Scheduler
→ ToolExecutor
→ Timeout / Error Classification / Retry
→ Operation Ledger
→ ToolResult
→ SessionEvent
→ ToolMessage
```

Local / Knowledge / MCP / Web / SubAgent Tool 均不得绕过。

## 2. Tool Contract

至少包含：

```text
name
description
args_schema
timeout_seconds
side_effect
risk_level
resource_keys?
execute()
```

建议额外支持：
- `idempotency_mode`
- `supports_reconcile`
- `dependency_metadata`
- `result_policy`

模型侧 Tool Definition 与 Runtime Tool MUST 来自同一 Contract，避免名称和 Schema 漂移。

## 3. ToolRegistry

只负责：
- register
- get
- list
- export model definitions

重复 Tool Name MUST 早失败。

Registry MUST NOT 负责：
- retry
- timeout
- session
- LLM routing
- 真正执行

## 4. ToolResult

统一结构：

```text
ok
message
data
error_code
retryable
metadata
artifact_ref?
operation_id?
```

建议 ErrorCode 至少：
- INVALID_ARGUMENT
- TIMEOUT
- TRANSIENT_ERROR
- PERMISSION_DENIED
- NOT_FOUND
- AMBIGUOUS
- EXECUTION_ERROR
- CANCELLED
- REPEATED_TOOL_CALL
- NEED_RECONCILE
- UNKNOWN

## 5. Validation

```text
raw model args
→ args_schema.model_validate()
→ valid: execute
→ invalid: INVALID_ARGUMENT ToolResult
→ model receives result
→ model may self-correct
```

Executor MUST NOT 偷偷替模型猜测/修复参数。

## 6. Retry

只有 ToolExecutor 能进行 Tool 执行域 Retry。

默认可重试：
- TIMEOUT（视 Tool 语义）
- TRANSIENT_ERROR
- 临时服务不可用

默认不重试：
- INVALID_ARGUMENT
- PERMISSION_DENIED
- NOT_FOUND
- AMBIGUOUS
- 确定性业务失败

底层 SDK 自动 retry SHOULD 关闭或明确纳入总预算，避免 Retry Amplification。

## 7. Dependency-aware Scheduler

冻结新规则：

> 是否并行由**显式数据依赖 + 资源冲突 + side effect**决定，而不是仅按 READ_ONLY/MUTATING 二分。

并行条件：
- 无 `depends_on`；
- 无资源冲突；
- 权限允许；
- Tool Contract 声明允许并行。

例如：
- `read(a.py)` 与 `read(b.py)`：可并行；
- `edit(a.py)` 与 `edit(b.py)`：若资源隔离明确，也可并行；
- `edit(a.py) → pytest`：必须串行；
- B 的参数依赖 A 输出：必须串行。

### V1 限制

V1 MUST NOT 让 Runtime 靠 LLM 自由文本“猜”依赖。

依赖来源：
- `depends_on: [tool_call_id]`
- `resource_keys`
- Tool metadata
- 同文件 / 同 workspace 资源冲突

Scheduler 可构建轻量 DAG，拓扑批次执行。

## 8. Permission / Risk

建议风险等级：
- READ_ONLY
- WORKSPACE_WRITE
- NETWORK
- DESTRUCTIVE
- PRIVILEGED

Policy 结果：
- ALLOW
- DENY
- REQUIRE_APPROVAL

Approval 应是单次 Tool Call 授权，不默认永久升级 Session 权限。

## 9. Operation Ledger

对于可能产生真实外部副作用的 Tool：

- Tool Call 开始前写 `PENDING/RUNNING`；
- 完成后写 `SUCCEEDED/FAILED/CANCELLED`；
- crash 后 RUNNING 进入 UNKNOWN/NEED_RECONCILE。

READ_ONLY Tool 可采用更轻的 ledger policy，但必须保持可追踪性。

## 10. Bash 特殊语义

`bash` Tool Runtime 成功 != 命令业务成功。

例如 `pytest` 返回 exit code 1：
- Tool 调用本身成功；
- `exit_code=1` 是业务结果；
- Agent 根据 stdout/stderr 决定下一步；
- Executor 不得当成 transient network failure 自动 retry。

## 11. Acceptance Criteria

- 重复 Tool Name 失败；
- 参数错误不重试；
- timeout/transient 按策略重试；
- deterministic error 不重试；
- `tool_call_id` 与 result 正确配对；
- 无依赖 Tool 可并行；
- 有依赖 Tool 严格按 DAG 执行；
- 冲突写操作不并发；
- Approval 可阻断并恢复；
- MCP/Knowledge/Coding Tool 均走同一 Executor。
