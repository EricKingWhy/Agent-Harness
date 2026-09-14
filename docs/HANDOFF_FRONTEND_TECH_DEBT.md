# 交接手册 / 集成提示词：后端技术债批次 → 前端

> **后端分支**：`feat/backend` @ `fa508ce`（批次 `169d9a4`–`fa508ce`，6 commits）
> **前端分支**：`feat/frontend` @ `807b7db`（本文档引用的行号以此为准，后续会漂移）
> **后端门禁**：ruff clean；pytest **1400 passed / 9 skipped / 39 deselected**，0 failed
> **关联**：ADR-0022（WS 逻辑心跳）、`docs/TECH_DEBT_FIX_SPEC.md`（Q1–Q4 规格）、`docs/BACKEND_CONTRACT_STREAMING_UI.md`（SSE 契约，**尚无 WS 章节**）
> **状态**：未 merge 到 main、未 push。前端可以先按本手册准备，等 main 集成后再对齐。

---

## 0. 怎么用这份文档

- **§1 是提示词**：整段复制给前端会话即可开工。
- **§2–§6 是交接细节**：给人类看的（前端 agent 也可以读）。
- 本批后端改动 **不破坏 SSE 契约**——如果前端暂时什么都不做，现状不会坏。真正的必做项只有 §4 的 T1/T2（续聊 amend 透传 + 一处过期注释），其余是"采用 WS 时再做"和"已知 Gap 记录"。

---

## 1. 提示词（可直接整段复制）

```text
你在 intelligence-agent-frontend（D:\intelligence-agent-frontend，分支 feat/frontend）做前端任务。
后端 feat/backend 刚完成一个技术债批次（后端分支 169d9a4–fa508ce，尚未合入 main）。
完整交接手册在 D:\intelligence-agent-backend\docs\HANDOFF_FRONTEND_TECH_DEBT.md，先读它。

本批唯一必做的前端动作（SSE 通道，不受后端未合并影响）：

T1. 续聊透传 staged amend 字段。
    后端 POST /api/sessions/{id}/messages 现在接受 reasoning_effort / agent_profile /
    context_providers / model，并在「空闲会话 → launched 直驱新 run」时真正生效。
    现状：web/src/lib/api.ts 的 SendMessagePayload 没有这四个字段；
    web/src/hooks/useSession.ts 的 sendFollowUp 只传 content/mode/max_steps；
    web/src/App.tsx 的续聊分支（handleSubmit 里 sendMessage(selectedId, task, ...)）
    把用户当前选的 model/agent_profile/reasoning_effort/context_providers 丢掉了。
    做法：
      - SendMessagePayload 增加 model?/agent_profile?/reasoning_effort?/context_providers?；
      - sendMessage 透传（缺省不传键，保持 payload 干净）；
      - sendFollowUp 增加可选 amend 参数；App.tsx 续聊分支按「有值才带」的模式传入
        （与 create 分支同一模式，空值不发键）。
    注意：只有 idle → launched 的新 run 会应用这些字段；在途 run 的 queued 消息忽略它们。
    验收：新增/更新单测覆盖「有值才带键」「全空 → payload 不含 amend 键」；
    续聊 idle 会话后新 run 使用所选模型/档位（后端侧可核对 session 事件）。

T2. 更新过期注释（不行为变更）。
    web/src/lib/api.ts 的 StartSessionPayload docstring 仍写着这些字段是
    "staged 契约、运行时记 INFO 后忽略"。后端已消费：agent_profile（ADR-0020a）、
    reasoning_effort、context_providers（ADR-0021）、model（ADR-0016 §5）。
    请把注释改成现状，不要留"前端不应断言已生效"这类已过期的说法。

不要做：
  - 不要改 SSE 帧形状 / seq 投影 / 消费机器（后端本批对 SSE 是纯内部重构，契约零变化）；
  - 不要在后端仓库改任何文件（后端归 feat/backend 会话）；
  - 不要现在迁 WS。若要迁，先读 §4 T3 与 §5 的坑点，并且要先补后端契约文档。

门禁：pnpm vitest run 全绿、pnpm tsc -b clean、oxlint 0 error（沿用仓库既有命令）。
完成后报告：改了什么文件、测试结果、是否还有未决项。
```

---

## 2. 后端做了什么（逐 commit）

| commit | 类型 | 内容 | 对前端的影响 |
| --- | --- | --- | --- |
| `169d9a4` | fix | P0-001：`send_message` 续聊 SSE 序列化崩溃修复 | 无（修后端崩溃） |
| `cf65d85` | refactor | P2-003：移除 ADR-0021 遗留的 `context_provider_entries` 死代码 | 无 |
| `443f583` | refactor | `web/serialization.py` 抽出共享事件信封；WS 通道测试修正 | 无（帧形状不变） |
| `0bfd4e0` | refactor | `AmendOptions` 聚合 amend 字段；`validate_session_id` 单一定义；`collect_dangling` 统一 | **有**：`/resume` 与 `/messages` 开始接受并透传 amend 字段 |
| `daa7b5d` | fix | **WS 服务端应用层逻辑心跳**；Q4d.2 live relay 测试修正；Q2 端点/idle 透传测试；信封与 amend 去重 | **有**：WS 新增 `server_ping` 下行，客户端须回 `pong` |
| `fa508ce` | docs | PHASE_STATUS 记录本批进度与门禁 | 无 |

关键点：**Q2 让 `POST /api/sessions/{id}/resume` 和 `POST /api/sessions/{id}/messages` 首次接受 amend 字段**（此前这两个端点完全忽略 `reasoning_effort`/`agent_profile`/`context_providers`/`model`，只有 `POST /api/sessions` 接受）。前端续聊路径因此有了"带着当前档位续聊"的能力。

---

## 3. 契约变更（面向前端）

### 3.1 新增能力：续聊/续跑接受 amend 字段

`POST /api/sessions/{id}/messages` 与 `POST /api/sessions/{id}/resume` 请求体现在接受：

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `reasoning_effort` | `string \| null` | 目录 id（`GET /api/reasoning-efforts`） |
| `agent_profile` | `string \| null` | 目录 id（`GET /api/agent-profiles`） |
| `context_providers` | `string[] \| null` | 目录 id 列表（`GET /api/context-providers`）；`[]` = 显式空集，`null`/不传 = 后端默认全集 |
| `model` | `string \| null` | catalog name（`GET /api/models`）；不传 = 默认链 |

生效范围（重要）：

- `/messages`：仅 **idle 会话 → `launched` 新 run** 时生效；**在途 run 的 `queued` 消息与 `mode=steer` 不应用这些字段**（在途 run 的 runtime 已固定，不抢断、不改写）。
- `/resume`：无在途 run 时拉起新 run 时生效；有在途 run → 409。
- 响应形状不变：`launched` → SSE 流；`queued`/`steered` → JSON 确认。前端现有的 content-type 分支逻辑继续适用。

校验语义（P1 修复后，见 §5）：

- **值/形状类**（`reasoning_effort`、`agent_profile` 的取值；`context_providers` 的每项非空）由 Pydantic 在 parse 期校验——**任何**请求的非法值都 422（集合是静态常量，不会因目录变化而失效）。
- **引用类**（`model`、`context_providers` 的 id）只在**会被应用**时才校验：`/resume` 总是校验；`/messages` 仅在 idle → launched 时校验。queued/steer 请求即使带失效的 `model` 也不会 422——该字段按契约被忽略。

### 3.2 新增契约：WS 服务端心跳（仅 WS 通道，SSE 不受影响）

端点 `ws://<host>/api/ws`。ADR-0022 决定用**应用层逻辑心跳**（ASGI 发不出 RFC 6455 控制帧）：

| 方向 | 帧 | 说明 |
| --- | --- | --- |
| 下行 | `{"type":"server_ping"}` | 每 **2s** 一个（`WS_PING_INTERVAL`） |
| 上行 | `{"type":"pong"}` | 对 `server_ping` 的应答；**任何**上行消息（`subscribe`/`send_message`/…）都算活性 |
| — | 服务端行为 | 连续 **30s** 无任何上行 → `close(code=1001, reason="heartbeat timeout")`（`WS_PING_TIMEOUT`） |

其余 WS 上行/下行词汇不变（`subscribe`/`send_message`/`steer`/`cancel`/`ping` 上行；`snapshot`/`event`/`done`/`error`/`pong` 下行）。

### 3.3 明确无变化（前端可放心）

- SSE 帧形状：`GET /api/sessions/{id}/stream`、`/api/sessions`、`/messages`(launched) 的信封字段与 seq 投影**零变化**——`443f583`/`daa7b5d` 只是把两条通道的构造收敛到 `_envelope()`，输出逐字段相同。
- 端点语义：detached-run（断连不取消）、cancel、404/409/422 分支均未改。
- session_id 校验行为未变（非法 → 422）。

---

## 4. 前端待办

### T1（必做）续聊透传 amend 字段

涉及文件（以 `feat/frontend` @ `807b7db` 为准）：

- `web/src/lib/api.ts:156` `SendMessagePayload` / `sendMessage` — 加 4 个可选字段并透传。
- `web/src/hooks/useSession.ts:646` `sendFollowUp` — 增加可选 amend 参数并传给 `apiSendMessage`。
- `web/src/App.tsx:252` 续聊分支 — 按 create 分支同一「有值才带」模式传入 `selectedModel` / `selectedAgentProfile` / `selectedReasoningEffort` / `selectedContextProviders`。

验收：

1. 单测覆盖「有值才带键」与「全空 → payload 不含 amend 键」（与 create 路径同风格）。
2. 续聊一个 idle 会话、显式选模型 → 新 run 使用该模型（后端事件里可核对）。
3. 在途会话发消息 → 仍走 queued JSON，amend 被忽略且 UI 不误报"已切换"。

### T2（必做）更新过期注释

`web/src/lib/api.ts:60-76` `StartSessionPayload` 的 staged/no-op 注释已过期（后端已消费 4 个字段）。只改注释，不改行为。

### T3（仅在决定采用 WS 时做）

1. 收到 `server_ping` 回 `{"type":"pong"}`（或保证 30s 内至少一条上行）。
2. `server_ping` **不得进入事件 reducer**——它是传输健康信号，不是 Agent 事件（SDD 02 §7.9）。
3. 处理 §5 的 P4（WS `snapshot` 帧与 live/SSE 帧形状不一致）。
4. 先让后端补 `docs/BACKEND_CONTRACT_STREAMING_UI.md` 的 WS 章节（当前该文档只有 SSE 章节）。

---

## 5. 坑点

**P1（已修复，2026-09-09）：续聊/续跑的 amend 校验现已与 create 路径对齐。**
修复前：`POST /api/sessions` 的三道闸门在 `/resume` 与 `/messages` 上都不存在——

| 字段 | `POST /api/sessions` | `/resume`、`/messages`（修复前） |
| --- | --- | --- |
| `reasoning_effort` | Pydantic `@field_validator` → 422 | 无校验，透传给 `create_chat_model` |
| `agent_profile` | Pydantic `@field_validator` → 422 | 无校验 → `BUILTIN_PROFILES[...]` **KeyError → HTTP 500** |
| `context_providers` | handler 对照 wiring 真实 id → 422 | 无校验 → `build_runtime` 记 WARNING 后**静默跳过** |
| `model` | `ModelConfig.from_catalog` → `InvalidDecision` → 422 | 无校验 → `ConfigError` 未被 handler 捕获 → **HTTP 500** |

修复后：未知 `reasoning_effort` / `agent_profile` → Pydantic 422；未知 `context_providers` / `model` 在**会被应用**时 → 422（`/resume` 总是校验；`/messages` 仅 idle → launched 时校验，queued/steer 忽略字段不校验）。详见 §3.1 的校验语义。

结论：前端**仍应只发目录端点返回的 id**；但已不再有 500——失效的引用类字段要么 422（会被应用时），要么被忽略（不会被应用时）。

> 修复前实测（2026-09-09）：`POST /api/sessions/{id}/messages` 带未知 `model` → `ConfigError` 未被捕获 → **500**；`build_runtime(agent_profile="nope")` → `KeyError('nope')`，同样未被捕获 → 500。修复后回归测试见 `tests/web/test_web_amend_validation.py`。

**P2：续聊的 422 语义与现有前端假设不符。**
`useSession.ts:663` 把 422 一律当"未知模型"（`UNKNOWN_MODEL_ERROR_TEXT`）。现在 `/messages` 的 422 可能来自：`InvalidSessionId`（session_id 非法）、未知 `model` / `context_providers`（仅 idle → launched 时）、非法 `reasoning_effort` / `agent_profile` 取值。建议按 `detail` 文本区分，或统一提示"续聊参数无效，请刷新选项后重试"。

**P3：amend 只在"拉起新 run"时生效。**
在途 run 的 queued 消息与 steer 不应用 amend（服务端按契约丢弃这些字段）；UI 不要在 queued/steer 路径提示"档位已切换"。

**P4（后端 Gap，WS 采用前需处理）：WS 快照帧与 live/SSE 帧形状不同。**
`websocket.py` 的 `snapshot` 用 `SessionEvent.to_dict()`（JSONL 形状：含 `event_id`、**无 `durability`**、`data` 为空时省略）；而 live `event` 帧和 SSE 帧用信封形状（`build_event_payload`，含 `durability`、无 `event_id`）。SSE 两条通道同形，WS 快照不同形——WS 客户端需要归一化，或让后端统一。本批未改（Scope 外）。

**P5：`server_ping` 不是 Agent 事件。** 别送进 reducer / 别渲染成可见事件；它是连接活性探测。

**P6：两套"心跳"不要混淆。** SSE 没有服务端心跳，前端仍靠 `RECONNECT_STALL_MS`（10s，`useSession.ts:137`）做客户端停摆检测；WS 的 30s 是**服务端**回收死对端。两者独立。

**P7：不要建议后端用控制帧心跳。** Starlette `WebSocket` 无 `send_ping`，uvicorn 对 `websocket.ping` 抛 `RuntimeError`——这是 ASGI 协议约束，探测证据见 ADR-0022。应用层帧是唯一可行且合规（SDD 02 §7.9）的方案。

---

## 6. 下一步建议

1. **前端票（本批收口）**：T1 + T2。这是本批唯一真实前端工作量，可在后端合入 main 前先做（SSE 契约未变，改动只依赖请求体新增可选字段）。
2. ~~**后端票 P1**：amend 校验对齐~~ **已完成**（`feat/backend`，与 §5 P1 同步更新）。
3. **后端票 P2**：WS `snapshot` 统一为信封形状（或前端加归一化），作为 WS 迁移的前置条件。
4. **契约文档**：`docs/BACKEND_CONTRACT_STREAMING_UI.md` 补 WS 章节（心跳 + 帧形状 + 上行词汇），否则 WS 迁移没有单一契约来源。
5. **WS 迁移本身**：不在本批范围，建议单独立票，前端先保持 SSE。
6. **测试脚手架去重（低优先）**：`tests/web/test_web_amend_validation.py` 与 `test_web_amend_passthrough.py`（以及 `test_web_context_providers_b2.py`）各自复制了 `_FakeMemoryProvider` + wiring 注入。值得建 `tests/web/conftest.py` 统一——纯测试基础设施，与本批功能无关。

---

## 7. 后端验证证据（供复核）

```
uv run ruff check src/ tests/          → All checks passed
uv run pytest -q                       → 1400 passed, 9 skipped, 39 deselected, 0 failed
uv run pytest tests/web/test_web_ws_relay.py \
              tests/web/test_web_amend_passthrough.py \
              tests/web/test_web_multiturn.py \
              tests/session/test_resume_amend_passthrough.py \
              tests/session/test_collect_dangling.py -q
                                       → 31 passed
```

WS 心跳的测试锁定：`tests/web/test_web_ws_relay.py::test_ws_server_heartbeat_ping_arrives`（间隔调小 → `server_ping` 到达、回 pong 后连接存活）、`::test_ws_dead_peer_closed_after_timeout`（不应答 → 服务端 `close(1001)`）。
