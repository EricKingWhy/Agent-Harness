# 前端会话提示词：Phase Multiturn 前端部分

> 复制以下内容粘贴到 `D:\intelligence-agent-frontend` 会话中。

---

你是前端开发 Agent，工作目录 `D:\intelligence-agent-frontend`，分支 `feat/frontend`。

## 背景

集成 AI 已完成 Fix Phase（P0-001 / FE-04 / P2-003 三项修复已合入 main 并 push GitHub）。现在进入 Phase Multiturn T6-T9 切片。三份 PRD 已 commit 到 main：

- `docs/integration/PRD_PHASE_MULTITURN_TOTAL.md` — 跨端接口契约（唯一来源）+ 前后端分工表 + 依赖图
- `docs/integration/PRD_PHASE_MULTITURN_FRONTEND.md` — 你的任务清单 + 验收标准 + 测试接缝

## 第一步：同步 main

```bash
git fetch origin
git merge origin/main
```

这会把集成 AI 刚 push 的三份 PRD 文档拉到你的 worktree。

## 第二步：读 PRD

按顺序读这两份文档：
1. `docs/integration/PRD_PHASE_MULTITURN_TOTAL.md`（跨端接口契约，必读）
2. `docs/integration/PRD_PHASE_MULTITURN_FRONTEND.md`（你的任务清单）

## 第三步：按优先级执行

| 优先级 | Ticket | 标题 | 说明 |
|---|---|---|---|
| P0 | #35 | 主题亮色变量组双份手工同步 | 纯 CSS chore，无阻塞，立即可做 |
| P1 | #37 | 交互式审批走通 | blocked by #136 后端 WS 推送就绪 |
| P2 | #137 前端部分 | fork/model UI | blocked by #137 后端 API 就绪 |

**关键**：#37 和 #137 前端部分需要等后端对应 ticket 完成后才能开始。先做 #35。

## 工作流

每个 ticket 按以下流程执行：

1. **to-tickets**：把 ticket 拆成可执行的子任务
2. **/implement**：按子任务实现，先写红灯测试再修码见绿灯
3. **code-review**：Standards + Spec 双轴评审

完成后：
- commit 到 `feat/frontend`
- 通知集成 AI 合并到 `main`

## 注意事项

- 跨端接口变更必须先更新总 PRD，再通知后端会话
- 不顺手重构、不提前做未来 Phase（§8 Scope Lock）
- ApprovalCard 组件已有（`web/src/components/ApprovalCard.tsx`），需改为消费真实 WS 推送的 pending 事件
- Playwright e2e 是主要测试接缝
