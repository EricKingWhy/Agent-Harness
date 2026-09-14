# 集成 AI 提示词 — `feat/frontend` 增量：恢复/分叉/滚动 三项缺陷修复 + 按钮巡检

> **给集成 AI（Git Integrator）的执行提示词。**
> 按 `AGENTS.md` §14 集成规则执行；**merge / push 必须用户明确批准**。
> 本文件由前端 Agent 在 `feat/frontend` worktree 完成本轮任务后起草。
> 所有哈希与计数均为**实测值**，仍请在集成时复测（§5 给了命令）。

---

## 0. 一句话

本分支新增 **1 个 commit**（见 §2 tip），交付内容 = 交接手册
`docs/HANDOFF_FRONTEND_RECOVER_FORK_SCROLL.md` 的 **A/B/C/D 四项**（用户实名报告的三条前端缺陷）
\+ 用户要求的**真实浏览器逐按钮巡检**中发现的 2 处缺陷。**未推送远程**（按用户指令，push 归集成 AI）。

---

## 1. 来源与授权链

| 环节 | 依据 |
| --- | --- |
| 用户实名报告 | 「点击了『恢复会话』为什么什么反应也没有？」「点击了『分叉』也啥也没有」「我滑轮往下滚他就自动又上去了」 |
| 交接手册 | `D:\intelligence-agent-backend\docs\HANDOFF_FRONTEND_RECOVER_FORK_SCROLL.md`（item A/B/C/D） |
| 用户授权接管 | `[$ask-matt]`「前端 ai 现在有事情，我授权你帮我修前端吧…修完要跑 code-review」→ 用户选择「停掉前端 AI，我接管做完」 |
| 用户追加要求 | 真实浏览器**每个功能按钮都点一遍**、问题实时写入文档、`/implement` → `/code-review` → 修 → `diagnosing-bug` → 再 `/code-review` 循环到零问题；**不许 push 远程**，完成后写提示词给集成 AI |

---

## 2. 交付清单

**分支**：`feat/frontend`
**本批新增 commit（2 个）**：
- `32356f4` — `fix(web): 恢复/分叉/滚动 三项缺陷修复 + 真实浏览器逐按钮巡检（含 BUG-004）`
- `0d6b82d` — `refactor(web): Inspector 的 Run 摘要收归 runState 单一状态机（deriveRunSummary）`（`/improve-codebase-architecture` 的低风险项）

（前一个 commit `8469a34` = 另一 Agent 的 BUG-001 修复；本批在其之上）

### 2.1 代码

| 文件 | 改动 | 对应 |
| --- | --- | --- |
| `web/src/lib/runState.ts` | `RUN_TERMINAL_TYPES` 收编 `run/interrupted`；新增 `hasUnterminatedRun`；`isRecoverableRun` 改为事件真值判定（末 run 缺终态 OR dangling）；新增纯函数 `recoverDoneMessage` | A |
| `web/src/hooks/useSession.ts` | `RecoverState` 增 `terminalRepaired` / `stillUnterminated` / `stillDangling`；`recover()` 前后各判定一次 | A |
| `web/src/lib/projection.ts` | 新增纯函数 `firstForkableTurnIndex` / `emptyChildTurnIndex`（最早可分叉轮 = `user_message_seq` 最小者，跳过注入轮/无锚点轮） | B |
| `web/src/components/Conversation.tsx` | 分叉按钮锚点用 `user_message_seq`；「child 是空会话」提示只在锚点即第 0 轮时出现；`wheel` 监听（同步脱离跟随 + 嵌套滚动链排除）；`overflow-anchor` 消费 | B/C |
| `web/src/lib/followLatest.ts` | 新增纯函数 `wheelDeltaPixels` / `nestedChainAbsorbs`（嵌套链余量累加 + `deltaMode` 折算） | C |
| `web/src/App.tsx` | 恢复入口判定接入 `isRecoverableRun`；恢复结果条渲染 `recoverDoneMessage`；`run/interrupted` 横幅区分 `step_id` 有无；**fork 在途去重按 origin 会话隔离** + 30s 超时；`Copy Run ID` 仅在有 `run_id` 时出现 | A/B/D + BUG-004 |
| `web/src/components/StepDetail.tsx` | run 时长终态集合改用 `RUN_TERMINAL_TYPES`（原先只认 completed/failed，`run/interrupted` 显示不出时长） | D 连带 |
| `web/src/styles/app.css` | `.conversation-scroll { overflow-anchor: none }`；`.recover-done` 状态条（复用既有 `--success`，**无新 token**） | C/A |

### 2.2 测试

| 文件 | 说明 |
| --- | --- |
| `web/src/lib/runState.test.ts` | `recoverDoneMessage` 8 条分支；`hasUnterminatedRun`；**`run/*` 词表漂移锁**（见 §3） |
| `web/src/lib/followLatest.test.ts` | 新增 11 条：`deltaMode` 0/1/2/未知、向下滚、边界等号、内外层分担、全零链、空链 |
| `web/src/lib/projection.test.ts` | `firstForkableTurnIndex` 6 条（含**乱序 seq** 这条唯一有区分度的） |
| `web/e2e/d-recover.spec.ts`（新） | 6 条：崩溃事件矩阵 + 「只补 run 终态」用例 |
| `web/e2e/b-fork.spec.ts` | B1 断言改为校验完整 `title` 属性（原先只比 12 字符前缀，改回 `step_id` 也过不了） |
| `web/e2e/j-scroll.spec.ts`（新） | 3 条：`overflow-anchor: none`；非流式无浮标；真实滚轮上滚 → 浮标 → 点回底 |
| `web/e2e/i-keyboard.spec.ts` | 新增 Copy Run ID 用例（`expect.poll` 读剪贴板，消除 write/read 竞态），**mutation 验证过** |

### 2.3 文档

- `docs/FRONTEND_ISSUES_LOG.md` —— 缺陷台账（BUG-003 / BUG-004 / OBS-003 / OBS-004 / OBS-005 / OBS-006 / **OBS-007**）+ 43 行逐按钮巡检表 + 真机埋点证据
- `docs/E2E_SCENARIO_MAP.md` —— 用例计数更新（472 vitest / 86 e2e / 16 spec）
- `docs/SDD_TICKET_TRACKER.md` —— 本批状态、门禁、遗留

### 2.4 架构扫描（`/improve-codebase-architecture`，用户要求的收尾步骤）

已扫描热点（`useSession.ts` / `App.tsx` / `api.ts` / `projection.ts`；近 40 次提交里被碰最多的文件），产出 4 个候选：

| 候选 | 结论 |
| --- | --- |
| 1. `StreamOrchestrator`（把 224 行流生命周期从 `useSession.ts` 的 10-ref 协议后抽出） | **Worth exploring，但明确不可无人监督执行**（最热路径、e2e 网薄、语义只在注释里）。仅报告。 |
| 2. `useFollowLatest`（三处接线的合并） | **Speculative**；代码库已显式推迟（ADR-0016，先例 C5 被否决）。仅报告。 |
| 3. Inspector 重新推导 Run 语义 | **已修**（`0d6b82d`）。 |
| 4. `applyEvent` 原地 push 未写在 Interface 上 | 判定今天无实际危害；仅补 `types.ts` 字段级 ⚠ 文档，**不改热路径语义**。 |

扫描报告（只读产物，未入库）：`%TEMP%rchitecture-review-20260911-0345.html`

---

## 3. 需要集成 AI 特别知情的 4 件事

### 3.1 本批含 2 处**超出**交接手册 A/B/C/D 的改动（请一并接受或要求我拆出）

1. **BUG-004（`Copy Run ID` 复制了 session id）** —— 不是手册项，是用户要求「每个按钮都点一遍」时**点出来的**：palette 的 `Copy Run ID` 动作此前调的是 `conversation.session_id`，标签与行为不符（两者都是 UUID，粘出去用错了才发现）。已修 + 有 e2e 锁。
2. **`FORK_TIMEOUT_MS` / `withTimeout`（30s 分叉超时）** —— 用户原始症状是「点分叉啥也没有」。原实现的失败路径只有 `catch`，若请求悬挂则界面**永远没有任何反馈**；超时把「静默悬挂」变成可见错误。

两者均按 `AGENTS.md` §8 登记在 `docs/FRONTEND_ISSUES_LOG.md`，此处显式列出以便集成时**知情接受**。

### 3.2 一项**预存在的界面矛盾已登记但故意未修**（§8 Scope Lock）

**OBS-007**：`projectRunInterrupted` 调 `finalizeRun(state, 'completed')` → 被中断的会话同时显示**绿色「已完成」脉冲**和「上次运行…中断」横幅。属改动前既有行为（本批 `projection.ts` 只新增了 `firstForkableTurnIndex`）。已记录机制、可辩护性、两种修法建议。**请勿在集成时顺手改**——它需要单独决策（是否给 `RunPulseDescriptor` 加第四态）。

### 3.3 词表漂移锁：新测试会替后端「报警」

`web/src/lib/runState.test.ts` 新增的 `run/*` 词表漂移锁会读 **`web/src/generated/event-types.ts`**（后端 `scripts/gen_event_types.py` 的生成物），断言每个 `run/*` 取值都被显式分类（`run/started` 或终态集合）。**后端若新增第四种 run 事件并重新生成该文件，本测试会变红**——这是设计意图（T8 加 `run/interrupted` 时三处枚举集体漏掉，正因没有这道门）。已 mutation 验证：注入 `run/paused` → `expected [ 'run/paused' ] to deeply equal []`。

⚠️ 因此：**若 `main` 上的生成物比本分支新，合并后请重跑 vitest**；变红不是回归，是要求你回答「新类型是不是终态」。

### 3.4 一处**无法用自动化锁定**的竞态（已用真机埋点取证）

滚动的「上滚同步脱离跟随」修复针对的是**子帧竞态**：`wheel` 之后、`scroll` 事件派发之前若有一次 delta 提交，位置法会来不及。任何确定性测试都无法区分「有 wheel 监听」与「只有 scroll 监听」——**请勿因 e2e 通过就删除 `Conversation.tsx` 的 wheel 监听**（该注释已写在源码里，`j-scroll.spec.ts` 文件头也写了）。证据是真机埋点：`before.following:true` → wheel → `suspended:true`，之后 6×250ms 采样 **0 次 PIN** 事件、`gap` 7221→15502 持续拉大。

---

## 4. 已知覆盖缺口（诚实清单，勿当成已验证）

| 项 | 状态 |
| --- | --- |
| `nestedChainAbsorbs` 的 **DOM 走链**那一半（组件内 `parentElement` 循环收集余量） | 无自动化（算术部分已单测） |
| 分叉双击抑制 / 切换会话丢弃在途结果 / 30s 超时 / `forkError` 切回重现 | 无自动化 |
| `StepDetail` 多 run 时长（依赖「run 顺序收口」假设） | 无自动化，注释已标注为假设 |
| 滚动条拖拽（非 wheel）路径的同步脱离 | 无自动化 |
| `ApprovalCard`（#37） | ~~**本 UI 中不可达**，无单测（OBS-006）~~ **勘误（第五轮）**：该结论已证伪——显式选权限档位即开启交互式审批，两键已真机点击并有回归锁 `web/e2e/n-approval-card.spec.ts`。见登记簿 OBS-006 订正条 |
| OBS-005 非默认 amend 档位 → provider 400 | 疑似后端/provider，非前端 |

---

## 5. 集成前预检（建议按序执行）

```bash
# ── 0. 现场确认（§14.2：先确认 repo / worktree / branch / status）──
git -C D:/intelligence-agent-frontend worktree list --porcelain
git -C D:/intelligence-agent-frontend status --short          # 期望：clean
git -C D:/intelligence-agent-frontend log --oneline -3

# ── 1. 复测本分支门禁（§16.6 前端门禁）──
cd D:/intelligence-agent-frontend/web
npx tsc -b
npx vitest run                 # 期望 472 passed / 27 files
npx oxlint                     # 期望 35 warnings / 0 errors（基线，未新增）
npx playwright test --workers=2   # 期望 86 passed（必须 --workers=2，4 worker 有资源竞争抖动）
npx vite build

# ── 2. 拓扑与冲突预判（§14.6「先回后正」）──
git -C D:/intelligence-agent-frontend fetch origin --prune
git -C D:/intelligence-agent-frontend rev-list --left-right --count origin/main...feat/frontend
git -C D:/intelligence-agent-frontend merge-base origin/main feat/frontend
git -C D:/intelligence-agent-frontend merge-tree --write-tree --name-only origin/main feat/frontend

# ── 3. 合并方向：origin/main → feat/frontend（冲突在 feature 侧解决）──
#    在 feat/frontend 上 merge origin/main、复测门禁、稳定后再合入 main
```

**预检实测（本文件写作时）**：

- `feat/frontend` HEAD = `bdb99d1`（+ 本批 1 commit）
- 相对 `origin/main`：**behind 23 / ahead 4**（main 已显著前进）
- merge-base = `697a085`
- `git merge-tree --write-tree --name-only origin/main feat/frontend` → **exit 0，无冲突文件**（当时快照；`main` 继续前进后需复测）

> ⚠️ 上一次集成（`c5149ad` 时期）曾预判 `AGENTS.md` §16 必冲突。本次 `merge-tree` 为干净——但**`main` 每前进一次就作废一次**，请以集成时复测为准。

---

## 6. 建议的进度回填（`docs/PHASE_STATUS.md`，frontend 协议偏离已在案）

按 `AGENTS.md` §16.6，前端在途进度记 `docs/SDD_TICKET_TRACKER.md`，**PHASE_STATUS.md 由集成 AI 在 merge 后回填**。建议条目：

```markdown
- 2026-09-11：**前端缺陷修复批次（恢复/分叉/滚动 + 真实浏览器逐按钮巡检）**。commit `32356f4` + `0d6b82d`
  （feat/frontend → main）。依据 `docs/HANDOFF_FRONTEND_RECOVER_FORK_SCROLL.md` A/B/C/D；
  额外修复 BUG-004（Copy Run ID 复制 session id）+ 分叉超时反馈。
  测试：vitest 472 passed / playwright 86 passed / oxlint 35w0e / tsc + vite build 通过。
  已在真实浏览器 + 真实后端验证 A/B/D 三项（真机回执见 FRONTEND_ISSUES_LOG OBS-003/OBS-004）。
  遗留：OBS-007（中断会话绿色「已完成」脉冲与中断横幅矛盾，预存在，需单独决策）。
  关单：不适用（本批为缺陷修复，非 ticket 交付）。
```

---

## 7. 关单与 push

- **本批不涉及 GitHub issue 关单**（是缺陷修复批次，非 ticket 交付）。
- **本分支未 push**（用户指令：push 由集成 AI 执行）。
- merge / push / PR 均需**用户明确批准**（`AGENTS.md` §14.4）。
