# 联合集成提示词：UI Polish 六票（前端）+ WS-6/WS-7（前后端两端）→ `main`

> **收件人**：Git Integrator（AGENTS.md §14 授权的集成角色）
> **写于**：2026-09-13（后端 Agent，工作区 `D:\intelligence-agent-backend`）
> **本文件的作用**：把**前端 AI 的交接手册**（`HANDOFF_UI_POLISH_BATCH.md`，UI Polish 六票）与本后端 Agent 的 **WS-6/WS-7 两端提示词**（`INTEGRATION_PROMPT_WS6_WS7_DIR_ROOTED_SESSION.md`）路由成**一条可执行的合并序列**，并把冲突面、门禁、真机清单、以及**前端 AI 提给后端的两个问题**的答案一次讲清。
> **用户授权范围（本次明确）**：解决冲突、`merge`、`push origin main`。
> **仍未授权 / 默认禁止**：`git push --force` / `--force-with-lease`、`git rebase`、`git reset --hard`、`git branch -D`、删除分支、删除 worktree、`git pull`（§14.4/§14.5）。
> **`.env` 的红线**：`D:\intelligence-agent-backend\.env` 的**值**不得出现在任何输出、文档或提交里；只提示"main worktree 需要配置哪些键"（§13.1.6）。

---

## 0. 一句话摘要 + 实测拓扑

**三条源分支、两次合并动作**：先把 WS-6/WS-7 的前端半合进 `feat/frontend`（1 个机械文档冲突），再把 `feat/backend` 与合并后的 `feat/frontend` 依次合进 `main`（**实测零冲突**）。顺序上**后端必须先于前端**：前端半会调用 WS-6/WS-7 的 `cwd` 与 `GET /api/host/dirs`，main 若先合前端会短暂出现"UI 调不存在的端点"，违反 §14.1「main 必须始终可运行」。

**权威 `main` = `cc5eee4`**（`docs(phase-status): record autonomous SDD batch (backend 56c) + WS-3/WS-5/MEM-5 frontend integration) → main`）。本次已 `git fetch origin --prune` 核对：GitHub 的 `origin/main` 与 `D:\intelligence-agent` 的本地 `main` **完全一致**。

> ⚠️ **开工前必做**：三个 clone 的 `origin/main` 远程跟踪缓存**各自陈旧且互不相同**（backend clone 曾停在 `bf81346`、frontend clone 曾停在 `63db650`、integration clone 才是 `cc5eee4`）。**不要在这些缓存上做冲突判断**——第一步统一 `git fetch origin --prune`，再复算 §0.1 的数字；若与下表不一致，**先停下来报告**（说明 main 又动了，冲突面要重算）。

### 0.1 三条分支（以下数字均为 2026-09-13 实测）

| # | 分支 | 所在目录 | tip | 领先 `main` | 待合 commit（旧→新） |
| --- | --- | --- | --- | --- | --- |
| A | `feat/backend` | `D:\intelligence-agent-backend` | 以 `git log -1` 为准（`6054391` 之上再追加**本文件自身**那 1 笔） | **6 + 1** | `50e96a4` → `561b553` → `21c0b06` → `9c158c9` → `a976064` → `6054391` →（本文件） |
| B | `feat/frontend` | `D:\intelligence-agent-frontend` | `b7fb862` | **8** | `0d2ef3a` → `cd107a2` → `1ae3bf2` → `236049f` → `522602d` → `e543ae1` → `d0ddac9` → `b7fb862` |
| B′ | `feat/frontend-ws6-ws7` | `D:\intelligence-agent-frontend-ws6`（**隔离 worktree**，base `522602d`） | `f6b53a7` | **8** | `0d2ef3a` → `cd107a2` → `1ae3bf2` → `236049f` → `522602d` → `f3849ac` → `51fc68c` → `f6b53a7` |

**关键实测结论（决定冲突面为什么这么小）**：

- `feat/backend` 从 `main` 分叉以来**从未触碰 `web/**` 任何文件**（`git diff --name-only origin/main...feat/backend | grep '^web/'` → 空）。
- 反之，B/B′ 的改动面里**没有 `src/agent_harness/**`、`tests/**`**。
- 两侧唯一的共享路径交集 = **恰好一个文件**：`docs/SDD_TICKET_TRACKER.md`（详见 §2.2）。
- **前端手册里"唯一已知冲突仍是 `AGENTS.md` §16"一句已过期**：实测两个 clone 的 `AGENTS.md` **逐字节相同**，且 A/B/B′ 三条分支都没有改它 → **不存在 AGENTS.md 冲突**，不必再去找它。

### 0.2 各批次的详细交接文档（本文件是路由，细节看它们）

| 批次 | 单一入口文档 | 位置 |
| --- | --- | --- |
| A：WS-6/WS-7 后端半 + 审查收口 | `docs/INTEGRATION_PROMPT_WS6_WS7_DIR_ROOTED_SESSION.md`（10 节：契约矩阵 / 门禁 / 两轴审查处置 / 坑点 / 合入后清单） | backend clone |
| A：契约事实源 | `docs/PRD_WS6_WS7_DIR_ROOTED_SESSION_AND_DIR_PICKER.md` + `docs/adr/0027-*.md` + `docs/adr/0028-*.md` | backend clone |
| B：UI Polish 六票 | `docs/HANDOFF_UI_POLISH_BATCH.md`（交接手册）+ `docs/integration/FRONTEND_REFRESH_PERSIST_INTEGRATION_PROMPT.md` §0/§10（前端声明的"集成 AI 唯一入口"）+ `docs/UI_POLISH_PRD.md` / `docs/UI_POLISH_TICKETS.md`（逐票规格） | frontend clone |
| B′：WS-6/WS-7 前端半 | 本文件 §1–§2 + frontend clone `docs/SDD_TICKET_TRACKER.md` 的 `### B-2` 节 | frontend clone |
| 历史（已合入 main，仅备查） | `docs/integration/INTEGRATION_PROMPT_FEAT_BACKEND_PENDING_BATCH.md`（那 12 个 commit 已在 `cc5eee4` 入 main，**不要重复合**） | 两 clone 均有 |
| 合并前自检脚本 | `docs/integration/verify-before-merge.sh`（frontend clone，§14.10 清单） | frontend clone |

---

## 1. 合并序列（§14.6「先回后正」+ §14.9「一次一条」）

### Step 0 — 前置（每条都要做，不要跳）

```bash
git -C D:/intelligence-agent-backend   fetch origin --prune
git -C D:/intelligence-agent-frontend  fetch origin --prune
git -C D:/intelligence-agent           fetch origin --prune

# worktree ↔ branch 映射（§14.2：禁止凭目录名猜 branch）
git -C D:/intelligence-agent-backend   worktree list --porcelain
git -C D:/intelligence-agent-frontend  worktree list --porcelain
git -C D:/intelligence-agent           worktree list --porcelain
```

期望：backend worktree = `feat/backend`（clean）；`D:\intelligence-agent-frontend` = `feat/frontend`（clean）；`D:\intelligence-agent-frontend-ws6` = `feat/frontend-ws6-ws7`（clean）；`D:\intelligence-agent` = `main`（clean）。任一 worktree **dirty 就不要开始**（§14.2）。

### Step 1 — B′ → B：在**前端 worktree** 里合并（唯一需要解冲突的一步）

**为什么在这一步而不是直接两条都合进 main**：B′ 的 base `522602d` 是 **U-2 的功能 commit**，**不含** U-2 的审查修复 `e543ae1` 与 U-3 `d0ddac9`。B′ 与 B 在 `docs/SDD_TICKET_TRACKER.md` 的**同一张批次台账表**上各插了一行/一节 → 有一个机械冲突。按 §14.6/§14.8，**在 feature worktree 解掉它**，不要让冲突进 main。

```bash
cd D:/intelligence-agent-frontend
git status                      # 必须 clean；当前已在 feat/frontend
git merge --no-ff feat/frontend-ws6-ws7
# → 预期恰好 1 个冲突：docs/SDD_TICKET_TRACKER.md（解决规则见 §2.1）
# 解决后：
git add docs/SDD_TICKET_TRACKER.md
git commit                      # merge commit（§14.4：需用户已批准的这次合并动作）
```

合并后**必须立刻在 B 上重跑前端门禁**（§16.6 五连 + §3.2 的隔离端口注意），因为这是第一次把 U-2/U-3 的修复与 WS-6/WS-7 前端半放在同一棵树上：

```bash
cd D:/intelligence-agent-frontend/web
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

**预期**：`g-visual-qa:82`、`r-project-groups:295` 这两条**从红转绿**——它们正是 UI-03 / UI-05 在途修复的目标，而 B′ 侧的 6 条失败是在**没有** `e543ae1` 的 `522602d` 上测出来的（见 §3.2）。若这两条仍红，说明两份 UI 改动在语义上真的打架了 → **停手报告**，不要改测试。

### Step 2 — A → main（后端先合）

对象在两个独立 clone 里，用**本地路径 fetch**（不必先 push feature 分支）：

```bash
cd D:/intelligence-agent
git fetch D:/intelligence-agent-backend feat/backend
git merge --no-ff FETCH_HEAD          # 实测：零冲突
```

合入后立刻跑后端全量门禁（§3.1）。**不要**在这一步顺手动前端。

### Step 3 — B（含 B′）→ main（前端后合）

```bash
cd D:/intelligence-agent
git fetch D:/intelligence-agent-frontend feat/frontend
git merge --no-ff FETCH_HEAD          # 实测：零冲突（但 §2.2 的共享文档要复核）
```

### Step 4 — main 上的完整验收（§4 清单）

后端 + 前端门禁 + **真机一遍**（真 `.env`、真模型、真浏览器）。`main` 必须可运行、可验证（§14.1）。

### Step 5 — push（用户已授权）

```bash
cd D:/intelligence-agent
git log --oneline -6                  # 最后一眼：确认是两条 merge commit + 预期内容
git push origin main
```

**禁止** `--force` / `--force-with-lease`。若 push 被拒（远端有新提交）→ **停手报告**，重新走 Step 0 的 fetch + 冲突复算，**不要**用 force 覆盖别人的提交。

---

## 2. 冲突（实测 `git merge-tree`，非推测）

### 2.1 Step 1 的唯一冲突：`docs/SDD_TICKET_TRACKER.md`（content）

实测命令（只读，不落盘）：

```bash
git -C D:/intelligence-agent-frontend merge-tree --write-tree --name-only feat/frontend feat/frontend-ws6-ws7
# → exit 1，冲突文件恰好 1 个：docs/SDD_TICKET_TRACKER.md
#   web/src/App.tsx / web/src/components/SessionList.tsx / web/src/styles/app.css 均为 Auto-merging（文本零冲突）
```

冲突形态（两边都在**同一张 `### 批次台账` 表**的 U-1 行之后插入）。下面这几行标记**行首刻意留了一个空格**——否则本文件会被 `git diff --check` 和「全仓扫描冲突标记」的集成脚本**永久误判为"未解决的冲突"**（本文件初版正是踩了这个坑，合入 main 后被复查抓到）：

```text
 <<<<<<< our（feat/frontend）
 | **U-2** | ...（含 U-2 审查结论 `e543ae1`）|
 | **U-3** | ...（UI-06 + 收尾）|
 =======
 | **U-2** | ...（旧的「未审」副本）|
 | U-3 | ...（旧的「未审」副本）|
 | **B-2** | **#169/#170 前端半** | **`522602d`**（= 本分支 base）| 零 P0/P1，5 P2 + 6 测试缺口全处置 | `51fc68c` |

### B-2：WS-6/WS-7 前端半（#169 / #170，隔离 worktree）
 ...（整节：隔离缘由 / 门禁 / 5173 复用坑 / 真机证据 / 审查处置 / 未决项）
 >>>>>>> their（feat/frontend-ws6-ws7）
```

**解决规则（唯一正确解，禁止 `--ours` / `--theirs` 一刀切，§14.7）**：

1. **保留 `feat/frontend` 一侧**的 `U-2` / `U-3` 两行 —— 它们是**更新版真相**（U-2 带了审查结论与 `e543ae1`，U-3 带了真实描述）；B′ 侧的这两行是它在 `522602d` 时刻的**过期副本**，删掉。
2. 在 `U-3` 行**之后追加** B′ 侧的 **`B-2` 行**（`#169/#170` 前端半）。
3. 完整保留 B′ 侧的 **`### B-2：WS-6/WS-7 前端半（#169 / #170，隔离 worktree）` 整节**（表格 + 门禁 + 5173 坑 + 真机 + 审查 + 未决）。
4. 文件其余部分**一律不动**。冲突标记清零后 `git diff --check` 必须干净。
5. 结果：一个**台帐表**里 U-1/U-2/U-3/B-2 四行齐备，其后是 UI Polish 章节与 B-2 章节，两者并存 —— 这是预期的最终形态，不是"多出来的东西"。

### 2.2 Step 2 与 Step 3 之间的**唯一共享文件**：`docs/SDD_TICKET_TRACKER.md`

实测：`A` 与 `B` 相对 `main` 的改动**文件名交集恰好是这一个**（`comm -12` 只有一行）。这是同一个文件路径被两个 worktree 当作各自 tracker 使用的历史遗留，两条边的插入点相距约 38 行：

- A（`feat/backend`）：`@@ -23,10 +23,24 @@` → 在"流程切换 + 批次记录（v2）"表附近插入 **+14 行**（WS-6/WS-7 后端半台账）。
- B（`feat/frontend`）：`@@ -61,6 +61,109 @@` 插入 **+103 行**（`### UI Polish 批次` 章节 + 台账行）、`@@ -609,3 +712,18 @@` 插入 **+15 行**（`## 关单补记`）。

**预期干净合并**（两个 hunk 不重叠）。**若仍报冲突**：这是纯粹的 **append-vs-append 文档冲突** → **两边都保留**，按"批次 id 分组、不重排他人条目"合并；**绝不允许**为了消掉冲突标记而删掉任一侧的批次记录。若出现**第三个**冲突文件 → **停手报告**（§14.7）。

### 2.3 文本零冲突但**必须语义复核**的三个文件（B′ ∩ B）

`web/src/App.tsx`、`web/src/components/SessionList.tsx`、`web/src/styles/app.css` 三方合并自动成功，但两份 UI 改动落在同一批组件/CSS 上，**合完要人工过一眼这三点**：

1. **`SessionList.tsx`**：B 侧是 UI-05 的 **Rail 真空态**（`showEmpty` 分支、`rail-empty-btn`），B′ 侧是**项目行 kebab 第一项**与**空项目占位区**（`.rail-empty-action`）。两者是**不同分支 / 不同类名**，必须**同时存在**：真空态（一个项目都没有）走 UI-05 按钮组；某项目下没有会话走 B′ 的「在此项目中新建任务 →」。别让其中一个的 early-return 把另一个吃掉。
2. **`App.tsx`**：两边各自加了 handler / import（B′：`handleStartTaskInProject` + `submitTask(..., { ownError: true })`；B：UI-01 的审批快捷键与 composer 锁定接线）。**检查 `submitTask` 的调用点没有被 UI-01 的改动覆盖**，且 `StartTaskInProjectDialog` 的挂载还在。
3. **`web/src/styles/app.css`**：B′ 的 `.dir-browser*` / `.project-path-callout*` / `.project-textarea*` 块与 B 的 token 体系（UI-02 的 `--text-xs` 12px / tertiary 对比度）**是叠加关系**：确认 `.dir-browser` 内的字号/颜色**走 token**、没有硬编码旧值，且 `.dir-browser-error` 与 `.project-error` 仍旧**是两个类共用一条规则**（这是有意为之，见 A 的提示词 §5.4；合并时别被"合并同类项"的直觉弄成一个）。

> 三方都不动 `web/src/types.ts` / `web/src/lib/api.ts` 的**既有部分**：B′ 往 `api.ts` **新增**了 `getHostDirs` / `startSessionErrorDetail`（加性），B 声明零动 → 无 API 层冲突面。**唯一例外**是 B′ 的 e2e 用到 `e2e/fixtures.ts`（B 未动该文件）。

### 2.4 幻影冲突（明确排除，省掉排查时间）

| 被怀疑的冲突 | 实测结论 |
| --- | --- |
| `AGENTS.md` §16（前端手册 §8 提到的"唯一已知冲突"） | **不存在**：两 clone 逐字节相同，三条分支都没改它 |
| `src/agent_harness/**` / `tests/**` | 只有 A 动 → 与 B/B′ 无交集 |
| `web/**` | 只有 B/B′ 动 → 与 A 无交集 |
| `docs/PHASE_STATUS.md` | **两条边都没在本次待合 commit 里改它**（历史批次已改）。合并完成后**由集成方回填**（§6） |

---

## 3. 门禁（合入后必须在 `main` 上重跑，不引用分支数字）

### 3.1 后端

```bash
cd D:/intelligence-agent
.venv/Scripts/python.exe -m ruff check src/ tests/
.venv/Scripts/python.exe -m pytest -q
```

分支实测（`feat/backend`）：`ruff` All checks passed；`pytest` → **2109 passed / 10 skipped / 42 deselected / 0 failed**。

**已知 flaky（非本次引入，别误判为回归）**：`tests/test_web_api.py::test_disconnect_leaves_run_running_and_cancel_stops_it`（SSE 断连时序竞争，5s 预算随机器负载偶发悬挂；已在 pristine HEAD 复现，PHASE_STATUS #152/#154 三次登记）。它在最后一次全量中**通过**；若这次红了，先隔离复跑该用例再判断。

### 3.2 前端（§16.6 硬要求）

```bash
cd D:/intelligence-agent/web
npx tsc -b && npx vitest run && npx oxlint && npx playwright test --workers=2 && npx vite build
```

| 分支 | 实测终值 |
| --- | --- |
| `feat/frontend`（UI Polish 尾） | tsc 0 · vitest **623 passed**（35 文件）· oxlint **38 warnings / 0 errors** · playwright **196 passed** · vite build ✓ |
| `feat/frontend-ws6-ws7`（B′） | tsc ✓ · vitest **626 passed** · oxlint 0 errors（38 既有 warnings）· playwright **208 passed / 6 failed** · vite build ✓ |

**B′ 那 6 条失败 = 3 个既有用例 ×2 视口**，已在 pristine 基线（`git stash` 掉 B′ 全部改动）同一隔离端口复现：`g-visual-qa:82`、`p-earlier-window:32`、`r-project-groups:295`。其中前两者的目标正是 UI-03/UI-05 → **Step 1 合并后应转绿**（见 §1 Step 1）；`p-earlier-window:32` 若仍红属独立既有项。

**B′ 登记的偶发**：`k-refresh-restore:159`（SSE 时序类）单视口失败过一次，隔离复跑 **3/3 全绿（每次 12 passed）**；`feat/frontend` 与本批 diff 都不触碰 refresh/reconnect 路径。

> ⚠️ **5173 复用坑（务必先读）**：`web/playwright.config.ts` 是 `5173 + reuseExistingServer: !CI`，会把**任何**已监听 5173 的 dev server 当成自己的。本机同时开着多个 worktree 时，e2e 会**静默跑别人的代码**（B′ 实测踩到：新增菜单项"不存在"）。**合并后跑门禁前先确认 5173 上跑的就是 `D:\intelligence-agent\web`**；若被占用，临时用 10 行隔离配置（`baseURL` + `--port 5273 --strictPort` + `reuseExistingServer: false`）跑，跑完删除、**不要入库**。

---

## 4. main 上的真机验收清单（§14.10 + 本批 AC）

真 `.env`、真 uvicorn、真模型、真浏览器。**逐条打勾，不要只看自动化测试**（两条批次都强调过真机）。

**WS-6（#169）**
- [ ] 「新建项目」用手填路径注册一个真实目录 → 侧栏出现该项目。
- [ ] 项目行 kebab **第一项** = 「在此项目中新建任务」；空项目占位区出现「在此项目中新建任务 →」。
- [ ] 确认面**逐字**出现 `Agent 将直接读写该目录：<真实路径>`；权限档显示默认「工作区写入」。
- [ ] 任务「用 read 工具以相对路径读取 `hello.txt`」→ 工具调用成功、复述文件真实内容（**相对路径能成功 = cwd 真的换过去了**）。
- [ ] **全程不出现审批卡**（默认档必须不发 `permission_mode`；出现审批卡 = 这条挂了）。
- [ ] 把该项目目录改名 → 再提交 → 错误**留在确认面**（后端 422 原文、无全局横幅、对话框不关）→ 目录改回后**重试成功**并落组。

**WS-7（#170）**
- [ ] 「新建项目」里的目录浏览器：根模式列出真实盘符（「向上」「选择此目录」在根模式**禁用**）。
- [ ] 点进 `D:\` 一级 → 只列目录、按名排序;进入某子目录后**两个输入框同步回填**。
- [ ] 改上方手填框并回车 → 浏览器**反向跳转**到该路径。
- [ ] 「选择此目录」→ 回执出现 → 注册成功。
- [ ] 路径条输入一个不存在的路径 → 就地显示后端 `detail` 原文（不翻译成"加载失败"）。

**UI Polish（B）**（真机抽查，细节见其交接手册 §5）
- [ ] 触发一次审批 → 卡片结构化参数 + 「Ctrl/Cmd+Enter 批准 / Ctrl/Cmd+Backspace 拒绝」生效，且**只有第一张 pending 卡**响应快捷键。
- [ ] 时间线按 run 分组，组头序数在尾窗裁剪后仍正确（Run 2 仍叫 Run 2）。
- [ ] 时长 <50ms 显示 `<50ms`（无假精度）；ReasoningBlock <1s 显示「持续 <1s」。
- [ ] 暗/亮主题切换后 tertiary 文字仍达 AA（亮色 4.5:1）。

---

## 5. 前端 AI 提给后端的两个问题：**答案**（本次实测，可直接据此关掉 UIP-DEFER）

### 5.1 问题：`tool/approval-requested` 是否携带超时时间戳（用于"还剩 N 秒自动拒绝"倒计时）？

**答案：没有。事件里不存在任何超时/截止/过期字段 → 倒计时不做（UIP-DEFER 关闭）。**

证据（均在已经位于 `main` 的代码里，**不属于本次待合批次**）：

- 事件 payload **全部 11 个字段**，构建于 `src/agent_harness/session/approval.py:60-72`：
  `approval_id` / `tool_name` / `tool_call_id` / `action_type` / `title` / `description` / `arguments_preview` / `permission` / `policy` / `reason` / `allowed_decisions`（固定 `["deny","approve_once"]`）。**无一个与时间相关**。
- 结算事件 `permission/resolved` 只有 3 个字段：`approval_id` / `decision` / `reason`（同文件 `:92-99`）。另注意：**不存在** `tool/approval-resolved` 这个类型。
- **没有**"查询待审批"的 HTTP 端点（只有 `GET /api/permission-modes` 静态枚举与 `POST /api/sessions/{id}/approve`）；待审批状态只能由事件流投影得出（`web/src/types.ts` 的 `PendingApproval` 也是这 11 个字段 + 事件封套的 `time`，不是截止时间）。
- 超时**确实存在**，但只是**服务端设置**：`src/agent_harness/config.py:36-39` `approval_timeout_seconds: float = 300.0`（注释：`≤0 = 无限等待`），由等待协程**内联**用 `asyncio.wait_for` 实施（`src/agent_harness/session/approval.py:74-91` + `tooling/approval_queue.py:59-73`），**没有任何后台任务或调度器**，也**从不发布到事件里**。
- 超时后是 **fail-closed 拒绝**：`reason` = `审批超时（300s 无决策），按 fail-closed 拒绝`，随后 `permission/resolved { decision: "deny" }`。
- 顺带一个容易踩的边界：**工具自身的 `tool.timeout_seconds` 管不到审批等待**——审批发生在 `tooling/executor.py:779`，位置在 `_execute_with_retry` / `asyncio.timeout(tool.timeout_seconds)`（`:816`）**之前**。

**因此**：前端若显示倒计时，就必须自己**硬编码 300s**，而 `approval_timeout_seconds` 可被配置（`≤0` 时**无限等待**、永远不会自动拒绝）→ 属于**不变量 #22（Web UI 不维护第二套不可对账的 Session 真相）** 与用户决策 D4（禁止硬编码 300s）的双重违例。**结论：不做，登记为"无字段，已关闭"。**

**附：超时的“结果”前端其实已经能诚实呈现**——B 批 UI-04 已把 `permission/resolved` 渲染为「审批已决（{decision}）」，超时即 `decision=deny`。若想更进一步把 `reason`（那句"审批超时…"）也显示出来，那是一个**加性、零契约变更**的小改进，**建议单独立票**（不要塞进本次合并）。

### 5.2 问题：本批对后端零契约变更，合并时无冲突面？

**答案：确认成立。** 实测 `feat/backend` 全部待合 commit **从未触碰 `web/**`**；`web/src/types.ts` / `web/src/lib/api.ts` 的既有内容两边都没改（B′ 只**新增**了 `getHostDirs` / `startSessionErrorDetail`）。唯一共享路径是 `docs/SDD_TICKET_TRACKER.md`（§2.2，append 型）。

**但要补一句前端手册没提到的**：本次合并**确实带来两处契约/能力的落地**，前端半已经消费它们——`POST /api/sessions` 的 `cwd`、`POST /api/projects` 的 `sessions_attached`、以及新端点 `GET /api/host/dirs`（含 422/404/403 的 `detail` 文案即契约）。合入后如果 UI 上出现"目录列不出来 / 提交报未知错误"，先查这三处契约是否与 §5.1 引用的 `INTEGRATION_PROMPT_WS6_WS7_*` 一致，而不是先怀疑前端。

---

## 6. 合入后收尾

1. **`docs/PHASE_STATUS.md` 回填**（进度单一事实源，§16.5）：两条批次各一条记录（批次名 / tickets / commit / 门禁数字 / 关单状态 / 集成提示词路径）。这一步**由集成方负责**。
2. **关单状态无需重复动作**：`#169`（WS-6）与 `#170`（WS-7）**已 CLOSED**，关单 comment 里已写明两端 commit 与"集成由集成 AI 执行"。合并完成后**不需要重新开单/关单**；如希望留痕，只在 comment 里补一句"已合入 main @ `<merge sha>`"。
3. **tracker 单一化的建议（仅建议，不在本次动）**：`docs/SDD_TICKET_TRACKER.md` 被 backend / frontend 两个 worktree 共用同一路径，是本次唯一冲突源。后续可以考虑拆分命名空间（如 `SDD_TICKET_TRACKER_BACKEND.md`）或在文件内约定"后端章节 / 前端章节"，避免每次集成都要解同一张表的冲突。**本次不要顺手做**（§8 Scope Lock）。
4. **分支 / worktree 清理需用户单独批准**（§14.4）：`feat/frontend-ws6-ws7` 与隔离 worktree `D:\intelligence-agent-frontend-ws6` 在合入后已无用途，但**删除必须等用户明确批准**。

---

## 7. 一页速查（给集成 AI 的执行顺序）

```text
0. 三个 clone 各 fetch origin --prune；确认 main = cc5eee4；四个 worktree 全 clean
1. cd D:/intelligence-agent-frontend
   git merge --no-ff feat/frontend-ws6-ws7
   → 解 docs/SDD_TICKET_TRACKER.md（§2.1 规则：留 B 的 U-2/U-3 行 + 追加 B′ 的 B-2 行 + 保留 B-2 整节）
   → git add + commit；重跑前端门禁（预期 g-visual-qa:82 / r-project-groups:295 转绿）
2. cd D:/intelligence-agent
   git fetch D:/intelligence-agent-backend feat/backend && git merge --no-ff FETCH_HEAD
   → 后端门禁：ruff + pytest（0 failed）
3. cd D:/intelligence-agent
   git fetch D:/intelligence-agent-frontend feat/frontend && git merge --no-ff FETCH_HEAD
   → 复核 §2.2 共享文档；前端门禁五连（避开 5173 复用坑）
4. §4 真机清单逐条打勾（WS-6 / WS-7 / UI Polish）
5. 回填 docs/PHASE_STATUS.md
6. git push origin main（已授权；禁止 force）
7. 报告：merge sha / 门禁数字 / 真机结论 / 剩余未决（§5.1 的 UIP-DEFER 关闭 + §6.3 建议）
```
