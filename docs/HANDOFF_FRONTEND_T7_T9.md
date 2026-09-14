# 前端交接手册：T7 #137 + T8 #138 + T9 #139

> **后端分支**：`feat/backend`（HEAD `c438a1e`）
> **前端分支**：`feat/frontend`
> **测试**：1485 passed / 9 skipped / 0 failed；ruff clean
> **生成物已更新**：`web/src/generated/event-types.ts`（+`MODEL_CHANGED`、+`RUN_INTERRUPTED`）

---

## 一、后端做了什么

### T7 #137 — 会话级模型切换 + Fork API/CLI（commit `ae553ad`）

**新增端点：**

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/sessions/{id}/model` | POST | 切换会话当前模型，写 `model/changed` 事件 |

请求体：
```json
{ "provider": "deepseek", "model_id": "deepseek-chat" }
```

响应（200）：
```json
{ "status": "changed", "provider": "deepseek", "model_id": "deepseek-chat" }
```

错误码：
- 404 = session 不存在
- 422 = provider/model_id 不在 catalog

**关键行为：**
- 切换不打断在途 run——下一轮 run 从事件流派生当前模型生效
- `GET /api/models` 的默认条目（`is_default=true`）也是合法 POST target = 切回默认链
- 与默认条目同 provider + 同名的 catalog 条目会被遮蔽（选不中），`GET /api/models` 不列出该死选项
- 响应回传规范 model_id（service 解析出的 picker id），**不回显请求值**——否则上游 `model_name` / `"default"` 别名会与事件里的 `to_model_id` 及 `GET /api/models` 的 id 对不上

**新增事件：**

```typescript
// web/src/generated/event-types.ts 已更新
MODEL_CHANGED: 'model/changed',
```

`model/changed` 事件 data 字段：
```json
{
  "from_provider": "openai",
  "from_model_id": "gpt-4o",
  "to_provider": "deepseek",
  "to_model_id": "deepseek-chat"
}
```

**Fork 端点：**

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/sessions/{id}/forks` | POST | 从历史用户消息 seq 派生 child session |

请求体：
```json
{ "from_seq": 5 }
```

响应（200）：
```json
{ "session_id": "child-uuid", "from_seq": 5 }
```

错误码：
- 404 = session 不存在
- 409 = 在途 run（历史未 settled）
- 422 = from_seq 不是合法 fork 锚点（不是用户消息 seq）

**Fork 关键行为：**
- 锚点消息本身不进 child seed（child 侧由用户重新发送，pi /fork 同款语义）
- child 继承父会话当前模型（seed 不含父 `session/started`，补一条 `model/changed`，否则父创建时选的 catalog 模型会在 child 静默回落默认链）
- HTTP 端点不生成 tail summary（确定性、无模型调用）
- copy-on-fork：父 workspace 整目录复制为 child 的

---

### T8 #138 — 崩溃恢复：run/interrupted + Ledger reconcile（commit `ccebf9a`）

**新增事件：**

```typescript
// web/src/generated/event-types.ts 已更新
RUN_INTERRUPTED: 'run/interrupted',
```

`run/interrupted` 事件结构：
```json
{
  "type": "run/interrupted",
  "session_id": "sess-xxx",
  "run_id": "run-xxx",
  "step_id": 3,
  "data": {
    "interrupted_seq": 42,
    "reason": "process_restart"
  }
}
```

**信封字段说明：**
- `run_id` — 被中断的 run 标识（前端按 run 归组）
- `step_id` — 中断发生在第几步（前端显示「上次运行在第 N 步中断」）
- `data.interrupted_seq` — 该 run 最后一条事件的 seq
- `data.reason` — 固定 `"process_restart"`

**崩溃扫描流程（web lifespan 启动时自动执行）：**

```
进程重启
→ 遍历所有 session
→ 检测无终态 run（run/started 之后没有 run/completed / run/failed / run/interrupted）
→ 补记 run/interrupted 事件
→ 强制跑 RecoveryCoordinator（Ledger-first reconcile）
→ UNKNOWN 工具调用无 ReconcileCallback 时安全拒绝
  （ReconcileRequired → ScanRecovery.NEEDS_MANUAL_RECONCILE）
→ 不伪造结果、不盲重跑（不变量 #14）
```

**续跑守卫（前端需要处理的 409）：**

当用户对一个有崩溃遗留（UNKNOWN 高风险 tool_call）的 session 发 `POST /api/sessions/{id}/messages`（继续/重发）时：

```json
// HTTP 409
{
  "detail": "存在需要人工裁决的 UNKNOWN Operation（bash(tool_call_id=call-1)）：..."
}
```

前端应：
1. 捕获 409，解析 detail 中的 `tool_name` 和 `tool_call_id`
2. 提示用户「此会话有未确认的高风险工具调用，需人工裁决」
3. 提供「调 `POST /api/sessions/{id}/recover` 重试」或「忽略」的选项
4. **不得**伪造「结果未知」继续——这是后端硬拒绝的

**扫描归属（单进程假设）：**
- 扫描只在**持有会话的进程**启动时执行一次（web lifespan）
- CLI 子命令**不扫描**——在途 run 只存在于本进程内存，短命命令无法区分「别的进程在跑」与「崩溃遗留」，误标会让两侧各自推算 seq 撞号
- 多进程/多 worker 需跨进程 run lease（后续 Phase）

---

### T9 #139 — Langfuse turn_index 埋点（commit `c438a1e`）

**变更内容：**

`Session.begin_run()` 现在返回 `(run_id, turn_index)` 并在 `RUN_STARTED` 事件 data 里写入 `turn_index`（1-based，该 session 里第几个 run）。

`RunTracer` 接受 `turn_index` 参数并放入 trace metadata，供 Langfuse UI 按 `session_id` 过滤时区分「第 N 轮」。

**前端影响：**

`RUN_STARTED` 事件 data 现在多一个字段：
```json
{
  "type": "run/started",
  "data": { "turn_index": 1 }
}
```

前端可以选择显示「第 N 轮」标签，也可以忽略这个字段（不影响现有行为）。

---

## 二、坑点 & 前端需要注意的事项

### 坑 1：`model/changed` 事件的 `from_*` 字段可能为 null

`from_provider` 和 `from_model_id` 是从事件流派生的（最后一条切换 > `session/started` 初值 > null）。如果会话从未切换过模型，这些字段会是 null。

**前端处理**：显示「切回默认链」时不要假设 `from_*` 一定有值。

### 坑 2：POST /model 响应的 model_id 不等于请求的 model_id

Service 会解析出规范 picker id（catalog 条目名，或默认链的默认模型名）。如果前端用请求值做本地状态更新，会与事件里的 `to_model_id` 及 `GET /api/models` 的 id 对不上。

**前端处理**：始终用响应里的 `model_id` 更新本地状态，不要用请求值。

### 坑 3：`GET /api/models` 会过滤掉被默认条目遮蔽的 catalog 条目

与默认条目同 provider + 同名的 catalog 条目不会被列出（选不中的死选项）。前端不需要特殊处理——后端已经过滤了。

### 坑 4：Fork 的 `from_seq` 必须是用户消息的 seq

`from_seq` 不是任意事件的 seq——它必须是 `user/message` 类型事件的 seq。如果传了一个非用户消息的 seq，后端返回 422。

**前端处理**：fork 选择器只列出用户消息作为合法锚点。

### 坑 5：`run/interrupted` 是 run 终态——fork 边界校验会认它

`RUN_TERMINAL_TYPES` frozenset 包含 `run/completed`、`run/failed`、`run/interrupted`。这意味着被中断轮之后的用户消息仍是合法 fork 锚点。

**前端处理**：fork 选择器不需要排除 `run/interrupted` 之后的消息——它们是合法锚点。

### 坑 6：崩溃恢复的 409 响应需要前端引导用户走人工裁决

当 `POST /api/sessions/{id}/messages` 返回 409 且 detail 包含「UNKNOWN」时，前端应提示用户「此会话有未确认的高风险工具调用，需人工裁决」，并提供「调 `POST /api/sessions/{id}/recover` 重试」或「忽略」的选项。

**前端处理**：
- 409 + detail 含「UNKNOWN」→ 显示人工裁决提示
- 409 + detail 含「active run」→ 显示「会话正在运行中」提示

### 坑 7：`RUN_STARTED` 事件 data 现在有 `turn_index` 字段

这是 T9 新增的字段。前端可以选择显示「第 N 轮」标签，也可以忽略这个字段（不影响现有行为）。

**前端处理**：如果显示轮次标签，用 `data.turn_index`；如果不显示，忽略即可。

### 坑 8：续聊追加不写 `session/resumed`——queue/steer/模型切换走旁路

`Session.append_event()` 是只 append 不修复 dangling 的入口。queue/steer/模型切换的追加优先用「在途 run 持有的 Session」——两个 Session 实例从同一磁盘快照各自推算 seq 会撞号（重复 seq 让会话不可 resume），且 run 的 listener 在册才能把事件实时广播给 SSE/WS 订阅者；无在途 run 时才只读加载。

**前端处理**：模型切换事件 `model/changed` 会通过 SSE/WS 实时推送，前端监听事件流更新 UI 即可。

### 坑 9：`begin_run()` 返回元组 `(run_id, turn_index)`

这是 T9 的变更。`Session.begin_run()` 现在返回 `tuple[str, int]` 而不是 `str`。所有调用方都已更新。

**前端影响**：无直接影响——这是后端内部变更。但如果前端有 TypeScript 类型定义引用了 `begin_run` 的返回类型，需要更新。

---

## 三、前端需要实现的 UI 部分

### T7 #137 前端部分

1. **模型选择器**：在会话设置中提供模型选择下拉框，数据来源 `GET /api/models`
   - 默认条目（`is_default=true`）= 切回默认链
   - 选择后调 `POST /api/sessions/{id}/model`
   - 用响应里的 `model_id` 更新本地状态

2. **Fork 选择器**：在历史消息上提供 fork 入口
   - 用户消息右键/菜单触发 fork
   - 调 `POST /api/sessions/{id}/forks` body `{from_seq}`
   - 成功后跳转到 child session

3. **模型切换事件监听**：监听 SSE/WS 事件流中的 `model/changed` 事件，更新 UI 显示当前模型

### T8 #138 前端部分

1. **中断提示 UI**：打开有 `run/interrupted` 的 session 时，显示「上次运行在第 N 步中断」
   - 从事件流（`GET /api/sessions/{id}/events` 或重连重放）里找最后一条 `run/interrupted`
   - `step_id` 显示「第 N 步」，`interrupted_seq` 定位中断点

2. **三个动作**：
   - **继续** → `POST /api/sessions/{id}/messages`（新 user 消息续聊）
   - **重发** → 用中断前的最后一条 user 消息内容再发一次 `messages`
   - **忽略** → 纯前端收起提示（可选：不改后端状态）

3. **409 人工裁决提示**：
   - 当 `POST /api/sessions/{id}/messages` 返回 409 且 detail 含「UNKNOWN」时
   - 提示用户「此会话有未确认的高风险工具调用，需人工裁决」
   - 提供「调 `POST /api/sessions/{id}/recover` 重试」或「忽略」的选项

### T9 #139 前端部分

1. **轮次标签**（可选）：在 run 展示区域显示「第 N 轮」标签
   - 数据来源：`RUN_STARTED` 事件的 `data.turn_index`
   - 如果不显示，忽略这个字段即可

---

## 四、API 契约速查

### 模型切换

```
POST /api/sessions/{id}/model
Body: { "provider": "deepseek", "model_id": "deepseek-chat" }
→ 200 { "status": "changed", "provider": "deepseek", "model_id": "deepseek-chat" }
→ 404 session 不存在
→ 422 provider/model_id 不在 catalog
```

### Fork

```
POST /api/sessions/{id}/forks
Body: { "from_seq": 5 }
→ 200 { "session_id": "child-uuid", "from_seq": 5 }
→ 404 session 不存在
→ 409 在途 run（历史未 settled）
→ 422 from_seq 不是合法 fork 锚点
```

### 列出模型

```
GET /api/models
→ 200 { "models": [ { "id": "...", "provider": "...", "is_default": true/false, ... } ] }
```

### 续聊消息

```
POST /api/sessions/{id}/messages
Body: { "content": "继续", "mode": "queue" }
→ 200 SSE 流（空闲 → 直接拉起新 run）
→ 404 session 不存在
→ 409 在途 run（queue 模式下不会发生）或 UNKNOWN 高风险 tool_call 需人工裁决
→ 422 content 为空或 mode 不合法
```

### 恢复会话

```
POST /api/sessions/{id}/recover
→ 200 恢复后的事件列表
→ 404 session 不存在
→ 409 存在需人工裁决的 UNKNOWN Operation
```

---

## 五、事件类型对照表

| 事件类型 | 说明 | T7/T8/T9 新增 |
|---|---|---|
| `session/started` | 会话创建 | |
| `session/resumed` | 会话恢复完成 | |
| `session/forked` | Fork 创建完成 | |
| `run/started` | Run 开始 | T9: data 加 `turn_index` |
| `run/completed` | Run 完成 | |
| `run/failed` | Run 失败 | |
| `run/interrupted` | Run 被崩溃打断 | **T8 新增** |
| `model/changed` | 会话模型切换 | **T7 新增** |
| `user/message` | 用户消息 | |
| `model/completed` | 模型调用完成 | |
| `model/failed` | 模型调用失败 | |
| `tool/call` | 工具调用 | |
| `tool/result` | 工具结果 | |
| `operation/reconcile-required` | 需人工裁决 | |
| `artifact/created` | Artifact 创建 | |
| `artifact/externalized` | Artifact 外置 | |
| `context/compacted` | 上下文压缩 | |
| `memory/degraded` | 记忆降级 | |
| `tool/failure-guard` | 工具失败守卫 | |
| `model/fallback` | 模型回退 | |
| `agent/delegation-started` | SubAgent 委托开始 | |
| `agent/delegation-finished` | SubAgent 委托结束 | |
| `reasoning/started` | 推理开始 | |
| `reasoning/delta` | 推理增量 | |
| `reasoning/completed` | 推理完成 | |
| `reasoning/interrupted` | 推理中断 | |
| `tool/approval-requested` | 工具审批请求 | |
| `permission/resolved` | 权限裁决 | |
| `tool/output_delta` | 工具输出增量 | |
| `text/delta` | 文本增量 | |
| `compaction/start` | 压缩开始 | |
| `compaction/end` | 压缩结束 | |
| `message/queued` | 消息入队 | |
| `queue/cancelled` | 队列取消 | |
| `steer/requested` | Steer 请求 | |
| `steer/applied` | Steer 应用 | |

---

## 六、测试覆盖

| 测试文件 | 测试数 | 说明 |
|---|---|---|
| `tests/session/test_model_change.py` | 26 | 模型切换事件、派生、fork 继承 |
| `tests/web/test_web_model_fork.py` | 11 | Web 层模型切换 + Fork API |
| `tests/model/test_model_catalog.py::TestFindCatalogEntry` | 5 | Catalog 条目查找 |
| `tests/recovery/test_scan_interrupted.py` | 11 | 崩溃扫描检测、标记、reconcile、幂等、kill test |
| `tests/web/test_web_multiturn.py::TestCrashReconcileGuard` | 2 | UNKNOWN 409 守卫 + terminal 精确回填 |
| `tests/session/test_fork.py::test_fork_from_interrupted_run_prefix` | 1 | run/interrupted 后 fork 合法性 |
| `tests/session/test_session.py::test_begin_run_increments_turn_index` | 1 | turn_index 递增 |
| `tests/observability/test_tracer.py::test_turn_index_passed_to_trace_metadata` | 1 | turn_index 传入 trace metadata |

全量：**1485 passed / 9 skipped / 0 failed**

---

## 七、未完成项 & 后续 ticket

| 项目 | 状态 | 说明 |
|---|---|---|
| T7 前端 UI | ⬜ 待前端实现 | 模型选择器、fork 选择器、model/changed 事件监听 |
| T8 前端 UI | ⬜ 待前端实现 | 中断提示 UI、409 人工裁决提示、继续/重发/忽略按钮 |
| T9 前端 UI | ⬜ 可选 | 轮次标签（data.turn_index） |
| A.4 compaction 子 span | ⬜ 后续迭代 | 既有 context_build_completed 已传 compacted_turn_count；独立 compaction 子 span 未加 |
| 架构深化候选 | ⬜ out-of-scope | `_drive` 分解、`SessionService` 拆分、Recovery 流程整合（§8 Scope Lock） |

---

## 八、集成 AI 注意事项

1. **`web/src/generated/event-types.ts` 是生成物**——合入后需确认前端 worktree 同步到最新版本
2. **`AGENTS.md` §16 SDD 长任务工作流协议**——本次新增的防指令漂移机制，请勿删除
3. **`CONTEXT.md` 更新**——`run/interrupted` 术语、Run 边界更新已写入
4. **未推送远程**——等你交给集成 AI 处理
