# #31 — Phase 4 Ticket E: Safe failure cascading for Tool batches

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T16:06:51Z
- **Closed**: 2026-09-03T16:54:05Z
- **Parent**: #26
- **Blocked by**: #27
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/31

---

## Parent

#26 — Phase 4 Spec: Storage + Operation Ledger + Recovery

## What to build

为 Tool 批次提供安全失败级联：含写操作的串行批次在一个调用永久失败后停止执行剩余调用并将其明确取消；全 READ_ONLY 并行批次继续独立完成，不让单个失败扩散。

## Acceptance criteria

- [ ] 串行批次中首个永久失败终止后续真实执行。
- [ ] 未执行的后续调用在 Ledger 中记录为 CANCELLED，并返回配对的取消 ToolResult。
- [ ] 全 READ_ONLY 并行批次的单个失败不取消或阻止其他调用。
- [ ] 每个调用使用独立 Operation 和独立事务，结果顺序保持与输入一致。
- [ ] INVALID_ARGUMENT、PERMISSION_DENIED 等执行前失败的 Ledger 语义明确且不会产生外部副作用。
- [ ] retry 仍只有 ToolExecutor 一层，批次调度器不增加第二套 retry。
- [ ] 串行级联、并行隔离、Ledger 状态和 ToolResult 配对有测试。

## Blocked by

- #27 — Ticket A
