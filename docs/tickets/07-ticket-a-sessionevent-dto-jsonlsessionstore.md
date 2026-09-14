# #7 — Ticket A: SessionEvent DTO + JsonlSessionStore + 单元测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T12:00:11Z
- **Closed**: 2026-09-03T12:35:25Z
- **Parent**: #6
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/7

---

## Parent

#6 (Phase 1 SessionEvent spec)

## What to build

SessionEvent 持久化的最底层：定义事件 DTO 与词汇表，实现 JSONL append-only 存储。

这是一个完整的垂直切片：从 SessionEvent 数据结构定义，到 JsonlSessionStore 的写入/读取 IO，到崩溃安全的读取验证，端到端可独立测试。上层 Session 聚合根和 derive_messages 在后续 ticket 中构建于此基础之上。

## Acceptance criteria

- [ ] `SessionEvent` frozen dataclass 定义完整：event_id / seq / time / type / session_id / run_id / agent_id / step_id / data / source_event_ids（可空字段允许 None）
- [ ] 10 种 event type 常量定义：`session/started`、`session/resumed`、`run/started`、`run/completed`、`run/failed`、`user/message`、`model/completed`、`model/failed`、`tool/call`、`tool/result`
- [ ] `JsonlSessionStore` 实现 `read_events(session_id) -> list[SessionEvent]` 和 `append_event(session_id, event) -> None`
- [ ] 文件布局 `.agent/sessions/<session_id>/events.jsonl`（或测试时用 tmp_path 自定义根目录）
- [ ] 写入：整行 `json.dumps(event) + "\n"` 一次 `file.write`，紧跟 `flush()`
- [ ] 读取：逐行 `json.loads`，无法解析的行跳过（崩溃安全：半行 = 没发生）
- [ ] 单元测试覆盖：DTO 构造与字段、写入读取 roundtrip、半行损坏跳过、seq 单调性读取
- [ ] ruff clean
- [ ] 现有 91 个默认套测试不受影响（本 ticket 不改动现有代码）

## Blocked by

None (can start immediately)
