# Global Code Review — 2026-09-04

> 双轴审查（Standards + Spec）覆盖 `e3d84f7...HEAD`（60 commits, issues #6–#33）。
> 按 user Directive B「精益求精，找到全局的 bug，如手术刀般切掉」执行。

---

## 审查范围

- 固定点：root commit `e3d84f7`
- HEAD：`9160ce8`（含本次修复）
- 210 files changed, ~31k insertions
- Standards 来源：`AGENTS.md` §7 不变量 + §9 Karpathy guidelines + `CONTEXT.md` 词汇 + 5 ADR
- Spec 来源：`docs/spec/00–14` + `docs/adr/0004`
- Smell baseline：Fowler 12 smells（judgement calls only）

---

## 已手术修复（本轮 commit `22fb938` + `9160ce8`）

### 1. derive.py 死代码 — **已删**

`session/derive.py:41-46` 计算 `resolved_tool_call_ids` 后从未读取。实际 dangling 检测走第二遍的 `block_ids` 路径。死变量与块检测语义矛盾——留下会让未来读者误以为它 gate 了合成注入。

**处置**：删除 6 行。零行为变化（345 passed）。

### 2. grep.py 内联 import — **已提**

`tools/grep.py:93,96` 在循环体内 `import fnmatch` / `from pathlib import PurePosixPath`。Divergent Change smell——把 import wiring 混进搜索逻辑。

**处置**：提到模块顶部。零行为变化。

### 3. 全仓 ruff lint 债 — **已清零**

PHASE_STATUS 声称「全仓 ruff clean」但 `demo/live_agent.py`（F401/RUF100/BLE001）和 `scripts/snapshot_tickets.py`（ISC004/UP017）仍有 18 处告警。

**处置**：删未用 import、删失效 noqa、BLE001 加 noqa（demo 顶层兜底合理）、ISC004 改显式括号。`ruff check .` 现在 `All checks passed`。

---

## 已确认的非 bug（记录，不动）

### A. `runtime.py:144` 访问 `session._events[-1]`

`begin_run()` 内部 append 了 `run/started` 事件，runtime 直接读私有 `_events[-1]` 取回。封装泄漏（Law of Demeter 违反），但**不是 bug**——行为正确，仅是 API seam 不干净。

**为什么不动**：修它需要 `begin_run()` 返回 `SessionEvent`，会改公开方法签名，影响 252 个测试和 demo。属于重构而非 bug 修复，超出 surgical scope。**记录为未来小重构候选。**

### B. `operation_id` 是 `tool_call_id` 的 computed alias

`storage/operation.py:42` 把 `operation_id` 实现为 `computed_field` 返回 `tool_call_id`。Spec 07 §4 列 `operation_id` 为独立字段。

**为什么不动**：CONTEXT.md 明确定义「绑定 `operation_id`（与 `tool_call_id` 1:1）」，且 ADR-0004 确认「Operation identity is exactly the originating tool_call_id」。computed_field 是这个不变量的**显式表达**，比冗余字段更安全。无 drift。

### C. Sidecar 恢复锁（`.recovery-lock`）

`coordinator.py` 用 `BEGIN EXCLUSIVE` 在 sidecar 文件上加跨进程锁。Spec 07 §9 的 8 步顺序未显式要求锁。

**为什么不动**：这是 Phase 4 实施时发现的**自死锁修复**——主 DB 上 EXCLUSIVE 会饿死 Ledger 自身的 reconcile 写入。sidecar 锁是正确性必需，不是 scope creep。docstring 已诚实记录。

---

## Phase-deferred 功能（不是 bug，是未来 Phase 的交付物）

以下 Spec-axis 发现**全部对应未开始的 Phase**，当前不实现是正确的——Roadmap 按依赖关系组织，不能跳过前置 Phase。

| # | 发现 | 对应 Phase | Roadmap 位置 |
|---|------|-----------|-------------|
| 1 | Repeated-Tool Guard (`REPEATED_TOOL_CALL`) | **Phase 12** | §12 交付物：「repeated tool guard」 |
| 2 | Model Fallback (timeout/429/transient) | **Phase 12** | §12 交付物：「Model Fallback」+ Gate「provider transient 有 fallback reason」 |
| 3 | Event vocab 缺失 (`session/forked`, `step/*`, `context/*`, `checkpoint/saved`, `artifact/created`, `agent/delegated`) | **Phase 5/7/13/14** | 各 Phase 交付物分别定义这些事件 |
| 4 | Tool Contract detail fields (`idempotency_mode`, `supports_reconcile`, `dependency_metadata`, `result_policy`) | **Phase 5–8** | 这些字段在 Artifact / MCP / Capability Phase 才需要 |
| 5 | Scheduler DAG (`depends_on` / `resource_keys`) | **Phase 2 后续深化** | 当前 READ_ONLY/MUTATING 二分满足 Phase 2 Gate；DAG 在 Phase 8 MCP 多工具场景深化 |
| 6 | Replay / Fork / Compaction | **Phase 5 / 14** | §14：「replay projector / fork boundary / lineage tree」；§5：「structured compaction」 |

**结论**：这些都不是当前 scope 的 bug。当前已交付的 Phase（0–4 + 9–10 精简版）满足各自的 Gate。

---

## 授权的提前施工（非 scope creep）

### Phase 9+10 精简版

`web/` + `run_stream` + SSE + React 前端。PHASE_STATUS 已标注 `🔄 IN PROGRESS (精简版提前)`，ADR-0005 记录决策，CONTEXT.md「Streaming / Web UI 层」术语已落。**用户明确授权**（见 PHASE_STATUS 更新日志 2026-09-04）。不变量 #22（前端不维护第二套真相）通过「前端直接消费 raw SessionEvent」守住。

---

## 已知的语义设计选择（记录，非 bug）

### D. Ledger-first `model/completed` 延迟写入

`runtime.py:206-209, 273-285`：当 `tracks_operations`，`model/completed` 在 tools 执行**后**才 append——Ledger 先写 PENDING/RUNNING，崩溃时 RecoveryCoordinator 能看到 operation 状态。

Spec 02 §2 的 loop 顺序是「aggregate complete AIMessage → tool execution」，但 07 §6 的 Ledger-first 崩溃安全要求更强。两个 spec 的优先级由 AGENTS.md §1.1 排定：当前模块（Storage/Recovery）规格 > 通用架构规格。**这是有意的 trade-off**，确保崩溃可恢复 > 忠实记录 loop 顺序。已由 Phase 4 Gate 验证（dangling=0, recoverable）。

### E. `RUNNING → UNKNOWN` 无条件推进

`coordinator.py:433-439`：recover 时 RUNNING 直接推 UNKNOWN→NEED_RECONCILE，不做 Tool-specific verify。

Spec 07 §6 说 UNKNOWN 需要「能验证实际状态」，但默认走 NEED_RECONCILE（交用户裁决）**正是安全默认**——不变量 #14「UNKNOWN 高风险 Tool 不盲重跑」。Tool-specific verify 是优化路径，默认安全拒绝是规格要求的底线。

---

## Summary

| 类别 | 数量 | 处置 |
|------|------|------|
| **真 bug / lint 债** | 3 | 已手术修复并推送 |
| **非 bug（封装泄漏等）** | 3 | 记录，不动 |
| **Phase-deferred 功能** | 6 | 正确未实现，对应未来 Phase |
| **授权提前施工** | 1 | 有 ADR + 用户授权 |
| **语义设计选择** | 2 | 有意 trade-off，守不变量 |

**底线**：当前已交付代码无已知真 bug。345 passed, 8 skipped, 3 deselected, ruff `All checks passed`。
