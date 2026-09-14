# 02 — Agent Runtime

## 1. 目标

实现一个可读、可测试、Async-first 的最小 Agent Loop。它只协调模型调用、Context、Tool Calling、事件与持久化，不包含具体业务能力。

## 2. 主循环

```text
accept user input
→ append user SessionEvent
→ build runtime context
→ call ModelProvider
→ stream ModelDelta events
→ aggregate complete AIMessage
→ if no tool calls: finalize
→ if tool calls:
     ToolExecutor.execute_batch(...)
     append tool results
     next step
→ until completed / max_steps / guard
```

Agent Loop MUST NOT 知道具体 Tool 怎么执行。

## 3. ModelProvider

抽象至少支持：

```text
invoke / astream
model identity
tool definitions
structured output
usage metadata
error classification
```

默认实现：
- OpenAI-compatible Adapter
- Qwen Adapter
- DeepSeek Adapter

Provider-specific HTTP/SSE 细节 SHOULD 复用 LangChain 或成熟官方 SDK，不自研协议层。

## 4. Streaming

Streaming MUST：

- 对外产生 `ModelDelta`；
- 同时聚合成完整 AIMessage；
- 完整 AIMessage 继续承担 `tool_calls`、SessionEvent、Checkpoint、下一轮输入。

不能因为有 Streaming 就只保存 token/chunk 而失去最终结构化消息。

## 5. Run / Step

建议语义：

- `Session`：跨请求的长期任务/对话容器；
- `Run`：一次用户请求驱动的一轮 Agent 执行；
- `Step`：一次模型决策及其后续 Tool batch。

`max_steps` 是 Agent Loop 的硬兜底。

## 6. Repeated Tool Guard

除了 `max_steps`，实现更具体的重复调用保护：

```text
same tool
+ same critical args
+ no relevant state/resource change
+ repeated N times
→ REPEATED_TOOL_CALL
```

MUST NOT 粗暴禁止所有重复 read。若发生 edit 后再次 read，状态已变化，允许重复。

## 7. Model Fallback

Model Fallback 只在 Provider 调用域触发。

允许：
- timeout
- 429
- provider unavailable
- 明确 transient provider error

禁止因为：
- Tool 参数错误
- 普通业务失败
- “答案看起来不好”
- Permission denied

就切换模型。

Fallback 每次发生 MUST 记录：
- primary provider/model
- fallback provider/model
- reason
- attempt
- run_id / step_id

## 8. Error Semantics

Runtime 应明确区分：
- model deterministic/config error；
- model transient error；
- tool deterministic error；
- tool transient error；
- cancellation；
- guard stop；
- recovery required。

不要用自由文本字符串推断异常类型。

## 9. MUST NOT

- 不得在 Loop 中硬编码 RAG/Finance/Coding。
- 不得在 Loop 中直接 `print()` 业务执行状态；必须 emit event。
- 不得把 LangGraph 作为 Loop 本身。
- 不得由 ModelProvider 重试 Tool。
- 不得无限自循环。

## 10. Acceptance Criteria

- 模型无 Tool 时正常结束；
- 单 Tool、多 Tool 均可循环；
- streaming 后 tool_calls 不丢；
- `max_steps` 可终止；
- repeated-tool guard 在无状态变化的重复调用时触发；
- Model transient failure 可 fallback；
- auth/config 错误不会无限 fallback；
- 每个 Step 都能在 SessionEvent/Diagnostic Log 中定位。
