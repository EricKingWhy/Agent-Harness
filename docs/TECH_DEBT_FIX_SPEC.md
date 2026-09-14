# 技术债修复规格

> 4 项技术债的修复方案,按 SDD 流程定义:问题 → 方案 → 验收标准 → 测试要求。
> 所有修改遵循 Scope Lock(§8)和 Surgical Changes(§9.3)。

---

## Q1: 统一 session_id 校验函数

### 问题

3 处用同一正则 `r"[A-Za-z0-9_-]+"` 做 session_id 校验,正则模式分散:

| 位置 | 异常类型 | 用途 |
|---|---|---|
| `web/app.py:405` `_validate_session_id` | `HTTPException(422)` | HTTP 边界预校验 + lineage router 回调 |
| `session/service.py:683` `_validate_session_id` | `InvalidSessionId` | 领域层守卫,所有 SessionService 入口调用 |
| `storage/s3_artifact.py:21` 构造器内联 | `ValueError` | 构造时防御性检查 |

### 方案

1. 在 `session/service.py` 中将 `_validate_session_id` 改为**公开函数** `validate_session_id(session_id: str) -> str`,内部抛 `InvalidSessionId`。保留现有正则 `r"[A-Za-z0-9_-]+"`。
2. `web/app.py` 删除自己的 `_validate_session_id`,改为 `from agent_harness.session.service import validate_session_id`。lineage router 回调(`register_lineage_routes(app, validate_session_id=...)`)改用此函数。
3. web handler 已有 `except InvalidSessionId → 422` 路径,自然覆盖。
4. `S3ArtifactStore` 的内联 guard **不动**(不同层、不同异常类型、构造期 fail-fast)。

### 验收标准

- [ ] 正则 `r"[A-Za-z0-9_-]+"` 在 session 层只定义一次
- [ ] `web/app.py` 不再有 `_validate_session_id` 函数定义
- [ ] lineage router 回调使用统一的 `validate_session_id`
- [ ] 现有 session_id 校验测试全部通过(invalid → 422/InvalidSessionId)
- [ ] ruff clean

### 测试要求

- 现有测试 `tests/session/test_service.py` 和 `tests/web/test_web_api.py` 应保持 green
- 新增 1 个测试:验证 `validate_session_id` 对合法/非法输入的行为(合法返回原值;非法抛 `InvalidSessionId`)

---

## Q2: 扩展 resume_and_launch 支持 staged amend 字段

### 问题

`create_and_launch` 接受并转发 `reasoning_effort` / `agent_profile` / `context_providers` / `model` 到 `build_runtime`。但 `resume_and_launch` 只接受 `session_id` / `task` / `max_steps`,这些字段在 resume 路径上静默丢失(默认 None = 全量 registry + 无 system_prompt 注入 + 所有 provider + 默认模型链)。

**影响场景:** 用户创建会话时指定 `agent_profile="coding"`,续聊(resume)后该 run 使用全量工具集而非 coding 子集——行为不一致。

### 方案

1. `resume_and_launch` 增加参数:`reasoning_effort: str | None = None` / `agent_profile: str | None = None` / `context_providers: list[str] | None = None` / `model: str | None = None`。默认 None = 当前行为。
2. `resume_and_launch` 内部调用 `build_runtime` 时透传这些参数。
3. `ResumeRequest` 增加可选字段:`reasoning_effort` / `agent_profile` / `context_providers` / `model`。
4. `POST /api/sessions/{id}/resume` handler 透传这些字段到 `resume_and_launch`。
5. `send_message` 的 idle 分支调 `resume_and_launch` 时也透传 amend 字段。
6. `drain_queued_message` 同理(虽然目前无调用者,保持接口一致)。

### 验收标准

- [ ] `resume_and_launch` 签名包含 4 个 staged amend 参数
- [ ] `ResumeRequest` 包含对应的可选字段
- [ ] `POST /api/sessions/{id}/resume` 透传 amend 字段
- [ ] `send_message` idle 分支透传 amend 字段
- [ ] `drain_queued_message` 透传 amend 字段
- [ ] 默认值 None 保持当前行为不变(向后兼容)
- [ ] ruff clean

### 测试要求

- 新增测试:验证 `resume_and_launch` 透传 amend 字段到 `build_runtime`(mock build_runtime,断言参数传递)
- 新增测试:验证 `POST /api/sessions/{id}/resume` 带 amend 字段时正确透传
- 新增测试:验证 `send_message` idle 分支带 amend 字段时正确透传
- 现有 resume/send_message 测试保持 green

---

## Q3: 提取共享 _collect_dangling helper

### 问题

两个函数扫描相同的 3 种事件类型(TOOL_CALL / MODEL_COMPLETED / TOOL_RESULT),维护相同的 `requested` / `resolved` 集合,但实现独立:

| 维度 | `_dangling_state` (coordinator) | `detect_dangling` (derive) |
|---|---|---|
| 返回值 | `tuple[set, set]` — (dangling_ids, call_event_ids) | `list[str]` — sorted dangling ids |
| MODEL_COMPLETED 处理 | 直接迭代 `tool_calls`,不 normalize | 经 `_normalize_tool_calls_for_projection()` 容错 |

### 方案

1. 在 `session/derive.py` 中新增 `_collect_dangling(events: list[SessionEvent]) -> tuple[set[str], set[str]]`:
   - 返回 `(dangling_ids, call_event_ids)`
   - 统一使用 `_normalize_tool_calls_for_projection` 做 MODEL_COMPLETED 容错
   - 扫描 TOOL_CALL / MODEL_COMPLETED / TOOL_RESULT 三种事件类型
2. `detect_dangling` 改为调用 `_collect_dangling`,返回 `sorted(result[0])`。
3. `RecoveryCoordinator` 删掉自己的 `_dangling_state`,改为 `from agent_harness.session.derive import _collect_dangling` 并调用。

### 验收标准

- [ ] `_collect_dangling` 在 `session/derive.py` 中定义,返回 `tuple[set[str], set[str]]`
- [ ] `detect_dangling` 调用 `_collect_dangling`
- [ ] `RecoveryCoordinator` 不再有 `_dangling_state` 方法,改为 import 共享 helper
- [ ] MODEL_COMPLETED 容错统一走 `_normalize_tool_calls_for_projection`
- [ ] 现有 dangling 检测测试全部通过
- [ ] ruff clean

### 测试要求

- 现有测试 `tests/session/test_derive_messages.py` 和 recovery 相关测试应保持 green
- 新增 1 个测试:验证 `_collect_dangling` 对含 call_event_ids 的场景返回正确的 tuple

---

## Q4: WebSocket + SSE 双通道全面修复

### 问题

WS 是声明的「主 streaming 通道」,SSE 是「灰度兼容路径」。存在以下问题:

1. **死代码:** `WS_PING_INTERVAL = 2.0` 和 `WS_PING_TIMEOUT = 30.0` 定义了但从未使用
2. **事件序列化重复:** `_event_to_sse_dict` (app.py) 和 `_event_to_ws_dict` (websocket.py) 各自构建几乎相同的 payload dict
3. **注释不准确:** docstring 声称「心跳 ping/pong(2s 默认,30s 超时断开)」但实际只有 client-initiated ping
4. **WS 测试薄弱:** 只有 4 个基础 smoke test,不覆盖多会话订阅、live event relay、disconnect cleanup

### 方案

#### 4a. 死代码清理 + 注释修正

1. 删除 `WS_PING_INTERVAL` 和 `WS_PING_TIMEOUT` 常量(或改为实际使用)。
2. 修正 `websocket.py` docstring:明确当前只有 client-initiated ping/pong,没有 server-initiated heartbeat。

#### 4b. 提取共享事件序列化函数

1. 在 `web/app.py` 或新的 `web/serialization.py` 中提取一个共享函数 `build_event_payload(event, session_id) -> dict`。
2. `_event_to_sse_dict` 和 `_event_to_ws_dict` 都改为调用这个共享函数。
3. 确保 SSE 帧格式(`{"data": json_string}`)和 WS 帧格式(直接 dict)的差异在各自包装层处理。

#### 4c. 实现 server-initiated heartbeat

1. 在 `handle_websocket` 中启动一个 heartbeat task,每 `WS_PING_INTERVAL` 秒发送一个 WebSocket ping frame(`websocket.send_bytes` with PING opcode,或使用 Starlette 的 `websocket.send_ping`)。
2. 如果客户端在 `WS_PING_TIMEOUT` 秒内没有响应任何消息(ping/pong/subscribe/etc.),则关闭连接。
3. heartbeat task 在 `finally` 中取消。

#### 4d. 扩展 WS 测试覆盖

1. 多会话订阅:连接 WS,subscribe session A,subscribe session B,验证两个 session 的事件都能收到。
2. Live event relay:subscribe 一个有 active run 的 session,验证增量事件通过 WS 推送。
3. Disconnect cleanup:连接 WS,subscribe,断开连接,验证 subscription 被清理(RunManager 不再持有 subscriber)。
4. Heartbeat:验证 server-initiated ping 在预期间隔内到达。

### 验收标准

- [ ] `WS_PING_INTERVAL` 和 `WS_PING_TIMEOUT` 要么被删除要么被实际使用
- [ ] `websocket.py` docstring 准确反映实际行为
- [ ] 共享事件序列化函数被 SSE 和 WS 路径共同使用
- [ ] server-initiated heartbeat task 在连接期间运行,在断开时被清理
- [ ] WS 测试覆盖:多会话订阅、live event relay、disconnect cleanup、heartbeat
- [ ] 现有 WS smoke tests 保持 green
- [ ] ruff clean

### 测试要求

- 新增多会话订阅测试
- 新增 live event relay 测试
- 新增 disconnect cleanup 测试
- 新增 heartbeat 测试
- 现有 4 个 WS smoke tests 保持 green

---

## 实施顺序

```
Q1 (session_id 校验统一)     → 最小改动,独立完成
Q3 (dangling 检测统一)       → 独立完成,不影响 Q1/Q2/Q4
Q2 (resume amend 字段扩展)   → 独立完成,不影响 Q1/Q3/Q4
Q4 (WS+SSE 双通道修复)       → 最大工作量,最后完成
```

每个 Q 完成后:
1. 运行全量测试(`uv run pytest -q`)
2. 运行 ruff(`uv run ruff check src/ tests/`)
3. 更新 PHASE_STATUS.md
