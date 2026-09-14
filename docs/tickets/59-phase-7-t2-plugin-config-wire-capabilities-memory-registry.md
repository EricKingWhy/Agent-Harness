# #59 — Phase 7 T2: Plugin Config + wire_capabilities + Memory 走 Registry

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T18:07:07Z
- **Closed**: —
- **Parent**: #57
- **Blocked by**: #58
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/59

---

## Parent

#57 — Phase 7 Spec: Capability / Plugin Foundation + Skills

## What to build

`CAPABILITIES` 环境变量（JSON）解析为类型化配置；`wire_capabilities()` 按 config 驱动 builtin factory 注册进 Registry 并把能力贡献接到 ToolRegistry / ContextProviders。Memory 装配从 Web `_build_runtime` 的直接 import 迁到 factory——**换 Memory Provider 只改配置，不改 Core/装配代码**（spec 08 §9 验收 1；ADR-0010 Q4/Q5/Q6）。

## Acceptance criteria

- [ ] Settings 增 `CAPABILITIES`（默认空串=空 map）；JSON 非法时明确报错，不静默吞
- [ ] `CapabilityConfigMap`：`{name: {provider, enabled, options}}`，经 Pydantic 校验
- [ ] builtin factory `memory`：配置齐（milvus+embedding）→ LangMemMemoryCapability（迁 Phase 6 Web 装配逻辑）；配置不齐 → 不注册（optional 路径，Web 行为与现状一致）
- [ ] `wire_capabilities(registry, config, *, tool_registry, context_providers)`：显式接线
- [ ] Web `_build_runtime` 改走 registry；无配置时行为与 Phase 6 收口态完全一致（现有测试不破）
- [ ] 测试：config 解析、factory 缺配置跳过、wire 后 registry 可查、Web 回归

## Blocked by

- #58（T1: Capability seam 核心）

