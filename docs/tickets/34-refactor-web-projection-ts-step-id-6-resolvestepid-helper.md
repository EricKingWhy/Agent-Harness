# #34 — refactor(web): projection.ts 中 step_id 兜底逻辑重复 6 处，抽 resolveStepId helper

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T19:56:03Z
- **Closed**: 2026-09-04T06:02:15Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/34

---

## Context
projection.ts 中 \`step_id ?? active_step_id ?? 1\` 形态的兜底表达式重复出现 6 处。每处语义相同（持久事件取自身 step_id，流式事件跟随 active_step_id，兜底 1），分散维护容易在新增事件类型时漏改。

## Evidence
\`git grep '?? active_step_id ?? 1' web/src/lib/projection.ts\` 命中多处（2026-09-04 code-review + 交接文档已知债清单）。

## Acceptance criteria
- [ ] 单一 \`resolveStepId(event, state)\` helper，6 处调用点全部替换
- [ ] 行为零变化（projectHistory 与 applyEvent 输出逐事件一致，用现有 E2E + tsc 验证）
- [ ] 不改任何投影语义（最小 diff）
