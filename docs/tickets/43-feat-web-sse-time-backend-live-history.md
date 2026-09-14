# #43 — feat(web): SSE 流式帧注入 time（backend 协作，live/history 时间同源）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T20:07:11Z
- **Closed**: 2026-09-04T08:28:59Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/43

---

## Context
架构扫描发现 SessionEvent 形状漂移：前端已补 time/event_id 消费（历史重建用事件真值时间，2026-09-04 修复），但 POST /api/sessions 的 SSE 帧（_event_to_sse_dict）不含 time——流式中的 started_at/completed_at 仍是客户端时钟，跨刷新与历史重建不一致。

**Backend 改动**：_event_to_sse_dict 的 durable 事件注入 SessionEvent.time（流式信号 model/delta 可注入发送时刻）。

## Acceptance criteria
- [ ] 每帧带 time
- [ ] 前端 projection 已写好 event.time ?? 回退，后端改完即自动生效（前端零改动）
- [ ] tests/test_web_api.py 每帧 session_id 断言旁加 time 断言
