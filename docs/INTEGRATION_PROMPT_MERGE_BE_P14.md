# 集成手册 — 双分支合入 main：feat/backend（ADR-0016 流式）+ feat/phase14（ADR-0017）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **授权**：用户已明确批准本次「检查 + 合并」任务；本手册内的 merge / 冲突处理 / push 即授权范围。超出本手册的动作（rebase / reset --hard / force-push / 删分支删 worktree）仍然禁止。
> **红线**：§14.2 每个写操作前确认 worktree 与分支；§14.7 冲突后停止自动解决、逐文件分析；§14.8 main 上遇复杂冲突先 abort；§14.9 一次一支；凭证零泄漏。
> **写于**：2026-09-06。分支 tips 以动手时 `git log -1` 为准（backend ≈ `de779ac`，phase14 ≈ 本文件提交后的 tip）。

---

## 0. 机器现状

| 路径 | 分支 | 角色 | 状态 |
| --- | --- | --- | --- |
| `D:\intelligence-agent` | `main` | 集成主战场 | e45956d（含 frontend Phase 13 + fallback 异构化） |
| `D:\intelligence-agent-backend` | `feat/backend` | B AI 流式改造（ADR-0016，T1-T8 已完成 + 自带集成手册） | 7 commits 领先 main，47 文件 +3192/-243 |
| `D:\intelligence-agent-phase14` | `feat/phase14` | Phase 14 Resume/Replay/Fork（ADR-0017，#107-#115 全关） | 干净叠在 main 上，11+ commits |

**合并顺序（两份 ADR 编号与两支各自的集成手册一致）**：`feat/backend` 先进 main → `feat/phase14` 再进。Phase 15（Langfuse）等本任务完成后另行从新 main 开工，与本任务无关。

**依赖与密钥**：两支均**零新 Python 依赖**。`.env` 无新密钥需求（main 侧 FALLBACK_MODEL_*=zhipu 已同步；phase14 worktree 本地 .env 有 LANGFUSE_* 属 Phase 15 范围——**不要复制、不要外传**）。

## 1. 前置检查

```bash
git fetch origin --prune
git -C D:\intelligence-agent-backend status --short   # 必须干净；若 dirty：停下报告用户（可能是另一会话仍在作业）
git -C D:\intelligence-agent-phase14 status --short   # 必须干净
git worktree list --porcelain                          # 核对映射
```

## 2. 第一支：feat/backend → main

1. **先回后正**（§14.6）在 backend worktree（若 §1 检查通过）：
   ```bash
   git -C D:\intelligence-agent-backend merge origin/main
   ```
   预期冲突极小（backend 自 main 较早分叉，main 移动主要来自 frontend/docs）——若有冲突，按 §14.7 逐文件分析：预计只有 `docs/PHASE_STATUS.md` 追加行，语义并集。完成后在该 worktree 跑该支自己的验证门（基线见其自带手册 `docs/INTEGRATION_PROMPT_STREAMING_UI.md`，在 feat/backend 上）。
2. **合入 main**：
   ```bash
   git -C D:\intelligence-agent merge --no-ff feat/backend -m "Merge feat/backend: ADR-0016 streaming UI batch (T1-T8) — detached-run RunManager + cancel endpoint + after_seq reconnect + reasoning family + tool output stream + multi-model catalog"
   ```
3. **main 侧验证**：`uv sync --all-extras` → `uv run pytest -q`（该支基线，零失败）→ `uv run ruff check src/ tests/` → `git diff --check`。
4. 流式冒烟可参考 backend 自带手册的场景清单（cancel / after_seq / 多模型），本机有凭证则做，无凭证记录跳过原因。

## 3. 第二支：feat/phase14 → main（冲突主战场）

1. **先回后正**在 phase14 worktree：
   ```bash
   git -C D:\intelligence-agent-phase14 merge origin/main   # 此刻 origin/main 已含第一支
   ```
   两支**9 个重叠文件**，全部加法性，逐文件预期如下——若与预期不符即按 §14.7 停下分析：

   | 文件 | backend 改了什么 | phase14 改了什么 | 处理 |
   | --- | --- | --- | --- |
   | `src/agent_harness/session/event.py` | reasoning 事件族 + block_id + STREAM_ONLY 修订 | + `SESSION_FORKED` | 语义并集，两边都要 |
   | `src/agent_harness/session/__init__.py` | 新事件导出 | + SESSION_FORKED 导出 | 并集 |
   | `src/agent_harness/session/session.py` | 流式追加/共持久化路径 | + `adopt_history` 方法 | 预期自动合并；验证 adopt_history 与流式路径互不干扰 |
   | `src/agent_harness/web/app.py` | **大改**（RunManager/cancel/after_seq 重构 create_app） | 仅 2 行 lineage 路由注册（懒 import + 调用） | **重点文件**：把 phase14 的 2 行按语义重放进 backend 的新结构，`GET /api/sessions/{id}/lineage` 必须存活 |
   | `src/agent_harness/cli.py` | 多模型目录/选择参数（T7） | + fork/replay/sessions 子命令与 dispatch 臂 | dispatch 并集，两边命令都要能跑 |
   | `src/agent_harness/model/config.py` | 多模型 catalog 配置 | + zhipu preset | 并集 |
   | `tests/session/test_event_store.py` | 全集断言扩 reasoning/tool 输出族 | 全集断言扩 session/forked | 并集：最终全集 = 两边事件之和 |
   | `docs/PHASE_STATUS.md` | 追加流式批次条目 | 追加 Phase 14 条目 | 两边条目都保留 |
   | `web/src/generated/event-types.ts` | 已再生成 | 已再生成 | **并集 event.py 后必须重新生成**（见下） |

2. **event.py 并集完成后立即再生成前端词表**（在 phase14 worktree）：
   ```bash
   uv run python scripts/gen_event_types.py
   git add web/src/generated/event-types.ts
   ```
   守卫测试 `tests/test_event_types_generated.py` 会兜底：漂移即失败并给出修复命令。
3. **phase14 分支全量验证门**：
   ```bash
   cd D:\intelligence-agent-phase14
   uv sync --all-extras
   uv run pytest -q        # 基线：phase14 自身 1089 passed / 9 skipped / 25 deselected；并集后总数≥该值，零失败
   uv run ruff check src/ tests/
   git diff --check
   # 可选（本机凭证）：uv run pytest tests/integration/test_phase14_gate.py -m integration -v   # 5 passed
   ```
4. **合入 main**：
   ```bash
   git -C D:\intelligence-agent merge --no-ff feat/phase14 -m "Merge feat/phase14: Phase 14 Resume/Replay/Fork (ADR-0017, #107-#115) — file-per-lineage fork + seed + lineage tree + copy-on-fork + tail summary + CLI fork/replay/sessions-tree + read-only web lineage API"
   ```
5. **main 侧终验**：`uv sync --all-extras` → `uv run pytest -q`（零失败）→ `ruff check` → `git diff --check`。冒烟（可选，造会话后）：`agent-harness fork <id> --from-message 1` / `agent-harness sessions --tree` / `agent-harness replay <id>`；流式端冒烟按 backend 手册。

## 4. Push 与收尾

1. 全绿后最后一步：`git -C D:\intelligence-agent push origin main`。
2. `docs/PHASE_STATUS.md` 追加集成记录条目：范围 / 冲突解法（特别是 web/app.py 与 event-types.ts 再生成）/ 验证数字。
3. 向用户报告：完成什么 / 改了哪些 / 测试结果 / commit 区间 / 遗留项。
4. **遗留交接**：Phase 15（Langfuse 观测 + 评测，ADR-0018 已定稿在 feat/phase14 上）将等本任务完成后由 Phase 15 会话从新 main 开工——不需要本任务做任何 Langfuse 相关动作。

## 5. 异常处理

- 任何冲突与预期表不符 / 涉及语义取舍 → 停下，写清两边逻辑与推荐语义，报告用户裁决（§14.7）。
- main 侧合并出现未预料的复杂冲突 → `git merge --abort`，回对应 feature worktree 解决（§14.8）。
- 两支中任一支验证门失败且 30 分钟内无法定位 → 停下报告，不带病 push。
