# F2 集成交接单 —— ModelPicker Combobox 升级

> **本文档由前端 AI 在 feat/frontend-d 完成 F2 后起草。**
> 完成时 feat/frontend-d HEAD = `5b7b91b`（本地，未 push）。
> 基线：`origin/main` = `431f75b`。

---

## 1. 分支映射

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-frontend` |
| Branch | `feat/frontend-d` |
| Base commit | `431f75b`（origin/main） |
| HEAD commit | `5b7b91b` |
| Commit count | 1 |
| Files changed | 4 |

---

## 2. 变更摘要

### 2.1 ModelPicker.tsx —— DropdownMenu → Popover + cmdk Command

**问题**：Phase 2a 的 ModelPicker 用 Radix DropdownMenu（`role="menu"`）。语义不准——menu 是动作菜单，不是可搜索的选项列表。

**方案**：升级为 Radix Popover + cmdk Command：
- **cmdk 注入 ARIA 角色**：`role="listbox"`（List）、`role="combobox"`（Input）、`role="option"`（Item），匹配 SDD §11「Combobox/Command-like」。
- **键盘导航内置**：方向键 / Home / End / Enter 由 cmdk 内置，无需自造 ArrowDown 拦截。
- **搜索过滤**：走 cmdk command-score，通过 `keywords` 字段把 provider 和 model 也纳入打分（输入「anthropic」能匹配到 claude-sonnet-4）。
- **Radix Popover 负责 portal 定位 + 外点关闭 + Esc 关闭**（§19「Esc 关闭最上层临时表面」）。

**契约向后兼容**（ModelPicker.test.tsx 6 条 SSR 断言全绿）：
- class 名 `composer-model` 仍在 trigger 上；
- `aria-label="模型选择"`；
- 空目录不渲染任何节点；
- 端点缺席时 trigger 文本为「默认链」。

### 2.2 新增依赖

| 包 | 版本 | 用途 |
| --- | --- | --- |
| `cmdk` | `1.1.1` | Command 菜单原语（role=listbox+combobox+option） |
| `@radix-ui/react-popover` | `1.1.23` | Portal 定位 + 外点关闭 + Esc 关闭 |

### 2.3 新增测试

**`web/e2e/model-picker.spec.ts`** —— F2 a11y 键盘导航 e2e 实测：
- 角色语义：打开后 `role="combobox"` + `role="listbox"` + `role="option"` 在场（cmdk 注入）；
- 键盘导航：Tab 进 trigger → Enter 打开 → 方向键移动 active → Enter 选档 → 浮层关闭 → trigger 文本更新；
- 搜索过滤：键入「claude」只剩匹配项（cmdk filter 把不匹配的 option 隐藏）；
- Esc 关闭浮层（§19）。

车道归属：vitest 车道只跑 SSR 契约（无 DOM 环境），交互实测在 Playwright（同 `i-keyboard.spec.ts` 的约定）。本文件不入 vitest 四门禁，归夜间/手动 e2e 车道。

---

## 3. 验证证据

### 3.1 四门禁

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| tsc | `pnpm exec tsc --noEmit` | 0 errors |
| oxlint | `pnpm exec oxlint src/components/ModelPicker.tsx e2e/model-picker.spec.ts` | 0 warnings, 0 errors |
| Vitest | `pnpm exec vitest run --pool=threads` | 364/364 passed (23 test files) |
| build | `pnpm run build` | ✓ built in 1.82s |

### 3.2 Playwright e2e

| 车道 | 命令 | 结果 |
| --- | --- | --- |
| chromium-1280 | `pnpm exec playwright test --project=chromium-1280` | 7/7 passed (18.5s) |

### 3.3 既有 6 测不破

```
src/components/ModelPicker.test.tsx (6 tests) — 6 passed
```

6 条 SSR 契约断言全绿：
1. 端点缺席（models 空）：选择器不渲染——不伪造列表 ✅
2. 目录在场：trigger 渲染且显示「默认链」当前选中（null 选中态）✅
3. selectedModel 有值 → trigger 显示该模型名 ✅
4. selectedModel 已不在目录 → 归一化为默认链 ✅
5. Radix DropdownMenu 内容项不在 SSR HTML 中（客户端 portal）✅
6. disabled=true → trigger 标记 aria-disabled ✅

---

## 4. 与 main 的正交性

### 4.1 改动范围

仅 4 个文件：
- `web/package.json` —— 新增 cmdk + @radix-ui/react-popover 依赖；
- `web/pnpm-lock.yaml` —— pnpm lockfile 更新；
- `web/src/components/ModelPicker.tsx` —— ModelPicker 实现（DropdownMenu → Popover+Command）；
- `web/e2e/model-picker.spec.ts` —— 新增 a11y 键盘导航 e2e 测试。

### 4.2 正交性分析

- **ModelPicker.tsx**：纯组件内部实现替换，对外接口（Props）不变，对 CSS 类名（`.composer-model`、`.model-picker-*`）不变。
- **package.json / pnpm-lock.yaml**：新增依赖，不修改既有依赖版本。与后端无关。
- **model-picker.spec.ts**：新增 e2e 测试文件，不影响既有 e2e 测试。

### 4.3 冲突预测

- **与 main 的冲突风险：极低**。改动集中在 ModelPicker 组件内部实现 + 新增依赖 + 新增测试文件，不触碰任何其他 Agent 可能修改的文件。
- **与 F1 的冲突风险：无**。F1 是 Composer control row（新增四个控件），F2 是 ModelPicker 内部升级，两者改动文件不重叠。
- **与 B1 的冲突风险：无**。B1 是后端清单端点，与前端 ModelPicker 无关。

---

## 5. 风险评估

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| cmdk 1.1.1 与 React 19 兼容性 | 低 | tsc + build + e2e 全绿，已验证 |
| cmdk 默认 filter 行为与旧 query 过滤不一致 | 低 | 自定义 filter 函数保持子串匹配语义；e2e 搜索测试通过 |
| Popover 动画与 DropdownMenu 不一致 | 低 | 复用现有 `.model-picker-content` CSS（含 keyframe 动画），视觉一致 |
| cmdk Input 自动聚焦行为 | 低 | e2e 键盘导航测试验证了 Tab → Enter → 方向键 → Enter 路径 |

---

## 6. Scope Lock 自检

- [x] 只升级 ModelPicker，不顺手重构其他组件
- [x] 不破坏现有 ModelPicker 测试（6 条全绿）
- [x] 不提前做未来 Phase（F1 Composer control row 是独立票）
- [x] 不扩大架构（cmdk 是 UI 原语，不触碰 Agent Loop / SessionEvent / Tool Runtime）
- [x] 不清理无关代码（DropdownMenu import 移除是本次改动的直接产物）

---

## 7. 待办

- [ ] Git Integrator 做只读检查（worktree 状态、拓扑核验、merge-tree 冲突预测）
- [ ] Git Integrator 报告集成计划
- [ ] 用户批准后 merge 到 main
- [ ] push 需用户单独批准（§14.4 / §14.11）

---

## 8. 参考

- HANDOFF_REMAINING_TICKETS.md F2（ModelPicker 升级 Combobox）
- SDD `docs/spec/Observable_Agent_Workspace_SDD/02_UI_UX_DESIGN_SPEC.md` §11
- ModelPicker.test.tsx 6 条 SSR 契约断言
- e2e/model-picker.spec.ts a11y 键盘导航 e2e 实测
