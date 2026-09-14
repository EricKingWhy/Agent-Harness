# 集成 AI 提示词 — feat/frontend → main

> **给集成 AI（Git Integrator）的执行提示词。**
> 按 `AGENTS.md` §14 集成规则执行；merge / push 需用户明确批准。
>
> **本文件已重写（2026-09-10 第四次，18:25）**：上一批 T7+T8+T9+深化 C1–C4 **已经并入 `main`**
> （`9964adc`），`main` 已继续前进到 **`ebb2d68`**（后端 session 集成）。当前 `feat/frontend`
> 有 **8 个前端增量 commit** 待集成，tip = **`b354896`**（已推送）。
> 本文件的哈希全部为实测值，但仍以**集成时实测**为准——或直接跑 §5 的预检脚本。

---

## 0. 任务

把 `feat/frontend` 的**最后一个增量**合入 `main`。

**背景**：T7 #137 / T8 #138 / T9 #139 主体 + 架构深化 C1–C4 **已于 `9964adc` 合入 `main`**，
其后 `977b319` 回填了 `PHASE_STATUS.md`、`ebb2d68` 又合了后端 session 集成。本分支的拓扑是：
`feat/frontend` 从**已进 main 的 `c00f742`** 再前进——因此本批只含**新 commit**，不是重做上一批。

**内容**：
1. **T9 #139 UI 层补完**（`cddea36`）：上一批只做了 `projection` 里的会话级 `turn_index`，
   但**漏了 UI 渲染**，且手册「选项 A」的设计有缺陷——会话级字段会被最新 run 覆盖，
   导致**历史轮次全部显示同一个数字**。本 commit 把 `turn_index` 改为 **per-turn 事实**
   （`Turn.turn_index`）并补上 `TurnView` 的「第 N 轮」渲染。
2. **F-DEFER-1 修复 + 暴露的 e2e 测试缺陷修正**（见 §4.5）。
3. **code-review 修复**（`4b45bc5`）：picker 键盘焦点落到 listbox + 长目录 fixture 去重。
4. **交付文档入库**（`e1990ec` / `85c427d` / `b354896`）：T9 专项说明、批次交付、code-review
   详情、**集成前预检脚本**（§5 推荐用它）。

### 0.1 Commit 清单（相对 `main` = `ebb2d68`；tip = `b354896`）

| commit | 内容 |
| --- | --- |
| `cddea36` | feat(web): T9 #139 轮次标签 UI——`turn_index` 落到当轮 + `TurnView` 渲染 |
| `949c92a` | fix(web): F-DEFER-1 补 `.model-picker-search-wrap.hidden` CSS + e2e；修正被该修复暴露的 4 个既有 e2e 断言缺陷 |
| `f2b4929` | docs(integration): 重写集成交接提示词至真实拓扑 + Tracker 勘误 |
| `4b45bc5` | fix(web): code-review 修复——picker 键盘焦点落到 listbox + 长目录 fixture 去重 |
| `eb999bc` | docs(integration): 集成提示词同步 `main` 新 tip `ebb2d68` |
| `e1990ec` | docs: 交付文档入库——T9 专项说明 + 批次概览 + code-review 说明 |
| `85c427d` | docs(integration): 新增集成前预检脚本 `verify-before-merge.sh` |
| `b354896` | docs(T9): 补记原地 `git init` 的遗留副作用——本地 `main` 分支缺失 |

> **共 8 个 commit**。请以 `git log --oneline <main>..feat/frontend` 实测为准。
>
> ⚠ **`cddea36` 不在 `main` 祖先链上**（`git merge-base --is-ancestor cddea36 ebb2d68` → NO）。
> 上一批合入 main 的是 `9964adc`（其中含 T9 的 `projection` 层）。UI 层补完 `cddea36` 在
> 本分支、**尚未进 main**——这正是本批要合的内容。

---

## 1. Git 拓扑（**2026-09-10 18:25 复核**）

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-frontend` |
| Branch | `feat/frontend` |
| HEAD | `b35489636e189d7902aa9cd263c73864901c84c9` |
| `main`（remote） | `ebb2d6850fbf333cb586b3885d41985c8ff3ce8d` |
| `feat/frontend`（remote） | `b35489636e189d7902aa9cd263c73864901c84c9`（**已推送，与本地对齐，无待推送**） |
| merge-base(`HEAD`, `main`) | **`c00f742`**（即「先回后正」的 merge 点） |
| ahead / behind | HEAD 领先 `main` **8 个 commit**；behind **6 个 commit** |

> **`main` 已从 `977b319` 前进到 `ebb2d68`**（集成 AI 又推了后端集成）。`behind = 6` 即
> `9964adc`(merge) → `977b319`(PHASE_STATUS) → … → `ebb2d68`(后端 session 集成)。
> **这 6 个 commit 改的是 `src/agent_harness/**`（后端 6 文件）+ `CONTEXT.md`
> + `docs/` 下 2 个文件，与
> 本分支零重叠**（见 §2 实测），故合并不是 fast-forward、但**无冲突**。

> ⚠ **本文件历史版本里的 `5c07fff` / `4f987fb` / `14 / 13` / `ahead 1` / `behind 0` /
> `cddea36 已在 main` / `ahead 3` / `behind 2` / `HEAD = 4b45bc5` 全部作废**——
> 那些都是更早快照。**当前唯一有效的是本节的 `b354896` / ahead 8 / behind 6。**

### 1.1 ⚠ `D:\intelligence-agent` 与前端仓库**已互相独立**（2026-09-10 实测）

这一条是本轮最重要的操作前提：

| | `D:\intelligence-agent` | `D:\intelligence-agent-frontend` |
| --- | --- | --- |
| `--git-dir` | `.git` | `.git` |
| `--git-common-dir` | `.git` | **`.git`**（不是 `.../worktrees/...`） |

**两者不共享对象库**（前端不再是 worktree，而是独立 clone）。后果：

- ✅ **好处**：前端那次 `.git` 全毁（pack 全丢）**没有波及 main 侧**——main 侧 `fsck` 干净。
- ⚠ **代价**：`D:\intelligence-agent` 里**看不到 `feat/frontend` 的对象**，
  **必须先 `git fetch origin feat/frontend`**，否则 `git merge origin/feat/frontend` 报
  `unknown revision`。**§5 的步骤已按此调整。**

---

## 2. 冲突预判：**本次无冲突**（2026-09-10 18:25 实测，对 `main = ebb2d68`）

```text
$ git merge-tree --write-tree --name-only main feat/frontend
ac73da9a0608b484d8916e6b251e71ccf442b673      # 只有 tree 哈希，无冲突段
```

> ⚠ 树哈希随 `HEAD` / `main` 变化：`382100d`（对 `cddea36`）→ `8f35c93`（对 `f2b4929`）
> → `e0998e9`（对 `4b45bc5` / `ebb2d68`）→ `bf49e27` → `f19a1b5`（对 `b354896`）
> → **`ac73da9`（本节实测）**。集成时请重跑，勿沿用。

自 merge-base `c00f742` 以来，两侧改动文件**零重叠**（已用 `comm -12` 交叉验证，交集为空）：

| 侧 | 改动文件 |
| --- | --- |
| `main`（`c00f742..ebb2d68`） | `CONTEXT.md` + `docs/INTEGRATION_PROMPT_ARCH_DEEPENING_C1_C3.md` + `docs/PHASE_STATUS.md` + `src/agent_harness/**`（6 个后端文件） |
| `feat/frontend`（`c00f742..b354896`） | `web/**` + 前端 `docs/**`（共 19 个） |

`AGENTS.md` 的 §16 冲突**已在上一批解决**（`9964adc` 之后 `main` 侧只有 `PHASE_STATUS.md` 一处），
本批不再涉及。

> 若集成时拓扑已变（`main` 又前进），**重新跑 `git merge-tree` 实测**，不要沿用本表。
> 或直接跑 §5 的预检脚本（它每次重新实测）。

### 2.1 ⚠ 用**三点** diff，别用两点（**血泪提醒**）

判断「合并会带什么进 main」**必须用三点** `git diff main...feat/frontend`
（等价于 `git diff $(git merge-base main feat/frontend) feat/frontend`）。

**两点 `git diff main feat/frontend` 会给出误导性结论**：它比较的是两个终态快照，
因此把 **`main` 侧新增**的文件（`src/agent_harness/session/approval.py`、
`model_switch.py`、`errors.py` 等）显示成「**删除**」：

```text
# ❌ 两点 diff —— 看起来像合并会删掉后端文件（False alarm）
$ git diff --stat main feat/frontend
 src/agent_harness/session/approval.py    | 150 ----------
 src/agent_harness/session/model_switch.py| 219 -------------
 src/agent_harness/session/errors.py      |  66 -----
 ...

# ✅ 三点 diff —— 合并真正引入的改动，19 个文件全在 docs/ + web/
$ git diff --stat main...feat/frontend
 docs/...  web/...                        (19 files, 1232 insertions(+), 194 deletions(-))
```

那些 `agent_harness` 文件是 **`ebb2d68` 里 main 侧新增的**，前端分支从 merge-base 起
没碰过它们 —— 「前端快照里没有」**不等于**「合并会删掉」。这与 `merge-tree` 的
「无冲突」结论一致。**别据此误报事故。**

---

## 3. 门禁证据（2026-09-10 在本分支实测）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Type check | `npx tsc --noEmit` | **exit 0**，无输出 |
| 单元测试 | `cd web && npx vitest run` | **27 files / 416 tests passed** |
| Lint | `npx oxlint` | **0 errors / 35 warnings**（全部既有，非本批引入） |
| e2e | `npx playwright test` | **58 passed**（双 viewport：chromium-1280 / chromium-1920） |
| 性能 | `npx vitest run -c vitest.perf.config.ts` | **2 files / 12 tests passed** |
| 生产构建 | `npx vite build` | ✓ built（仅既有 chunk-size 提示） |

> ⚠ 上一版写「46 passed」。**修正为 58**：F-DEFER-1 修复新增
> `e2e/picker-search-visibility.spec.ts`（5 条）+ 补齐既有 spec，总数上升。
> 另注：`949c92a` 曾引入一版**回归**（`pickControl` 误用 `combo.fill()`，短目录下挂起
> 30s，致 12 条 e2e 失败），已在 **`4b45bc5`** 内修正，**当前 58/58 全绿**。

> ⚠ **跑 e2e / build 前先 `rm -rf web/test-results web/dist`**——目录文件数 >50 时会被
> 沙箱 safe-delete 守卫拦截，看起来像测试失败，实为环境限制。

---

## 4. 本次契约接触面

### 4.1 新增：per-turn `turn_index`（`web/src/types.ts`）

```ts
export interface Turn {
  // ...
  /** T9 #139：本轮 run 的轮次索引（1-based，来自 run/started data.turn_index）。
   *  per-turn 事实——同轮所有事件共享，供 TurnView 渲染「第 N 轮」标签。
   *  null = 该轮未携带该字段（旧版后端 / 非 run 起始路径）。 */
  turn_index: number | null;
}
```

**为什么改 per-turn**：上一版把 `turn_index` 存在会话级 `ConversationState` 上，每次新 run
都覆盖，历史轮次读到的永远是**最新那个数字**。`run/started` 只携带当轮索引，而
「当轮」在生产时序里 = `user/message`（建轮）之后、`run/started` 到达时的最后一个 turn。

### 4.2 投影（`web/src/lib/projection.ts`）

```ts
function projectRunStarted(state: ConversationState, event: AgentEvent): void {
  state.run_status = 'running';
  const idx = event.data.turn_index;
  if (typeof idx !== 'number' || !Number.isFinite(idx)) return;
  state.turn_index = idx;              // 会话级镜像（Langfuse / turn 元数据消费方）
  const last = state.turns[state.turns.length - 1];
  if (last) {                          // 不用 withTurnAt——它在无匹配时会新建空 turn
    const turn = cloneTurn(last);
    turn.turn_index = idx;
    replaceTurnAt(state, state.turns.length - 1, turn);
  }
}
```

> `state.turn_index` 会话级镜像**保留**（向后兼容既有消费方）；per-turn 字段是新增的真相源。

### 4.3 UI（`web/src/components/Conversation.tsx` + `app.css`）

- `TurnView` 改为 `export`（对齐 `ChainNodeView` 测试模式），新增 `turnIndex?: number | null` prop
- 渲染：`{turnIndex != null && turnIndex > 0 && <div className="turn-index-label">第 {turnIndex} 轮</div>}`
- 实例化处传 `turnIndex={turns[vi.index].turn_index}`
- CSS 新增 `.turn-index-label`（`app.css`）

### 4.4 测试

| 文件 | 新增 |
| --- | --- |
| `web/src/lib/projection.test.ts` | +4：per-turn 落位 / 多轮不互相覆盖 / 无前驱不建孤立轮 / 缺字段保持 null |
| `web/src/components/Conversation.test.tsx` | +4：`TurnView` 标签渲染（`turnIndex` 有值 / null / 0 / 负值） |

### 4.5 F-DEFER-1 修复（**本批附带，值得单独说明**）

**问题**：三个 picker（`ModelPicker` / `ControlPicker` / `ContextProviderPicker`）都挂了
`model-picker-search-wrap${长目录 ? '' : ' hidden'}`，但 CSS 里**从来没有**
`.model-picker-search-wrap.hidden { display: none }` 规则——class 挂了等于没挂，
短目录下搜索框一直显示（与设计意图相反）。

**修复**：补上该 CSS 规则（cmdk 要求 `CommandInput` 始终留在 DOM，故用 `display:none`
隐藏而非条件卸载组件）。新增 e2e `web/e2e/picker-search-visibility.spec.ts`（5 条）锁死行为。

**⚠ 该修复暴露了 4 个既有 e2e 的潜在断言缺陷**（此前因 CSS 缺失而「假通过」）：

| 文件 | 缺陷 | 修正 |
| --- | --- | --- |
| `e2e/model-picker.spec.ts` | 用 `MODELS`（3 条）却断言 `combobox` 可见 + 键入过滤 | 改用长目录（5 模型）；`combobox` 仅作长目录断言；过滤测试保留 |
| `e2e/control-row.spec.ts` | 「键入 ask 过滤」用 3 条 `PERMISSION_MODES` | 拆出独立用例用 6 条长目录测过滤；原用例改用 `listbox` 判开 |
| `e2e/context-providers.spec.ts` | 用 `combobox` 当「浮层已开」信号 | 改用 `[role="listbox"]` |
| `e2e/continuation.spec.ts` | 同上 | 同上 |
| `e2e/fixtures.ts` | `pickControl` / `pickFirstModel` 硬依赖 `combo.fill('')` 建立焦点 | 「浮层已开」改判 `[role="listbox"]:visible`，并**显式 `listbox.focus()`**（见下方「后续发现」） |

**根因**：cmdk 把 `role="combobox"` 放在 `CommandInput` **本身**。搜索框 `display:none` 时，
该 role 也一起从 a11y 树消失，**且输入框拿不到焦点**（focus 落到浮层容器，`type` 静默无效）。
因此「浮层是否打开」必须用 `[role="listbox"]`（`CommandList`，恒可见）判定。

> 这是**修 bug 暴露旧测试的坏断言**，不是本批引入的回归；修正后 e2e **58 passed**（含新 5 条）。
>
> **后续发现（同一 commit 内已修）**：改用 `listbox` 判开后，`pickControl` 一度保留了对
> 搜索框的 `combo.fill('')`。实测证明该调用在短目录下会**永久挂起**（该 `role="combobox"`
> 元素 rect 为 0×0，`fill` 等不到可交互状态 → 30s 超时），且 `getByRole('combobox', { name })`
> 命中 **0** 个（aria-label 不落在 input 上）。**根因**：浮层打开后 `activeElement` 是
> popover 容器 `DIV[role="dialog"]`，键盘事件不落到 cmdk 的方向键承接者。
> **正解**：显式 `[role="listbox"]:visible` `.focus()` 后再走方向键——长短目录同一路径、无分支。
> 该修正已在 **`4b45bc5`** 内（与其余 4 条 spec 的同类修正、长目录 fixture 去重同一 commit）。

### 4.6 明确未动的部分

- SSE 帧形状 / seq 投影 / `consumeSSE` **零改动**
- 未迁 WebSocket；`permission_mode` 不在 `/messages` amend 契约内，未传
- 上一批（T7/T8/深化 C1–C4）的对外接口面**均已并入 main**，本批不重复

---

## 5. 集成步骤

> 📄 **若要一份自包含、可直接照做的执行单**，见 **`docs/integration/MERGE_EXECUTION_ORDER.md`**
> （含取值纪律、FAIL 处置表、手验通过标准、回滚指令）。本节是其精简版。

```text
1. 前置检查（**在待合并侧前端仓库执行**，推荐用脚本，它每次重新实测）
   bash docs/integration/verify-before-merge.sh
   #   ↑ 只读：ls-remote 实测 + 工作树干净度 + HEAD 对齐 + merge-tree + 重叠检查
   #   全绿才继续；FAIL 处置见 §5.3
   #   ⚠ 必须在下一步「先回后正」**之前**跑（时序说明见 §5.1）
   #   ⚠ 脚本只覆盖本仓库，检查不了 main 侧（见 §5.2）

   或手工：
   git -C D:/intelligence-agent-frontend status --short      # 应为干净
   git -C D:/intelligence-agent-frontend log --oneline -3
   git ls-remote origin main feat/frontend                   # 实测两侧 sha

2. 先回后正（§14.6，需用户批准）
   git -C D:/intelligence-agent-frontend fetch origin --prune
   git -C D:/intelligence-agent-frontend merge main          # 预计 clean（见脚本输出）
   # 若 main 又前进且出现冲突 → 停止，按 §14.7 语义化解决并请用户确认

3. 在 feat/frontend 上复跑门禁（§3 六条；先 rm -rf web/test-results web/dist）
   # 该步会在此分支产生新 commit → 此后不要再跑步骤 1 的预检（会因 HEAD≠origin 报 FAIL，属预期，见 §5.1）

4. 合入 main 并验证（§14.4，需用户批准）
   # ⚠ 关键：D:\intelligence-agent 与前端仓库**不共享对象库**（§1.1）
   #    ——它里面没有 feat/frontend 的对象，**必须先 fetch**，否则报 unknown revision
   git -C D:/intelligence-agent fetch origin feat/frontend

   # 预演确认无冲突（应只打印一个 tree 哈希，无冲突段）
   git -C D:/intelligence-agent merge-tree --write-tree --name-only main origin/feat/frontend

   # 合并（--no-ff 保留 8 个 commit 的批次边界）
   git -C D:/intelligence-agent merge --no-ff origin/feat/frontend \
       -m "merge: 前端批次（T9 UI + F-DEFER-1 + code-review 修复 + 交付文档）"

   # 合并后复跑门禁（⚠ 需先 pnpm install，web/ 依赖不随 git 过来）
   cd D:/intelligence-agent/web && pnpm install
   rm -rf test-results dist                  # 相对 web/（避开沙箱 safe-delete 守卫）
   npx tsc --noEmit
   npx vitest run                            # 期望 416/416
   npx oxlint                                # 期望 0 error / 35 warning
   npx vitest run -c vitest.perf.config.ts   # 期望 12/12
   npx playwright test                       # 期望 58 passed
   npx vite build

5. 手验（在 D:\intelligence-agent 起完整项目做前后端联调）
   **通过标准**：
   (a) 多轮会话（连发 ≥3 轮消息）里每轮显示「第 1 轮 / 第 2 轮 / 第 3 轮」**逐轮递增**，
       **不是全部同一个数字** —— 这是 T9 修的原始 bug，必须验。
   (b) 三个 picker（模型 / 权限模式 / 上下文提供者）在**短目录**下**搜索框隐藏**、
       长目录下**显示且可过滤** —— F-DEFER-1 的行为。
   **若 (a) 失败**：说明 per-turn `turn_index` 未正确落位，**不要 push**，
   回滚本次 merge（`git -C D:/intelligence-agent reset --hard <merge 前的 main sha>`）并回报。

6. 追加 PHASE_STATUS.md 记录（§6，纯追加条目，不会冲突）
   # 该 commit 必须在 merge commit **之后**、push **之前**（对齐 AGENTS.md §16.4）

7. push（§14.4，需用户批准）
   git -C D:/intelligence-agent push origin main
```

**禁止**：`git pull`、在 dirty worktree 上 merge、`reset --hard`（步骤 5 的回滚除外）、
`rebase`、`push --force`、未经批准删分支/worktree。

> ⚠ 步骤 4 里 `merge-tree main origin/feat/frontend` 的**参数顺序无关**（`main` 在前或
> `origin/feat/frontend` 在前都行），但**必须都用「已 fetch 到的 ref」**——
> 在 `D:/intelligence-agent` 里直接写 `feat/frontend` 会失败（那是本地分支名，不存在）。

### 5.1 ⚠ 预检脚本的时序（**照顺序执行才不会误判**）

`verify-before-merge.sh` 第 3 项断言「本地 HEAD == `origin/<branch>`」。
因此：

- ✅ **正确**：步骤 1（预检）→ 步骤 2（先回后正）→ 步骤 3（复跑门禁）。
  步骤 2-3 会**在本地产生新 commit**，此后本地 HEAD 必然超前 origin。
- ❌ **错误**：在步骤 2-3 之后再跑预检 —— 第 3 项**必然 FAIL**，
  但那是**预期行为**（本地确实领先），**不是仓库损坏**。

若需在合并前重新确认无冲突，用步骤 4 的 `merge-tree` 命令即可（不依赖 HEAD==origin 断言）。

### 5.2 ⚠ 预检脚本只覆盖**待合并侧**

`verify-before-merge.sh` 硬性要求 CWD = `D:\intelligence-agent-frontend`，
所有检查都针对**该仓库**。它**无法检查** `D:\intelligence-agent`（目标侧）。
目标侧的健康度请单独确认：

```bash
git -C D:/intelligence-agent fsck --connectivity-only   # 应无错误输出
git -C D:/intelligence-agent rev-parse main             # 应 = ls-remote 的 main
```

> 实测记录（2026-09-10）：main 侧 `fsck` 干净、`--git-common-dir` = `.git`
> （即独立仓库，非 worktree），`main` = `ebb2d68` 与远端一致。

### 5.3 FAIL 处置手册（按脚本输出的检查项分类）

| 哪一项 FAIL | 含义 | 处置 |
| --- | --- | --- |
| 1. 远端实测 | `ls-remote` 取不到分支 | 检查网络 / `origin` 配置 / 分支名拼写 |
| 2. 工作树干净度 | 有已跟踪文件未提交 | **先处理**：提交或 stash（§14.2 禁止在 dirty 上 merge） |
| 3. HEAD 对齐 | 本地 ≠ `origin/<branch>` | **先在步骤 1 之前** fetch；若仍在步骤 2-3 之后，属预期（见 §5.1） |
| 4. merge-tree | 有冲突段 | 停止，按 `AGENTS.md` §14.7 语义化解决并请用户确认 |
| 5. 文件重叠 | 双侧改了同一文件 | **不等于冲突**，但需人工确认改动是否可共存，再决定 |

> 未跟踪文件（`--untracked-files=no`）**不判 FAIL**，脚本只以 info 列出。
> 它们**不会**随 merge 进入 main（merge 只处理已跟踪内容），无需清理。

---

## 6. `docs/PHASE_STATUS.md` 待追加条目（建议文本）

```markdown
- 2026-09-10：**集成记录：feat/frontend T9 #139 UI 补完 + F-DEFER-1 + code-review 修复 → main**。
  commit（tip `b354896`，共 8 个）：`cddea36`（T9 UI）+ `949c92a`（F-DEFER-1 修复）
  + `f2b4929`（交接文档）+ `4b45bc5`（code-review 修复）+ `eb999bc`、`e1990ec`、`85c427d`、
  `b354896`（交付文档入库 + 集成前预检脚本）。
  交付：①T9 #139 UI 层——`turn_index` 由会话级改为 **per-turn 事实**（`Turn.turn_index`，
  修掉「历史轮次显示同一个数字」的设计缺陷）+ `TurnView`「第 N 轮」渲染 + 8 条测试；
  ②F-DEFER-1——补 `.model-picker-search-wrap.hidden` CSS（三个 picker 的短目录应隐藏搜索框，
  此前 class 挂了但无规则）；③顺带修正被该修复暴露的 4 个既有 e2e 断言缺陷（用 `combobox`
  当「浮层已开」信号，短目录下该 role 会随搜索框隐藏——改用 `[role="listbox"]`），
  并把 picker 键盘 helper 的焦点显式落到 listbox（原依赖 `fill()` 建立焦点，短目录下会挂起）；
  ④code-review 去重：长目录 fixture 抽为 `fixtures.ts` 公共导出（消除 catalog drift）；
  ⑤新增 `docs/integration/verify-before-merge.sh` 只读预检脚本（6 项实测）。
  **冲突**：无（`merge-tree` 对 `main × b354896` 实测 clean，tree = `ac73da9`；
  两侧改动零重叠——`main` 侧为 `src/agent_harness/**`（6）+ `CONTEXT.md` + `docs/`（2），
  本侧全在 `web/` + 前端 docs）。
  门禁：tsc 0 + vitest 27 files / 416 passed + oxlint 0 error / 35 既有 warning +
  playwright **58 passed**（双 viewport）+ perf 12 passed + vite build OK。
```

---

## 7. 未完成项 & 后续 ticket

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| T7 / T8 / T9 主体 | ✅ 已合入 main | `9964adc` + `977b319` 回填 |
| **T9 #139 UI 层** | ✅ 本批完成 | per-turn `turn_index` + TurnView |
| **F-DEFER-1** | ✅ 本批完成 | CSS 规则 + e2e 全覆盖 |
| **C1 深化（StreamOrchestrator）** | ⚠ **部分交付（已在 main）** | 仅第一刀 `ReconnectController`。剩余：`coalescer` / `stallCheck` / `doTruncatedRebuild` / seq-gap 分流仍在 hook 内，目标形状 `lib/stream-orchestrator.ts`（注入 `fetchStream` / `scheduleTimer` / `clock`）。**风险说明见 `docs/ARCHITECTURE_REVIEW.md`** |
| C5（ConversationState 拆分） | ❌ 已否决 | YAGNI + 参考实现反证 |
| `session/forked` 摘要文案 | 📋 待定 | 已知类型但 Timeline 仍落「未知事件」（pre-existing） |
| 7 个未接线事件类型 | 📋 待定 | `artifact/externalized`、`context/compaction_start\|end`、`message/queued`、`queue/cancelled`、`steer/requested\|applied` 已登记为 `unhandledProjection`，需产品确认是否显示 |

---

## 8. 后端依赖确认

| 后端功能 | 后端 commit | 前端消费方式 | 在 main？ |
| --- | --- | --- | --- |
| `POST /api/sessions/{id}/model` | `ae553ad` (T7) | `changeSessionModel()` | ✅ |
| `POST /api/sessions/{id}/forks` | `ae553ad` (T7) | `forkSession()` | ✅ |
| `model/changed` 事件 | `ae553ad` (T7) | projection `MODEL_CHANGED` | ✅ |
| `run/interrupted` 事件 | `ccebf9a` (T8) | projection `RUN_INTERRUPTED` | ✅ |
| `RUN_STARTED.data.turn_index` | `c438a1e` (T9) | projection `RUN_STARTED` → per-turn | ✅ |

> 本批**无新增后端依赖**——全部消费既有契约。

---

## 9. 集成 AI 注意事项

1. **本批是 8 个 commit 的文档+代码混合批次**，但 `merge-tree` 实测**无冲突**，
   改动面清晰（`web/**` + 前端 `docs/**`）。不要把它当成上一批那样的大重构
   ——上一批已在 `9964adc` 完成。
2. **`web/src/generated/event-types.ts` 本次未改**——若后端 `session/event.py` 后续变化，
   在后端 worktree 跑 `uv run python scripts/gen_event_types.py` 后同步。
3. **e2e 断言用 `[role="listbox"]` 判「浮层已开」是刻意的**（§4.5）——不要改回 `combobox`。
   picker 键盘 helper 也**不要**再对搜索框调 `fill()`（短目录下会挂起 30s）。
4. **推送前先实测远端 sha**（本文件哈希会随修订变化）：`git ls-remote origin main feat/frontend`。
5. **工作区清洁度**：`test-results/` 与 `docs/HANDOFF_WORKBUDDY_FRONTEND.md` 等为过程产物，
   提交时不要纳入（`test-results/` 应在 `.gitignore`）。
6. **合并方向**：`feat/frontend` ahead 8 / behind 6，合并不是 fast-forward——`main` 侧那 6 个
   commit 只碰 `src/agent_harness/**` + `CONTEXT.md` + `docs/` 下 2 个文件，与本分支**零重叠**，
   预计 clean。若 `main` 又前进，重跑 `git merge-tree` 实测（或跑 §5 预检脚本）。
7. **`D:\intelligence-agent` 与前端仓库不共享对象库**（§1.1）——在 main 侧合并
   **必须先 `git fetch origin feat/frontend`**，然后使用 `origin/feat/frontend`
   这个 ref 名（**不是** `feat/frontend`）。这是本批最容易踩的坑。
8. **判断「合并带什么进 main」用三点 diff** `main...feat/frontend`（§2.1）。
   两点 diff `main feat/frontend` 会把 main 侧**新增**的后端文件显示成「删除」——
   **那是假象，别据此误报事故**。
