# #33 — Phase 4 Ticket G: UNKNOWN bash reconciliation and Phase gate

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T16:06:57Z
- **Closed**: 2026-09-03T19:49:46Z
- **Parent**: #26
- **Blocked by**: #30, #32
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/33

---

## Parent

#26 — Phase 4 Spec: Storage + Operation Ledger + Recovery

## What to build

以真实 RUNNING bash 崩溃场景验证 UNKNOWN Operation 不会盲重跑，完成人工 reconcile 后收口 Phase 4 的全部恢复 Gate 和回归验证。

## Acceptance criteria

- [ ] bash 处于 RUNNING 时真实 Kill，恢复后状态为 UNKNOWN / NEED_RECONCILE。
- [ ] 没有 ReconcileCallback 时 bash 不执行；有 callback 时仅按显式 verdict 继续。
- [ ] operation/reconcile-required 事件可从持久 SessionEvent 中观察。
- [ ] 并发 recover 不产生重复 Recovery ToolResult 或重复副作用。
- [ ] Phase 4 五个独立 Kill 场景全部通过。
- [ ] 最终 Gate：duplicate confirmed side effect = 0、dangling tool call = 0、Workspace 恢复正确。
- [ ] 全量 pytest 与 Ruff 通过，并记录 Phase 4 Gate 证据；只有全部通过后才能更新 PHASE_STATUS。

## Blocked by

- #30 — Ticket D
- #32 — Ticket F
