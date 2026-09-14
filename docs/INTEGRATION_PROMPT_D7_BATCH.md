# Phase 15 D7 DEFER 批集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend`（D7 DEFER 批，单 commit `dbb48a5`）合入 `main` 并完成验证
> **写于**：2026-09-07，分支 tip 以 `git -C D:\intelligence-agent-backend log -1` 为准
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏（`.env` 值不进任何输出/提交）；每次合并动作前确认 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）

---

## 0. 机器现状

| 路径 | 分支 | HEAD | 角色 |
| --- | --- | --- | --- |
| `D:\intelligence-agent` | `main` | `0ac49f3` | 集成主战场 |
| `D:\intelligence-agent-backend` | `feat/backend` | `dbb48a5` | D7 批施工区（本次提交源） |

- **拓扑**：`merge-base(origin/main, feat/backend) = 2d7f87a`（trace_url 契约）
  - feat/backend 领先 main **1 commit**（`dbb48a5`，D7 批：8 文件 +117/-15，**未碰 `docs/PHASE_STATUS.md`**）
  - main 领先 feat/backend **1 commit**（`0ac49f3`，trace_url 集成记录：只改 `docs/PHASE_STATUS.md` +2 行）
  - **双方修改零重叠 → 3-way merge 零冲突**，会产生一个 merge commit（不是 fast-forward）
- **改动范围**：8 文件 +117/-15（`config.py` Settings 新字段 / `sink.py` factory+init / `tracer.py` model_call_completed / `runtime.py` 调用点 / `observability/__init__.py` 装配 / 2 测试文件 / `PHASE15_GATE.md` Gap 表更新）
- **新 Python 依赖**：**无**（复用 Phase 15 已有的 `langfuse` optional extra）
- **新 env**：**2 个新可选 env**
  - `LANGFUSE_TRACING_ENVIRONMENT`（缺省 `development`，trace 不再落入 `default` 环境）
  - `LANGFUSE_RELEASE`（空=不塞，SDK 自决；非空透传给 SDK init 作为版本/SHA 一等字段）
  - 两者都经 `Settings` → `LangfuseSink` factory → SDK init 透传；空值不覆盖云端项目配置
- **数据库/schema 变更**：**无**（只在 SDK init 多传两个 kwargs，不动任何持久化结构）

## A. 变更摘要（给集成 AI 的语义账）

**契约**：Phase 15 真实模型 smoke Gate 暴露的 5 条 Gap，本批处理其中 3 条代码侧：

1. **Gap 1 environment**（中严重度）：`Settings.langfuse_tracing_environment`（缺省 `development`）经 `LangfuseSink` factory 透传到 SDK init——trace 不再落入 Langfuse 的 `default` 环境，可区分 prod/staging/dev。
2. **Gap 2 release**（低严重度）：`Settings.langfuse_release`（空=不塞，SDK 自决）同款透传——release 是 Langfuse 一等字段，用于按版本对比（`git_commit` 已在 metadata，但 release 是一等字段）。
3. **Gap 5 tool_calls 轮 output**（低严重度）：`RunTracer.model_call_completed` 新增 `tool_call_names` 参数；当模型返回 tool_calls 但 content 空（典型 tool_calls 轮）时，写 `<tool_calls: add, search>` 结构化标记，让 Langfuse UI 可读（此前显示成 None）；`runtime.py` 调用点同步下发 calls 名单。**仅空 content + 有 tool_calls 时兜底**——正常回答轮不受影响。

**未处理的 2 条（非代码侧，已在 PHASE15_GATE.md 标注）**：
- Gap 3 cost_details：Langfuse 云端 UI 配置项（在项目设置定义模型定价），代码侧不消费成本字段
- Gap 4 user_id：明确 DEFER web 场景——单用户 CLI 可接受；web 多用户接入时在 Sink 层加 user_id 入参

**规格对账**：ADR-0018 D7（trace 元数据完整性延伸）+ §6 Reuse First（environment/release 用 SDK 一等字段，不手拼）+ 不变量 #21（新参数只走 factory 透传，不动故障隔离边界——disabled sink 仍是 no-op，熔断/异常吞语义不变）。

## B. 预检查

```bash
git fetch origin --prune
git -C D:\intelligence-agent-backend status --short   # 必须干净（已提交）
git worktree list --porcelain
# 拓扑确认：
git rev-list --count origin/main..feat/backend        # 预期 1（dbb48a5）
git rev-list --count feat/backend..origin/main        # 预期 1（0ac49f3）
git merge-base feat/backend origin/main               # 预期 2d7f87a
# 零冲突预判：确认 dbb48a5 没碰 PHASE_STATUS.md
git diff 2d7f87a..dbb48a5 --name-only | grep PHASE_STATUS && echo "⚠️ 有重叠需逐文件分析" || echo "✅ 零重叠 → 干净 merge commit"
```

## C. 合入（3-way merge，产生 merge commit）

```bash
cd D:\intelligence-agent
git merge --no-ff feat/backend -m "Merge feat/backend: Phase 15 D7 DEFER 批——environment/release 透传 + tool_calls 轮 output 标记（ADR-0018 D7，dbb48a5）"
```

**冲突预测**：**零**（双方修改无重叠——main 只改 PHASE_STATUS.md，feat/backend 只改源码+测试+Gate 文档）。若意外出现冲突 → 按 §14.7 立即停止，逐文件分析，**不得机械取边**。

> 注：为什么不是 fast-forward？因为 main 在 trace_url 合入后独立前进了一个集成记录 commit（`0ac49f3`），拓扑已是分叉。`--no-ff` 显式产生 merge commit，保留两边历史可追溯。cherry-pick 也可行（单 commit 干净），但 §14.4 把 cherry-pick 列入需 approval 操作，且 merge 更完整地保留分支语义——本提示词推荐 merge 路径。

## D. 验证 Gate（main 侧为准）

```bash
cd D:\intelligence-agent
uv sync --all-extras          # 复用已有 langfuse extra，无需新装
uv run pytest -q              # 基线预期：1191（trace_url 合入基线）+ 4（本批新增）= 1195 passed / 9 skipped / 0 failed
                              # evaluation 测试若因 langfuse 包未装失败，是环境问题不算回归
uv run ruff check src/ tests/
git diff --check
```

**冒烟（推荐，可选，需 `LANGFUSE_*` 凭证）**：从 main 启后端，造一个会话跑一条会触发 tool_calls 的任务，检查 Langfuse UI：
1. trace 的 `environment` 字段 = `development`（不再是 `default`）
2. 若设了 `LANGFUSE_RELEASE`，trace 的 `release` 字段非空
3. 第一轮 generation（tool_calls 轮）的 output 显示 `<tool_calls: add>` 而非 None

```bash
# 可选冒烟（需 main worktree .env 里 LANGFUSE_* 已配）：
cd D:\intelligence-agent
uv run uvicorn agent_harness.web.app:create_app --factory --host 127.0.0.1 --port 8000 &
# 造会话跑任务，检查 Langfuse UI 上 trace 的 environment/release/output 标记
```

## E. Push 与收尾

1. 全绿后 `git push origin main`
2. `docs/PHASE_STATUS.md` 追加集成记录条目（验证数字、merge commit hash、新 env 字段知会）
3. 向用户报告：完成什么 / 改了哪些 / 测试结果 / commit 区间 / 遗留项
4. **遗留项交接**：
   - Gap 3 cost_details：通知用户在 Langfuse 云端项目设置定义模型定价（非代码任务）
   - Gap 4 user_id：DEFER web 场景，登记到后续 web 接入批次
   - review 无阻塞性发现（本批 TDD 红→绿，4 新测试，双轴自审在 commit 前完成）

## F. 一句话给集成 AI

**单 commit 3-way merge，零冲突（双方修改无重叠），零新依赖，2 个新可选 env，预期 1195 passed；合入后通知用户 Gap 3 是云端配置项 + Gap 4 DEFER web。**
