# #9 — Ticket C: Session 聚合根 + 生命周期 + 单元测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T12:01:34Z
- **Closed**: 2026-09-03T12:35:26Z
- **Parent**: #6
- **Blocked by**: #7, #8
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/9

---

## Parent

#6 (Phase 1 SessionEvent spec)

## What to build

Session 领域聚合根：持有 session_id 与已加载事件列表，对外提供 start / resume / append / derive_messages / begin_run / end_run 业务方法。这是 Runtime 和外部世界（CLI/Web UI）交互的单一入口。

完整垂直切片：从新建/恢复 Session，到 append 事件，到投影 messages，到标记 Run 边界，端到端可独立验证。

## Acceptance criteria

- [ ] `Session.start(store, *, agent_id="default") -> Session`：生成 session_id、创建 JSONL、append `session/started` 事件
- [ ] `Session.resume(store, session_id) -> Session`：加载 JSONL、校验 seq 单调、append `session/resumed` 事件
- [ ] `Session.append(event_type, data, **ids) -> SessionEvent`：分配 seq（单调递增）、同步写 JSONL、更新内存 events list
- [ ] `Session.derive_messages() -> list[AnyMessage]`：委托 derive_messages 纯函数，从内存 events 投影
- [ ] `Session.begin_run() -> str`：生成 run_id、append `run/started`、返回 run_id
- [ ] `Session.end_run(run_id, *, status, final_text="") -> None`：append `run/completed` 或 `run/failed`
- [ ] `session/__init__.py` 导出 Session、SessionEvent、JsonlSessionStore、derive_messages
- [ ] 单元测试：start → append 多条 → derive_messages 一致；resume 加载 → seq 校验 → derive_messages 与 start 后一致；begin_run/end_run 事件正确写入
- [ ] ruff clean

## Blocked by

- #7 (Ticket A — 需要 SessionEvent DTO + JsonlSessionStore)
- #8 (Ticket B — 需要 derive_messages 纯函数)
