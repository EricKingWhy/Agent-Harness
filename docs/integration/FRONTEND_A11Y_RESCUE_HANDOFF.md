# Integration Handoff — feat/frontend-a11y-rescue → main

> **给集成 AI（Git Integrator）的交接单。**
> 救回两个孤儿 commit：a11y 收尾 + 竞品调研文档。
> 按 AGENTS.md §14 集成规则执行；merge / push 等需要用户明确批准的动作，**先报告后执行**。

---

## 0. TL;DR

| 项 | 值 |
| --- | --- |
| 源 worktree | `D:\intelligence-agent-frontend` |
| 源分支 | **`feat/frontend-a11y-rescue`**（从 main 新切） |
| 目标分支 | `main`（`D:\intelligence-agent` worktree） |
| 源 HEAD | `9f935c9` |
| main HEAD（集成前） | `4225af4` |
| commits ahead of main | **2** |
| diff stat | 3 files, +174 / −3 |
| 工作树状态 | **clean** |
| 测试 | **24 files / 368 tests 全绿** |
| tsc | **干净** |
| oxlint | **0 errors**（33 pre-existing warnings） |
| `git diff --check` | **干净** |

**集成结论**：超小 diff（a11y 修复 + 纯 docs），不碰 F1 / Composer / ControlPicker 等任何活跃代码，与 main 当前 HEAD 文件无重叠。风险极低。

---

## 1. 为什么存在这个分支

Phase 1+2 前端重构在 `feat/frontend-c` 上交付时，最后两个 commit（a11y 收尾 + 竞品调研）发生在一个会话上下文压缩后，没被纳入集成交接单。另一个会话从新 main 开 `feat/frontend-d`/`feat/frontend-e` 做了 F2（ModelPicker Combobox 升级）和 F1（Phase 2b Composer control row），都没 cherry-pick 这两个 commit。

结果：这两个 commit 一直孤立在 `feat/frontend-c` 上，main 从未拿到：
- workspace-mode-bar 还是旧的 `role="tablist"`/`aria-selected`（应该是 `role="toolbar"`/`aria-pressed`——它没有真正的 panel 切换，tablist 语义不准确）。
- `.detail-tab:active` 和 `.workspace-mode:active` 的 `transform: scale(0.97)` 仍缺 `prefers-reduced-motion` 守护（spec §18/§21 要求）。
- 竞品调研文档（Phase 2b 设计依据）从未进 main。

本分支从 main 切出，cherry-pick 这两个 commit，干净救回。

---

## 2. 两个 commit

### 2.1 `b19efc1` fix(web): a11y 收尾——workspace-mode-bar 语义 + active scale reduced-motion

| 文件 | 变更 |
| --- | --- |
| `web/src/App.tsx` | workspace-mode-bar：`role="tablist"` → `role="toolbar"`；button：`role="tab"`/`aria-selected` → `type="button"`/`aria-pressed`（它没有 tabpanel，不是真 tablist） |
| `web/src/styles/app.css` | `.detail-tab:active` 和 `.workspace-mode:active` 的 `transform: scale(0.97)` 加 `@media (prefers-reduced-motion: reduce)` override |

spec 依据：SDD §18/§21（reduced motion）、ARIA tablist/tabpanel 契约。

### 2.2 `9f935c9` docs(research): Composer 控制行竞品调研——8 家产品对照 + Phase 2b 5 条启示

| 文件 | 变更 |
| --- | --- |
| `docs/research/composer-control-row-benchmark.md`（新） | 161 行，8 家产品（Cursor/v0/Replit/Devin/Claude Code/ChatGPT/Linear/Copilot Chat）的 Composer 控制行设计调研，含对比表和 5 条 Phase 2b 启示 |

纯 docs，不碰任何代码。

---

## 3. 与 main 的正交性

本 diff 触及的文件：
- `web/src/App.tsx`（仅 workspace-mode-bar 的几行 role 属性）
- `web/src/styles/app.css`（两个 reduced-motion 媒体查询块）
- `docs/research/composer-control-row-benchmark.md`（新文件）

main 最近改动（F1/F2）触及的是：
- `web/src/components/Composer.tsx`、`ControlPicker.tsx`、`ModelPicker.tsx`、`web/src/lib/api.ts`、`web/src/styles/app.css` 的 Composer/ModelPicker 相关段落

**`app.css` 有潜在重叠**——F1 可能在同文件加过 `.composer-controls` 等样式。但 cherry-pick 已成功 auto-merge，冲突预演通过（见 §4）。**App.tsx 的 workspace-mode-bar 段落 F1/F2 都没碰**，无冲突风险。

---

## 4. 冲突预测

```
git cherry-pick 7f919c2 d5f5c76   # 已成功，auto-merge 无冲突
git diff main...HEAD --check       # 干净
```

预期**无冲突**。

---

## 5. 验证证据

```bash
# 在 D:\intelligence-agent-frontend\web
pnpm exec tsc -b    # EXIT 0
pnpm lint           # 0 errors, 33 pre-existing warnings
pnpm test           # 24 files / 368 tests 全绿
```

`git diff --check main...HEAD`：干净。

---

## 6. 集成执行步骤（§14）

> ⚠️ 每个需要批准的动作（merge / push）**先报告后执行**。

### 6.1 只读检查

```bash
git -C D:/intelligence-agent fetch origin --prune
git -C D:/intelligence-agent status              # 必须干净
git -C D:/intelligence-agent rev-parse HEAD      # 记录集成前 main HEAD

git -C D:/intelligence-agent-frontend status     # 必须干净
git -C D:/intelligence-agent-frontend rev-parse feat/frontend-a11y-rescue  # 应为 9f935c9

git -C D:/intelligence-agent diff main...feat/frontend-a11y-rescue --stat
git -C D:/intelligence-agent log main..feat/frontend-a11y-rescue --oneline
```

### 6.2 执行 merge（需用户批准）

```bash
git -C D:/intelligence-agent checkout main
git -C D:/intelligence-agent merge --no-ff feat/frontend-a11y-rescue \
  -m "merge(web): a11y 收尾 + 竞品调研文档 → main

救回两个孤儿 commit（feat/frontend-c 遗留）：
- workspace-mode-bar 语义从 tablist 改为 toolbar（无 tabpanel，tablist 不准确）
- .detail-tab / .workspace-mode 的 active scale 加 prefers-reduced-motion 守护
- Composer 控制行竞品调研文档（8 家产品，Phase 2b 设计依据）

详见 docs/integration/FRONTEND_A11Y_RESCUE_HANDOFF.md。"
```

### 6.3 集成后验证（§14.10）

```bash
# 在 D:\intelligence-agent\web
pnpm exec tsc -b && pnpm lint && pnpm test && pnpm build
```

### 6.4 Push（需用户单独批准）

---

## 7. 不做什么

- ❌ 不改 F1 / Composer / ControlPicker / ModelPicker（那些是已集成的活跃代码）
- ❌ 不回退 workspace-mode-bar 的设计（用户明确批准的方案 B）
- ❌ 不顺手重构

---

## 8. 风险评估

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| app.css 与 F1 新增样式冲突 | 极低 | cherry-pick auto-merge 已通过；改的是不同 CSS 段落 |
| a11y 语义改动破坏测试 | 极低 | 没有测试对 workspace-mode-bar 的 role 做断言（已核实） |
| reduced-motion 守护影响视觉 | 零 | 只在 `prefers-reduced-motion: reduce` 时生效 |

**总体风险：极低。建议集成。**
