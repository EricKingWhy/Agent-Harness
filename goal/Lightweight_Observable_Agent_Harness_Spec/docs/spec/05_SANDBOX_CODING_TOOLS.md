# 05 — Sandbox + Coding Tools

## 1. 核心原则

Sandbox 是 Runtime 安全边界，不是 Prompt。

错误：

```text
System Prompt: 不要访问用户其他目录
```

正确：

```text
Tool
→ Sandbox Capability
→ Container
→ Session Workspace
```

## 2. Session-scoped Sandbox

默认模型：

```text
Session
→ SandboxSession
→ container_id + volume/workspace
```

生命周期：

```text
new session
→ create/import workspace

exit
→ stop container allowed
→ keep persistent volume/workspace

resume
→ restore mapping
→ ensure container running

delete
→ explicit cleanup
```

同一 Session 的 Main / Coding / Research（如需要读取）可以看到同一个 workspace，但 Tool Permission 不同。

## 3. Workspace Import

默认禁止把 Host 真实项目目录直接高权限 bind mount 给 Agent。

推荐：

```text
Host Project
→ explicit import/copy
→ persistent Docker volume
→ /workspace
```

未来可增加受控 bind-mount Provider，但不是默认。

## 4. Sandbox Contract

保持薄：

```text
ensure_started()
exec()
read_text()
write_text()
copy_in()
stat()
stop()
```

Tool 业务语义不要写进 Sandbox。

## 5. 默认 Coding Tools

V1：

- `read`
- `write`
- `edit`
- `bash`
- `grep`
- `glob`
- `apply_patch`
- `git_status`
- `git_diff`

### read
READ_ONLY。

### write
WORKSPACE_WRITE，明确覆盖语义。

### edit
保留：

```text
exact old_string → new_string
```

- 0 match → NOT_FOUND
- 1 match → success
- >1 match → AMBIGUOUS

### apply_patch
复杂多处修改优先使用，仍需 path/workspace guard。

### bash
默认按高风险 MUTATING/NETWORK 可配置处理，返回：

```text
exit_code
stdout
stderr
duration
```

### git
V1 仅 `status/diff` 等只读能力。
MUST NOT 自动 commit/push/reset --hard。

## 6. Permission Policy

建议参考 DeepSeek Harness 的分层思想：

- `read-only`
- `workspace-write`
- `danger-full-access`（默认不授予）

高风险操作：
- 可 `REQUIRE_APPROVAL`；
- Approval 只针对本次 Tool Call；
- 不因一次批准永久放开后续命令。

## 7. 并发与写冲突

同一 Session Workspace：
- 无依赖、无资源冲突的 Tool 可并行；
- 同一文件写入、同一构建目录副作用、依赖链必须串行；
- 多写 Agent 并发时至少使用 session-level write lease/lock；
- V1 不做多 worktree 并行 Coding Team。

## 8. Recovery

恢复顺序必须先恢复 Sandbox，再继续 Agent：

```text
load Session/Workflow state
→ load sandbox mapping
→ ensure sandbox started
→ reconcile operations
→ restore message/event consistency
→ resume
```

不能先让 Agent 执行，再发现 workspace 消失。

## 9. Acceptance Criteria

- Agent 无法越过 `/workspace` 读取 Host 敏感路径；
- Session restart 后 workspace 仍存在；
- edit 多匹配明确失败；
- pytest exit_code=1 不被 Tool retry；
- dangerous bash 可触发 approval；
- 两个无冲突文件操作可以并发；
- 冲突写操作被串行化；
- Kill/Resume 后已经完成的写操作不会盲目重复。
