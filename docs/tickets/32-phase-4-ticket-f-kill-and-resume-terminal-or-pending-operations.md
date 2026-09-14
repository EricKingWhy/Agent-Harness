# #32 — Phase 4 Ticket F: Kill and resume terminal or PENDING Operations

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T16:06:54Z
- **Closed**: 2026-09-03T19:50:02Z
- **Parent**: #26
- **Blocked by**: #29, #31
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/32

---

## Parent

#26 — Phase 4 Spec: Storage + Operation Ledger + Recovery

## What to build

使用真实子进程和可注入 kill hook 验证已知终态及 PENDING Operation 的崩溃恢复。新进程恢复后必须保留 Workspace、补齐消息链，并保证已确认的副作用不会执行第二次。

## Acceptance criteria

- [ ] ToolExecutor 提供仅用于精确故障注入的可选 kill_hook，生产默认行为不变。
- [ ] Tool 成功、Ledger 已写终态、tool/call 已持久化但 result event 未写时可被真实 Kill。
- [ ] 新进程 recover 后生成正确 Recovery ToolResult，dangling tool call 为零。
- [ ] write 等已成功副作用在恢复中不重复，duplicate side effect 为零。
- [ ] PENDING Operation 在恢复中默认 skip，不调用真实 Tool。
- [ ] 多 Tool 部分完成后崩溃仍能恢复所有已知 Operation，并保持结果配对。
- [ ] Session Workspace 在新进程中恢复到原映射。
- [ ] 每个 Kill 场景为独立 integration test，且有超时保护避免测试挂死。

## Blocked by

- #29 — Ticket C
- #31 — Ticket E
