# 集成提示词：#190 中心列「输出」面（前端）→ `main`

**一句话**：中心列多了一个「输出」面——把本会话所有命令的输出聚到一处，**只读如实**：
面内明示"本项目命令为一次性执行，无交互终端"，且刻意不出现任何暗示可输入的元素。

工作区：`D:\intelligence-agent-frontend`，分支 `feat/frontend`，基线 `6d040e9`（= #182 的
文档 commit）。**只动前端**。

---

## 1. 本轮 commit

| commit | 内容 |
| --- | --- |
| `8605668` | `feat(panel): #190` 实现 + 测试 + e2e（13 文件，+853 / −171） |
| （随后一条） | `docs(panel): #190` 在途进度登记（`docs/SDD_TICKET_TRACKER.md`）+ 本提示词 |

> 提交信息经一次 **amend**：初版写成"`TerminalTab` 补上 stderr 通道"，与 AC7 事实不符
> （见 §6.1）。未 push，故 amend 安全、无远端影响。

---

## 2. 为什么叫「输出」而不是 Terminal

本项目**没有 PTY**：`sandbox/local.py` 是一次性 `subprocess.Popen`，输出经 `tool/output_delta`
合帧推送。叫 Terminal 等于承诺一个不存在的输入能力（撞 PRD §4"不得伪造"）。
业界**只读**输出的先例都不叫 Terminal——Replit 把 Console（只读日志）与 Shell（可输入）
明确拆成两个东西，GitHub Actions 叫 logs，VS Code 的 Tasks、Chrome 的 Console 同理。
故命名「输出」，并在面内把能力边界说明白（不是免责声明，是如实描述）。

---

## 3. 改了什么

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/commandOutput.ts`（新） | `isCommand` / `commandResult` / `commandOutputs` / `commandOutputText`——"什么算一次命令"的**唯一答案**（AC2 明令不得两处各写一份） |
| `web/src/components/ToolOutputStream.tsx`（新） | 从 `ToolCard.tsx` **原样搬移**（不重写），新增 `showCaret` / `expandable` 两个开关；对话里的工具卡行为逐字不变 |
| `web/src/components/OutputPanel.tsx`（新） | 只读说明（**空态与非空态都有**）+ 按工具调用分组（`#i` / 命令原文 / exit code / 状态）+ 就地展开 + `等待输出…` |
| `web/src/lib/projection.ts` | `allTools(state)` 单一走法：Inspector 的 run 级清单与「输出」面共用 |
| `web/src/components/StepDetail.tsx` | `TerminalTab` 改用 `isCommand` / `commandResult`（**渲染零变化**，AC7） |
| `web/src/lib/capabilities.ts` | `terminal.implemented = true`——与 `App.tsx` 的渲染**成对**，少任何一半都得到空面板 |
| `web/src/App.tsx` | `tab.key === 'terminal'` → `<OutputPanel tools={tools} />`；`tools` 来自 `allTools` |
| `web/src/styles/app.css` | `.output-panel` 一族 + `.tool-out-expand-btn`；`.output-list` 独占滚动（不让面板与输出体各滚一次） |
| `web/e2e/fixtures.ts` | （#182 已备）capabilities mock 够用，本票未改 |
| `web/e2e/x-output-panel.spec.ts`（新） | 7 条 × 2 视口 |
| `web/e2e/workspace-modes.spec.ts` | **按 #182 票面注释翻转骨架期守卫**：`terminal: true` → 出现；`changes` 仍在 #189 |

**新增测试**：`web/src/lib/commandOutput.test.ts`（10）、`web/e2e/x-output-panel.spec.ts`（7 × 2 视口）。

---

## 4. AC 对照（票面 7 条）

| AC | 状态 | 证据 |
| --- | --- | --- |
| 1 命名「输出」+ 面内明示只读 | ✅ | `OutputPanel` 首行 `role="note"`：「只读：本项目命令为一次性执行，无交互终端（不能在此输入或重跑）。」**空态也保留**（e2e 空态用例断言该句仍在） |
| 2 聚合本会话命令输出；分组 + 复制 | ✅ | 聚合抽为 `lib/commandOutput`，`TerminalTab` **反向**改用它（一条走法而非两份实现）；`.output-item` 按 `tool_call_id` 分组；每组自己的工具条带「复制全部输出」 |
| 3 长输出**就地**折叠；截断与 #186 同策略 | ✅ | 尾窗预算 8000 字符；超出时工具条出「展开全部（共 N 字符）/ 收起」，**不新开导航面**；e2e 用 `HEAD_MARKER`/`TAIL_MARKER` 证明"展开前头部不在 DOM、展开后在" |
| 4 能力为假不渲染 | ✅ | e2e：`terminal: false` → tab 与面板都不出现 |
| 5 无任何暗示可输入的元素 | ✅ | e2e 断言面板内 `input/textarea/[contenteditable]` 为 0、"运行"-类按钮为 0、`.stream-caret` 为 0（**运行中**那条也单独锁） |
| 6 e2e：有输出时出现 + 无输入类元素；能力为假不渲染 | ✅ | `x-output-panel.spec.ts` 7 条（含空态、长输出、运行中、无输出） |
| 7 抽聚合逻辑不改 Inspector 既有行为 | ✅ | `TerminalTab` 的渲染表达式逐字未变（仍只渲染 `result.stdout` 与 exit code） |

---

## 5. 门禁基线（供集成时比对）

- `cd web && npx tsc -b` → 0
- `npx vitest run` → **701 passed**
- `npx oxlint` → **0 error**（41 warnings 全为既有；本票新增文件**零 warning**）
- `npx playwright test --workers=2` → **266 passed**
- `npx vite build` → 0

---

## 6. 未交付 / 已知边界（**别当成回归**）

1. **Inspector 的 `TerminalTab` 仍不显示 `stderr`**。它此前只读 `result.stdout`，AC7 明令
   "不得改变 Inspector 侧既有行为"，所以本票**没有**顺手修。而「输出」面经 `ToolOutputStream`
   是**通道保真**的（stdout/stderr 分色）。于是同一个概念在两处看到的内容不同——这是有意
   留下的差异，建议在 #183 里决定是否对齐（本 worktree 已在 tracker 记一笔）。
2. **#186 的"截断策略统一"尚未发生**。本票只保证"就地展开、单一渲染器"这条策略与 #186
   一致；#186 还要把 artifact/diff 的 marker 文案两端对齐、`ChangesTab` 改调 `DiffBlock`。
   提醒一句：`ToolOutputStream` 现在已经是"命令输出"的单一渲染器，#186 再抽
   artifact/diff 的渲染器时**不要**把命令输出也一起重构。
3. **`changes`（「文件/改动」）面仍未实现**（#189）。`centerTabs` 只放行 `implemented` 的面；
   接内容面时必须**同时**改登记表标记与 `App.tsx` 的渲染，否则会得到一个空白面板。
4. `x-output-panel.spec.ts` 里用 `String.fromCharCode(10)` 而不是 `'\n'` 转义——因为生成该
   文件时转义链路过长，写坏过一次（字面量被折成真换行）。这不是风格偏好，是防复发的。

---

## 7. 给集成 AI 的动作（沿用 §14 纪律）

1. `git -C D:\intelligence-agent fetch origin --prune`；`git diff main...feat/frontend` 应只剩
   #182 + #190 的 commit（#182 已关单，见 `INTEGRATION_PROMPT_PANEL_182.md`）。
2. **先回后正**：把 `origin/main` 合进 `feat/frontend`，在 feature 分支上解决冲突、跑门禁
   （§5），**再**合 `feat/frontend` → 本地 `main`。
3. 冲突处理遵循 §14.7：逐文件分析，**禁止**机械 `ours`/`theirs`。本票与 `feat/backend` 的
   #185 **无文件重叠**（前端 vs 后端），预期无冲突。
4. `git push origin main` **需用户明确批准**后再执行；`feat/frontend` 分支本轮**不需要**推。
5. 关单依据：AC 见 §4；#190 的 GitHub issue 由本轮交付方关闭（comment 写明分支/commit 与
   §6 的两条边界）。
