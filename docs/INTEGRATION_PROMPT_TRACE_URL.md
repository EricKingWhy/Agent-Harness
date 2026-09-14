# trace_url 契约集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend`（trace_url 契约实现，单 commit `2d7f87a`）合入 `main` 并完成验证
> **写于**：2026-09-07，分支 tip 以 `git -C D:\intelligence-agent-backend log -1` 为准
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏（`.env` 值不进任何输出/提交）；每次合并动作前确认 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）
> **前置状态**：`feat/backend` 已 fast-forward 到 main tip `c29a4f9`（含 Phase 15 + frontend-B 收尾批），本 commit `2d7f87a` 在其上纯加 trace_url 契约——**fast-forward 合入，零冲突**

---

## 0. 机器现状

| 路径 | 分支 | 角色 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | 集成主战场 |
| `D:\intelligence-agent-backend` | `feat/backend` | trace_url 施工区（本次提交源） |

- **拓扑**：`merge-base(origin/main, origin/feat/backend) = c29a4f9`；feat/backend 领先 main **1 commit**（`2d7f87a`），main 领先 feat/backend **0 commits** → **纯 fast-forward，无 merge commit，零冲突**
- **改动范围**：8 文件 +377/-30（纯增量，无删除文件、无移动）
- **新 Python 依赖**：**无**（复用 Phase 15 已有的 `langfuse` optional extra）
- **新 env**：**无**（复用 Phase 15 已配的 `LANGFUSE_*`；trace_url 由官方 SDK 从已有 host+project 配置合成，零新配置）
- **数据库/schema 变更**：**无**（只在 `SessionEvent.data` dict 里加键，不动 schema）

## A. 变更摘要（给集成 AI 的语义账）

**契约**：`run/completed.data` 与 `run/failed.data` 新增 `trace_url` 字段（人类可点击的 Langfuse trace URL），与现有 `trace_id`（机器可读）并列保留。官方 `langfuse.get_trace_url(trace_id=…)` 合成，零手拼（§6 Reuse First）。Langfuse 未启用时 `trace_url` 恒 `null`（同 `trace_id` 降级模式）。

**四层改动**（commit `2d7f87a`）：
1. `LangfuseSink.get_trace_url(trace_id)`（sink.py）：官方 SDK 薄封装，故障隔离同款（熔断期丢弃 + 异常吞返回 None + disabled→None）
2. `RunTracer.trace_url` + `_finalize_trace_url()`（tracer.py）：终态（`run_completed`/`run_failed`）懒构造、幂等缓存
3. `runtime.py` 六终态分支：**时序修复**——`tracer.run_completed/run_failed` 移到 `session.end_run` 之前（trace_url 构造时机在终态调用里，必须先于读取）；并行下发 `trace_url`
4. `session.end_run`（session.py）：`trace_id` + `trace_url` 对称下发到 completed + failed；**顺手补既有 bug**：失败路径此前丢弃 trace_id（只 completed 写）；`cancelled_terminal` 同款对称化

**前端影响（通知前端 B 用）**：
- `run/completed.data.trace_url` 和 `run/failed.data.trace_url` 现在存在（Langfuse 开启=URL，未启用=null）
- `trace_id` 行为**有一处变化**：失败 run 此前不写 `trace_id`，现在对称写入（机器可读 trace handle 不再因失败路径丢失）——前端若有"failed run 不含 trace_id"的断言需更新
- 消费清单已在 brief §7 列清：types.ts `ConversationState.trace_url`；projection.ts 抽 `data.trace_url`（缺省 null）；StepDetail.tsx `trace_url` 有值时把 `trace_id` 渲染成 `<a href target=_blank rel=noopener>`；App.tsx 可选 "Open Trace" 命令（无 trace_url 时不出现）

## B. 预检查

```bash
git fetch origin --prune
git -C D:\intelligence-agent-backend status --short   # 必须干净（已提交并 push）
git worktree list --porcelain
# 拓扑确认：
git rev-list --count origin/main..origin/feat/backend   # 预期 1
git rev-list --count origin/feat/backend..origin/main   # 预期 0
```

## C. 合入（fast-forward）

```bash
git -C D:\intelligence-agent merge --ff-only feat/backend
```

**冲突预测**：**零**（fast-forward）。若意外出现冲突 → 按 §14.7 立即停止，逐文件分析，不得机械取边。

## D. 验证 Gate（main 侧为准）

```bash
cd D:\intelligence-agent
uv sync --all-extras          # 复用已有 langfuse extra，无需新装
uv run pytest -q              # 基线：1189 passed / 9 skipped / 27 deselected，零失败
                              # 2 个 evaluation 失败（langfuse 包未装）是环境问题，不算回归
uv run ruff check src/ tests/
git diff --check
```

**冒烟（推荐，可选）**：从 main 启后端，造一个会话跑一条任务（Langfuse 开启），检查 `run/completed.data.trace_url` 非空且可点击打开 Langfuse UI 对应 trace；再触发一次失败 run（如撞 max_steps），确认 `run/failed.data.trace_url` 同样非空。

```bash
# 可选冒烟（需 main worktree .env 里 LANGFUSE_* 已配——Phase 15 已同步过）：
cd D:\intelligence-agent
uv run uvicorn agent_harness.web.app:create_app --factory --host 127.0.0.1 --port 8000 &
# curl 或浏览器造会话，检查 run/completed 的 data.trace_url
```

## E. Push 与收尾

1. 全绿后 `git push origin main`
2. `docs/PHASE_STATUS.md` 追加集成记录条目（验证数字、fast-forward 合入、前端影响知会）
3. 向用户报告：完成什么 / 改了哪些 / 测试结果 / commit 区间 / 遗留项
4. **遗留项交接**：
   - 通知前端 B 开消费侧票（projection.ts 抽 `data.trace_url` + StepDetail `<a>` 渲染 + App.tsx 可选 "Open Trace" 命令 + projection/组件单测）
   - review 发现的两条非阻塞观察项（见下方 §F）记入观察，不阻塞合入

## F. code-review 结论（双轴，已记录非阻塞）

集成 AI 不需要处理这两条，但应知情（来自合入前的 `/code-review`）：

**Standards 轴**：
- **Data Clump / Duplicated Code**（judgement call，非硬违规）：`runtime.py` 里 `(tracer.trace_id if tracer else None)` + `(tracer.trace_url if tracer else None)` 这对守护出现了 6 次。一个小 helper（如 `RunTracer.terminal_fields()` 返回 dict）能消除。**不在本票范围（§8 Scope Lock），记为后续清理候选**。
- **§7 #4 "Event ≠ Diagnostic Log" 边界问题**（值得团队签字但非阻塞）：`trace_url` 是 `trace_id` 的派生渲染串，放进 `SessionEvent.data` 是否越界？反驳：`trace_id`、`usage_total`、`cost_usd` 已经在 `data` 里且都是派生/计算量；契约明确要求 trace_url 在 data 中——这是**文档化的契约例外**，不是私自扩容。建议在 ADR-0018 或后续 ADR 里显式记录此例外（不阻塞本合入）。

**Spec 轴**：
- **零实质缺失**：六终态全覆盖、sink wrapper 齐、tracer 字段对称、`session.end_run` 扩展——契约要求全数满足。
- **行为变化点已暴露**：失败 run 现在持久化 `trace_id`（既有 bug 修复）+ `trace_url`（新增）——前端消费侧需知道这是**对称化**，不是破坏 trace_id 契约。
- **幂等性边界**（低风险，已分析）：`_finalize_trace_url` 在 `trace_url is not None` 时跳过；若首次 `get_trace_url` 返回 None（disabled/breaker），后续重试允许覆盖——理论上非严格幂等，但实践中终态只调一次，无实际危害。

## G. 一句话给集成 AI

**fast-forward 单 commit 合入，零冲突，零新依赖，零 schema 变更，1189 passed 复跑预期；合入后通知前端 B 开 trace_url 消费侧票。**
