# Phase 15 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/phase15`（Phase 15 Langfuse 旁路观测 + 评测，ADR-0018，tickets #117-#125）合入 `main` 并完成验证
> **写于**：2026-09-07，分支 tip 以 `git -C D:\intelligence-agent-phase15 log -1` 为准
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏（`.env` 值不进任何输出/提交）；每次合并动作前确认 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）
> **前置状态**：Phase 14 + ADR-0016 已在 main（c65ebd9 及之后）；feat/phase15 从集成后的 main 干净分叉，预期无冲突

---

## 0. 机器现状

| 路径 | 分支 | 角色 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | 集成主战场 |
| `D:\intelligence-agent-phase15` | `feat/phase15` | Phase 15 施工区 |

- 内容：9 票（观测 Sink/Tracer/JSONL 审计/flush/eval 骨架/P0 cases/smoke/Gate）+ ADR-0018 已随 feat/phase14 在 main（本分支只含代码与测试 + Gate/审计/集成文档）
- **新 Python 依赖**：optional-dependencies 新组 `observability = ["langfuse>=3"]`——`uv sync --all-extras` 自动覆盖；不装该 extra 时旁路完全缺席（Key 空 = 零 import）
- 新增 env 族：`LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL / LANGFUSE_TRACE_CONTENT`——**已在 phase15 worktree `.env` 配好，需要把这几行同步复制到 main worktree `.env`（只复制文件内容，任何值不得出现在文档/输出/提交里）**
- 前端影响：**零**（事件词表未变；run/completed.trace_id 从恒 null 变为「Langfuse 开启时=真实 trace id」——前端已消费该可选字段，灰字「未追踪」自动变可用，无需前端改动）

## A. 预检查

```bash
git fetch origin --prune
git -C D:\intelligence-agent-phase15 status --short   # 必须干净
git worktree list --porcelain
```

## B. 先回后正 + 合入

```bash
git -C D:\intelligence-agent-phase15 merge origin/main   # 预期干净（本分支即从 main 分叉；仅 docs 并集级差异）
git -C D:\intelligence-agent merge --no-ff feat/phase15 -m "Merge feat/phase15: Phase 15 Langfuse bypass observability + eval (ADR-0018, #117-#125) — fault-isolated sink + run/model/tool/subagent tracing + trace_id backfill + deterministic eval + real-cloud gates"
```

冲突预测：**预期零冲突**。若出现，最可能在 `docs/PHASE_STATUS.md`（追加行并集）——按 §14.7 逐文件分析，语义并集，不得机械取边。

## C. 验证 Gate（main 侧为准）

```bash
cd D:\intelligence-agent
uv sync --all-extras          # observability extra 随 all-extras 安装
uv run pytest -q              # 基线：1173 passed / 9 skipped / 27 deselected，零失败（±个位数波动不得失败）
uv run ruff check src/ tests/ evaluation/
git diff --check
# 真云 Gate（可选，推荐；需上一步同步的 LANGFUSE_* 在 main 侧 .env）：
uv run pytest tests/integration/test_phase15_gate.py -m integration -v   # 2 passed（真云上传→回捞审计 + seed 幂等/Experiment）
```

冒烟（可选）：造会话跑一条任务后，Langfuse UI（jp 区项目）应出现 `agent-run` trace（session 聚合、generation 带 usage、tool 观测）；`run/completed.data.trace_id` 非空。

## D. Push 与收尾

1. 全绿后最后一步 `git push origin main`
2. `docs/PHASE_STATUS.md` 追加集成记录条目（验证数字 / .env 同步情况）
3. 向用户报告：完成什么 / 改了哪些 / 测试结果 / commit 区间 / 遗留项
4. **遗留项交接**：①真实模型 smoke（`evaluation/smoke.py`，手动车道）建议集成后在 main 跑一次真链路；②D7 DEFER（generation 带 model_parameters、`resumes` 恢复链 metadata）已登记 ADR-0018 与 PHASE15_GATE.md，后续批次处理

## E. 异常处理

- 真云 Gate 遇 Langfuse 云/本地网络抖动（ConnectError / 404 回捞超时）：按退避复跑（测试内置 48s 回捞重试）；连续失败则如实记录 SKIPPED 原因，**默认车道全绿即可合入**（真云 Gate 是增强证据，不是合入前提）
- 任何预期外冲突 → 停下报告用户（§14.7）
