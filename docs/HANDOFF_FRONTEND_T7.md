# 前端交接手册：#137 Phase Multiturn T7 — 模型切换 + Fork UI

> **后端分支**：`feat/backend`（HEAD `c438a1e`，已合入 main `977b319`）
> **前端分支**：`feat/frontend`
> **后端测试**：1485 passed / 9 skipped / 0 failed；ruff clean
> **Issue**：[#137](https://github.com/EricKingWhy/intelligence-agent/issues/137)（OPEN，后端完成，前端 UI 待做）

---

## 一、后端已交付的 API 契约

### 1. POST `/api/sessions/{session_id}/model` — 切换会话当前模型

**请求体**：
```json
{
  "provider": "deepseek",
  "model_id": "deepseek-chat"
}
```

**响应**（200）：
```json
{
  "status": "changed",
  "provider": "deepseek",
  "model_id": "deepseek-chat"
}
```

**错误码**：
| 状态码 | 含义 |
|---|---|
| 404 | session 不存在 |
| 422 | provider/model_id 不在 catalog |

**关键行为**：
- 切换不打断在途 run——下一轮 run 从事件流派生当前模型生效
- `GET /api/models` 的默认条目（`is_default=true`）也是合法 POST target = 切回默认链
- 与默认条目同 provider + 同名的 catalog 条目会被遮蔽（选不中），`GET /api/models` 不列出该死选项
- 响应回传规范 model_id（service 解析出的 picker id），**不回显请求值**——否则上游 `model_name` / `"default"` 别名会与事件里的 `to_model_id` 及 `GET /api/models` 的 id 对不上

### 2. POST `/api/sessions/{session_id}/forks` — 从历史点 fork

**请求体**：
```json
{
  "from_seq": 5
}
```

**响应**（200）：
```json
{
  "session_id": "child-uuid",
  "from_seq": 5
}
```

**错误码**：
| 状态码 | 含义 |
|---|---|
| 404 | session 不存在 |
| 409 | 在途 run（历史未 settled） |
| 422 | from_seq 不是合法 fork 锚点（不是用户消息 seq） |

**关键行为**：
- 锚点消息本身不进 child seed（child 侧由用户重新发送，pi /fork 同款语义）
- child 继承父会话当前模型（seed 不含父 `session/started`，补一条 `model/changed`，否则父创建时选的 catalog 模型会在 child 静默回落默认链）
- HTTP 端点不生成 tail summary（确定性、无模型调用）
- copy-on-fork：父 workspace 整目录复制为 child 的

### 3. GET `/api/sessions/{session_id}/lineage` — 会话谱系树

**响应**（200）：
```json
{
  "session_id": "sess-xxx",
  "ancestors": [
    { "session_id": "parent-uuid", "origin": "fork", "fork_point_seq": 5 }
  ],
  "children": [
    { "session_id": "child-uuid", "origin": "fork", "fork_point_seq": 3, "created_at": "..." }
  ],
  "edges": [
    { "from": "parent-uuid", "to": "sess-xxx", "origin": "fork", "fork_point_seq": 5 }
  ]
}
```

### 4. 新增事件类型

`web/src/generated/event-types.ts` 已更新（后端生成物）：

```typescript
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

**注意**：`from_provider` 和 `from_model_id` 可能为 null（会话从未切换过模型时从 `session/started` 初值派生）。

---

## 二、前端现状 & 缺口

### 已有组件

| 文件 | 说明 |
|---|---|
| `web/src/components/ModelPicker.tsx` | Radix Popover + cmdk 实现的模型选择器，数据来源 `GET /api/models` |
| `web/src/components/Composer.tsx` | 有 `onModelChange?: (name: string \| null) => void` 回调，传入 ModelPicker |
| `web/src/hooks/useSession.ts` | 会话 hook，管理 SSE 流、事件投影 |
| `web/src/lib/api.ts` | REST API 客户端，已有 `getModels()`、`startSession()`、`sendMessage()` 等 |

### 缺失部分（需要实现）

#### A. `changeModel()` API 函数（`web/src/lib/api.ts`）

当前 `api.ts` 没有 `changeModel` 函数。需要新增：

```typescript
export async function changeModel(
  sessionId: string,
  provider: string,
  modelId: string,
): Promise<{ status: string; provider: string; model_id: string }> {
  const res = await apiFetch(
    `/api/sessions/${encodeURIComponent(sessionId)}/model`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model_id: modelId }),
    },
  );
  if (!res.ok) throw new Error(`change model ${res.status}`);
  return res.json();
}
```

#### B. `forkSession()` API 函数（`web/src/lib/api.ts`）

当前 `api.ts` 没有 `forkSession` 函数。需要新增：

```typescript
export async function forkSession(
  sessionId: string,
  fromSeq: number,
): Promise<{ session_id: string; from_seq: number }> {
  const res = await apiFetch(
    `/api/sessions/${encodeURIComponent(sessionId)}/forks`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_seq: fromSeq }),
    },
  );
  if (!res.ok) throw new Error(`fork ${res.status}`);
  return res.json();
}
```

#### C. 模型切换 UI 接线（`web/src/hooks/useSession.ts` 或新 hook）

需要在会话视图中接入模型切换：

1. 用户通过 ModelPicker 选择模型
2. 调用 `changeModel(sessionId, provider, modelId)`
3. 用响应里的 `model_id` 更新本地状态（**不要用请求值**）
4. 监听 SSE/WS 事件流中的 `model/changed` 事件，实时更新 UI

**坑点**：
- POST /model 响应的 `model_id` 是 service 解析出的规范 picker id（catalog 条目名，或默认链的默认模型名），不等于请求的 `model_id`
- 如果前端用请求值做本地状态更新，会与事件里的 `to_model_id` 及 `GET /api/models` 的 id 对不上
- `from_provider` 和 `from_model_id` 可能为 null（会话从未切换过模型）

#### D. Fork 选择器 UI（`web/src/components/Conversation.tsx` 或新组件）

需要在历史消息上提供 fork 入口：

1. 用户消息右键/长按/菜单按钮触发 fork
2. 调用 `forkSession(sessionId, userMessageSeq)`
3. 成功后切到 child session 视图（`session_id` 来自响应）
4. 处理错误码：409（在途 run）、422（非法锚点）

**坑点**：
- `from_seq` 必须是 `user/message` 类型事件的 seq，不是任意事件的 seq
- fork 后的 child session 需要通过 `listSessions()` 或 `getSessionEvents(childId)` 加载
- child 继承父会话当前模型（不需要前端额外处理）

---

## 三、AC 对照表

| AC | 后端 | 前端 | 状态 |
|---|---|---|---|
| 同一 session 中途换模型，`MODEL_CHANGED` 写入 JSONL | ✅ `POST /api/sessions/{id}/model` | ModelPicker → `changeModel()` | 后端完成 |
| 下一轮 run 使用新模型，上下文不丢 | ✅ `resume_and_launch` 从事件流派生 | 监听 `model/changed` 更新 UI | 后端完成 |
| `POST /api/sessions/{id}/model` 工作 + 校验 provider 可用性 | ✅ catalog 寻址 + provider 一致 + 可装配校验 | — | 后端完成 |
| `POST /api/sessions/{id}/forks` 从指定 seq 派生新 session | ✅ 复用 `fork.py` / `lineage.py` | Fork 选择器 → `forkSession()` | 后端完成 |
| fork 出的新 session 独立，原 session 不受影响 | ✅ file-per-lineage + copy-on-fork | — | 后端完成 |
| CLI `/model` 和 `/fork` 工作 | ✅ `demo/live_agent.py` 真实接线 | — | 后端完成 |
| 复用 fork.py/lineage.py，不重写 | ✅ | — | 后端完成 |
| ruff clean + 测试 green | ✅ 1485 passed / 9 skipped / 0 failed | — | 后端完成 |

---

## 四、测试建议

### 单元测试

1. **`changeModel()` API 函数**：mock fetch，断言请求 URL/method/body 正确，响应解析正确
2. **`forkSession()` API 函数**：同上
3. **ModelPicker 接线**：选择模型后调用 `changeModel()`，用响应 `model_id` 更新本地状态

### E2E 测试

1. **模型切换 E2E**：创建会话 → 通过 ModelPicker 切换模型 → 断言 `model/changed` 事件被正确接收和显示
2. **Fork E2E**：创建会话发几条消息 → 在某条消息上触发 fork → 断言新 session 创建成功 → 断言原 session 不受影响

Prior art：`web/e2e/continuation.spec.ts` + `web/e2e/fixtures.ts` 的 `routeApi` mock 模式。

---

## 五、相关文件索引

### 后端（已合入 main）

| 文件 | 说明 |
|---|---|
| `src/agent_harness/web/app.py:1190` | `POST /api/sessions/{id}/model` 端点 |
| `src/agent_harness/web/lineage.py:112` | `POST /api/sessions/{id}/forks` 端点 |
| `src/agent_harness/session/service.py:1014` | `SessionService.change_model()` |
| `src/agent_harness/session/service.py:1046` | `SessionService.fork()` |
| `src/agent_harness/session/event.py:96` | `MODEL_CHANGED = "model/changed"` 常量 |
| `web/src/generated/event-types.ts:44` | `MODEL_CHANGED: 'model/changed'` 生成物 |

### 前端（需要修改）

| 文件 | 改动 |
|---|---|
| `web/src/lib/api.ts` | 新增 `changeModel()` 和 `forkSession()` 函数 |
| `web/src/hooks/useSession.ts` | 接入模型切换逻辑，监听 `model/changed` 事件 |
| `web/src/components/ModelPicker.tsx` | 可能需要微调，确保选择后调用 `changeModel()` |
| `web/src/components/Conversation.tsx` 或新组件 | Fork 选择器 UI |
| `web/src/lib/projection.ts` | 可能需要处理 `model/changed` 事件的投影 |

---

## 六、集成提示词

给前端 AI 的提示词：

```
你需要实现 #137 Phase Multiturn T7 的前端 UI 部分。后端 API 已全部就绪并合入 main。

## 任务

1. 在 `web/src/lib/api.ts` 新增两个函数：
   - `changeModel(sessionId, provider, modelId)` → POST /api/sessions/{id}/model
   - `forkSession(sessionId, fromSeq)` → POST /api/sessions/{id}/forks

2. 模型切换 UI：
   - ModelPicker 选择后调用 `changeModel()`
   - 用响应里的 `model_id` 更新本地状态（不用请求值）
   - 监听 SSE/WS 事件流中的 `model/changed` 事件，更新 UI

3. Fork 选择器 UI：
   - 在历史用户消息上提供 fork 入口（右键/菜单按钮）
   - 调用 `forkSession(sessionId, userMessageSeq)`
   - 成功后切到 child session 视图
   - 处理 409（在途 run）和 422（非法锚点）错误

## 关键约束

- `from_seq` 必须是 `user/message` 类型事件的 seq
- POST /model 响应的 `model_id` 是规范 picker id，不等于请求值
- `from_provider`/`from_model_id` 可能为 null
- 不要伪造列表：`GET /api/models` 返回空数组时隐藏选择器入口
- child session 继承父会话当前模型（不需要前端额外处理）

## 测试

- 单元测试：`changeModel()` 和 `forkSession()` 的请求/响应格式
- E2E：模型切换流程 + fork 流程
- Prior art：`web/e2e/continuation.spec.ts` + `web/e2e/fixtures.ts`

## 后端 API 契约

详见 `docs/HANDOFF_FRONTEND_T7.md`。
```
