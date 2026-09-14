# #30 — Phase 4 Ticket D: Human reconciliation for UNKNOWN Operations

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T16:06:48Z
- **Closed**: 2026-09-03T19:50:07Z
- **Parent**: #26
- **Blocked by**: #29
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/30

---

## Parent

#26 — Phase 4 Spec: Storage + Operation Ledger + Recovery

## What to build

让崩溃时处于 RUNNING 的 Operation 进入 UNKNOWN / NEED_RECONCILE，并通过独立 ReconcileCallback 由用户裁决。即使 Tool 提供可验证建议，也不得自动验证或盲目重跑高风险副作用。

## Acceptance criteria

- [ ] 定义 ReconcileHint、ReconcileVerdict 和独立的 ReconcileCallback contract。
- [ ] Tool 默认 reconcile_hint 为 unverifiable；read/write/edit/glob/grep/git_status/git_diff 提供 verifiable 建议；bash 保持默认。
- [ ] RUNNING 崩溃状态进入 UNKNOWN，再进入 NEED_RECONCILE。
- [ ] UNKNOWN 与 NEED_RECONCILE 始终调用 ReconcileCallback；没有 callback 时安全拒绝。
- [ ] 支持 CONFIRM_SUCCESS、CONFIRM_FAILURE、RETRY、ABANDON 四种显式裁决，RETRY 只能来自用户裁决。
- [ ] 进入 NEED_RECONCILE 时追加 operation/reconcile-required SessionEvent；checkpoint/saved 仍不进入事件流。
- [ ] UNKNOWN bash 永不自动重跑。
- [ ] 默认安全行为、各 Tool hint、四种 verdict、状态和事件均有测试。

## Blocked by

- #29 — Ticket C
