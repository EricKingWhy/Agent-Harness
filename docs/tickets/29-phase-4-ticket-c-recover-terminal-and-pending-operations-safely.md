# #29 — Phase 4 Ticket C: Recover terminal and PENDING Operations safely

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T16:06:45Z
- **Closed**: 2026-09-03T19:50:12Z
- **Parent**: #26
- **Blocked by**: #27, #28
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/29

---

## Parent

#26 — Phase 4 Spec: Storage + Operation Ledger + Recovery

## What to build

提供 RecoveryCoordinator.recover(session_id) 单一入口，按冻结的恢复顺序找回 Session、Workspace 和 Ledger 状态。已知终态及 PENDING Operation 必须生成与原 tool_call_id 配对的 Recovery ToolResult，且不能重新执行已确认副作用。

## Acceptance criteria

- [ ] RecoveryCoordinator 按 Issue #26 的 8 步顺序恢复 Session 和 Sandbox。
- [ ] SUCCEEDED、FAILED、CANCELLED 且缺少结果事件的 Operation 分别合成准确 ToolResult。
- [ ] PENDING 由可注入 PendingPolicy 处理，默认 skip 并合成 skipped ToolResult，不自动执行。
- [ ] 所有恢复结果复用原 tool_call_id；恢复后消息投影不存在已处理的 dangling call。
- [ ] Runtime Context 从恢复后的持久 SessionEvent 重新派生。
- [ ] 同一 session 的并发恢复由 SQLite pessimistic transaction 串行化；实现不得声称 SQLite 提供行级锁。
- [ ] 恢复决策先完成再写结果；协调器失败抛出异常且不记录虚假的恢复完成状态，再次调用可安全重试。
- [ ] 终态、PENDING、Workspace 恢复、并发和幂等行为有测试。

## Blocked by

- #27 — Ticket A
- #28 — Ticket B
