# 合并执行单 — `feat/frontend` → `main`

> **给集成 AI / 执行合并的授权角色。**
> 依据 `AGENTS.md` §14（Git Workflow / Merge Safety）。**merge 与 push 均需用户明确批准。**
>
> **本单是自包含的执行指令。** 全部哈希均为 2026-09-10 18:40 实测值，
> **但执行时应以现场实测为准**（见 §2 的取值纪律）。

---

## 0. 一句话任务

把 `feat/frontend`（tip `697a085`，9 个 commit）合入 `main`（`ebb2d68`）。
**实测无冲突、零文件重叠**，预计 clean merge。

---

## 1. 前置事实

| 项 | 值 |
| --- | --- |
| 待合并分支 | `feat/frontend` = **`697a085109a5922bd1e48f673ef76692fe98c953`** |
| 目标分支 | `main` = **`ebb2d6850fbf333cb586b3885d41985c8ff3ce8d`** |
| merge-base | **`c00f7424927e5fb74ad36c5cb61cfa23095843b7`** |
| ahead / behind | **9 / 6**（非 fast-forward，属正常） |
| 远端 URL | `https://github.com/EricKingWhy/intelligence-agent.git` |

### 1.1 ⚠️ 最重要的前提：两个仓库**不共享对象库**

| | `D:\intelligence-agent`（目标） | `D:\intelligence-agent-frontend`（源） |
| --- | --- | --- |
| `--git-dir` | `.git` | `.git` |
| `--git-common-dir` | **`.git`** | **`.git`** |

`--git-common-dir` 都是 `.git`（**不是** `.../worktrees/...`）→ **两者是两个独立仓库**，
不是 worktree，**对象库不共享**。

**后果（必须遵守）**：

- `D:\intelligence-agent` 里**没有** `feat/frontend` 的对象，
  **必须先 `git fetch origin feat/frontend`**。
- 之后只能用 **`origin/feat/frontend`** 这个 ref 名。
  ❌ 写裸 `feat/frontend` → `fatal: Needed a single revision`（本地无此分支）。

> 2026-09-10 复核：`D:\intelligence-agent` 侧 `fsck --connectivity-only` **干净**，
> `main` = `ebb2d68` 与远端一致。

---

## 2. 取值纪律（**别照抄本单的哈希**）

本单所有哈希是**快照**。理由：`main` 会继续前进；`merge-tree` 的树哈希**随双方 tip 变化**——
本批期间同一命令已给出过 `e0998e9` → `bf49e27` → `f19a1b5` → `ac73da9` → **`c4c0b89`**
（HEAD 每前进一步它就变一次，**这是正常的**）。

**执行前请重取**：

```bash
git ls-remote origin main feat/frontend
```

---

## 3. 冲突预判：**无冲突**（实测）

> 下面的实测在**前端仓库**（`D:/intelligence-agent-frontend`，此处 `main` 与
> `feat/frontend` 两个本地 ref 都存在）执行。**在 main 侧仓库执行时**
> 请改用 §5 步骤 1 的形式（`origin/feat/frontend`，且先 fetch）。

```text
# 前端仓库内（本单作者实测现场）
$ git merge-tree --write-tree --name-only main feat/frontend
c4c0b8995fa698c5860b8ea0154e014df3e58667      # 只有 tree 哈希，无冲突段
```

自 merge-base `c00f742` 以来，双侧改动文件**零重叠**：

| 侧 | 改动 |
| --- | --- |
| `main`（`c00f742..ebb2d68`） | `src/agent_harness/**`（6）+ `CONTEXT.md` + `docs/`(2) = **9 文件** |
| `feat/frontend`（`c00f742..697a085`） | `web/**` + 前端 `docs/**` = **20 文件** |
| 交集 | **空**（`comm -12` 交叉验证） |

### 3.1 ⚠️ 判断「合并带什么进 main」用**三点** diff

✅ `git diff main...feat/frontend`（三点 = `merge-base..feat`）→ **20 文件，全在 `docs/` + `web/`**

❌ `git diff main feat/frontend`（两点）→ 会把 **main 侧新增**的后端文件
（`src/agent_harness/session/approval.py`、`model_switch.py`、`errors.py` 等）
显示成「**删除**」。

**那是假象**——那些文件是 `ebb2d68` 里 main 侧新增的，前端分支从 merge-base 起从未碰过。
「前端快照里没有」≠「合并会删掉」。**别据此误报事故。**

---

## 4. 本批内容（9 个 commit）

| commit | 内容 |
| --- | --- |
| `cddea36` | feat(web): T9 #139 轮次标签 UI——`turn_index` 落到当轮 + `TurnView` 渲染 |
| `949c92a` | fix(web): F-DEFER-1 补 `.hidden` CSS + e2e；修正被暴露的 4 个坏断言 |
| `f2b4929` | docs(integration): 重写集成交接提示词至真实拓扑 + Tracker 勘误 |
| `4b45bc5` | fix(web): code-review 修复——picker 键盘焦点落到 listbox + 长目录 fixture 去重 |
| `eb999bc` | docs(integration): 集成提示词同步 main 新 tip `ebb2d68` |
| `e1990ec` | docs: 交付文档入库——T9 专项说明 + 批次概览 + code-review 说明 |
| `85c427d` | docs(integration): 新增集成前预检脚本 `verify-before-merge.sh` |
| `b354896` | docs(T9): 补记原地 `git init` 的遗留副作用——本地 `main` 分支缺失 |
| `697a085` | docs: 集成交接文档 code-review 修复——消除必然失败的步骤 + 同步权威入口 |

**代码改动只有 3 个 commit**（`cddea36` / `949c92a` / `4b45bc5`），其余 6 个是文档。

**契约接触面**（详见 `docs/integration/FRONTEND_INTEGRATION_PROMPT.md` §4）：

- `Turn.turn_index`：**新增** per-turn 字段（`web/src/types.ts`）
- `projectRunStarted` 同步写 per-turn（`web/src/lib/projection.ts`）
- `TurnView` 改 `export` + 新增 `turnIndex` prop（`web/src/components/Conversation.tsx`）
- **SSE 帧形状 / seq 投影 / `consumeSSE` 零改动**

---

## 5. 执行步骤

```bash
# ────────────────────────────────────────────
# 步骤 0：环境确认（只读）
# ────────────────────────────────────────────
cd D:/intelligence-agent
git status --short                 # 应为干净（§14.2 禁止在 dirty 上 merge）
git rev-parse main                 # 记下 merge 前的 sha（回滚要用）
git ls-remote origin main feat/frontend

# ────────────────────────────────────────────
# 步骤 1：取对象 + 预演冲突
# ────────────────────────────────────────────
# ⚠ 独立仓库，必须先 fetch
git fetch origin feat/frontend

# 预演：应只打印一个 tree 哈希，无冲突段
git merge-tree --write-tree --name-only main origin/feat/frontend
#   ├─ 只有 1 行 tree 哈希  → 无冲突，继续
#   └─ 出现文件名/冲突段    → 停止，按 AGENTS.md §14.7 语义化解决并请用户确认

# ────────────────────────────────────────────
# 步骤 2：合并（需用户批准）
# ────────────────────────────────────────────
git merge --no-ff origin/feat/frontend \
    -m "merge: 前端批次（T9 UI + F-DEFER-1 + code-review 修复 + 交付文档）"
# --no-ff 保留 9 个 commit 的批次边界，便于回溯

# ────────────────────────────────────────────
# 步骤 3：复跑门禁（必做）
# ────────────────────────────────────────────
cd D:/intelligence-agent/web
pnpm install                      # ⚠ main 侧无 node_modules，必须先装
rm -rf test-results dist          # 避开沙箱 safe-delete 守卫（目录文件数 >50 会被拦）
npx tsc --noEmit                  # 期望 exit 0，无输出
npx vitest run                    # 期望 27 files / 416 passed
npx oxlint                        # 期望 0 error / 35 既有 warning
npx vitest run -c vitest.perf.config.ts   # 期望 2 files / 12 passed
npx playwright test               # 期望 58 passed（双 viewport）
npx vite build                    # 期望 ✓ built

# ────────────────────────────────────────────
# 步骤 4：手验（§6 有通过标准）
# ────────────────────────────────────────────
# 在 D:\intelligence-agent 起完整项目做前后端联调

# ────────────────────────────────────────────
# 步骤 5：回填 PHASE_STATUS.md（§7 有建议文本）
# ────────────────────────────────────────────
# ⚠ 该 commit 必须在 merge commit 之后、push 之前（对齐 AGENTS.md §16.4）

# ────────────────────────────────────────────
# 步骤 6：推送（需用户批准）
# ────────────────────────────────────────────
git push origin main
```

**禁止**：`git pull`、在 dirty worktree 上 merge、`rebase`、`push --force`、
未经批准删分支/worktree。（步骤 4 失败时的 `reset --hard` 回滚除外，见 §6。）

---

## 6. 手验通过标准

**必须验两项**（都是本批的真实交付点）：

### (a) T9 轮次标签 —— **这是本批修复的原始 bug，必验**

- 操作：连发 **≥3 轮**消息
- 期望：每轮显示「**第 1 轮 / 第 2 轮 / 第 3 轮**」**逐轮递增**
- ❌ 反例：所有轮次显示**同一个数字** → 说明 per-turn `turn_index` 未正确落位

### (b) F-DEFER-1 短目录行为

- 操作：打开三个 picker（模型 / 权限模式 / 上下文提供者）
- 期望：**短目录**（≤5 条）下**搜索框隐藏**；**长目录**下**显示且可过滤**

### 若 (a) 失败 → **不要 push，回滚**

```bash
git -C D:/intelligence-agent reset --hard <步骤 0 记下的 merge 前 main sha>
# 然后回报前端侧：per-turn turn_index 未生效
```

---

## 7. `docs/PHASE_STATUS.md` 待追加条目（建议文本）

```markdown
- 2026-09-10：**集成记录：feat/frontend T9 #139 UI 补完 + F-DEFER-1 + code-review 修复 → main**。
  commit（tip `697a085`，共 9 个）：`cddea36`（T9 UI）+ `949c92a`（F-DEFER-1 修复）
  + `4b45bc5`（code-review 修复）+ 其余 6 个为交付文档入库与预检脚本。
  交付：①T9 #139 UI 层——`turn_index` 由会话级改为 **per-turn 事实**（`Turn.turn_index`，
  修掉「历史轮次显示同一个数字」的设计缺陷）+ `TurnView`「第 N 轮」渲染 + 8 条测试；
  ②F-DEFER-1——补 `.model-picker-search-wrap.hidden` CSS；
  ③修正被该修复暴露的 4 个既有 e2e 断言缺陷（改用 `[role="listbox"]` 判「浮层已开」）；
  ④code-review 去重：长目录 fixture 抽为 `fixtures.ts` 公共导出；
  ⑤新增 `docs/integration/verify-before-merge.sh` 只读预检脚本。
  **冲突**：无（`merge-tree` 实测 clean；双侧改动零重叠——`main` 侧 `src/agent_harness/**`
  + `CONTEXT.md` + `docs/`(2)，本侧全在 `web/` + 前端 docs）。
  门禁：tsc 0 + vitest 27 files / 416 passed + oxlint 0 error / 35 既有 warning +
  playwright **58 passed**（双 viewport）+ perf 12 passed + vite build OK。
```

---

## 8. 未完成项（**非本批范围**，供知悉）

| 项目 | 状态 |
| --- | --- |
| C1 深化 `StreamOrchestrator` | 部分交付（仅 `ReconnectController`）；`attachLiveStream` 仍约 200 行闭包，提取被判风险过高 |
| C5（`ConversationState` 拆分） | ❌ 已否决（YAGNI + 参考实现反证） |
| `session/forked` Timeline 摘要文案 | 待定（pre-existing） |
| 7 个未接线事件类型 | 待产品确认是否显示 |
| 本批未写 `PHASE_STATUS.md` | 按 §16.4 由集成时回填（见 §7） |

---

## 9. 附：预检脚本（可选，推荐）

若想自动化检查，在前端仓库跑（**只读**）：

```bash
cd D:/intelligence-agent-frontend
bash docs/integration/verify-before-merge.sh
```

它做 6 项检查：环境 / `ls-remote` 实测 / 工作树干净度 / HEAD 对齐 / `merge-tree` /
文件重叠。全绿 exit 0；任一 FAIL 即 exit 1 并给处置提示。

**三条使用须知**：

1. **必须在「先回后正」之前跑。** 它断言「本地 HEAD == `origin/<branch>`」，
   而一旦你在前端分支上产生任何新 commit，此后跑它**必然 FAIL**（属**预期**，非损坏）。
2. **它只覆盖待合并侧**（前端仓库），**检查不了** `D:\intelligence-agent`。
   目标侧请单独确认：`git -C D:/intelligence-agent fsck --connectivity-only`。
3. 门禁复跑它**只打印命令、不代跑**（避免给出误导性的通过结论）。

---

## 10. 回滚与故障处置

| 情形 | 处置 |
| --- | --- |
| 步骤 1 出现冲突段 | 停止，按 `AGENTS.md` §14.7 语义化解决，请用户确认 |
| 步骤 3 门禁红 | **不要 push**；判断是本批引入还是环境问题（`test-results/` 守卫拦截看起来像失败） |
| 步骤 4 (a) 手验失败 | `reset --hard` 回 merge 前 sha（§6） |
| 文件重叠检查非空 | **不等于冲突**，但需人工确认改动可否共存 |
| 发现 `main` 又前进 | 重取 sha、重跑 `merge-tree`；本单所有哈希作废 |
