# 本批次交付概览 — feat/frontend `b354896`

**日期**：2026-09-10
**分支**：`feat/frontend`（`D:\intelligence-agent-frontend`）
**状态**：**8 个 commit 已推送 origin**；门禁全绿；工作树干净
**目标**：合入 `main`（当前 `ebb2d68`）——`ahead 8 / behind 6`，实测**无冲突**

> **本文件是本批次交付的权威入口。** 细节分文档见：
> - `docs/integration/MERGE_EXECUTION_ORDER.md` —— **独立合并执行单**（自包含、可直接照做）
> - `docs/integration/FRONTEND_INTEGRATION_PROMPT.md` —— **给集成 AI 的执行指令**（含实测拓扑与冲突预判）
> - `docs/integration/verify-before-merge.sh` —— **集成前预检脚本**（只读、每次重新实测，全绿才 merge）
> - `docs/CODE_REVIEW_FIXES_2026-09-10.md` —— 第一轮 code-review（代码）发现与修复详情
> - `docs/CODE_REVIEW_FIXES_2026-09-10b.md` —— 第二轮 code-review（交接文档）发现与修复详情
> - `docs/T9_TURN_INDEX_DELIVERY.md` —— T9 专项说明（per-turn `turn_index` 的设计推理与核实过程）
>
> ⚠️ **哈希均为快照，集成时以 `git ls-remote` 实测为准。** 预检脚本已内置该纪律。
> ⚠️ **本文件曾滞后 3 个 commit**（2026-09-10 code-review 发现：header 仍写 `eb999bc` / 5 个 commit）。
> 已同步至 `b354896` / 8 个。**判断数量以 `git rev-list --count main..HEAD` 实测为准。**

## 本批 8 个 commit

| commit | 内容 |
| --- | --- |
| `b354896` | docs(T9): 补记原地 `git init` 的遗留副作用——本地 `main` 分支缺失 |
| `85c427d` | docs(integration): 新增集成前预检脚本 `verify-before-merge.sh`（只读、每次实测） |
| `e1990ec` | docs: 交付文档入库——T9 专项说明 + 批次概览 + code-review 说明 |
| `eb999bc` | docs(integration): 集成提示词同步 main 新 tip `ebb2d68` + 本分支 tip `4b45bc5` |
| `4b45bc5` | fix(web): code-review 修复——picker 键盘焦点落到 listbox + 长目录 fixture 去重 |
| `f2b4929` | docs(integration): 重写集成交接提示词至真实拓扑 + Tracker 勘误 |
| `949c92a` | fix(web): F-DEFER-1 补 `.hidden` CSS + e2e；修正被该修复暴露的 4 个坏断言 |
| `cddea36` | feat(web): T9 #139 轮次标签 UI——`turn_index` 落到当轮 + `TurnView` 渲染 |

---

## 一、做了什么

### 1. T9 #139 UI 层补完（`cddea36`）

上一批只做了 `projection` 的会话级 `turn_index`，**漏了 UI 渲染**，且设计有缺陷：会话级字段被最新
run 覆盖 → **所有历史轮次显示同一个数字**。

修复：把 `turn_index` 改为 **per-turn 事实**（`Turn.turn_index`），`RUN_STARTED` 到达时落到
「最后一个 turn」（生产时序：`user/message` 建轮 → `run/started` 携带索引）；`TurnView` 渲染
「第 N 轮」。会话级镜像 `state.turn_index` 保留，向后兼容既有消费方。

新增 8 条测试（projection 4 + Conversation 4）。

### 2. F-DEFER-1 修复（`949c92a`）

三个 picker 都挂了 `model-picker-search-wrap hidden`，但 CSS 里**从来没有 `.hidden` 规则**——
短目录下搜索框一直显示，早前 UX 修复从未生效。补上
`.model-picker-search-wrap.hidden { display: none; }`（cmdk 要求 CommandInput 留在 DOM，
用 display:none 隐藏而非卸载）。

新增 e2e `picker-search-visibility.spec.ts`（5 条）。

### 3. 集成提示词重写与同步（`f2b4929` + `eb999bc`）

旧版写的是 merge-base `5c07fff` / HEAD `4f987fb` / 14-13 ahead——**全部作废**。实际：
T7+T8+T9+深化 C1–C4 **已并入 main**（`9964adc` + `977b319`）。重写为实测拓扑后，
`main` 又前进到 `ebb2d68`（后端 session 集成），再由 `eb999bc` 同步一次。

### 4. code-review 修复（`4b45bc5`）

见 `docs/CODE_REVIEW_FIXES_2026-09-10.md`。三项：
① **回归修复**——`pickControl` 的 `combo.fill('')` 在短目录下挂起 30s，导致 12 条 e2e 失败；
② **catalog drift 去重**——长目录 fixture 抽为 `fixtures.ts` 公共导出；
③ **集成文档 4 处事实错误勘误**（ahead/behind/`cddea36` 归属/merge-tree 哈希/e2e 数量）。

---

## 二、关键决策与重要发现

### 🔍 发现一：F-DEFER-1 修复暴露了 4 个既有 e2e 的"假通过"断言

补 CSS 后，4 个老 spec **立刻失败**——它们用 `[role="combobox"]` 当"浮层已打开"的信号。
但 **cmdk 把 `role="combobox"` 放在 `CommandInput` 本身**：搜索框 `display:none` 时该 role
一并从 a11y 树消失，**且输入框拿不到焦点**（focus 落浮层容器，`page.keyboard.type` 静默无效）。

正确做法：`[role="listbox"]`（CommandList，恒可见）判浮层开启；测搜索过滤需目录 >5 条。
已修正 `model-picker` / `control-row` / `context-providers` / `continuation` / `fixtures`。

### 🔍 发现二（最关键）：浮层打开后焦点落在 popover 容器，不在 trigger 也不在 input

`pickControl` 改用 listbox 判开后，我保留的 `if (combo.isVisible()) combo.fill('')` 使
**12 条 e2e 全挂**。探针实测根因：

- 短目录：`role="combobox"` 被 `.hidden` wrap 包住，**rect 0×0** → `fill` 挂起 30s（不是跳过）
- 长目录：`getByRole('combobox', { name })` **命中 0 个**（aria-label 不落在 input 上）
- **真根因**：`document.activeElement` 是 `DIV[role="dialog"]`，键盘事件没落到 cmdk 的方向键
  承接者（`[role="listbox"]`, `tabIndex=-1`）

**正解**：显式 `[role="listbox"]:visible`.focus() 后再走方向键——长短目录同一路径、无分支。
已固化为 skill `playwright-cmdk-picker`。

### 🔍 发现三：ref 吞没 + 对象库整体清扫

`.git/refs/heads/feat/` 反复被沙箱清扫；`git commit` 在 HEAD 悬空时会造**无父 root commit**
（污染历史）→ 改用 **`commit-tree` 管线**（`read-tree` → `add` → `write-tree` →
`commit-tree -p` → sha 直推），全程不读 HEAD，免疫该故障。

**更严重的一次**（本批施工开始时）：`objects/pack/*.pack` **全部消失**（只剩 `.idx`）、
`refs/` 目录整个不见 → git 直接报 `not a git repository`。恢复方式：原地 `git init` +
`remote add` + `fetch`。**零数据损失**（origin 完好）。见 skill `git-ref-recovery`。

---

## 三、门禁证据（本分支实测，code-review 修复后重跑）

| 门禁 | 结果 |
| --- | --- |
| `npx tsc --noEmit` | **0 错误** |
| `npx vitest run` | **27 files / 416 tests passed** |
| `npx oxlint` | **0 errors / 35 warnings**（全部既有，非本批引入） |
| `npx playwright test` | **58 passed**（chromium-1280 + chromium-1920） |
| `npx vitest run -c vitest.perf.config.ts` | **2 files / 12 tests passed** |
| `npx vite build` | ✓ built |

---

## 四、commit 链与合并预检

```
b354896  docs(T9): 补记原地 git init 的遗留副作用——本地 main 分支缺失
85c427d  docs(integration): 新增集成前预检脚本 verify-before-merge.sh（只读、每次实测）
e1990ec  docs: 交付文档入库——T9 专项说明 + 批次概览 + code-review 说明
eb999bc  docs(integration): 同步 main 新 tip ebb2d68 + 本分支 tip 4b45bc5
4b45bc5  fix(web): code-review 修复——picker 键盘焦点落到 listbox + 长目录 fixture 去重
f2b4929  docs(integration): 重写集成交接提示词至真实拓扑 + Tracker 勘误
949c92a  fix(web): F-DEFER-1 短目录隐藏搜索框——补 .hidden CSS + e2e
cddea36  feat(web): T9 #139 轮次标签 UI——turn_index 落到当轮 + TurnView 渲染
                            ↓ (parent)
                      c00f742  ← merge-base，已在 main 中
```

**拓扑（2026-09-10 18:25 实测）**：

| 项 | 值 |
| --- | --- |
| `feat/frontend` | **`b354896`**（已推送） |
| `main` | **`ebb2d68`** |
| ahead / behind | **8 / 6** |
| merge-tree(`main`, `b354896`) | **`ac73da9`**（仅 tree 哈希，**无冲突段**） |
| 双侧文件交集 | **空**（`comm -12` 交叉验证） |

> ⚠️ 哈希是快照。`main` 会继续前进——**合并前跑预检脚本**（它每次重新实测，不读常量）：
> ```bash
> bash docs/integration/verify-before-merge.sh
> ```
> 或手工：
> ```bash
> git ls-remote origin main feat/frontend
> git merge-tree --write-tree --name-only <HEAD> <main>
> ```
> > 实测记录：`merge-tree(eb999bc, ebb2d68)` = `e0998e9`（17:55）；对 `e1990ec` 重跑得 `bf49e27`；
> > 对 `b354896` 得 **`ac73da9`**（HEAD 前进 → 树哈希随之变化，**属正常**，
> > 无冲突结论不变）。这正是**不该在文档里写死哈希**的实证。

### 四.1 ⚠ 判断「合并带什么进 main」用**三点** diff

`git diff main...feat/frontend`（三点 = `merge-base..feat`）才是合并真正引入的改动（19 文件，
全在 `docs/` + `web/`）。**两点** `git diff main feat/frontend` 会把 main 侧**新增**的后端文件
（`src/agent_harness/session/*.py`）显示成「删除」——**那是假象，别据此误报事故**。
详见 `FRONTEND_INTEGRATION_PROMPT.md` §2.1。

---

## 五、交给集成 AI

1. 把 **`b354896`** 合入 `main`（预计 clean；合并前重跑 `merge-tree` 实测
   或跑 `verify-before-merge.sh`）
2. 回填 `docs/PHASE_STATUS.md`（`FRONTEND_INTEGRATION_PROMPT.md` §6 有建议文本）
3. **推送前实测** `git ls-remote origin main feat/frontend`

> ⚠️ **`D:\intelligence-agent` 与前端仓库不共享对象库**——在 main 侧合并**必须先
> `git fetch origin feat/frontend`**，并使用 `origin/feat/frontend` 这个 ref 名。
> 完整步骤与坑位见 `FRONTEND_INTEGRATION_PROMPT.md` §5。

**未完成项**（详见 `FRONTEND_INTEGRATION_PROMPT.md` §7）：
- C1 深水 `StreamOrchestrator`（`attachLiveStream` 仍约 200 行闭包；风险高，非本轮）
- `session/forked` Timeline 摘要文案、7 个未接线事件类型是否显示（需产品确认）
- `api.ts` 两个 FIELDS 表 amend 四项重复（可选重构）
