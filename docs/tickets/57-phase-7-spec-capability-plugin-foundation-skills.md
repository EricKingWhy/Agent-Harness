# #57 — Phase 7 Spec: Capability / Plugin Foundation + Skills

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T18:06:45Z
- **Closed**: —
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/57

---

## Parent

Phase 7 — Capability / Plugin Foundation + Skills（spec 14）

## What to build

把 Phase 6 的点对点 Capability seam（MemoryCapability → LangMem → MemoryContextProvider）泛化为通用机制：capability registry + provider descriptors + plugin config + SKILL.md discovery + progressive disclosure + Context injection（spec 14 Phase 7 交付清单）。使未来新增领域能力（Finance 等）不修改 Agent Core（spec 08 §1/§8）。

工程依据：spec 08 全文、spec 09 §2（Skills）、13 §2/§3/§5（Pi/DSH PORT DESIGN + Registry BUILD）、ADR-0010、ADR-0011、CONTEXT.md Phase 7 术语。

## Acceptance criteria（Phase 7 Gate，spec 14）

- [ ] 新增 demo capability 不改 Agent Loop（agent/runtime.py 零改动）
- [ ] Skill 全文不默认永久进 Context（默认只有目录，全文按需 load）
- [ ] spec 08 §9 验收：切换 Memory Provider 不改 Core；Provider 不支持能力时明确报错；Optional Provider 故障可降级；插件不能绕过 Tool Permission / Operation Ledger
- [ ] 全量测试绿 + ruff clean

## Blocked by

None（Phase 6 已收口）。

