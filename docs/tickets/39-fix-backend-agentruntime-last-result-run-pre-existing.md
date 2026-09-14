# #39 — fix(backend): AgentRuntime._last_result 实例态在并发 run 下有竞态（pre-existing）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T19:57:07Z
- **Closed**: —
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/39

---

## Context
AgentRuntime 把 _last_result 挂在实例上（runtime.py），供 run() 同步取结果。同一 runtime 实例并发跑两个 run 时互相覆盖。Phase 9/10 web 层每请求新建 runtime（_build_runtime），当前无实际触发路径，但 run_stream 与 run 混用或未来复用 runtime 时会踩。

**归属：backend 领域**（feat/backend 会话），前端不修。记录自交接文档已知债清单 + 2026-09-04 code-review 复核确认仍在。

## Acceptance criteria
- [ ] _last_result 移入 run() 局部 / 返回值，或 runtime 加并发守卫（backend 会话决定）
- [ ] 有并发 run 的回归测试
