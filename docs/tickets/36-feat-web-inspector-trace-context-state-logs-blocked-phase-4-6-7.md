# #36 — feat(web): Inspector Trace/Context/State/Logs 面板（blocked：后端数据源，Phase 4/6/7）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T19:56:29Z
- **Closed**: 2026-09-04T08:47:48Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/36

---

## Context
spec 11 §5 Inspector 右栏规划了 Overview / Trace / Context / Tools / State / Logs。当前 V1 只实现 Overview（label+value）+ Tools 列表 + Checkpoint/Artifact 空槽。Trace/Context/State/Logs 需要 runtime 数据（context token 统计、state 快照、结构化日志 API），数据面不存在。

**Blocking：** 后端 Phase 4/6/7 数据面（artifact/context/checkpoint/operation ledger 查询 API）。前端严禁为它造第二套真相（不变量 #22）。

## Acceptance criteria
- [ ] 后端提供对应只读查询 API（Backend 会话领域）
- [ ] 前端按 MASTER.md 克制风渲染（Apple Settings 式 label+value / 克制的 usage bar / JSONL viewer）
- [ ] 不引入状态库（ADR-0005 冻结）
