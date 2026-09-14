# Integration Handoff — feat/frontend-c → main

> **给集成 AI（Git Integrator）的交接单。**
> 本文件是 `feat/frontend-c` 分支进入 `main` 的完整证据包。
> 按 AGENTS.md §14 集成规则执行；merge / push 等需要用户明确批准的动作，**先报告后执行**。

---

## 0. TL;DR

| 项 | 值 |
| --- | --- |
| 源 worktree | `D:\intelligence-agent-frontend` |
| 源分支 | **`feat/frontend-c`** |
| 目标分支 | `main`（`D:\intelligence-agent` worktree） |
| 源 HEAD | `35cff2f` |
| main HEAD（集成前） | `98e3cc1` |
| commits ahead of main | **9** |
| diff stat | 19 files, +5124 / −139 |
| 工作树状态 | **clean**（无未提交、无未追踪源码） |
| 测试 | **23 files / 364 tests 全绿** |
| tsc | **干净** |
| oxlint | **0 errors**（33 pre-existing warnings，均不在本 diff 触及的变更行） |
| `git diff --check` | **干净**（仅 SDD markdown 的故意 two-space line break，非缺陷） |

**集成结论**：这是一个纯前端 UI shell + ModelPicker 重构，**不碰任何后端代码**，与 `feat/backend-c` 正交。可以直接单独合入 `main`，风险低。

---

## 1. 变更摘要（按 commit 顺序）

```
cb47196 docs(sdd): Phase 0 — Observable Agent Workspace SDD + Frontend Audit
8ea2a0b feat(web): Phase 1a — 设计 token 对齐 SDD 语义 surface 模型
4f4f670 feat(web): Phase 1b — shell 容器层级对齐 SDD（chrome 比 workspace 更安静）
00b4e1a feat(web): Phase 1c — Inspector 五 tab 美化（分段控件 + 空状态 + section 分隔）
4073be5 feat(web): Phase 1d — Workspace 方案 B 空架子（Chat 常驻 + Split/Preview 模式条）
d8c1d29 feat(web): Phase 2a — ModelPicker 从原生 select 升级为 Radix Popover
fc1e2c4 fix(web): code-review 缺陷修复——aria-selected 契约 + Inspector 容器查询
9714137 fix(web): harden ModelPicker selection and search
35cff2f fix(web): code-review 二轮——ModelPicker 选择归一化 + Esc 冒泡 + reduced-motion 守护
```

### 内容分三块

1. **SDD 文档**（`docs/spec/observable-workspace-sdd/`，11 个新文件）
   - PRD、UI/UX spec、Runtime/Event contract、Frontend SDD、Backend SDD、Implementation plan、Acceptance test plan、Decision log、Benchmark/reuse matrix、Frontend audit。
   - 这些是前端重构的规格来源，属于公共项目资产（§13.1 第 5 条），应随 commit 进入 main。

2. **设计 token + shell 层级**（Phase 1a/1b）
   - `web/src/index.css`：dark/light 语义 token（`--surface-canvas/chrome/workspace/elevated`、固定 accent dark `#f1b3ca` / light `#c96990`）。`--bg-*` 保留为 legacy alias。
   - `web/src/styles/app.css` `.app-regions`：修复原先错误用 `--surface-1` 导致 chrome/workspace 层级反转。

3. **Inspector + Workspace + ModelPicker**（Phase 1c/1d/2a + 两个 fix 轮）
   - `StepDetail.tsx`：Inspector 五 tab（Timeline/Chat/Changes/Terminal/Artifacts）美化——icon + label 分段控件、selected pill、空状态、section 分隔。**五 tab 仍在右栏 Inspector，未移动到 Workspace。** run-level 持久 tab strip 的 `aria-selected` 从硬编码 `false` 改为真实 `active`。
   - `App.tsx`：Workspace 新增 mode bar（Chat / Split / Preview）。**Chat 始终是主阅读面，Split/Preview 是用户明确批准的空 scaffold，不隐藏 Chat。** 响应式 Inspector 折叠：`<1200px` 默认收起，用户手动 toggle 优先（`userToggledRef`）。
   - `ModelPicker.tsx`（新文件）：原生 `<select>` → Radix DropdownMenu + Portal。provider 分组、搜索过滤、失效 selectedModel 归一化为"默认链"、空目录隐藏入口（不伪造列表）、Esc/Enter 冒泡满足 §19、reduced-motion 守护满足 §18/§21。
   - `Composer.tsx`：消费 `ModelPicker`。
   - 测试：`ModelPicker.test.tsx`（新，6 tests）、`Composer.test.tsx`（更新为 Radix trigger 契约）、`StepDetail.test.tsx`（13 tests 不变继续通过）。

---

## 2. 验证证据

在 `D:\intelligence-agent-frontend\web` 执行（源 worktree）：

```bash
pnpm exec tsc -b          # EXIT 0，干净
pnpm lint                 # 0 errors，33 warnings（pre-existing，不在本 diff 变更行）
pnpm test                 # 23 files / 364 tests 全绿，duration 2.63s
```

在 `D:\intelligence-agent-frontend`（源 worktree 根）：

```bash
git status --short        # 空（工作树 clean）
git diff --check          # 仅 SDD markdown 的 two-space line break（故意，非缺陷）
git diff main...HEAD --check   # 同上
```

### 浏览器 GUI QA（本会话内已完成）

| 宽度 | 期望 | 实测 |
| --- | --- | --- |
| 1440 | 三栏 240 / flex / 320 | PASS |
| 1280 | 三栏 240 / flex / 320 | PASS |
| 1024（全新加载） | Inspector 自动折叠 240 / flex / 0 | PASS |
| 1024（手动 toggle） | Inspector 打开 240 / flex / 280 | PASS |
| 820 | Rail 56px 图标栏 / Inspector 0 | PASS |
| 768 | Rail 56px / Inspector 0 | PASS |
| 浅色模式 | surface 层级正确（chrome < workspace） | PASS |
| ModelPicker 空目录 | 入口隐藏 | PASS |
| ModelPicker 选择 | 选择后菜单关闭、失效 selected 归一化、搜索过滤 | PASS |

---

## 3. Code review 结果（两轴，基于 `main...HEAD`）

### Standards axis：0 hard violations，5 judgement calls（均已审视）

- **ModelPicker Check 标记读原始 selectedModel 与归一化 effectiveSelectedModel 不一致** → 已在 `35cff2f` 修复（统一 `effectiveSelectedModel`）。
- Composer inline noop 可能影响 memo 引用稳定性 → 当前 ModelPicker 未 memo，无实际影响。
- `--surface-2` 留 raw hex 而 sibling 用 `var()` → 美观性，不影响功能。
- workspace-mode-bar 用 `role="tablist"` 但无对应 `tabpanel` → 与既有 StepDetail 同模式，非回归。
- app.css 末尾空行 → 已在 `35cff2f` 清掉。

### Spec axis：4 missing / 2 creep / 3 wrong（已分类）

**已修复**：
- ModelPicker 动画无 reduced-motion 守护（§18/§21）→ 已在 `35cff2f` 修复。
- 搜索框 `onKeyDown` 无脑 `stopPropagation` 阻断 Esc（§19）→ 已在 `35cff2f` 修复为只拦方向键。

**已知技术取舍，不在本次修复范围**（记录在案，不阻塞集成）：
- Token 命名：实现以 `--surface-*` 为主、`--bg-*` 为 alias，与 spec §4.1 字面命名不同，但**数值一致且向后兼容**。spec §4.1 与 legacy alias 共存的现实决定这是合理取舍；强行改名会破坏既有 CSS。
- ModelPicker 用 Radix `DropdownMenu`（`role="menu"`）而非 `Combobox`/`Command`（`role="listbox"`）→ 已知语义差距，spec §11 写的是"Combobox/Command-like"，DropdownMenu 是当前可复用 primitive 的最小实现。升级到真正 Combobox 是后续增强项，不阻塞本次集成。

**Reviewer 误报**（已核实，非真实 gap）：
- "Inspector 不可折叠" → 事实上 `App.tsx` 有 `inspectorOpen` 状态、toggle 按钮、`@media (max-width: 1200px)` 自动折叠，reviewer 漏读了既有代码。
- "无响应式断点处理" → 同上，`app.css` 已有 1200px / 820px 断点。
- Workspace Split/Preview scaffold 被某轮 review 误判为 speculative generality → **用户明确批准的设计前置**，按 §9.1 用户指令优先级最高，不阻塞。

---

## 4. 用户明确批准的范围决策（集成时不得回退）

1. **Inspector 五 tab 不移动**，只在原位美化。
2. **Workspace 只放 Chat + Composer**；Chat 是主阅读面，不被 tab 切走。
3. **Workspace Split/Preview 是批准的空 scaffold**，等后端完成后升级——**不是缺失工作，不是过度设计**。
4. **ModelPicker 空目录必须隐藏入口**，不伪造列表；当前选择只提交偏好，不是会话内模型真相。
5. **Phase 2b Composer control row（Context/Agent/Reasoning/Permission）因后端契约未到而 deferred**——不在本 diff，不是缺失工作。

集成 AI 若在 review 中发现疑似"缺失"或"过度设计"，请先对照本节再判断，不要单方面要求回退这些用户决策。

---

## 5. 与 backend 的正交性

本 diff **不触及任何后端代码、API 契约、事件 schema**：
- `web/src/lib/api.ts` 未改（`/api/models` 契约早已存在，ModelPicker 只是换消费侧 UI）。
- 无 schema 文件、无 event type、无 backend runtime 改动。
- 所有 diff 限定在 `docs/spec/observable-workspace-sdd/` 和 `web/`。

因此：
- **可以单独合入 main，不影响 `feat/backend-c`。**
- backend 完成后仍需**单独**走一次集成（§14.9：一次只集成一个 feature branch）。

---

## 6. 集成执行步骤（建议，按 §14）

> ⚠️ 每个需要批准的动作（merge / push）**先报告后执行**，等用户明确确认。

### 6.1 集成前检查（只读，无需批准）

```bash
# 在 main worktree（D:\intelligence-agent）
git -C D:/intelligence-agent fetch origin --prune
git -C D:/intelligence-agent status                    # 必须干净
git -C D:/intelligence-agent rev-parse HEAD            # 记录集成前 main HEAD
git -C D:/intelligence-agent log --oneline -5          # 确认 main 状态

# 在 frontend worktree（D:\intelligence-agent-frontend）
git -C D:/intelligence-agent-frontend status           # 必须干净
git -C D:/intelligence-agent-frontend rev-parse feat/frontend-c   # 应为 35cff2f

# 三点 diff（merge-base 比较）
git -C D:/intelligence-agent-frontend diff main...feat/frontend-c --stat
git -C D:/intelligence-agent-frontend log main..feat/frontend-c --oneline

# 冲突预演（不实际合并）
git -C D:/intelligence-agent-frontend merge-base main feat/frontend-c
```

### 6.2 集成方向（§14.6「先回后正」）

```
origin/main ──→ D:\intelligence-agent (main)
                      │
                      ▼
           merge feat/frontend-c into main
                      │
                      ▼
                 new main HEAD
```

### 6.3 执行 merge（需用户批准）

推荐在 `D:\intelligence-agent`（main worktree）执行，而不是在 frontend worktree：

```bash
git -C D:/intelligence-agent checkout main
git -C D:/intelligence-agent merge --no-ff feat/frontend-c \
  -m "merge(web): Phase 1–2 Observable Agent Workspace 前端重构 → main

集成 feat/frontend-c（9 commits, cb47196..35cff2f）：
- SDD 文档（docs/spec/observable-workspace-sdd/）
- Phase 1a/1b 设计 token + shell 层级
- Phase 1c Inspector 五 tab 美化
- Phase 1d Workspace 方案 B（Chat 常驻 + Split/Preview scaffold）
- Phase 2a Radix DropdownMenu ModelPicker
- 两轮 code-review 修复

验证：tsc 干净 / oxlint 0 errors / Vitest 364 全绿 / git diff --check 干净 / 浏览器 GUI QA 6 档宽度 + 浅色模式 PASS。

详见 docs/integration/FRONTEND_C_INTEGRATION_HANDOFF.md。"
```

### 6.4 冲突处理（§14.7）

预期**无冲突**（本 diff 与 main 当前 HEAD `98e3cc1` 触及的文件无重叠）。若出现：

1. **立即停止**，不要机械 `ours`/`theirs`。
2. 逐文件分析：main 改了什么、feat/frontend-c 改了什么、为何冲突、两侧逻辑能否并存。
3. **报告用户**，等批准后再解决。

### 6.5 集成后验证（§14.10 Validation Gate）

在 `D:\intelligence-agent\web`：

```bash
pnpm install               # 若 lockfile 有变化
pnpm exec tsc -b           # 必须干净
pnpm lint                  # 必须 0 errors
pnpm test                  # 必须 364 全绿
pnpm build                 # 必须成功（确认能产出生产构建）
```

在 `D:\intelligence-agent`：

```bash
git status                 # 干净
git log --oneline -3       # merge commit 在顶
git diff --check           # 干净
```

可选：启动完整项目（前后端联调）确认 Inspector/Workspace/ModelPicker 在 main 上行为一致。

### 6.6 Push（§14.4，需用户单独批准）

集成后验证全通过，**再单独请用户批准** `git push origin main`。不要在 merge 批准里隐含 push 批准。

---

## 7. 不做什么

- ❌ 不合并 `feat/backend-c`（§14.9：一次一个 feature branch）。
- ❌ 不改任何后端代码、API、schema。
- ❌ 不回退 §4 的任何用户批准决策。
- ❌ 不擅自把 ModelPicker "升级"成 Combobox（已知取舍，后续单独 ticket）。
- ❌ 不擅自把 `--surface-*` 改名成 spec §4.1 字面命名（会破坏 legacy alias）。
- ❌ 不在 main 上临时拼接冲突解决（§14.8：复杂冲突回 frontend worktree 解决）。

---

## 8. 集成后交给谁

集成完成、main 验证通过、push 完成后，后续工作分两条独立线：

1. **后端**：`feat/backend-c` 完成后，单独走一次集成（重新 fetch/diff/merge-base/conflict analysis，因为 main 已变）。
2. **前端 Phase 2b**：等后端 AI 返回 Context/Agent/Reasoning/Permission 契约后，在新的 feature branch 上继续 Composer control row。**不在已合并的 feat/frontend-c 上继续。**

---

## 9. 风险评估

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| 与 main 当前 HEAD 冲突 | 极低 | 本 diff 触及文件与 main 无重叠 |
| 破坏既有 CSS | 低 | `--bg-*` legacy alias 保留，向后兼容 |
| ModelPicker a11y 语义弱 | 中（已知取舍） | DropdownMenu 而非 Combobox；记录为后续增强，不阻塞 |
| 测试在 main 环境失败 | 极低 | 前端 worktree 已验证；main worktree 验证后确认 |
| 响应式在 main 回归 | 极低 | 6 档宽度 + 浅色模式已 QA |

**总体风险等级：低。建议集成。**
