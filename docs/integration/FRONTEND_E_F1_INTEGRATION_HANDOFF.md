# F1 集成交接单 —— Phase 2b Composer Control Row

> **本文档由前端 AI 在 feat/frontend-e 完成 F1 后起草。**
> 完成时 feat/frontend-e HEAD = `2dc4ee3`（本地，未 push）。
> 基线：`origin/main` = `2015c69`（B1 已集成）。

---

## 1. 分支映射

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-frontend` |
| Branch | `feat/frontend-e` |
| Base commit | `2015c69`（origin/main，B1 集成后） |
| HEAD commit | `2dc4ee3` |
| Commit count | 1 |
| Files changed | 8 |

---

## 2. 变更摘要

### 2.1 新增文件

| 文件 | 用途 |
| --- | --- |
| `web/src/components/ControlPicker.tsx` | 通用单选控件，复用 ModelPicker Popover+cmdk 模式 |
| `web/src/components/ControlPicker.test.tsx` | SSR 契约测试 4 条 |
| `web/e2e/control-row.spec.ts` | Playwright e2e 交互测试 |
| `docs/integration/INTEGRATOR_B1_MERGE_PROMPT.md` | B1 集成提示词（已过时，B1 已入 main） |

### 2.2 修改文件

| 文件 | 改动 |
| --- | --- |
| `web/src/lib/api.ts` | 新增 `CatalogEntry` 类型 + 四个 fetch 函数 + 扩展 `StartSessionPayload` |
| `web/src/components/Composer.tsx` | 扩展 Props 接收四组 control row 数据 + 新增 `composer-controls` 行 |
| `web/src/App.tsx` | 新增三组 `useState` + `fetchControlCatalogs` + `handleSubmit` 注入 staged 字段 |
| `web/src/styles/app.css` | 新增 `.composer-controls` flex 容器 + `.composer-control` trigger 样式 |
| `web/e2e/fixtures.ts` | 扩展 `ApiMock` 接口 + `routeApi` 新增四条路由 |

### 2.3 实现要点

**ControlPicker 组件**：
- 复用 ModelPicker 的 Radix Popover + cmdk Command 模式
- 数据源是 `CatalogEntry`（`{id, display_name, description}`）
- 空目录 → `return null`（调用方隐藏入口）
- `selectedId` 有值 → trigger 显示 `display_name`；null → placeholder
- Esc 关闭浮层（§19）；方向键/Enter 由 cmdk 内置

**Composer control row**：
- 在 textarea 下方加一行 `composer-controls` flex 容器
- 含三个 ControlPicker：Permission Mode / Agent Profile / Reasoning Effort
- ModelPicker 不在此行——它仍靠 `align-self: flex-end` 浮在 dock 右下

**App.tsx 状态管理**：
- 三组 `useState<CatalogEntry[]>` + `useState<string | null>`
- `fetchControlCatalogs()` 用 `Promise.all` 并行拉取三个端点
- `handleSubmit` 注入 `permission_mode` / `agent_profile` / `reasoning_effort` 到 POST body

**API 层**：
- `CatalogEntry` 类型：`{id, display_name, description}`
- 四个 fetch 函数：`getPermissionModes()` / `getAgentProfiles()` / `getReasoningEfforts()` / `getContextProviders()`
- `StartSessionPayload` 扩展四个 staged 字段

---

## 3. 验证证据

### 3.1 四门禁

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| tsc | `pnpm exec tsc --noEmit` | 0 errors |
| oxlint | `pnpm exec oxlint` | 0 errors, 10 warnings (pre-existing setState-in-effect) |
| Vitest | `pnpm exec vitest run --pool=threads` | 368/368 passed (24 test files) |
| build | `pnpm run build` | ✓ built in 1.08s |

### 3.2 Playwright e2e

| 车道 | 命令 | 结果 |
| --- | --- | --- |
| chromium-1280 | `pnpm exec playwright test --project=chromium-1280` | 8/8 passed (16.9s) |

### 3.3 新增测试明细

**ControlPicker SSR 契约（4 条）**：
1. 端点缺席（entries 空）：控件不渲染 ✅
2. 目录在场：trigger 渲染 + aria-label 在场 ✅
3. selectedId 有值 → trigger 显示 display_name ✅
4. disabled=true → trigger 标记 aria-disabled ✅

**e2e control-row.spec.ts**：
- 四个控件 trigger 在场（ModelPicker + Permission/Agent/Reasoning）
- 键盘打开浮层 + cmdk combobox/listbox/option 角色在场
- 搜索过滤：键入「ask」只剩匹配项
- Esc 关闭浮层（§19）
- Enter 选第一个 option → trigger 文本更新

---

## 4. 与 main 的正交性

### 4.1 改动范围

仅 8 个文件，全部在前端 `web/` 目录：
- 3 个新组件/测试文件
- 1 个新 e2e 测试文件
- 3 个修改的现有文件（api.ts / Composer.tsx / App.tsx）
- 1 个修改的 e2e fixture 文件
- 1 个 CSS 文件修改

### 4.2 正交性分析

- **与后端的冲突风险：无**。F1 是纯前端改动，不触碰后端代码。
- **与 F2 的冲突风险：无**。F2 改的是 ModelPicker.tsx，F1 新建 ControlPicker.tsx，两者不重叠。
- **与 main 上其他改动的冲突风险：极低**。所有改动都在 `web/` 目录内，main HEAD `2015c69` 的改动也在 `web/` 目录内（F2 ModelPicker Combobox 升级），但 F1 新建文件 + 扩展现有接口，不修改 F2 的 ModelPicker.tsx。

### 4.3 冲突预测

| 文件 | 冲突风险 | 说明 |
| --- | --- | --- |
| `web/src/lib/api.ts` | 低 | 新增函数和类型，不修改既有函数 |
| `web/src/components/Composer.tsx` | 低 | 扩展 Props + 新增 control row JSX |
| `web/src/App.tsx` | 低 | 新增状态和 fetch + 扩展 handleSubmit |
| `web/src/styles/app.css` | 低 | 新增 .composer-controls 和 .composer-control 样式 |
| `web/e2e/fixtures.ts` | 低 | 扩展 ApiMock 接口 + routeApi 新增路由 |
| 新建文件 | 无 | 全新文件 |

---

## 5. 风险评估

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| cmdk 1.1.1 与 React 19 兼容性 | 低 | tsc + build + e2e 全绿，已验证 |
| ControlPicker 与 ModelPicker 模式不一致 | 低 | 复用同模式（Popover+cmdk），e2e 验证角色语义 |
| POST /api/sessions payload 字段名错误 | 低 | StartSessionPayload 扩展字段名与后端契约对齐 |
| 空目录降级行为不一致 | 低 | ControlPicker 和 ModelPicker 都用 `entries.length === 0 → return null` |
| Context Providers 多选控件未实现 | 低 | 当前 context-providers 返空数组，ControlPicker 单选模式已够用；多选是后续需求 |

---

## 6. Scope Lock 自检

- [x] 只加 Composer control row，不动 Inspector / Workspace / Conversation 等既有区块
- [x] 不破坏现有 ModelPicker 测试（6 条全绿）
- [x] 不提前做未来 Phase（Context Providers 多选是后续需求）
- [x] 不扩大架构（ControlPicker 是 UI 原语，不触碰 Agent Loop / SessionEvent / Tool Runtime）
- [x] 不清理无关代码（DropdownMenu import 移除是 F2 改动的直接产物）

---

## 7. 待办

- [ ] Git Integrator 做只读检查（worktree 状态、拓扑核验、merge-tree 冲突预测）
- [ ] Git Integrator 报告集成计划
- [ ] 用户批准后 merge 到 main
- [ ] push 需用户单独批准（§14.4 / §14.11）

---

## 8. 参考

- `D:\intelligence-agent-backend\docs\integration\FRONTEND_PROMPT_B1.md` — 后端 B1 契约 + 前端 F1 执行手册
- `D:\intelligence-agent\docs\integration\HANDOFF_REMAINING_TICKETS.md` — 遗留项交接单
- SDD `docs/spec/Observable_Agent_Workspace_SDD/02_UI_UX_DESIGN_SPEC.md` §11
- AGENTS.md §14 Git Workflow / Merge Safety
