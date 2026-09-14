# 集成手册：feat/FIX-test-BUG（BUG-013/014）→ main

> **写给集成 AI / Git Integrator**。本次合并经用户 2026-09-14 明确批准完整链路：
> 提示词 → 无冲突验证 → 合并 main → 推送 GitHub。
> 本文档是合并对象、冲突预测、验证门禁、推送顺序的单一手册。

---

## 1. 合并对象

**分支**：`feat/FIX-test-BUG`（worktree `D:\intelligence-agent-fixbug`）
**基线**：merge-base = `9727344`（= main 当前 HEAD 的前一条，main 上已有）
**领先 main**：5 个 commit，全部在本批次：

| commit | 内容 |
| --- | --- |
| `b556d3a` | fix(prompt): BUG-013 快照瘦身——删 model/tools 变量 + 工具澄清句（#187，已关单） |
| `adb8dc2` | fix(memory): BUG-014 记忆链路弹性——检索 10s/SDK 重试 2 + 抽取/整合退避重试 1（#188，已关单） |
| `0081fe7` | refactor(memory): consolidation 重试的 inline asyncio import 收敛到模块顶部（#188 自审） |
| `91a433c` | docs(phase-status): 登记 BUG-013（#187）与 BUG-014（#188）修复 |

（第 5 个 = 上述 4 个 + 交接时的基线，`git log` 实测为准。）

## 2. 冲突预测（已实测：零冲突）

`git merge-tree --write-tree feat/backend feat/FIX-test-BUG` 输出干净树（exit 0，无 CONFLICT 行）。

**原因**：fixbug 分支动的文件（`prompt/`、`memory/`、`assembly.py`、`capability/wiring.py`、`config.py` + tests）与 backend 分支独有工作（`storage/artifact*`、`web/`）零重叠。

## 3. ⚠️ backend 分支有 2 个未集成 commit（不在本批次范围）

`feat/backend` 领先 fixbug 分支 2 个 commit（**#185 artifact 相关，issue 仍 OPEN**）：

- `a38767d` feat(web): #185 外置 artifact 内容只读 HTTP 接口
- `2c658a2` fix(artifact): #185 AC4 —— MinIO load 不再伪造元数据

**处置**：这 2 个 commit 是另一会话的在途工作、票未关单，**不属于本次合并**。本次只合并 fixbug 分支（用户批准的范围）；backend 在途批次等 #185/#186 完成后由集成 AI 按既有流程另行合并。**不要**顺手把 backend 一起合进来。

**顺序后果**：backend 那批合入 main 后，需重新 fetch/diff/conflict 分析（§14.9 一次一支）。

## 4. 合并步骤（在 `D:\intelligence-agent` main 执行）

```bash
# 1) 对象库独立传对象（backend 仓是独立 clone，fixbug worktree 的对象在那边）
git -C D:/intelligence-agent fetch D:/intelligence-agent-backend feat/FIX-test-BUG

# 2) 预检（应显示 5 个 commit / merge-tree 干净）
git log --oneline main..FETCH_HEAD
git merge-tree --write-tree main FETCH_HEAD

# 3) 合并（无冲突预期；若出现未预测的冲突，按 §14.7/§14.8 停止并 abort 报告）
git merge --no-ff FETCH_HEAD -m "merge(fixbug): BUG-013 快照瘦身+工具澄清(#187) + BUG-014 记忆链路弹性(#188) → main"

# 4) 合并后立即自检（PHASE_STATUS 应同时含两分支条目）
grep -c "BUG-013" docs/PHASE_STATUS.md   # ≥1
grep -c "BUG-014" docs/PHASE_STATUS.md   # ≥1
```

**未跟踪项（不阻塞合并）**：main 工作区有 `?? .env.bak-integration`、`?? docs/INTEGRATION_REPORT_WS6_WS7_UI_POLISH.md`（其他会话产物，保持不动）。

## 5. 验证门禁（合并后、push 前）

在 `D:\intelligence-agent`：

```bash
uv run ruff check src/ tests/          # 必须干净
uv run pytest tests/ -q                # 基线：2140 passed / 20 skipped
```

**已知非失败项（与本次合并无关，不得掩盖也不算 FAIL）**：
- `tests/evaluation/test_eval_skeleton.py` 2 条：真云 Langfuse 测试，需网络凭证，改动前后行为一致（stash 验证过）；
- 并行跑前端 e2e 时 web 传输层可能出现资源竞争 flaky（隔离复跑即绿）。

合并后基线预期与 fixbug 分支实测一致：**2140 passed / 20 skipped / 2 failed（真云）**，若 web flaky 复现按隔离复跑确认。

## 6. push GitHub（用户已批准）

验证门禁通过后：

```bash
git push origin main
```

- push 前先 `git fetch origin --prune` 确认 origin/main 没有新提交（本轮实测 origin/main 与 local main 同步：领先 0 / 落后 0）。
- 若 push 被拒（origin 有新提交），停止并重新分析，**不 force push**。
- push 后验证：`git log origin/main -1` 应显示本次 merge commit。

## 7. `.env` 提示（只提醒，密钥值不进文档）

- 本批无新增 env 键。`memory_search_timeout_seconds` 是 Settings 字段，env 可选（不配 = 默认 10s），**不需要**同步到 `.env`。
- 既有 `EMBEDDING_*` / `MILVUS_*` / `LANGFUSE_*` 键名不变。

## 8. 执行清单（checklist）

- [ ] fetch 对象库 → log/merge-tree 预检（5 commit / 零冲突）
- [ ] `git merge --no-ff FETCH_HEAD`
- [ ] PHASE_STATUS 自检（BUG-013/BUG-014 条目都在）
- [ ] ruff + 全量 pytest 门禁（§5 基线）
- [ ] `git push origin main`（先 fetch 确认无竞争）
- [ ] push 后验证 origin/main tip
