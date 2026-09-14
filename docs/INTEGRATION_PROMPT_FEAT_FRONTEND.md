# 集成提示词：feat/frontend → main

> **分支**：`feat/frontend` ｜ **Worktree**：`D:\intelligence-agent-frontend`
> **分支尖端**：`d5f2225`（docs 交接）｜ **批次主体**：`a518d3f..4b588af` + `7e79445`/`807b7db`
> **目标**：`D:\intelligence-agent` 的 `main` @ `3a662a9`（已含 feat/backend 全部成果）
> **merge-base**：`46990fb` ｜ **ahead / behind**：`feat/frontend` 10 / `main` 8
> **规模**：21 files, +916 / −151（含 2 份交接文档）
> **合并难度**：✅ **低**——变更路径与 main 侧零交集，`git merge-tree` 实测 0 冲突
> **验证**：本提示词由后端会话独立复跑前端五道门禁后写成（见 §2），非仅引用前端自述
> **批准**：merge / push 均需用户明确批准（AGENTS.md §14.4）

---

## 1. 结论

可以合并。前端 `feat/frontend` 的改动**只落在 `web/**` + 两份 docs + `AGENTS.md`**，
与 main 侧的后端改动（`src/agent_harness/**`、`tests/**`、`docs/**`）**路径零交集**；
后端会话已实测 `git merge-tree --write-tree main feat/frontend` → **exit 0 / 0 conflicts**。

---

## 2. 独立验证证据（后端会话复跑，非引用前端自述）

| 项 | 命令 / 方法 | 结果 |
| --- | --- | --- |
| 路径交集 | `comm -12 <(git diff --name-only 46990fb main) <(git diff --name-only 46990fb feat/frontend)` | **空集**（main 19 路径 / frontend 21 路径） |
| 冲突预判 | `git merge-tree --write-tree main feat/frontend` | exit 0，**0 conflicts** |
| 后端自有文件 | 检查前端 diff 是否含 `src/`、`tests/`、`generated/event-types.ts` | **未触碰**（generated 契约文件保持后端 owned） |
| 类型检查 | `cd web && npx tsc -b` | exit 0 |
| 单元测试 | `cd web && npx vitest run` | **25 files / 377 tests passed** |
| Lint | `cd web && npx oxlint` | **0 errors / 35 warnings**（warning 全为既有） |
| e2e | `cd web && npx playwright test --workers=2` | **46 passed (1.0m)** |
| 生产构建 | `cd web && npx vite build` | ✓ built（仅既有 >500kB chunk 提示） |
| 工作树 | `git -C D:/intelligence-agent-frontend status --short` | 仅 3 项预存 untracked，无未提交改动 |
| 契约一致性 | 人工复核 `api.ts` / `useSession.ts` / `App.tsx` / `projection.ts` | 与后端 `SendMessagePayload` 四字段、422 语义、`tool/approval-requested` / `permission/resolved` 事件名一致 |
| 流式路径 | `projection.ts` diff 逐行 | **纯加法**（新增审批事件分支 + `pending_approvals` 初始字段），SSE 流式路径零改动 |

后端侧基线（main 现状）：`ruff` clean；`pytest -q` **1415 passed / 9 skipped / 39 deselected，0 failed**。

---

## 3. 集成步骤（按 AGENTS.md §14）

### 3.1 前置检查（只读）

```bash
git worktree list --porcelain
git -C D:/intelligence-agent status --short --branch        # 期望：仅预存 untracked，tracked 干净
git -C D:/intelligence-agent-frontend status --short        # 期望：仅 3 项预存 untracked
git -C D:/intelligence-agent-backend log --oneline -1       # 期望 3a662a9 为 main 祖先
git -C D:/intelligence-agent log --oneline -3               # 期望 main @ 3a662a9
```

### 3.2 先回后正（§14.6，需用户批准后执行）

```bash
git -C D:/intelligence-agent-frontend fetch origin --prune
git -C D:/intelligence-agent-frontend merge main
```

- 用**本地 `main`**（不是 `origin/main`）：本地 main 含尚未 push 的后端成果（领先 origin 8 commit）。
- 预期**无冲突**（§2）。若出现冲突：**立即停止**，按 §14.7 逐文件分析后请求用户批准；禁止 `ours`/`theirs` 机械处理，禁止 `git add`。

### 3.3 在 feat/frontend 上复跑门禁（§14.10）

```bash
cd D:/intelligence-agent-frontend/web
npx tsc -b
npx vitest run
npx oxlint
npx playwright test --workers=2
npx vite build
```

> e2e 必须用 `--workers=2`：4 worker 全量并行存在资源竞争型抖动（前端交接 §7.4），非确定性失败。

### 3.4 合入 main（§14.4，需用户批准）

```bash
git -C D:/intelligence-agent merge --no-ff feat/frontend -m "merge(frontend): 续聊 amend 透传 + #37 交互式审批 + #35 主题纪律 → main"
```

> 3.2 之后 `feat/frontend` 已包含 main，默认会 fast-forward；`--no-ff` 保留一个可追溯的集成点（与仓库既有 `Merge branch 'feat/frontend'` 惯例一致）。

### 3.5 main 上验证（§14.10 + §13.3）

```bash
# 后端
cd D:/intelligence-agent && uv run ruff check src/ tests/ && uv run pytest -q
# 前端
cd D:/intelligence-agent/web && npx tsc -b && npx vitest run && npx oxlint && npx vite build
# 前后端联调（用户/集成角色）
# 在 D:\intelligence-agent 起完整项目，走一遍：创建会话 → 续聊（带 amend）→ 审批卡 → 取消/重连
```

### 3.6 push（§14.4，需用户批准）

```bash
git -C D:/intelligence-agent push origin main
```

> 本地 main 领先 origin 8 commit（后端批次），集成后为 9+ commit。push 前确认 main 全绿。

**禁止**：`git pull`、dirty worktree 上 merge、`reset --hard`、`rebase`、`push --force`、未经批准删分支/worktree、在 main 上临时拼接复杂业务逻辑。

---

## 4. 合并后属于预期变化（不是回归）

1. **UI 会开始显示此前被吞掉的错误横幅**（前端 `3560d92`）：viewing-mode 历史加载 effect 原先无条件 `setError(null)`，把 `sendFollowUp` / 重连的失败提示同批抹掉。修复后只在真正切换会话时清错误。联调时看到续聊/重连错误提示属**修复后的正确行为**。
2. **续聊 422 文案变化**：`UNKNOWN_MODEL_ERROR_TEXT` → `CONTINUE_PARAMS_ERROR_TEXT`（`续聊参数无效（422）：请刷新选项后重试`）。create 路径文案不变。
3. **审批卡内联渲染**（#37）：消费既有 `tool/approval-requested` / `permission/resolved` 事件；`postApproval` 请求体改为 `{approval_id, approved, decision}`（与后端 `ApproveRequest` 一致）。

---

## 5. 已知未修项（均不阻塞合并，已由前端交接 §7 记录）

| # | 项 | 性质 | 归属 |
| --- | --- | --- | --- |
| 1 | `context_providers: []` 无法表达「显式零个」 | 契约表达能力 Gap：后端 ADR-0021 定义 `[]`=显式空集 / 缺省=全部；前端「有值才带」使 `[]` 不发键 | **用户 / 后端定契约**，前端再跟 |
| 2 | `isUnknownModelError` 死路径（文案被 `提交失败：`/`续聊失败：` 前缀包裹，精确相等永不匹配） | 存量 bug，**已存在于 main**（`5ecbdba` / `5d47725`）；本批只报告 | 用户决定是否单独立票 |
| 3 | `.hidden` 缺 CSS 规则（模型数 ≤5 时搜索框不隐藏） | 存量 bug，**已存在于 main**（`275d76b`）；已记 `docs/FRONTEND_DEFER.md` F-DEFER-1 | 用户决定是否单独立票 |
| 4 | e2e 4-worker 抖动 | 资源竞争，非确定性；判据用 `--workers=2` | 无需修 |
| 5 | 冻结规格 `reasoning_effort` 误引 `(ADR-0018 D7)`（实际 `79e2860`） | 事实勘误，非需求变更；规格冻结需用户批准 | 后端勘误（`03_RUNTIME_EVENT_CONTRACT.md:617`、`08_DECISION_LOG.md:136`） |
| 6 | WS `snapshot` 帧与 live/SSE 帧形状不一致 | 后端 WS 采用前置项（前端未迁 WS，不影响） | 后端（见 `docs/HANDOFF_FRONTEND_TECH_DEBT.md` §6） |
| 7 | `BACKEND_CONTRACT_STREAMING_UI.md` 缺 WS 章节 | 文档缺口 | 后端（同上） |
| 8 | `tests/web` 三文件重复 fake provider + wiring 注入 | 测试脚手架去重 | 后端（同上，低优先） |

---

## 6. 完成后回报

- 实际 merge 结果（是否 fast-forward / 有无冲突）
- 3.3 与 3.5 两轮门禁的实际输出
- push 是否执行（须用户批准）
- 联调发现的问题（若有）
