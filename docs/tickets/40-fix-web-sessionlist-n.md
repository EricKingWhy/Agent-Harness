# #40 — fix(web): SessionList 相对时间（'N 分钟前'）不随时间流逝刷新

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T19:57:09Z
- **Closed**: 2026-09-04T06:46:00Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/40

---

## Context
SessionList 的相对时间在渲染时计算，组件不重渲染就一直显示旧值（挂载 10 分钟后仍显示挂载时的'2 分钟前'）。轻微 UX，不阻塞。

## Acceptance criteria
- [ ] 方案 A（推荐）：1 分钟一次的轻量 tick 触发重渲染，仅 SessionList 可见时
- [ ] 方案 B：接受现状（选中/刷新即更新）
