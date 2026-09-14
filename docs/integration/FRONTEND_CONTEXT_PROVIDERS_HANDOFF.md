# Integration Handoff — feat/frontend-context-providers → main

> **给集成 AI（Git Integrator）的交接单。**
> 补齐 Ticket F1 第四控件：ContextProviderPicker（多选）。
> 按 AGENTS.md §14 集成规则执行；merge / push 需用户明确批准。

---

## 0. TL;DR

| 项 | 值 |
| --- | --- |
| 源 worktree | `D:\intelligence-agent-frontend` |
| 源分支 | **`feat/frontend-context-providers`** |
| 目标分支 | `main` |
| 源 HEAD | `12c8065` |
| commits ahead | **1** |
| diff stat | 6 files, +345 / −9 |
| 工作树 | **clean** |
| tsc | **干净** |
| oxlint | **0 errors**（33 pre-existing warnings） |
| Vitest | **25 files / 372 tests 全绿**（+4 新增） |
| `git diff --check` | **干净** |
| code-review | 两轴 clean（0 hard / 1 judgement = 未来考虑提取共享 base） |

---

## 1. 为什么存在

Ticket F1 验收标准要求 Composer control row 四个控件落地，其中 Context Providers（多选）因后端当时诚实返空而推迟。现在后端 `context_providers` 已 runtime 真实消费（`e18b7fa`，ADR-0020b），`/api/context-providers` 在装配 provider 后返回真实清单。前置条件满足，补齐第四控件。

---

## 2. 变更摘要

### 新增

| 文件 | 内容 |
| --- | --- |
| `web/src/components/ContextProviderPicker.tsx` | 多选 Radix Popover + cmdk Command 控件；toggle 不关闭 popover；trigger 显示计数（`Context · N`）；checkbox 字符指示选中态；空目录 return null |
| `web/src/components/ContextProviderPicker.test.tsx` | 4 条 SSR 契约：空目录隐藏、trigger 渲染、计数显示、aria-disabled |
| `web/e2e/context-providers.spec.ts` | e2e：键盘 toggle + Esc 关闭 + POST `context_providers: string[]` payload 验证 + 空目录降级 |

### 修改

| 文件 | 变更 |
| --- | --- |
| `web/src/components/Composer.tsx` | 引入 `ContextProviderPicker`；新增 `selectedContextProviders` / `onContextProvidersChange` props；接入 control row |
| `web/src/App.tsx` | 解锁 `setSelectedContextProviders`（之前 `_` 标记 unused）；传入 Composer；422 恢复路径同步过滤死选中值 |
| `web/src/styles/app.css` | `.ctx-picker-checkbox` 样式 + `.sel` 状态 accent 着色 |

---

## 3. 与 main 的正交性

本 diff 触及文件：
- `ContextProviderPicker.tsx` / `.test.tsx`（新文件）
- `context-providers.spec.ts`（新文件）
- `Composer.tsx`（仅 ContextProviderPicker 引入段 + props）
- `App.tsx`（仅 contextProviders 状态解锁 + Composer 传参 + 422 恢复一行）
- `app.css`（仅 `.ctx-picker-checkbox` 段）

main 近期改动（runtime 子批次、F1 fixes）触及的是后端 `app.py` 和前端 Composer 的其他段落 / api.ts / ControlPicker.tsx。**预期无冲突**——`Composer.tsx` 和 `App.tsx` 有重叠但改的是不同段落（ContextProviderPicker 引入 vs 其他控件修复）。

---

## 4. 验证证据

```bash
pnpm exec tsc -b    # EXIT 0
pnpm lint           # 0 errors, 33 pre-existing warnings
pnpm test           # 25 files / 372 tests 全绿
git diff --check    # 干净
```

---

## 5. code-review 结果

- **Standards**：0 hard / 1 judgement（ContextProviderPicker 与 ControlPicker 结构同构，未来可提取共享 base；当前不提取因为单选/多选语义差异足够大，且只有两个实例——符合「rule of three」延迟重构原则 + §8 Scope Lock）。
- **Spec**：0 missing / 0 creep / 0 wrong。完整满足 Ticket F1 第 4 项验收标准。

---

## 6. 集成步骤（§14）

```bash
# 只读检查
git -C D:/intelligence-agent fetch origin --prune
git -C D:/intelligence-agent status
git -C D:/intelligence-agent-frontend status
git diff main...feat/frontend-context-providers --stat
git log main..feat/frontend-context-providers --oneline

# merge（需用户批准）
git -C D:/intelligence-agent checkout main
git -C D:/intelligence-agent merge --no-ff feat/frontend-context-providers \
  -m "merge(web): ContextProviderPicker——Composer control row 第四控件（多选）→ main"

# validation gate
cd D:/intelligence-agent/web && pnpm exec tsc -b && pnpm lint && pnpm test && pnpm build
```

---

## 7. 风险评估

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| Composer.tsx 与 main 近期改动冲突 | 低 | 不同段落（ContextProviderPicker 引入 vs F1 fix） |
| context_providers 端点仍返空时控件不可见 | 无 | 空目录 return null，行为正确 |

**总体风险：低。建议集成。**
