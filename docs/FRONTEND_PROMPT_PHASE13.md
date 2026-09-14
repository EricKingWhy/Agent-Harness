# Phase 13 前端适配提示词（前端 AI 执行手册）

> **收件人**：前端 AI（`D:\intelligence-agent-frontend`，分支 `feat/frontend`）
> **任务**：适配 Phase 13 Multi-Agent 的两个新 SessionEvent——`agent/delegation-started` / `agent/delegation-finished`（父流白盒委派事件）
> **写于**：2026-09-06，后端 Phase 13 已完成（feat/backend `80eaad6`，#82-#93 全关，Gate 8/8）
> **红线**：永不 force-push / rebase / reset --hard；`web/src/generated/event-types.ts` 是 **backend-owned** 文件（绝不能手改，只能随 merge 到达）；`lib/projection.ts` 是单一投影源（不变量 #22，不建第二套会话真相）；每次 git 写操作前确认 worktree 与分支（§14.2）

---

## 0. 前置依赖（顺序红线）

本批事件的类型常量在 backend-owned 的 `web/src/generated/event-types.ts` 里（`AGENT_DELEGATION_STARTED` / `AGENT_DELEGATION_FINISHED`），**随 feat/backend → main 的集成 merge 到达**。集成 AI 手册见 `D:\intelligence-agent-backend\docs\INTEGRATION_PROMPT_PHASE13.md`。

- 若集成尚未完成：先等集成，或经用户确认后直接从 `origin/main`（或 feat/backend）拿该文件——**不要自己往 generated 文件里加常量**
- 开工步骤 0（先回后正，§14.6）：`git -C D:\intelligence-agent-frontend fetch origin --prune && git merge origin/main`（冲突预期：`docs/PHASE_STATUS.md` 语义并集；`generated/event-types.ts` 两侧同 blob 应自动收敛）

## 1. 事件契约（冻结，后端已 Gate 验收）

两个事件只出现在**父 session 流**（child 的完整多轮历史在 child 自己的 JSONL，不在父流——这是后端 Gate 4 验收过的不变量，前端不要试图在父流里找 child 内幕）：

```ts
// agent/delegation-started —— 委派开始（与 tool/call(delegate) 同批落盘，在其后）
{
  target: string;          // 子代理 profile 名：'research_review' | 'coding'（V1 三内置，main 不经 delegate）
  task: string;            // 给 child 的完整任务描述（自洽，父对话不含在内）
  child_session_id: string; // child 独立会话 id —— 钻取主键
}

// agent/delegation-finished —— 委派结束（阻塞语义：返回即 child 已终态）
{
  target: string;
  child_session_id: string;
  status: 'completed' | 'failed';  // child 终态，无中间态
  summary: string;                 // 结构化结果的文字摘要（可能很长，见下）
}
```

**summary 溢出约定**（后端 #86）：summary 超过 8192 字符且未配 overflow store 时，会被截断并追加指针后缀：

```
[summary 超限已截断至 8192 字符；完整输出见 child session <child_session_id>]
```

前端可识别该后缀（或直接按长度截断展示 + 「查看完整输出」入口），不需要解析更多结构。

**流内位置**：两个事件出现在 `tool/call(delegate)` 与 `tool/result` **之间**（pending_events 通道）；并行委派时一对 start/finish 按完成顺序落盘。事件流里它们是**编排事实**，不是模型/工具内部噪音。

**child 会话数据**：`GET /api/sessions/{child_session_id}/events`（Phase 9 既有 API）返回 child 完整事件流；child session 也会出现在 `GET /api/sessions` 列表里（同 store）。

## 2. 适配范围（最小闭环 → 增强，按序交付）

### A. 最小闭环（必做）

1. **`lib/projection.ts`**：为两个事件各加 case（模板 = Phase 12 的 `TOOL_FAILURE_GUARD`/`MODEL_FALLBACK` case，`:360-393` 附近）。建议投影形态（在你们冻结的设计决策内自行定夺）：
   - 委派在 Trace Ladder / Timeline 上是**一个编排节点**（「委派 → research_review」），started 创建节点、finished 回填状态（completed=成功态 / failed=失败态，复用 DSH 工具四态视觉语言）
   - summary 默认折叠（长文本），展开显示全文；`child_session_id` 可见且可复制
   - `model_fallback` 同款：`ConversationState` 不需要新全局字段——委派是 turn 级事实，建议挂 turn/step 级（与你们 Phase 12 的 `turn.notices` 机制对齐）
2. **`lib/eventKind.ts`**（若有事件分类表）：两个事件归类为编排/委派类（不是 model-delta 噪音，不进密度折叠的 delta 桶）
3. **不要**把 delegation 事件渲染进聊天正文——它是执行链事实（Trace Ladder / Inspector 域），不是对话消息
4. **vitest**：projection 纯函数用例（started 建节点 / finished 回填 completed 与 failed / summary 指针后缀识别 / 并行双委派两对事件）——Phase 12 批是 +7 条，本批量级类似
5. Gate：`tsc clean` + vitest 全绿 + 生产构建通过

### B. 增强（可选，一个批处理内量力）

- **child 钻取**：点击委派节点 → Inspector 打开 child session（`GET /api/sessions/{id}/events` 拉取，复用现有 session 视图渲染 child 的执行链）。做不了完整钻取就先做「新窗口打开该 session」（列表里 child session 本来就在）
- **委派徽标**：会话列表/头部若有 agent 归因位，delegation 事件可贡献「多代理」标记

## 3. 不做的事（边界）

- 不解析/依赖 child JSONL 的内部事件结构做父流渲染（child 内幕只属于 child 视图）
- 不手改 `generated/event-types.ts`；不绕过 projection.ts 在组件里散落 switch
- 不为「未来异步委派 / depth>1 / lineage tree」预建抽象（Phase 14 地盘；后端 V1 = 阻塞串行/并行、depth=1）
- 后端行为参考：启用 multiagent 需要 CAPABILITIES 配置（集成 AI 手册 §D2）——未启用时父流不会出现这两个事件，前端无需开关

## 4. 完成后

按 §13.2 默认流程：commit 到 feat/frontend（不 push、不合 main），向用户报告：改了什么 / 测试结果 / commit / 是否建议合并。集成顺序遵循 §14.9：feat/backend 已先行，本批是纯前端批。
