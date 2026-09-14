# #38 — question(web): 是否引入 Vitest 前端单测框架（ADR-0005 冻结范围外的 stack 决策）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T19:57:05Z
- **Closed**: 2026-09-04T05:19:19Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/38

---

## Context
当前前端保障 = Python 契约测试 + tsc + 人工浏览器 E2E。lib/projection.ts（纯函数状态机）、lib/markdown.tsx（解析器）是高价值单测对象，但无前端测试框架。引入 Vitest 是**新 dev dependency**，需确认是否在 ADR-0005 冻结意图内（冻结清单写的是"无状态管理库/无 CSS 框架/传输层 SSE"，测试框架未明确列入）。

**需要项目所有者裁决**——不裁决不动（AGENTS.md §9.1：新增规格外基础设施需用户决策）。

## Acceptance criteria
- [ ] 用户裁决：引入 / 不引入
- [ ] 若引入：先覆盖 projection.ts（事件折叠语义）与 markdown.tsx（解析边界），纯函数优先
