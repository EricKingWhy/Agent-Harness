# ADR-0003: Phase 1 SessionEvent — append-only Event Log + derive_messages

- **Status**: Accepted
- **Date**: 2026-09-03
- **Phase**: 1 (SessionEvent + Model + Minimal Agent Loop)
- **Spec**: `docs/spec/03_SESSION_EVENT_MODEL.md`, `docs/spec/02_AGENT_RUNTIME.md`
- **Supersedes**: 无（首次决策）
- **Superseded by**: 无

## Context

Phase 1 之前，`AgentRuntime` 用内存 `list[AnyMessage]` 跑 Agent Loop，进程退出全丢。
Roadmap Phase 1 Gate 要求"简单对话重启后可恢复历史"，且规格不变量 #3 要求"Session Event-sourced / append-only"。
必须引入 SessionEvent 模块，把 Agent 交互历史的主要事实源从内存 messages list 迁移到持久化事件流。

本 ADR 记录实现 Phase 1 SessionEvent 时经过 grilling 锁定的 14 项关键决策。

## Decision

### 1. Phase 1 边界：只做 Event DTO + JSONL Store + derive_messages + 基础 Resume

进 Phase 1：SessionEvent DTO、10 种 event vocabulary 子集、JsonlSessionStore、derive_messages、基础 Resume。
推迟：Checkpoint / Operation Ledger / Reconcile（Phase 4）、Fork / Replay projector（Phase 14）、流式 model/delta（Phase 9）。
理由：Phase 1 Gate 只要"重启可恢复"，提前做 Ledger / Fork 是投机抽象，违反 Scope Lock。

### 2. 后端：JSONL-only，不抽 SessionStore ABC

V1 只实现 `JsonlSessionStore` 具体类。SQLite / PostgreSQL 留到 Phase 4 再抽 ABC 接入。
拒绝同时实现 JSONL + SQLite（避免"双主事实源"复杂度）。
拒绝先抽象再实现（YAGNI——只有一种后端时 ABC 是空壳）。

### 3. AgentRuntime 迁移：增量改造，messages 退化为缓存

`run()` 开始时 `derive_messages(load_events(session_id))` 拿到内存 messages list，循环内部仍用 messages list；每轮把 user / AI / tool 内容同步 append 到 SessionStore。
内存 messages list 退化为"运行期缓存"，events 才是事实源。
拒绝"每轮从 events 重新投影全历史"（O(n²) 且破坏全部现有测试）。

### 4. Diagnostic Log 与 SessionEvent：两套并存

`logging.py` 的 JSONL Diagnostic Log（span / trace / agent_decision）保留不动——它是可观察执行链路，规格 §2.2 明确要全链路追踪。
新增 SessionEvent 作为业务事实源（resume / replay / derive 用）。
Runtime 在关键节点（user_message / ai_message / tool_call / tool_result）双写：Diagnostic Log（保持可观察）+ SessionEvent（保持可恢复）。
拒绝合并（事件文件混入 span 噪音，违反 §3 "payload 采用类型化 DTO"）。
拒绝替换（Diagnostic Log 的执行链路观察价值独立存在）。

### 5. Event vocabulary V1 子集：10 种

```
session/started, session/resumed
run/started, run/completed, run/failed
user/message
model/completed, model/failed
tool/call, tool/result
```

推迟：model/delta（Phase 9 流式）/ step/*（step_id 已嵌在 model/tool 事件里）/ context/*（Phase 5）/ checkpoint/saved（Phase 4）/ operation/reconcile-required（Phase 4）/ artifact/created（Phase 5）/ agent/*（Phase 13）/ approval/*（Phase 3 后续）。

### 6. dangling tool_call：检测 + 注入合成 ToolMessage

当事件序列结尾存在 `tool/call` 无匹配 `tool/result`（进程崩溃场景）：
- derive_messages 检测后注入合成 `ToolMessage`（content="工具执行被中断，结果未知"），让消息链自洽。
- 同时把合成 ToolMessage 作为新 `tool/result` 事件 append 回 SessionStore（`source_event_ids` 指向原 `tool/call`，`dangling=true`），下次 resume 时链已自洽。
- derive_messages 打 WARN 告知调试者。

拒绝检测后抛错（Phase 1 没有 Ledger 做对账，上层无法决策）。
拒绝静默丢弃（OpenAI / Anthropic API 会因孤立 tool_calls 无 tool_result 而报错）。

### 7. Session / Run ID 生命周期：Session 模块工厂

`Session.start(store)` / `Session.resume(store, session_id)` 是唯一构造入口。
`AgentRuntime.run(session, user_input)` 接受 Session 实例，run_id 在 run() 内生成。
拒绝调用方裸传 session_id（Session 状态散落到 Runtime / CLI）。
拒绝 Runtime 自管 id（Session 是领域对象，状态应自包含）。

### 8. Phase 状态追踪：docs/PHASE_STATUS.md

新建 `docs/PHASE_STATUS.md` 作为 Phase 进度单一事实源（状态 + commit + Gate 证据）。
规格文件（`14_IMPLEMENTATION_ROADMAP.md` 等）保持冻结，不被进度修改。
AGENTS.md / CLAUDE.md 加一句"首次进入先读 PHASE_STATUS.md"。

### 9. 文件布局：.agent/sessions/<session_id>/events.jsonl

每个 Session 一个目录（`.agent/sessions/<session_id>/`），里面放 events.jsonl。
未来 checkpoint / workspace 也归到此目录下。
`.agent/` 已在 `.gitignore`（运行时产物）。
`logs/agent.jsonl` 保持纯 Diagnostic Log。

### 10. 崩溃安全：逐行 json.dumps + flush + 读取跳过坏行

写入：整行 `json.dumps(event) + "\n"` 一次 `file.write`，紧跟 `flush()`。
读取：逐行 `json.loads`，无法解析的行跳过并标记 corrupted。
崩溃语义：写到最后一行有效事件为止，半行等于没发生。

### 11. Session API 形状

```python
class Session:
    session_id: str
    events: list[SessionEvent]

    @classmethod
    def start(cls, store, *, agent_id="default") -> Session: ...
    @classmethod
    def resume(cls, store, session_id) -> Session: ...
    def append(self, event_type, data, **ids) -> SessionEvent: ...
    def derive_messages(self) -> list[AnyMessage]: ...
    def begin_run(self) -> str: ...
    def end_run(self, run_id, *, status, final_text="") -> None: ...
```

`append()` 同步（blocking）——JSONL 一次 file.write 很快，异步引入复杂度但 Phase 1 无收益。
`derive_messages()` 无副作用，每次重新投影。

### 12. derive 配对：以 AIMessage 为单位

一次 `model/completed` 投影成一条 AIMessage（带全部 tool_calls），后续每条 `tool/result` 按 `tool_call_id` 匹配成 ToolMessage。
符合 OpenAI / Anthropic / LangChain 的标准消息格式契约。

### 13. 测试改造：单一入口 + helper 函数

`run(session, user_input)` 是唯一入口（删除旧的 `run(user_input)`）。
提供 `make_session(tmp_path)` 测试便利函数，把"构造 ephemeral Session + tmp_path JsonlStore"压成一行。
现有 ~15-20 处 AgentRuntime 构造点批量替换，工作量约 30 分钟。
改造后所有测试天然覆盖 SessionEvent 流程。

### 14. PHASE_STATUS.md 初始盘点

Phase 0 Repo Foundation：✅ COMPLETED
Phase 1 SessionEvent：🔄 IN PROGRESS（AgentRuntime + ModelProvider 已落地，SessionEvent 部分本次补齐）
Phase 2 Tool Runtime：✅ COMPLETED（Permission / Capability seam 留待 Phase 7 深化）
Phase 3 Docker Sandbox + Coding Tools：🔄 PARTIAL（Sandbox + read/write/bash 已有，缺 edit/grep/glob/apply_patch/git_status/git_diff + Approval + Session-scoped 生命周期）
Phase 4-15：⬜ NOT STARTED

## Consequences

- **正向**：Phase 1 Gate 达成（重启可恢复）；为 Phase 4 Recovery / Phase 14 Fork / Replay 奠定事实源基础；AgentRuntime 与 SessionStore 解耦，未来换后端不动 Runtime。
- **负向**：现有 91 个测试需改造（~15-20 处）；引入新模块增加约 300-400 行代码；每条消息双写（Diagnostic + Event）有微小性能开销。
- **风险**：derive_messages 与 messages list 的一致性依赖 append 的原子性——若 append 成功但内存更新失败会不一致。缓解：append 与内存更新在同一同步方法内顺序执行，append 失败则不更新内存（异常上抛）。
