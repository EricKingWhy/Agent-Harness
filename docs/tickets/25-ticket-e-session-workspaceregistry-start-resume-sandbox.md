# #25 — Ticket E: Session 集成 WorkspaceRegistry（start/resume 绑定 sandbox）+ 测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:45:03Z
- **Closed**: 2026-09-03T14:20:29Z
- **Parent**: #20
- **Blocked by**: #23
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/25

---

## Parent

#20 — Phase 3 Spec: Session-scoped Sandbox 生命周期

## What to build

把 WorkspaceRegistry 接入 Session 生命周期。Session.start 和 Session.resume 新增可选参数 workspace_registry：提供时自动 create/get Sandbox 并绑定到 session.sandbox 属性；不提供时行为不变（向后兼容）。这让 Agent Runtime 能通过 Session 访问绑定的 Sandbox，实现 Session-scoped 的 workspace 管理。

## Acceptance criteria

- [ ] Session.start() 新增可选参数 `workspace_registry: WorkspaceRegistry | None = None`。提供时调 registry.create(session_id) 绑定 sandbox。
- [ ] Session.resume() 新增同名可选参数。提供时调 registry.get(session_id) 恢复 sandbox。
- [ ] Session 新增只读属性 `sandbox: Sandbox | None`（不传 registry 时为 None）。
- [ ] 不传 registry 时 Session 行为完全不变（向后兼容，现有测试全绿）。
- [ ] 测试（`tests/session/test_session_workspace.py`）：
  - Session.start(registry) → session.sandbox 不是 None，workspace_root 存在。
  - Session.resume(registry) → session.sandbox 恢复，workspace 文件还在。
  - 不传 registry → session.sandbox 是 None。
  - Session.start(registry) → write 文件 → Session.resume(registry) → sandbox.read_text 读到文件。
- [ ] 所有现有测试仍通过。

## Blocked by

- #23（Ticket C：WorkspaceRegistry 必须先落地）

