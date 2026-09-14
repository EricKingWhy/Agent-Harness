# 前端 PRD：Phase Multiturn 前端部分

> **前端会话专用。** 必须先读 `PRD_PHASE_MULTITURN_TOTAL.md`（跨端接口契约的唯一来源）。
> 本文件只定义前端要消费的接口（引用总 PRD 契约）+ UI 组件需求 + 前端独立任务 + 测试接缝。

---

## 1. 任务清单

| 优先级 | Ticket | 标题 | 阻塞 |
|---|---|---|---|
| P0 | #35 | 主题亮色变量组双份手工同步 | 无阻塞，可立即开始 |
| P1 | #37 | 交互式审批走通 | blocked by #136 后端 WS 推送就绪 |
| P2 | #137 前端部分 | fork/model UI | blocked by #137 后端 API 就绪 |

---

## 2. Ticket #35: 主题亮色变量组双份手工同步

### 2.1 背景

`web/src/index.css` 中亮色 token 存在两份：
- `@media (prefers-color-scheme: light) :root` — 系统偏好兜底（无 JS 时首帧正确）
- `:root[data-theme='light']` — 手动切换

CSS 原生没有变量组复用机制，修改时必须两处同步。2026-09-04 已从 3 份收敛到 2 份。

### 2.2 要做什么

**方案 A（推荐）：接受现状并保留注释**
- CSS 无 mixin，收益/风险比不划算
- 保留文件内自警注释
- 在 `CONTRIBUTING.md` 或 `AGENTS.md` 中记录"改亮色变量必须同步两处"

**方案 B：构建期生成收敛**
- 用 PostCSS / Sass 变量在构建期生成两份 CSS
- 浅色模式视觉回归（截图对比）必须过

### 2.3 验收标准

- [ ] 要么接受现状并保留注释（推荐），要么用构建期生成收敛
- [ ] 若收敛：浅色模式视觉回归（截图对比）必须过

### 2.4 测试接缝

- **视觉回归**：Playwright 截图对比（dark + light 模式）
- Prior art：`web/e2e/continuation.spec.ts` 的 Playwright 模式

---

## 3. Ticket #37: 交互式审批走通

> **勘误（as-built 契约，2026-09-09）**：本节 §3.1–§3.2 正文与下面的 JSON 示例是旧稿，
> **已作废**。实际契约以 `PRD_PHASE_MULTITURN_TOTAL.md` §2.2（已勘误）为准：
>
> - 推送不是 WS 自定义帧，而是既有事件流里的 **durable 事件**
>   `tool/approval-requested` / `permission/resolved`。WS 帧外层是
>   `{"type":"event","session_id":...,"event":{<信封>}}`，前端必须取 `event` 再匹配 `type`。
> - 审批上下文字段：`data.approval_id` / `data.tool_name` / `data.tool_call_id` /
>   `data.permission` / `data.policy` / `data.reason` / `data.allowed_decisions`
>   （词表 `["deny","approve_once"]`，不是 `allow`/`reject`）。
> - 回传端点是 `POST /api/sessions/{session_id}/approve`，body
>   `{approval_id, approved, decision, reason}`；200 返回
>   `{"status":"resolved","approval_id":...,"decision":...}`。
> - 超时 fail-closed 由**后端**兜底（`APPROVAL_TIMEOUT_SECONDS`，默认 300s → 自动 deny
>   并写 `permission/resolved`）。前端**不需要**自己倒计时后发 reject；若前端在
>   后端超时之前发（reject 或 approve_once）仍合法（200），后端超时之后再发才是
>   409（one-shot）。

### 3.1 现有基础设施

- **ApprovalCard 组件**：`web/src/components/ApprovalCard.tsx`
  - 已有 warning 玻璃 + 批准/拒绝按钮
  - 已有 `POST /api/sessions/{id}/approvals/{call_id}` 回传逻辑
  - V1 seam：后端使用 auto-approve，所以这个组件很少显示
- **WS 连接**：已有 `/api/ws` WebSocket 连接逻辑
- **后端审批端点**：已有 `POST /api/sessions/{id}/approvals/{call_id}`

### 3.2 要做什么

**A. 消费 WS 推送的 `APPROVAL_REQUESTED` 事件**

当后端通过 WS 推送审批请求时，前端需要：

1. 监听 WS 消息中的 `approval_requested` 类型
2. 提取审批上下文：`call_id`, `tool_name`, `args_summary`, `scope`, `allowed_decisions`
3. 弹出 ApprovalCard modal 显示审批信息
4. 用户决策后通过 HTTP POST 回传

**WS 消息格式（来自总 PRD §2.2）：**

```json
{
  "type": "approval_requested",
  "session_id": "sess-xxx",
  "call_id": "call-xxx",
  "tool_name": "write_file",
  "args_summary": "path=/foo/bar.py, content=...",
  "scope": "workspace-write",
  "allowed_decisions": ["allow", "reject"]
}
```

**HTTP 回传（来自总 PRD §2.2）：**

```json
// POST /api/sessions/{id}/approvals/{call_id}
{"decision": "allow"}   // 或 "reject"
```

**B. ApprovalCard 接真实 pending 事件**

当前 ApprovalCard 是静态展示组件。需要改为：
1. 从 WS 消息流接收 `approval_requested` 事件
2. 维护一个 pending approvals 队列（前端本地状态）
3. 展示当前 pending 审批，用户决策后从队列移除
4. 决策后通过 HTTP POST 回传到后端

**C. 审批超时处理**

- fail-closed：超时默认拒绝
- 前端需要在审批弹窗后启动倒计时
- 超时后自动调用 `POST /approvals/{call_id}` with `{"decision": "reject"}`

### 3.3 验收标准

- [ ] 后端 pending queue + 推送（后端 #136 负责）
- [ ] ApprovalCard 接真实 pending 事件（frontend 消费真值，不造本地队列）
- [ ] 批准/拒绝回传后工具继续/终止的 E2E
- [ ] 审批 fail-closed（超时默认拒绝）
- [ ] 审批 one-shot（同一 callId 只能决策一次）

### 3.4 测试接缝

- **E2E 审批流程**：Playwright e2e
  1. mock WS 推送 `approval_requested` 事件
  2. 验证 ApprovalCard modal 弹出
  3. 点击批准/拒绝
  4. 验证 HTTP POST 回传被拦截
  5. 验证工具继续执行或终止
- **超时测试**：mock WS 推送后等待超时时间，验证自动拒绝
- Prior art：`web/e2e/race-guard.spec.ts` + `web/e2e/continuation.spec.ts`

---

## 4. Ticket #137 前端部分: fork/model UI

> **as-built 契约（2026-09-09，后端 #137 已实现，可开工）**
>
> - `POST /api/sessions/{id}/model` body `{"provider": "zhipu", "model_id": "glm-4.5"}`。
>   `model_id` = `GET /api/models` 返回条目的 `name`（不是上游 `model_name`）；`provider`
>   必须与条目一致。成功 200 `{"status":"changed","provider","model_id"}`（`model_id`
>   是规范 picker id：条目名，或默认链的默认模型名）；422 = 不在 catalog；
>   404 = session 不存在。**选中 `is_default: true` 的条目 = 切回默认链**（合法，事件
>   `to_model_id: null`）——picker 应把它当普通选项处理，不要在前端禁止。`from_*` 可能为 null。
>   与默认条目同 provider + 同名的 catalog 条目不会出现在 `GET /api/models` 里（被默认条目遮蔽）。
> - `POST /api/sessions/{id}/forks` body `{"from_seq": <用户消息 seq>}`。
>   成功 200 `{"session_id": "<child>", "from_seq": ...}`；409 = 在途 run；422 = 锚点非法。
>   `from_seq` 只接受**用户消息**的 seq（可用边界由后端 `find_fork_boundaries` 决定）。
> - 事件是 **`model/changed`**（不是 `model_changed`），data 字段
>   `from_provider` / `from_model_id` / `to_provider` / `to_model_id`（`from_*` 可能为 null）。
>   前端在事件流里取 `event` 再匹配内层 `type`。**投递时机**：若切换时该 session
>   有在途 run，事件经该 run 的 listener 实时推给已订阅的 SSE/WS；若空闲，
>   没有 run 级订阅可推——picker 应直接用 POST 响应的 `model_id` 做乐观更新，
>   durable 事件在重连重放 / 下一轮 run 的事件流里到达。

### 4.1 现有基础设施

- **后端 API**：`POST /api/sessions/{id}/model` + `POST /api/sessions/{id}/forks`（后端 #137 负责）
- **前端 WS/SSE 消费**：已有
- **历史消息列表**：已有

### 4.2 要做什么

**A. Fork 触发 UI**

从历史消息右键/菜单触发 fork：
1. 在历史消息上提供"从这里分叉"菜单项
2. 点击后调用 `POST /api/sessions/{id}/forks` with `{"from_seq": <message_seq>}`
3. 成功后切换到新 session 视图

**B. Model 切换 UI（可选，后续迭代）**

如果 Composer control row 有 model picker：
1. 选择新模型后调用 `POST /api/sessions/{id}/model`
2. 监听 `MODEL_CHANGED` 事件更新 UI

### 4.3 验收标准

- [ ] 前端从历史消息右键/菜单触发 fork
- [ ] fork 成功后切换到新 session 视图
- [ ] （可选）model 切换 UI 工作

### 4.4 测试接缝

- **Fork E2E**：Playwright e2e
  1. 发几条消息
  2. 在某条消息上触发 fork
  3. 验证新 session 创建成功
  4. 验证原 session 不受影响
- Prior art：`web/e2e/continuation.spec.ts`

---

## 5. 执行顺序

```
#35 CSS 亮色变量组    ← P0，无阻塞，可立即开始
  ↓
#37 交互式审批走通    ← P1，blocked by #136 后端 WS 推送就绪
  ↓
#137 前端部分         ← P2，blocked by #137 后端 API 就绪
```

每个 ticket 按 to-tickets → /implement → code-review 流程执行。
完成后通知集成 AI 合并到 `main`。

---

## 6. 与后端的接口对齐

前端消费的所有接口都在总 PRD（`PRD_PHASE_MULTITURN_TOTAL.md`）中定义。
如果后端实现偏离了总 PRD 的契约，前端应立即报告，由集成 AI 裁决。

| 接口 | 前端消费方式 | 对应后端 ticket |
|---|---|---|
| WS `tool/approval-requested` 事件（取 `event` 后匹配 `type`） | 监听 WS 事件流 | #136 |
| `POST /api/sessions/{id}/approve`（body 带 `approval_id`） | HTTP 回传审批决策 | #136 |
| `POST /api/sessions/{id}/model` | HTTP 切换模型 | #137 |
| `POST /api/sessions/{id}/forks` | HTTP 从历史点 fork | #137 |
| SSE/WS `model/changed` 事件（取 `event` 后匹配 `type`） | 监听事件流更新 UI | #137 |
| `run/interrupted` 事件（信封带 `run_id` / `step_id`，data 带 `interrupted_seq` / `reason`） | 打开 session 时在事件流里检测 → 显示"上次运行在第 N 步中断" + 继续/重发/忽略 | #138 |

### 6.1 崩溃恢复（#138）前端契约

- **事件名是 `run/interrupted`**（不是 `run_interrupted`）。打开已有 session 时，
  从事件流（`GET /api/sessions/{id}/events` 或重连重放）里找最后一条
  `run/interrupted`：`step_id` 显示"第 N 步"，`interrupted_seq` 定位中断点。
- 三个动作复用既有端点，后端不新增：
  - **继续** → `POST /api/sessions/{id}/messages`（新 user 消息续聊）；
  - **重发** → 用中断前的最后一条 user 消息内容再发一次 `messages`；
  - **忽略** → 纯前端收起提示（可选：不改后端状态）。
- 若后端扫描时发现 UNKNOWN 工具调用（副作用未知），该 session 不会自动
  合成结果，也不会写 `session/resumed`；前端不应假设"已恢复"。此时**继续 /
  重发都会返回 409**（后端拒绝伪造"结果未知"，不变量 #14），detail 点名
  需要裁决的 `tool_name` / `tool_call_id`；按需引导用户走
  `POST /api/sessions/{id}/recover` 的人工裁决路径（409 = 需裁决）。
