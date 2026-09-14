# 11 — Streaming / API / Web UI

## 1. Event ≠ Log

`AgentEvent` 是 Runtime 对外业务执行事件，可被 CLI/SSE/UI/Test/Trace 消费。

`Diagnostic Log` 是 Debug/运维内部记录。

Runtime 禁止直接把 `print()` 当事件机制。

## 2. AgentEvent

建议：

```text
AgentStarted
RunStarted
ModelStarted
ModelDelta
ModelCompleted
ToolStarted
ToolCompleted
ToolFailed
ApprovalRequested
CheckpointSaved
ContextCompacted
ArtifactCreated
AgentDelegated
RecoveryRequired
RunCompleted
AgentFailed
```

事件必须携带统一 ID。

## 3. CLI

CLI 是第一公民。

至少支持：
- 新建 Session；
- resume；
- replay；
- fork；
- 查看当前 session/run；
- 流式模型输出；
- Tool 调用状态；
- Approval；
- context budget；
- compact；
- 基础 artifact inspect。

## 4. FastAPI SSE

最小接口可为：

```text
POST /chat/stream
→ create/run Agent
→ AgentEvent async iterator
→ SSE frames
```

SSE 只负责 Surface，不得拥有 Runtime 状态。

客户端断开：
- 检测 disconnect；
- 明确 Runtime task 是否 cancel 或继续；
- 清理 generator/queue；
- 不破坏 Session/Operation 一致性。

## 5. 轻量 Web Session Inspector

目标不是做 IDE，而是“看见 Agent 全链路”。

### 左侧
- Sessions
- Runs
- Fork Tree

### 中间
- Conversation
- Agent activity
- Tool calls

### 右侧 Step Detail
- model request/result metadata
- tool args/result
- retry
- operation state
- artifact
- context/compaction
- checkpoint
- recovery

### 操作
- Resume
- Replay
- Fork
- Approve / Reject
- inspect artifact

## 6. UI 状态来源

Web 前端 SHOULD 直接消费：

```text
SessionEvent history
+
live AgentEvent stream
```

UI 不得维护第二套不可对账业务真相。

## 7. Transport

V1 可以：
- SSE：Agent server → UI 实时事件；
- REST：Session/Run/Artifact 查询。

不要求 WebSocket，除非双向 steering/approval 证明有必要。

## 8. Backpressure / Queue

如果内部使用 `asyncio.Queue`：
- queue 有明确生命周期；
- Agent completion/error 必须发送终止信号；
- disconnect 时不得永久泄露 producer task；
- durable event 不依赖 Queue 存活；
- Queue 只是实时传输，不是持久化。

## 9. Acceptance Criteria

- CLI 可实时看到 ModelDelta；
- ToolStarted/Completed 可实时显示；
- SSE disconnect 无 task/queue 泄漏；
- UI 可刷新后从 SessionEvent 重建；
- Fork Tree 可显示；
- Approval 可以闭环；
- Langfuse/前端挂掉不影响 durable Session。
