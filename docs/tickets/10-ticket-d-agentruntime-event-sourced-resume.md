# #10 — Ticket D: AgentRuntime event-sourced 改造 + 测试迁移 + Resume 集成测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T12:02:09Z
- **Closed**: 2026-09-03T12:35:26Z
- **Parent**: #6
- **Blocked by**: #9
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/10

---

## Parent

#6 (Phase 1 SessionEvent spec)

## What to build

把 AgentRuntime 从内存 messages list 迁移到 event-sourced 架构：`run()` 接受 Session 对象，循环内同步 append 事件，messages 退化为运行期缓存。同时改造全部现有测试，新增 Resume 集成测试。

这是 Phase 1 的收官 ticket：完成后 Phase 1 Gate 达成（简单对话重启后可恢复历史）。

## Acceptance criteria

- [ ] `AgentRuntime.run(session: Session, user_input: str)` 签名替换旧的 `run(user_input: str)`
- [ ] 循环开始：`session.append("user/message", {"content": user_input})`
- [ ] 每轮模型调用后：`session.append("model/completed", {...})` 或 `session.append("model/failed", {...})`
- [ ] 工具执行后：逐条 `session.append("tool/call", {...})` + `session.append("tool/result", {...})`
- [ ] Run 生命周期：`session.begin_run()` / `session.end_run(run_id, status=...)` 包裹整个循环
- [ ] messages list 仍用于循环内传给模型（运行期缓存），但事实源是 events
- [ ] Diagnostic Log 保持不变（`_log()` 继续调用），实现双写
- [ ] 提供 `make_session(tmp_path) -> Session` 测试 helper
- [ ] 改造 `tests/agent/test_agent_loop.py` 全部 ~10 处 AgentRuntime 构造点
- [ ] 改造 `tests/agent/test_integration_coding.py` 全部 ~3 处构造点
- [ ] 新增 Resume 集成测试（ScriptedModel 跑半段 → 创建新 Session.resume → derive_messages → 继续 → 验证历史完整）
- [ ] 现有 91 个默认套测试全部继续通过（改造后）
- [ ] 新增的 Session 模块测试全部通过
- [ ] ruff clean
- [ ] Phase 1 Gate 达成：进程重启后可从 JSONL 恢复完整对话历史
- [ ] 完成后关闭 #6（Phase 1 spec）

## Blocked by

- #9 (Ticket C — 需要 Session 聚合根完整 API)
