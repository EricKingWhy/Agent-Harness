# 前端交接手册：feat/frontend — T7/T8/T9 + 架构深化

> **给 workbuddy 的交接手册。**
> 你也是前端，使用 `feat/frontend` 分支。后端已写完交接手册发给你的 workbuddy 了。
> 本文件告诉你：当前状态是什么、哪些已完成、**唯一剩余的工作是什么**。

---

## 0. 快速定位

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-frontend` |
| Branch | `feat/frontend` |
| HEAD | `c00f742`（merge main 第一步） |
| 后端交接手册 | `D:\intelligence-agent-backend\docs\HANDOFF_FRONTEND_T7_T9.md` |
| SDD Tracker | `docs/SDD_TICKET_TRACKER.md` |
| 集成提示词 | `docs/integration/FRONTEND_INTEGRATION_PROMPT.md` |

---

## 1. 已完成的 Tickets

### FE-T7 #137 — 会话级模型切换 + Fork UI ✅

**API 函数**（`web/src/lib/api.ts`）：
- `changeSessionModel(sessionId, provider, modelId)` → `POST /api/sessions/{id}/model`
- `forkSession(sessionId, fromSeq)` → `POST /api/sessions/{id}/forks`

**投影**（`web/src/lib/projection.ts`）：
- `MODEL_CHANGED` 事件 → `projectModelChanged()` 更新 `conversation.model`

**UI 接线**（`web/src/App.tsx`）：
- `handleModelChange(name)` — 已有会话时调 `changeModel(selectedId, entry.provider, name)`，用响应里的规范 `model_id` 更新本地状态（不用请求值）
- `handleFork(fromSeq)` — 调 `fork(selectedId, fromSeq)` → 成功后 `selectSession(result.session_id)` 切到 child session
- Fork 按钮 — `Conversation.tsx` 用户消息上的 `.fork-btn`，`onFork={handleFork}`

### FE-T8 #138 — 崩溃恢复 UI — run/interrupted + 409 守卫 ✅

**投影**（`web/src/lib/projection.ts`）：
- `RUN_INTERRUPTED` 事件 → `projectRunInterrupted()` 标记终态 + 存 `run_interrupted`

**类型**（`web/src/types.ts`）：
- `ConversationState.run_interrupted: { step_id: number | null; interrupted_seq: number | null; reason: string } | null`

**UI**（`web/src/App.tsx`）：
- 中断横幅 — `conversation?.run_interrupted` 存在且非 streaming 时显示 `.interrupt-banner`：「上次运行在第 N 步中断（原因：…）」
- Recover 入口 — `canRecover` 判定 + `.recover-btn` 三态（idle/pending/error/conflict）
- 409 守卫 — `useSession.ts:sendFollowUp` 捕获 HTTP 409 → 解析 `detail` → 抛「存在需要人工裁决的高风险操作」，不伪造结果继续

### FE-T9 #139 — 轮次标签（turn_index 显示）✅ 已完成

commit `cddea36`：`Turn.user_message_seq` + `TurnView` 渲染「第 N 轮」标签。

真实浏览器验证（2026-09-10）：会话 28eb3302 有 5 轮对话，页面正确渲染
「第 1 轮」~「第 5 轮」，每轮标签独立、per-turn 正确。

---

## 2. 你需要做的工作

**当前状态：T7/T8/T9 全部完成，BUG-001（分叉 422）已修复。**

没有剩余工作。以下是已完成项的清单，供参考：

- ✅ T7 #137 — 会话级模型切换 + Fork UI（commit `71c01dd`）
- ✅ T8 #138 — 崩溃恢复 UI — run/interrupted + 409 守卫（commit `c137a23`）
- ✅ T9 #139 — 轮次标签 turn_index 显示（commit `cddea36`）
- ✅ BUG-001 — 分叉按钮传 user_message_seq 而非 step_id（commit `8469a34`）

### 门禁

```bash
cd web
npx tsc -b           # type check
npx vitest run        # unit tests (27 files / 422 tests)
npx oxlint            # lint (0 errors / 35 warnings expected)
npx playwright test --workers=2  # e2e (46 tests)
npx vite build        # production build
```

**关键约束**：
- `turn_index` 为 `null` 时不显示标签（旧版后端不发这个字段）
- `turn_index` 为 `0` 或负数时不显示（防御性）
- 标签只在 `turn.status !== 'streaming'` 时显示？还是流式期间也显示？——建议流式期间也显示，因为 `RUN_STARTED` 在流式开始前就到了
- 不破坏现有 `TurnView` 的 memo 行为——`turn_index` 变化时才重渲染

---

## 3. 已完成的架构深化批次

### C1 — ReconnectController 重连策略状态机 ✅（第一刀）

`web/src/lib/reconnect.ts` — 无 React / 无定时器 / 无 I/O 的重连策略状态机。
- `ReconnectController` 类封装额度计数、单飞标记、进展游标
- `decideStreamEnd()` / `reconnectDelayMs()` / `MAX_RECONNECT_ATTEMPTS` 等纯函数
- 19 个单测锁住此前无测试的状态迁移
- `useSession.ts` 通过 re-export 保持既有导入路径

### C2 — projection.ts 事件语义注册表 ✅

`web/src/lib/projection.ts` — `EVENT_SEMANTICS: Record<EventTypeValue, EventSemantics>` 穷尽注册表取代两个并行 switch。
- 编译期穷尽性已实验验证：注入 `FUTURE_THING` → `tsc` TS2741
- 7 个未接线事件类型显式登记为 `unhandledProjection`（保持既有兜底行为）

### C3+C4 — Composer 档位映射单一构造器 + 归一化归属 api 层 ✅

`web/src/lib/amend.ts` — `toAmendFields()` / `toCreateControls()` Composer 档位 → 契约字段名的单一映射点。
`web/src/lib/api.ts` — `BodyFields<T>` 字段表取代手写请求体（payload 新增字段未登记 → tsc 失败）。

---

## 4. 文件索引

### 前端核心文件

| 文件 | 说明 |
| --- | --- |
| `web/src/App.tsx` | 主应用组件，所有 handler 在这里 |
| `web/src/hooks/useSession.ts` | 会话 hook，管理 SSE 流、事件投影、重连 |
| `web/src/lib/projection.ts` | 事件投影——纯函数 turning AgentEvents into ConversationState |
| `web/src/lib/api.ts` | REST API 客户端 |
| `web/src/lib/reconnect.ts` | 重连策略状态机（C1 第一刀） |
| `web/src/lib/amend.ts` | Composer 档位 → 提交字段的单一映射点 |
| `web/src/components/Conversation.tsx` | 会话视图组件，TurnView 在这里 |
| `web/src/components/Composer.tsx` | 输入框组件 |
| `web/src/types.ts` | TypeScript 类型定义 |
| `web/src/generated/event-types.ts` | 后端生成物——事件类型常量 |

### 测试文件

| 文件 | 说明 |
| --- | --- |
| `web/src/lib/projection.test.ts` | 投影层单测 |
| `web/src/lib/reconnect.test.ts` | 重连控制器单测 |
| `web/src/lib/api.test.ts` | API 函数单测 |
| `web/src/lib/amend.test.ts` | amend 映射单测 |
| `web/src/components/Conversation.test.tsx` | Conversation 组件单测 |
| `web/e2e/*.spec.ts` | Playwright e2e 测试（12 files / 46 tests） |

---

## 5. 后端 API 契约摘要

### POST `/api/sessions/{session_id}/model` — 切换会话当前模型

**请求体**：
```json
{ "provider": "deepseek", "model_id": "deepseek-chat" }
```

**响应**（200）：
```json
{ "status": "changed", "provider": "deepseek", "model_id": "deepseek-chat" }
```

**错误码**：404 = session 不存在；422 = provider/model_id 不在 catalog

### POST `/api/sessions/{session_id}/forks` — 从历史点 fork

**请求体**：
```json
{ "from_seq": 5 }
```

**响应**（200）：
```json
{ "session_id": "child-uuid", "from_seq": 5 }
```

**错误码**：404 = session 不存在；409 = 在途 run（历史未 settled）；422 = from_seq 不是合法 fork 锚点

### GET `/api/sessions/{session_id}/lineage` — 会话谱系树

**响应**（200）：
```json
{
  "session_id": "sess-xxx",
  "ancestors": [{ "session_id": "parent-uuid", "origin": "fork", "fork_point_seq": 5 }],
  "children": [{ "session_id": "child-uuid", "origin": "fork", "fork_point_seq": 3, "created_at": "..." }],
  "edges": [{ "from": "parent-uuid", "to": "sess-xxx", "origin": "fork", "fork_point_seq": 5 }]
}
```

### 新增事件类型

```typescript
MODEL_CHANGED: 'model/changed',     // T7 #137
RUN_INTERRUPTED: 'run/interrupted',  // T8 #138
```

`model/changed` 事件 data：
```json
{
  "from_provider": "openai",
  "from_model_id": "gpt-4o",
  "to_provider": "deepseek",
  "to_model_id": "deepseek-chat"
}
```

`run/interrupted` 事件 data：
```json
{ "interrupted_seq": 42, "reason": "process_restart" }
```

`run/started` 事件 data（T9 #139 新增字段）：
```json
{ "turn_index": 1 }
```

---

## 6. 门禁基线

**基线日期：2026-09-11（真机验收批次 `b4181ad` 实跑；下方数字随批次推进，比对时以最新一次实跑为准）**

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Type check | `npx tsc -b` | exit 0 |
| 单元测试 | `npx vitest run` | 28 files / 497 tests passed |
| Lint | `npx oxlint` | 0 errors / 35 warnings（全部既有，**基线值：不得升高**） |
| e2e | `npx playwright test --workers=2` | 112 passed |
| 生产构建 | `npx vite build` | ✓ built |

**另有一条不入 CI 的联调车道**：`web/e2e-live/`（真后端 + 真模型，无 `page.route` mock），配置 `web/playwright.live.config.ts`，跑法 `npx playwright test --config playwright.live.config.ts`（需后端已启动）。**新增任何测试目录时，务必同时改两处**：`playwright.config.ts` 的 `testDir` 与 `vitest.config.ts` 的 `exclude`——只改一侧会让单测车道把 Playwright 用例当单测收集而整体变红（第五轮踩过）。

---

## 7. 注意事项

1. **不要推送远程 GitHub** — push 由集成 AI 执行
2. **`web/src/generated/event-types.ts` 是后端生成物** — 不要手动改，后端 `scripts/gen_event_types.py` 重新生成后会同步
3. **AGENTS.md §16 SDD 工作流协议** — 本次新增的防指令漂移机制，请勿删除
4. **工作区有未跟踪文件** — `test-results/` 和两份历史 untracked 文档，均非本批产物
5. ~~**T9 是唯一剩余工作**~~ **（已过时，2026-09-11 勘误）** — T9 轮次标签早已完成（commit `cddea36`，页面真实渲染「第 1 轮」~「第 6 轮」，见本手册 §1/§2）。T7/T8/T9 全部完成，勿再重复实现。当前剩余项见 `docs/SDD_TICKET_TRACKER.md` §3/§4 与 `docs/FRONTEND_ISSUES_LOG.md`
6. **SDD 流程** — 每个 ticket 都走 `/implement` → `/code-review` → 修复 → 再 `/code-review` 直到零 finding
7. **不推送远程** — 本分支全部为本地 commit，push 归集成 AI 执行
