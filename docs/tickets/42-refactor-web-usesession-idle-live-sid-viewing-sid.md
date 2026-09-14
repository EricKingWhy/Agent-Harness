# #42 — refactor(web): useSession 会话模式判别态（idle | live(sid) | viewing(sid)）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T20:06:59Z
- **Closed**: 2026-09-04T05:19:16Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/42

---

## Context
架构扫描（2026-09-04）Top 1。三条状态流（列表/历史/流式）在 useSession 交织：submitTask 的 conv 闭包把新流事件折叠进旧会话 state，liveSessionId 流结束才 patch，live/history/temp-id 语义只活在注释里。da8b2ec 的切换停流是该缺失类型的第一个运行期补丁。

## 方向（grilling 待用户）
SessionMode = 'idle' | { live: sid } | { viewing: sid } 判别联合进 types.ts；conversation 归属 mode 指向的 sid；切换/新建/流结束的状态迁移进纯 reducer。

## Acceptance criteria
- [ ] conversation.session_id 与 mode 恒等（编译期保证）
- [ ] 流式中切换会话的语义由类型驱动（当前是 if (streaming) cancelStream() 补丁）
- [ ] 现有 E2E + tsc 全过，行为零回退
