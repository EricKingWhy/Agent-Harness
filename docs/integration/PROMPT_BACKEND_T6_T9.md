# 后端会话提示词：Phase Multiturn T6-T9

> 复制以下内容粘贴到 `D:\intelligence-agent-backend` 会话中。

---

你是后端开发 Agent，工作目录 `D:\intelligence-agent-backend`，分支 `feat/backend`。

## 背景

集成 AI 已完成 Fix Phase（P0-001 / FE-04 / P2-003 三项修复已合入 main 并 push GitHub）。现在进入 Phase Multiturn T6-T9 切片。三份 PRD 已 commit 到 main：

- `docs/integration/PRD_PHASE_MULTITURN_TOTAL.md` — 跨端接口契约（唯一来源）+ 前后端分工表 + 依赖图
- `docs/integration/PRD_PHASE_MULTITURN_BACKEND.md` — 你的任务清单 + 验收标准 + 测试接缝

## 第一步：同步 main

```bash
git fetch origin
git merge origin/main
```

这会把集成 AI 刚 push 的三份 PRD 文档拉到你的 worktree。

## 第二步：读 PRD

按顺序读这两份文档：
1. `docs/integration/PRD_PHASE_MULTITURN_TOTAL.md`（跨端接口契约，必读）
2. `docs/integration/PRD_PHASE_MULTITURN_BACKEND.md`（你的任务清单）

## 第三步：按优先级执行

| 优先级 | Ticket | 标题 | 说明 |
|---|---|---|---|
| P0 | #136 | T6 审批 WS 推送 + HTTP 回传 | 解锁前端 #37，最高优先 |
| P1 | #138 | T8 崩溃恢复 + Ledger reconcile | 纯后端，解锁 #139 |
| P2 | #137 | T7 模型切换 + Fork API | 后端 API 部分 |
| P3 | #139 | T9 Langfuse 多轮埋点 + DoD 全量回归 | 最终验证，依赖 #138 |

## 工作流

每个 ticket 按以下流程执行：

1. **to-tickets**：把 ticket 拆成可执行的子任务
2. **/implement**：按子任务实现，先写红灯测试再修码见绿灯
3. **code-review**：Standards + Spec 双轴评审

完成后：
- commit 到 `feat/backend`
- 通知集成 AI 合并到 `main`

## 注意事项

- 所有 tool 执行仍走 ToolExecutor 单一路径（不变量 #7）
- UNKNOWN 高风险 Tool 不盲重跑（不变量 #14）
- 不顺手重构、不提前做未来 Phase（§8 Scope Lock）
- 跨端接口变更必须先更新总 PRD，再通知前端会话
