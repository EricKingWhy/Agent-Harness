# 集成提示词：feat/backend → main（#136 审批 fail-closed 超时收口）

> **✅ 已执行（2026-09-10）**：`main` 上 `047f2af merge(backend): #136 审批 fail-closed 超时 + PRD T6 契约勘误 → main`
> （--no-ff，9 files +485/−64，零冲突），main 门禁复跑 **1425 passed / 9 skipped / 39 deselected / 0 failed** + ruff clean。
> 本文件保留为执行记录；后续 feat/backend 开工前需先 `git merge main`（feat/backend 落后 main 2 commit）。

> **分支**：`feat/backend` ｜ **Worktree**：`D:\intelligence-agent-backend`
> **分支尖端**：`6fcc79f`（fix(#136) 审批 fail-closed 超时 + PRD T6 契约勘误）
> **目标**：`D:\intelligence-agent` 的 `main` @ `c689f07`（feat/frontend 集成后）
> **merge-base**：`c689f07` ｜ **ahead / behind**：`feat/backend` 1 / `main` 0
> **规模**：9 files, +485 / −64（3 src + 1 test + 5 docs）
> **合并难度**：✅ **极低**——main 是 feat/backend 的直接祖先，`git merge-tree --write-tree main feat/backend` **exit 0 / 0 conflicts**
> **验证**：后端会话在 feat/backend 上全量复跑（见 §2），无已知 bug
> **批准**：merge / push 均需用户明确批准（AGENTS.md §14.4）

---

## 1. 结论

可以合并。这是一次**单 commit 的收口修复**，只动了 `src/agent_harness/**`、`tests/**`、`docs/**`，
与前端路径（`web/**`）零交集；main 本身是 feat/backend 的祖先（behind=0），
合并既无冲突风险，也不需要反向回并。

**修的是什么**：上一轮 feat/frontend 集成后复查发现 #136 T6 被记为 DONE，但
PRD §2.2 C 的「fail-closed：超时默认拒绝」从未实现——交互式审批
`await queue.wait_for(approval_id)` 无限等待，无人决策的危险工具会永久挂住 run。
本批补齐超时语义，并勘误了两份 PRD 里与 as-built 不符的审批契约。

---

## 2. 独立验证证据（feat/backend 上复跑）

| 项 | 命令 / 方法 | 结果 |
| --- | --- | --- |
| 拓扑 | `git rev-list --left-right --count main...feat/backend` | `0 1`（main 是祖先） |
| 冲突预判 | `git merge-tree --write-tree main feat/backend` | exit 0，**0 conflicts** |
| 空白/标记 | `git diff --check` | clean |
| Lint | `uv run ruff check src/ tests/` | **All checks passed** |
| 新增定向测试 | `uv run pytest tests/session/test_approval_timeout.py -q` | **10 passed** |
| 审批/上下文定向 | 5 个相关测试文件合并跑 | **38 passed** |
| 全量 | `uv run pytest -q` | **1425 passed / 9 skipped / 39 deselected / 0 failed**（= main 基线 1415 + 10） |
| 工作树 | `git status --short` | 仅 6 项预存 untracked（非本批），tracked 干净 |

> 已知非确定性：`tests/web/test_web_batch51_spec_contract.py` 的真服务器用例在
> 组合跑时偶发时序抖动（隔离跑与复跑均绿，全量跑绿）。沿用仓库既有记录口径，
> 不是本批引入，不阻塞合并。

---

## 3. 集成步骤（按 AGENTS.md §14）

### 3.1 前置检查（只读）

```bash
git worktree list --porcelain
git -C D:/intelligence-agent status --short --branch        # 期望：tracked 干净（仅预存 untracked）
git -C D:/intelligence-agent-backend log --oneline -1       # 期望 6fcc79f
git -C D:/intelligence-agent log --oneline -1               # 期望 c689f07
git -C D:/intelligence-agent merge-base --is-ancestor main feat/backend && echo "main 是祖先"
```

### 3.2 先回后正（§14.6）

`main` 已是 `feat/backend` 的祖先（behind=0），**反向回并无事可做**，
直接进入正向合并即可：

```bash
git -C D:/intelligence-agent-backend merge main   # 期望：Already up to date
```

> 不要执行 `git pull`（§14.5）。

### 3.3 合入 main（§14.4，需用户批准）

```bash
git -C D:/intelligence-agent merge --no-ff feat/backend -m "merge(backend): #136 审批 fail-closed 超时 + PRD T6 契约勘误 → main"
```

> 用 `--no-ff` 保留可追溯集成点（与仓库既有 `merge(...)` 惯例一致）。

### 3.4 main 上验证（§14.10）

```bash
cd D:/intelligence-agent
uv run ruff check src/ tests/
uv run pytest -q          # 期望 1425 passed / 9 skipped / 39 deselected / 0 failed
git diff --check
```

前端无需重跑：本批零 `web/**` 触碰。

### 3.5 push（§14.4，需用户批准）

```bash
git -C D:/intelligence-agent push origin main
```

**禁止**：`git pull`、dirty worktree 上 merge、`reset --hard`、`rebase`、
`push --force`、未经批准删分支/worktree。

---

## 4. 合并后属于预期变化（不是回归）

1. **交互式审批现在会超时拒绝**：等待超过 `APPROVAL_TIMEOUT_SECONDS`（默认 300s，
   `≤0` 关闭）仍无决策 → 自动 `deny` 并写 `permission/resolved`。
   联调时若审批卡无人操作，run 会在 5 分钟后以「审批超时…按 fail-closed 拒绝」结束——
   这是修复后的正确行为，不是挂死。
2. **迟到审批变 409**：超时后前端再点批准/拒绝，`POST /api/sessions/{id}/approve`
   返回 409（one-shot），前端应提示「该审批已过期」。
3. **非交互式 session 行为不变**：默认 auto-approve / deny callback 路径不产生审批事件。

---

## 5. 已知未修项（均不阻塞合并）

| # | 项 | 性质 | 归属 |
| --- | --- | --- | --- |
| 1 | GitHub issue #131–#139 仍全部 OPEN | 进度追踪缺口（代码已落地的 T1–T6 未关单） | 用户 / 集成角色决定何时关单 |
| 2 | `CONTEXT.md` 的 “Approval Card” 仍写 `POST /sessions/{id}/approve`（缺 `/api`） | 预存文档漂移，本批只报告 | 用户决定是否单独立票 |
| 3 | 6 项预存 untracked（`docs/INTEGRATION_PROMPT_*.md` ×5 + `docs/goal/GOAL_RUNTIME_REASONING_EFFORT.md`） | 历史会话过程产物 | 用户已决定「不需要动」 |
| 4 | `docs/PRD_ENTERPRISE_MULTI_TURN_SESSION.md` 在 main worktree 中是 **untracked** | 唯一权威 PRD 未进版本控制，其他 worktree 看不到 | 用户决定是否 `git add` |

---

## 6. 完成后回报

- 实际 merge 结果（fast-forward / --no-ff / 有无冲突）
- §3.4 门禁的实际输出
- push 是否执行（须用户批准）
- 是否顺带关闭 T1–T6 的 GitHub issue（需用户授权）
