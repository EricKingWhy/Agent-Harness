# #35 — chore(web): 主题亮色变量组双份手工同步（media 查询 + data-theme）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: —
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T19:56:26Z
- **Closed**: —
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/35

---

## Context
index.css 中亮色 token 存在两份：\`@media (prefers-color-scheme: light) :root\`（系统偏好兜底，无 JS 时首帧正确）与 \`:root[data-theme='light']\`（手动切换）。CSS 原生没有变量组复用机制，修改时必须两处同步（文件内注释已自警）。2026-09-04 已从 3 份收敛到 2 份（删除了冗余 dark 组）。

## Evidence
index.css 亮色变量组 ×2。

## Acceptance criteria
- [ ] 要么接受现状并保留注释（推荐：CSS 无 mixin，收益/风险比不划算），要么用构建期生成收敛
- [ ] 若收敛：浅色模式视觉回归（截图对比）必须过
