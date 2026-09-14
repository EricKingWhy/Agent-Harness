# #6 — Phase 1 Spec: SessionEvent 模块 — append-only Event Log + derive_messages + 基础 Resume

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T11:58:40Z
- **Closed**: 2026-09-03T12:35:48Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/6

---

## Problem Statement

当前 `AgentRuntime` 用内存 `list[AnyMessage]` 跑 Agent Loop，进程退出后全部对话历史丢失。
规格不变量 #3 要求 Session Event-sourced / append-only，Roadmap Phase 1 Gate 要求"简单对话重启后可恢复历史"。
需要一个 SessionEvent 模块作为 Agent 交互历史的主要事实源，支撑 Resume、未来 Phase 4 的 Recovery 和 Phase 14 的 Fork/Replay。

## Solution

新建 `session/` 包，实现 append-only typed SessionEvent + JSONL SessionStore + derive_messages 投影 + Session 聚合根。
改造 `AgentRuntime.run()` 从 `run(user_input)` 变为 `run(session, user_input)`，循环内同步 append 事件，内存 messages list 退化为运行期缓存。

设计已通过 grilling 冻结为 ADR-0003（`docs/adr/0003-session-event-model-phase1.md`），14 项决策全部锁定。

## User Stories

1. 作为 Agent Runtime 开发者，我希望 Agent 的对话历史持久化为 append-only 事件流，这样进程崩溃后能恢复完整会话。
2. 作为 Agent Runtime 开发者，我希望有一个 `Session` 聚合根作为 Runtime 和外部世界（CLI/Web UI）的单一交互入口，这样调用方不需要手动管 session_id 和 event log。
3. 作为 Agent Runtime 开发者，我希望 `Session.start()` 能创建新会话并写 `session/started` 事件，这样新会话有明确的起始标记。
4. 作为 Agent Runtime 开发者，我希望 `Session.resume(session_id)` 能从 JSONL 加载事件、校验 seq 单调性、写 `session/resumed` 事件，这样重启后能无缝继续。
5. 作为 Agent Runtime 开发者，我希望有一个 `derive_messages()` 纯函数从事件序列投影出模型可见 messages，这样 Runtime 能从事件事实源驱动模型调用。
6. 作为 Agent Runtime 开发者，我希望 `derive_messages()` 能把 `tool/call` 和 `tool/result` 按 `tool_call_id` 正确配对成 AIMessage + ToolMessage 格式，这样符合 OpenAI/Anthropic/LangChain 标准消息契约。
7. 作为 Agent Runtime 开发者，我希望事件序列中存在 dangling tool_call（有 tool/call 无 tool/result）时，`derive_messages()` 能检测并注入合成 ToolMessage（content="工具执行被中断，结果未知"），这样消息链保持自洽，模型能看到失败并自主决策。
8. 作为 Agent Runtime 开发者，我希望合成的 dangling ToolMessage 同时作为新 `tool/result` 事件 append 回 SessionStore（标记 `dangling=true`），这样下次 Resume 时事件链已自洽，不会再次 dangling。
9. 作为 Agent Runtime 开发者，我希望每次 `run()` 调用生成 `run_id` 并写 `run/started` / `run/completed` / `run/failed` 事件，这样 Run 边界清晰，为 Phase 14 Fork 提供切分依据。
10. 作为 Agent Runtime 开发者，我希望 AgentRuntime 循环内每轮把 user_message / ai_message / tool_call / tool_result 同步 append 到 SessionStore，这样事件流与运行时状态始终一致。
11. 作为 Agent Runtime 开发者，我希望 SessionStore 写入采用逐行 `json.dumps + flush`，这样进程崩溃时最多丢失正在写的半行，读取时跳过无法解析的行即可。
12. 作为 Agent Runtime 开发者，我希望 SessionEvent 文件按 `.agent/sessions/<session_id>/events.jsonl` 组织，这样每个 Session 的所有状态（事件、未来 workspace、未来 checkpoint）集中在一个目录。
13. 作为 Agent Runtime 开发者，我希望 Diagnostic Log（`logs/agent.jsonl`）与 SessionEvent 分层并存，这样执行链路观察（span/trace）不污染业务事实源。
14. 作为测试编写者，我希望有一个 `make_session(tmp_path)` 测试 helper，这样现有 ~15-20 处 AgentRuntime 构造点能一行替换为 event-sourced 版本。
15. 作为 CLI 用户，我希望重启程序后能用 session_id 恢复之前的对话，这样不丢失上下文。
16. 作为多 Agent 协作者，我希望有 `docs/PHASE_STATUS.md` 记录每个 Phase 的完成状态，这样接手时不会重复已完成的工作。

## Implementation Decisions

### 模块边界

新建 `src/agent_harness/session/` 包，包含：
- **SessionEvent DTO + EventEnvelope**：frozen dataclass，字段包括 event_id / seq / time / type / session_id / run_id / agent_id / step_id / data / source_event_ids。
- **JsonlSessionStore**：薄 IO 层，只负责 `read_events(session_id) -> list[SessionEvent]` 和 `append_event(session_id, event) -> None`。不持有业务状态，不抽 ABC（YAGNI——Phase 4 加 SQLite 时再抽）。
- **Session 聚合根**：持有 `session_id` + `events: list[SessionEvent]`（内存缓存）。对外 API：`start()` / `resume()` / `append()` / `derive_messages()` / `begin_run()` / `end_run()`。
- **derive_messages 纯函数**：从 events 投影 messages，负责配对与 dangling 检测，无副作用。

### Event vocabulary V1（10 种）

```
session/started, session/resumed
run/started, run/completed, run/failed
user/message
model/completed, model/failed
tool/call, tool/result
```

其余 event type（model/delta / step/* / context/* / checkpoint/saved / operation/* / artifact/* / agent/* / approval/*）推迟到对应 Phase。

### Session API 形状

```python
class Session:
    session_id: str
    events: list[SessionEvent]

    @classmethod
    def start(cls, store: JsonlSessionStore, *, agent_id: str = "default") -> Session: ...
    @classmethod
    def resume(cls, store: JsonlSessionStore, session_id: str) -> Session: ...
    def append(self, event_type: str, data: dict, **ids) -> SessionEvent: ...
    def derive_messages(self) -> list[AnyMessage]: ...
    def begin_run(self) -> str: ...
    def end_run(self, run_id: str, *, status: str, final_text: str = "") -> None: ...
```

- `append()` 同步（blocking）写 JSONL + 更新内存 events。
- `derive_messages()` 每次重新投影，无副作用。
- `begin_run()` 生成 run_id + append `run/started`。
- `end_run()` append `run/completed` 或 `run/failed`。

### AgentRuntime 改造

`run()` 签名从 `run(user_input: str)` 变为 `run(session: Session, user_input: str)`。
循环开始：`session.append("user/message", {"content": user_input})` + `messages = session.derive_messages()`。
每轮模型调用后：`session.append("model/completed", {...})`。
工具执行后：逐条 `session.append("tool/call", {...})` + `session.append("tool/result", {...})`。
messages list 仍用于循环内传给模型（运行期缓存），events 是事实源。

### 崩溃安全

写入：整行 `json.dumps(event) + "\n"` 一次 `file.write`，紧跟 `flush()`。
读取：逐行 `json.loads`，无法解析的行跳过（半行 = 没发生）。
文件布局：`.agent/sessions/<session_id>/events.jsonl`（`.agent/` 已在 `.gitignore`）。

### Diagnostic Log 保留不动

现有 `logging.py` 的 JSONL Diagnostic Log 保持原样。Runtime 在关键节点继续调 `_log()` 写 Diagnostic（保持可观察），同时 append SessionEvent（保持可恢复）。两套分层，Event ≠ Log（不变量 #5）。

### Phase 状态追踪

新建 `docs/PHASE_STATUS.md` 作为实施进度单一事实源（已完成）。AGENTS.md / CLAUDE.md 已加读取指引。

## Testing Decisions

### 测试切入 seam

**单一 seam：`AgentRuntime.run(session, user_input) -> AgentRunResult`**。
所有测试通过这个最高层入口验证，不直接测内部方法。新增 Session 模块的单元测试也优先通过 `Session.start/resume + derive_messages` 外部 API 验证。

### 测试策略

1. **SessionEvent / Store 单元测试**（新增 `tests/session/`）：
   - SessionEvent DTO 构造与字段验证。
   - JsonlSessionStore 写入 + 读取往返（roundtrip）。
   - 崩溃安全：手动写入半行 JSONL，验证读取跳过。
   - seq 单调性校验。

2. **derive_messages 单元测试**：
   - 纯对话事件投影成 HumanMessage + AIMessage。
   - tool_call + tool_result 配对成 AIMessage(tool_calls) + ToolMessage。
   - dangling tool_call 检测 + 合成 ToolMessage 注入 + 回 append 验证。
   - 多工具单轮配对。

3. **Session 生命周期测试**：
   - start → append 多条 → derive_messages 一致。
   - resume 加载 → seq 校验 → derive_messages 与内存一致。
   - begin_run / end_run 事件写入。

4. **AgentRuntime 改造后的回归测试**：
   - 现有 91 个测试通过 `make_session(tmp_path)` helper 改造，验证 ScriptedModel 场景在 event-sourced 下行为不变。
   - 新增 1-2 个 Resume 集成测试：跑半段 → 重新 resume → derive_messages → 继续。

### 测试 helper

`make_session(tmp_path) -> Session`：构造 ephemeral Session（用 tmp_path 做 SessionStore 根目录），把现有 ~15-20 处 `runtime.run(user_input)` 的改造压成一行替换。

### 既有测试先例

- `tests/agent/test_agent_loop.py`：ScriptedModel 四象限测试模式（A/B/C/D 场景）——延续这个风格写 Session 的场景测试。
- `tests/agent/test_integration_coding.py`：真实 LLM 端到端 + `@pytest.mark.integration` marker——Resume 集成测试用同样 marker。

## Out of Scope

- **Checkpoint**（显式快照点）—— Phase 4。
- **Operation Ledger + Reconcile**—— Phase 4。
- **Fork**（创建子 Session lineage）—— Phase 14。
- **Replay projector**（逻辑重放，冻结 Tool Result）—— Phase 14。
- **SQLite / PostgreSQL SessionStore**—— Phase 4 抽 ABC 时再加。
- **SessionStore ABC**—— 只有一种后端时不抽（YAGNI）。
- **流式 model/delta 事件**—— Phase 9。
- **context/built / context/compacted 事件**—— Phase 5。
- **Web UI Session Inspector**—— Phase 10。

## Further Notes

- 设计决策详见 `docs/adr/0003-session-event-model-phase1.md`（14 项决策已冻结）。
- 领域术语详见 `CONTEXT.md` Session/Event 层（8 个新增术语）。
- Phase 进度详见 `docs/PHASE_STATUS.md`。
- 复用矩阵决策：Session Tree/Fork/Resume 为 PORT DESIGN（参考 Pi + DeepSeek Harness），但 Phase 1 只实现基础 Resume，产品级 Fork/Replay 推迟。
