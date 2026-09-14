# #22 — Ticket B: ApprovalRequest/Response + ToolExecutor approval gate + per-call 审批

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:43:23Z
- **Closed**: 2026-09-03T14:20:18Z
- **Parent**: #19
- **Blocked by**: #21
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/22

---

## Parent

#19 — Phase 3 Spec: Approval / REQUIRE_APPROVAL 机制

## What to build

在 ToolExecutor 的验证链中插入 Approval 关卡（validate → approval gate → execute）。新增 ApprovalRequest / ApprovalResponse 数据类和 ApprovalCallback 类型。ToolExecutor 构造接受 policy 和 approval_callback（有安全默认值）。审批只对当次 Tool Call 生效，不持久化状态。无 callback 时 DANGER 级别默认拒绝。

## Acceptance criteria

- [ ] ApprovalRequest（tool_name, args, permission, policy, reason）和 ApprovalResponse（approved, reason）定义。
- [ ] ApprovalCallback 类型别名定义。
- [ ] ToolExecutor.__init__ 新增可选参数 `policy: PermissionPolicy = WORKSPACE_WRITE`、`approval_callback: ApprovalCallback | None = None`。
- [ ] approval gate 逻辑（在 validate 后 execute 前）：
  - DANGER_FULL_ACCESS → 放行。
  - tool.permission 级别 <= policy 级别 → 放行。
  - 超级别或 DANGER 在 WORKSPACE_WRITE 下 → 需要 approval：无 callback → PERMISSION_DENIED；有 callback → 调 callback，approved 放行 / denied → PERMISSION_DENIED。
  - 批准只影响当次 execute（每次 execute 独立检查）。
- [ ] 测试（`tests/tooling/test_approval_gate.py`）：
  - DANGER_FULL_ACCESS → bash 放行。
  - WORKSPACE_WRITE + bash + 无 callback → PERMISSION_DENIED。
  - WORKSPACE_WRITE + bash + auto-approve → 成功。
  - WORKSPACE_WRITE + bash + auto-deny → PERMISSION_DENIED。
  - READ_ONLY + write → PERMISSION_DENIED。
  - READ_ONLY + read → 放行。
  - WORKSPACE_WRITE + read/write → 放行。
  - per-call scoping：连续两次 bash + auto-approve → callback 被调两次，两次都成功。
  - ApprovalRequest 包含正确的 tool_name/args/permission/policy/reason。
- [ ] 现有测试回归：ToolExecutor 默认 policy=WORKSPACE_WRITE 时，现有测试中 bash 的使用需调整为提供 auto-approve callback 或 DANGER_FULL_ACCESS policy（否则 bash 被拒）。**注意**：这可能需要更新现有测试的 ToolExecutor 构造——评估影响并最小化改动。

## Blocked by

- #21（Ticket A：PermissionPolicy + ToolPermission 必须先定义）

