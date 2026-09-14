# Ticket P2-003：移除 ADR-0021 `context_provider_entries` 死读端

> **Spec**：Issue #140
> **车道**：后端 `D:\intelligence-agent-backend`（`feat/backend`）
> **优先级**：P2（清理，无紧迫性；但需谨慎——写端活着）
> **⚠ 与审计描述的差异**：审计称 `ContextProviderEntry` / `register_context_provider` 是 dead code（只查了 `assembly.py`）。深入核查后发现更精确：**写端活着、读端死了**——详见下文。修复需有意识的 wiring 编辑，不是随手删。

---

## 背景

B2 双实现冲突（ADR-0020b vs ADR-0021）经混合方案解决（`TICKET_B2_MIXIN_HANDLER_422.md`）：**保留 ADR-0020b** 的 `wiring.context_providers` 裸 list + `_select_context_providers`，只借 ADR-0021 的 handler 层 422。

ADR-0021 的三件套在混合方案后应被移除，但 `wiring.py` 仍保留：
- `ContextProviderEntry` dataclass（`wiring.py:36`）
- `register_context_provider()` 的 **id→map 写半段**（`wiring.py:50-69`）
- `context_provider_entries: dict` 字段（`wiring.py:85`）

## 读端真相（关键）

`context_provider_entries` **map 在 `wiring.py` 之外零消费**：

```text
grep -rn "context_provider_entries" src/ → 仅 wiring.py 自身
```

所有真正的读端（ADR-0020b 机制）都用**裸 list**，不用 map：
- `assembly.py:278` → `_select_context_providers(wiring.context_providers, ...)`
- `web/app.py:872, 903` → `for provider in wiring.context_providers` / `getattr(p, "name", None)`（422 校验从 provider 实例读 id，**不读 map**）

而 `register_context_provider` 被 `_wire_memory`（`wiring.py:147`）与 `_wire_skills`（`wiring.py:213`）**实际调用**，它同时做两件事：
1. `wiring.context_provider_entries[provider_id] = entry` ← **死**（无人读）
2. `wiring.context_providers.append(provider)` ← **活**（被 read 端消费）

## 要做什么

移除死读端，保留活语义：

1. 删除 `ContextProviderEntry` dataclass（`wiring.py:36-47`）。
2. 删除 `context_provider_entries` 字段（`wiring.py:85`）。
3. 把 `register_context_provider` 简化为只做活的那半——`wiring.context_providers.append(provider)`，删掉 entry 构造与 map 写入（或就地内联为 `append`）。

**验证**：改动后全量 `pytest` 通过；`grep -rn "context_provider_entries\|ContextProviderEntry" src/ tests/` 零匹配。422 混合方案（`app.py:897-931`）行为不变——它只依赖 `wiring.context_providers`。

## 回归测试

dead-code 清理属**绿灯型**（无红灯可先写）：以「引用扫描 + 全量回归」为门。
- `grep -rn "context_provider_entries\|ContextProviderEntry" src/ tests/` → 必须零匹配。
- 全量后端 `pytest` 通过（含 B2 context_providers 运行时消费 + 422 校验测试）。

## 不要做什么

- ❌ 不动 `_select_context_providers`（`assembly.py`，ADR-0020b 赢家机制）。
- ❌ 不动 handler 层 422（`app.py:897-931`，已按混合方案保留）。
- ❌ 不动 `memory/context_provider.py` / `skills/context_provider.py` 的 `name` 类属性（422 靠它读 id）。
- ❌ 不引入新的 provider registry 子系统。

## ⚠ 风险提示（执行前请确认）

本 ticket 比 P0-001 / FE-04 更微妙：`register_context_provider` 不是完全死代码——它保持 `context_providers` 裸 list 的一致性。若改动不当可能影响装配。建议**优先级最低**、独立执行、以全量回归兜底。若与在途 B2 重构交织，可考虑延后到重构收尾后单独清理。
