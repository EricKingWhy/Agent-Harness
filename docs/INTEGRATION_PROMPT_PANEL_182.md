# 集成提示词：#182 删 Split/Preview + 能力声明显隐骨架（前端）→ `main`

**一句话**：中心列不再是"固定模式条"，而是**由 `GET /api/capabilities` 驱动**的 tab 集
（`Chat` 恒存在，其余面声明为真时出现）。此前前端对能力目录**零消费**。

工作区：`D:\intelligence-agent-frontend`，分支 `feat/frontend`，基线 `3706e9b`。
本票**只动前端**，但其消费的端点在后端（`src/agent_harness/web/app.py:903-943`，早已存在）。

---

## 1. 本轮 commit

| commit | 内容 |
| --- | --- |
| `9320e72` | `feat(panel): #182` 实现 + 测试 + e2e 守卫（9 文件） |
| （随后一条） | `docs(panel): #182` 在途进度登记（`docs/SDD_TICKET_TRACKER.md`）+ 两张票面/PRD 的顺序订正 |

---

## 2. 改了什么

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/capabilities.ts`（新） | **声明键 → 可见名的唯一登记处**（声明 `terminal`、渲染成「输出」；PRD §3.5：本项目无 PTY，叫 Terminal 等于承诺不存在的输入能力）；响应解析（防御式）；显隐派生（数据拿不到/空目录 → PRD 缺省 `chat`+`timeline`；多能力**取并集**）；tab 集派生（恒含 Chat；**声明为真但尚无实现的面不渲染**）；选中面失效的落点；方向键/Home/End 目标键 |
| `web/src/components/WorkspaceTabs.tsx`（新） | `role="tablist"` + roving tabindex；键盘只把事件接回上面的纯函数（本仓无 jsdom，语义在单测、接线在 e2e） |
| `web/src/App.tsx` | 删 `WORKSPACE_MODES` / `RESERVED_MODE_NOTE` / `.workspace-mode-bar`；加能力拉取（失败降级、不阻塞）；**每个可见面各一个稳定 id 的 tabpanel**（非激活 `hidden`，不卸载） |
| `web/src/styles/app.css` | `.workspace-mode*` → `.workspace-tab*`（同一视觉语言）；新增 `.workspace-panel` 与 `.workspace-panel[hidden]` |
| `web/src/lib/api.ts` | `getCapabilities()`（失败抛错，由消费方降级——不在 api 层静默填缺省） |
| `web/e2e/fixtures.ts` | capabilities mock + 错误注入 + `onCapabilitiesGet` 计数口 |
| `web/e2e/workspace-modes.spec.ts` | 改写为守卫（7 用例 × 2 视口） |

**新增测试**：`web/src/lib/capabilities.test.ts`（27）、`web/src/components/WorkspaceTabs.test.tsx`（4）、
`web/e2e/workspace-modes.spec.ts`（7）。

---

## 3. AC 对照（票面 7 条）

| AC | 状态 | 证据 |
| --- | --- | --- |
| 1 删 Split/Preview 与 `reserved` 残留；spec 改为守卫 | ✅ | `App.tsx`/`app.css` 无 `.workspace-mode*` 存活代码；`workspace-modes.spec.ts`：「Workspace 模式」工具条、Split/Preview 按钮、预留文案全部 count 0 |
| 2 tab 集 = Chat + 声明为真的面 | ✅（结构）/ ⚠ 可观测性见 AC6 | `capabilities.ts::centerTabs`；单测 + e2e |
| 3 数据不可得 → 缺省语义；Chat 永不消失 | ✅ | 空目录 / 404 两条 e2e 都断言「恰好 Chat」且 `aria-selected=true`；单测覆盖 `always` 绕过声明 |
| 4 声明为假不渲染；名称↔键显式登记 | ✅ | 单测断言 `terminal`→「输出」且**任何**面名都不含 Terminal；登记表是唯一来源 |
| 5 `aria-selected` 如实、可 Tab 到达、方向键可移动 | ✅ | SSR 单测锁 ARIA/roving tabindex；方向键语义在纯函数单测（含环绕/Home/End/无关键返回 null）；e2e 锁真实接线（单 tab 原地不动、焦点不丢） |
| 6 两组 mock 断言 tab 集恰好符合声明 | ⚠ **骨架期口径** | 今天只有 Chat 有实现，所以真/假两组渲染结果相同；e2e 把两组并排断言"差别只在 `implemented`"，并用 `onCapabilitiesGet` 计数证明**端点确实被消费且无请求循环**。完整的"声明为真 → 出现"要等 #189 / #190（票面已记，且它们要翻转本 spec 的骨架期守卫） |
| 7 不改三区几何与 Conversation/Composer | ✅ | e2e 断言 `.app-regions` 三轨为 `240px / 1fr / 320px` 且输入框与对话可见；全量 e2e 252 passed |

---

## 4. 集成后**必须真机**验证的点

1. 打开应用 → 中心列顶部是 tab 条且只有 `Chat`（本部署 `CAPABILITIES=""` 时后端返回空目录，
   落到缺省语义——**与今天的界面一致**，不是回归）。
2. 若在 `.env` 里装配了声明 `surfaces` 的能力（当前无能力填 `surfaces`，`app.py:911` 有记），
   tab 才可能变多——**但今天没有面实现**，所以仍然只有 Chat；这是 #182 的诚实边界，不是 bug。
3. 键盘：`Tab` 能落到 tab 条、`←/→/↑/↓/Home/End` 不把焦点丢出条外（单 tab 时原地不动）。
4. 三区几何与对话滚动/输入行为与合并前一致（全量 e2e 已覆盖，真机再扫一眼）。

---

## 5. 门禁基线（供集成时比对）

- `cd web && npx tsc -b` → 0
- `npx vitest run` → **690 passed**
- `npx oxlint` → **0 error**（41 warnings 全为既有，无本票新增）
- `npx playwright test --workers=2` → **252 passed**
- `npx vite build` → 0

---

## 6. 未交付 / 已知边界（**别当成回归**）

1. **`changes` / `terminal` 两个面今天不渲染**——它们没有实现（#189 / #190）。`centerTabs`
   只放行 `implemented` 的面；接内容面时必须**同时**改登记表标记与 `App.tsx` 的渲染，
   否则会得到一个空白面板（票面与代码注释都写了这一条）。
2. **AC6 的完整口径待 #189 / #190**（见 §3），并且它们要**翻转** `e2e/workspace-modes.spec.ts`
   的骨架期守卫。这是有意留下的、有注释的临时断言，不是遗漏。
3. `centerTabs(surfaces, registry)` 的第二个参数是**单测用的纯函数入参**，生产不传——
   code-review 提过它是否算"为未来造抽象"，保留的理由：它让"实现落地后同一函数即渲染"
   这条规则可测（写在 docstring 里）。
4. 能力多来源时取**并集**（"装配进来的某个能力能产出该面即可见"）。前端没有"当前能力"这个
   概念（后端不暴露），不发明它；若将来后端给出 active capability，这里要重新评估。

---

## 7. 给集成 AI 的动作（沿用 §14 纪律）

1. `git -C D:\intelligence-agent fetch origin --prune`；`git diff main...feat/frontend` 应只剩
   本票两个 commit（本 worktree 在自己这轮之前已与 origin/main 同步过）。
2. **先回后正**：把 `origin/main` 合进 `feat/frontend`，在 feature 分支上解决冲突、跑门禁（§5），
   **再**合 `feat/frontend` → 本地 `main`。
3. 冲突处理遵循 §14.7：逐文件分析，**禁止**机械 `ours`/`theirs`。本票与 `feat/backend` 的
   #185 **无文件重叠**（前端 vs 后端），预期无冲突。
4. `git push origin main` **需用户明确批准**后再执行；`feat/frontend` 分支本轮**不需要**推。
5. 关单依据：AC 见 §3；#182 的 GitHub issue 由本轮交付方关闭，关单评论会写明分支与 commit、
   以及 AC6 的骨架期口径。
