# #62 — Phase 7 T5: demo capability + Web 接线 + Phase 7 Gate 集成

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T18:07:57Z
- **Closed**: —
- **Parent**: #57
- **Blocked by**: #59, #61
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/62

---

## Parent

#57 — Phase 7 Spec: Capability / Plugin Foundation + Skills

## What to build

Phase 7 Gate 的实证切片：一个纯配置注册的 demo capability（`TickerCapability`，贡献一个 `tick` 工具），从 config 到 ToolExecutor 全链路走通且 **AgentRuntime / Agent Loop 零改动**；Web 装配消费 Registry（memory + skills + demo 三能力共存）；可选能力缺失降级实证（spec 08 §8 + 14 Gate 两条）。

## Acceptance criteria

- [ ] `TickerCapability`：descriptor（OPTIONAL_RUNTIME）+ 贡献 `tick` Tool（READ_ONLY，实现 ContributesTools Protocol）；仅在 config 显式启用时注册
- [ ] **Gate 1 断言**：demo capability 全链路不触碰 agent/runtime.py；Agent 用 ScriptedModel 调 tick 成功回填
- [ ] Web `_build_runtime` 走 wire_capabilities：memory（有配置）/ skills / demo 三能力共存装配
- [ ] 降级实证：config 不含某能力 / provider 构造失败 → `optional()` None → 装配跳过 → Runtime 正常（08 §7）
- [ ] 集成测试 tests/capability/test_phase7_gate.py：ScriptedModel + demo tool 执行闭环 + skills 目录注入 + 默认上下文无 skill 全文
- [ ] 全量套绿 + ruff clean

## Blocked by

- #59（T2: Plugin Config + wire_capabilities）
- #61（T4: SkillCapability + 渐进披露闭环）

