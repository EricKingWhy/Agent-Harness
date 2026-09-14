# #37 — feat(web): 交互式审批走通（pending approval queue，blocked：WebSocket seam，ADR-0005 Q14 defer）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T19:56:31Z
- **Closed**: —
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/37

---

## Context
ApprovalCard 组件已写（warning 玻璃 + 批准/拒绝 + POST /approve），V1 后端 auto-approve 走不到。真正交互式审批需要 pending approval queue + 服务端推送（WebSocket seam，见 src/agent_harness/web/app.py 中间件空壳与 approve endpoint 的 202 seam）。

**Blocking：** 后端审批事件流 + POST /approve 实际生效（backend 领域，ADR-0005 Q14）。

## Acceptance criteria
- [ ] 后端 pending queue + 推送
- [ ] ApprovalCard 接真实 pending 事件（frontend 消费真值，不造本地队列）
- [ ] 批准/拒绝回传后工具继续/终止的 E2E
