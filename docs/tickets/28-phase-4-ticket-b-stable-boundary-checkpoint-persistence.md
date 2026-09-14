# #28 — Phase 4 Ticket B: Stable-boundary Checkpoint persistence

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T16:06:42Z
- **Closed**: 2026-09-03T19:50:17Z
- **Parent**: #26
- **Blocked by**: #27
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/28

---

## Parent

#26 — Phase 4 Spec: Storage + Operation Ledger + Recovery

## What to build

让 AgentRuntime 在四个稳定边界保存可恢复 Checkpoint，并通过可替换策略控制保存行为。Checkpoint 是恢复辅助数据，不进入 SessionEvent；Session metadata 与 Operation Ledger 共用同一 SQLite 文件但保持独立 Store contract。

## Acceptance criteria

- [ ] 定义 CheckpointStore 和 SessionMetaStore ABC，并提供各自的 SQLite 默认实现。
- [ ] checkpoints 与 session_meta schema 符合 Issue #26，三类 SQLite Store 可共享同一数据库文件。
- [ ] 实现 CheckpointPolicy、OnStableBoundary、NoCheckpoint、EveryStep。
- [ ] AgentRuntime 在 USER_ACCEPTED、MODEL_COMPLETED、TOOL_BATCH_COMPLETED、FINAL_COMPLETED 四个边界调用 policy。
- [ ] checkpoint/saved 不写入 SessionEvent。
- [ ] Session metadata 支持 archived 标记和显式 cleanup；不实现自动 TTL。
- [ ] PostgreSQL 只由 ABC 形成替换边界，不提供实现。
- [ ] 四个边界、策略替换、schema 和 cleanup 均有测试；现有测试保持通过。

## Blocked by

- #27 — Ticket A
