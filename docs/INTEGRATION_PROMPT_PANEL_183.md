# 集成提示词：#183 Inspector 升级（前端）→ `main`

**一句话**：Inspector 从"清单**或**详情"改成"清单**+**详情（Linear peek 同源模式）"，
配套 peek 升级链：↑↓ 换条目、Esc 关闭不卸载、Space 快按/按住、钉住跨会话、整页宽读、
可拖宽 320→480（全部视图状态，不持久化）。

工作区：`D:\intelligence-agent-frontend`，分支 `feat/frontend`，
基线 `2ae4e38`（= #184 的文档 commit）。**只动前端**。

---

## 1. 本轮 commit

| commit | 内容 |
| --- | --- |
| `6426a55` | `feat(panel): #183` 实现 + 测试 + e2e（8 文件，+631 / −97） |
| （随后一条） | `docs(panel): #183` 在途进度登记（`docs/SDD_TICKET_TRACKER.md` § 第十八轮）+ 本提示词 |

---

## 2. 改了什么

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/inspectorPanel.ts`（新） | 纯逻辑：拖宽夹取（320→480 + 中心列保护）/ ↑↓ 边界（不环绕）/ Space 快按阈值 / Esc 三层语义 / 清单行身份 |
| `web/src/components/StepDetail.tsx` | 去掉事件级**早退分支** → `.detail-body` = 清单 + 选中项详情两块独立滚动区；面板键位（↑↓/Esc/Space）；头部 钉住/整页/关闭 + 左缘拖宽手柄；行 `aria-current`；Timeline 按需扩窗 + 选中项滚进视野；工具 Output 段改走中心列同一个 `ToolOutputStream` |
| `web/src/App.tsx` | 面板视图状态（`pinned`/`expanded`/`width`/`peekOpen`）+ `onPanelAction` 单入口；栅格改用 `--inspector-w`；整页 class；命令面板新增"整页打开 Inspector"；未钉住时"离开会话"收起面板 |
| `web/src/styles/app.css` | `.detail-resizer` / `.detail-ctrl` / `.detail-peek*` / `.timeline-row.sel` / `.detail-terminal-row.sel` / `.inspector-fullpage` / `.detail-peek[hidden]` |
| `web/e2e/y-inspector-peek.spec.ts`（新） | 7 条 × 2 视口 |
| `web/src/components/StepDetail.peek.test.tsx`（新） | 结构契约 13 条 |
| `web/src/lib/inspectorPanel.test.ts`（新） | 纯逻辑 19 条 |
| `web/src/components/StepDetail.test.tsx` | 补齐新增 props（既有 18 条不变） |

**零后端改动、零新 API、零契约变更。**

---

## 3. 行为语义（评审时要看的三条，都不是默认套路）

1. **钉住 = 面板跨会话保持展开**。未钉住时**只有"离开一个正在看的会话"**（切到另一个
   会话）才收起面板；**首次进入不算离开**（否则"点开第一个会话"会把手动打开的面板
   关掉）。选中项属于它所在的会话，换会话必清选中——不拿 A 会话的事件站在 B 会话里
   （不变量 #22）。
2. **Esc 三层**：整页 → 退回；有预览 → 关预览（面板与清单留在原地）；否则 → 收起面板。
   面板内的 Esc 调 `stopPropagation`，所以**不会**同时触发全局"中断流式"；焦点在面板外
   时 Esc 仍归全局中断（既有行为）。
3. **拖宽的上限用实测值**（拖拽开始时的「中心列 + 面板」宽度），不是 viewport 减常量：
   rail 在 <820px 变 56px，用常量会在断点上算错。中心列保底 360px 由夹取函数负责，
   没给中心列加 `min-width`（栅格溢出 + `overflow:hidden` 会直接裁掉，比压窄更糟）。

---

## 4. 门禁（全绿）

```
cd web
npx tsc -b                            # 0
npx vitest run                        # 749 passed（+32）
npx oxlint                            # 0 error / 44 warnings（= 基线，新文件与新代码零 warning）
npx playwright test --workers=2       # 286 passed（+14）
npx vite build                        # 0
```

---

## 5. 集成时要注意

- **无契约变更**：`App.tsx` 只加状态与 props，`StepDetail` 的 props 新增 `panel` +
  `onPanelAction`（唯一调用方是 `App.tsx`），其它组件未动。
- **一处既有行为被扩大**：没有钉住时切换会话会收起 Inspector（这是 AC4 的语义）。
  已跑全量 e2e 确认既有 272 条无回归。
- **未做的相邻项（Scope Lock）**：`ChangesTab` 内联 `.diff-cols` → `DiffBlock` 的收敛
  属 **#186 AC3**；`tabCounts.terminal` 与 `TerminalTab` 行判据不一致（`name === 'bash'`
  vs `isCommand`）是既有小账，已在 tracker 留痕，未在本票顺手改。
- **不建议只合本票**：本批的审查按 v2 批量循环跑（#183 + #189 一起，fixed point
  `2ae4e38`），集成 AI 应按批合并。

---

## 6. 关单状态

#183 **未关单**：按 §14.12，代码完成但尚未合入 `main`，关单 comment 需写明分支与
commit——留给集成 AI 合并后关闭（或由本 AI 在批量审查通过后再关）。
