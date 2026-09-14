# #58 — Phase 7 T1: Capability seam 核心 — Descriptor / Error / Registry

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: OPEN
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T18:07:05Z
- **Closed**: —
- **Parent**: #57
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/58

---

## Parent

#57 — Phase 7 Spec: Capability / Plugin Foundation + Skills

## What to build

任何 Capability Provider 都能以"descriptor + 实例"注册进一个命名 Registry；Consumer 按名取用，缺失/不支持/停用三种失败各自得到明确的 `CapabilityError`，OPTIONAL 消费者走 `optional()` 拿 None 降级。这是 spec 08 §2/§3/§5/§7 的最小完整实现（ADR-0010 Q1-Q3）。

## Acceptance criteria

- [ ] `CapabilityDescriptor` 字段齐 spec 08 §5 清单（name/version/provider_name/capabilities[]/risk/supports_streaming/supports_recovery/supports_concurrency/config_schema）+ `degradation` 三分类 + `enabled`；`supports(sub)` 判定子能力
- [ ] `CapabilityError` 四码：not_found / unsupported / disabled / init_failed（ADR-0010 Q3）
- [ ] `CapabilityRegistry.register(descriptor, provider)`：重复同名注册抛错不覆盖
- [ ] `get(name)` 缺失抛 not_found；`optional(name)` 缺失返回 None；`descriptor(name)`；`available()` 列已注册 descriptor
- [ ] disabled 的 provider：`get` 抛 disabled，`optional` 返回 None
- [ ] 测试位置 tests/capability/，全量套保持绿

## Blocked by

None (can start immediately).

