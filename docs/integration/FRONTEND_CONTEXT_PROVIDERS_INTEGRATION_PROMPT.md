# Integration Prompt — feat/frontend-context-providers → main

> **给集成 AI（Git Integrator）的执行提示词。**
> 按 AGENTS.md §14 集成规则执行；merge / push 需用户明确批准。

---

## 0. 任务

将 `feat/frontend-context-providers` 分支合入 `main`。

**内容**：ContextProviderPicker——Composer control row 第四控件（多选）。补齐 Ticket F1 验收标准中推迟的第四个控件。

---

## 1. 分支映射

| 项 | 值 |
| --- | --- |
| 源 worktree | `D:\intelligence-agent-frontend` |
| 源分支 | `feat/frontend-context-providers` |
| 目标 worktree | `D:\intelligence-agent` |
| 目标分支 | `main` |
| 源 HEAD | `12c8065` |
| merge-base | `080e1f1`（= 当前 main HEAD） |
| commits ahead | **2**（`12c8065` feat + `9094f8e` docs） |
| diff stat | 7 files, +458 / −9 |

---

## 2. 变更清单

### 新增文件（3）

| 文件 | 内容 |
| --- | --- |
| `web/src/components/ContextProviderPicker.tsx` | 多选 Radix Popover + cmdk Command 控件；toggle 不关闭 popover；trigger 显示计数（`Context · N`）；checkbox 字符指示选中态；空目录 return null |
| `web/src/components/ContextProviderPicker.test.tsx` | 4 条 SSR 契约测试：空目录隐藏、trigger 渲染、计数显示、aria-disabled |
| `web/e2e/context-providers.spec.ts` | Playwright e2e：键盘 toggle + Esc 关闭 + POST `context_providers: string[]` payload 验证 + 空目录降级 |

### 修改文件（4）

| 文件 | 变更 |
| --- | --- |
| `web/src/App.tsx` | 解锁 `setSelectedContextProviders`（之前 `_` 标记 unused）；传入 Composer；422 恢复路径同步过滤死选中值（+1 行 correctness fix） |
| `web/src/components/Composer.tsx` | 引入 `ContextProviderPicker`；新增 `selectedContextProviders` / `onContextProvidersChange` props；接入 control row |
| `web/src/styles/app.css` | `.ctx-picker-checkbox` 样式 + `.sel` 状态 accent 着色 |
| `docs/integration/FRONTEND_CONTEXT_PROVIDERS_HANDOFF.md` | 集成交接单 |

---

## 3. 预检（只读，§14.3）

```bash
# 确认 worktree 映射
git worktree list --porcelain

# 确认源分支状态
git -C D:/intelligence-agent-frontend status
git -C D:/intelligence-agent-frontend log --oneline -3

# 确认目标分支状态
git -C D:/intelligence-agent status
git -C D:/intelligence-agent log --oneline -3

# fetch 最新
git -C D:/intelligence-agent fetch origin --prune

# 确认 merge-base = main HEAD
git -C D:/intelligence-agent merge-base main feat/frontend-context-providers
git -C D:/intelligence-agent rev-parse main

# diff 检查
git -C D:/intelligence-agent diff main...feat/frontend-context-providers --stat
git -C D:/intelligence-agent diff main...feat/frontend-context-providers --check
```

---

## 4. 冲突风险评估

| 文件 | 与 main 近期改动的关系 | 冲突风险 |
| --- | --- | --- |
| `ContextProviderPicker.tsx` / `.test.tsx` | 新文件，main 无此文件 | 无 |
| `context-providers.spec.ts` | 新文件 | 无 |
| `App.tsx` | main 未改此文件（F1 fixes 已在 main 中） | 低 |
| `Composer.tsx` | main 未改此文件 | 低 |
| `app.css` | main 未改此文件 | 低 |
| `FRONTEND_CONTEXT_PROVIDERS_HANDOFF.md` | 新文件 | 无 |

**总体冲突风险：低。** merge-base = main HEAD，为 fast-forward 或 clean merge。

---

## 5. 集成步骤（需用户批准）

```bash
# 1. 切到目标 worktree
cd D:/intelligence-agent

# 2. 确认在 main 分支
git branch --show-current  # 应为 main

# 3. merge（--no-ff 保留分支拓扑）
git merge --no-ff feat/frontend-context-providers \
  -m "merge(web): ContextProviderPicker——Composer control row 第四控件（多选）→ main"

# 4. validation gate
cd web
pnpm exec tsc -b        # tsc 0 errors
pnpm lint               # oxlint 0 errors
pnpm test               # vitest 全绿
pnpm build              # build 成功
```

---

## 6. 验证证据（源分支）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| tsc | `pnpm exec tsc --noEmit` | 0 errors |
| vitest | `pnpm exec vitest run --pool=threads` | 25 files / 372 tests 全绿 |
| git diff --check | `git diff main...HEAD --check` | 干净 |

---

## 7. code-review 结果

两轴 review（Standards + Spec）：

- **Standards**：0 hard violation / 1 judgement call（ContextProviderPicker 与 ControlPicker 结构同构，未来可提取共享 base；当前不提取因为单选/多选语义差异足够大，且只有两个实例——符合 rule of three 延迟重构原则 + §8 Scope Lock）。
- **Spec**：0 missing / 0 creep / 0 wrong。完整满足 Ticket F1 第 4 项验收标准。

---

## 8. 集成后

- 更新 `docs/PHASE_STATUS.md` 记录此次集成。
- 如需 push GitHub，按 §14.4 获得用户明确批准后执行 `git push origin main`。

**总体风险：低。建议集成。**
