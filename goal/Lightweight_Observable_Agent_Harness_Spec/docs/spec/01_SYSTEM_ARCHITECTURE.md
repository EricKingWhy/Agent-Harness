# 01 — System Architecture

## 1. 总体分层

```text
┌──────────────────────────────────────────────┐
│ Surfaces                                     │
│ CLI │ FastAPI/SSE │ Web Session Inspector   │
└──────────────────────┬───────────────────────┘
                       │ AgentEvent
┌──────────────────────▼───────────────────────┐
│ Agent Runtime Core                           │
│ AgentLoop │ ModelProvider │ ContextBuilder   │
│ Session │ Run │ Step │ Guard                 │
└─────────────┬───────────────┬────────────────┘
              │               │
     ┌────────▼───────┐ ┌────▼────────────────┐
     │ Tool Runtime   │ │ Capability Context   │
     │ Registry       │ │ Memory / Skill /     │
     │ Executor       │ │ Knowledge / etc.     │
     │ Scheduler      │ └──────────────────────┘
     └───────┬────────┘
             │
 ┌───────────▼──────────────────────────────────┐
 │ Capability / Provider Layer                  │
 │ Coding │ Sandbox │ MCP │ Knowledge │ Web     │
 │ Memory │ Artifact │ SubAgent │ Observability │
 └─────────────┬────────────────────────────────┘
               │
 ┌─────────────▼────────────────────────────────┐
 │ Persistence / External Systems               │
 │ JSONL │ SQLite/PostgreSQL │ MinIO │ Milvus    │
 │ Langfuse │ Remote MCP │ Model APIs           │
 └──────────────────────────────────────────────┘
```

## 2. 强制依赖方向

### Core 可以依赖

- Python 标准库；
- Pydantic 等基础 Contract 库；
- 本项目抽象接口；
- ModelProvider interface；
- Session/Event interface；
- Tool Runtime interface。

### Core MUST NOT 直接依赖

- Milvus concrete client；
- MinIO concrete client；
- LangMem concrete classes；
- Langfuse concrete tracing；
- LangGraph StateGraph；
- 某个 Web Search SDK；
- 某个 MCP Server；
- 某个前端实现。

这些只能位于 Adapter / Provider 层。

## 3. 建议代码边界

以下是职责建议，不要求机械使用相同目录名，但依赖边界 MUST 保持：

```text
src/
├─ core/
│  ├─ agent/
│  ├─ model/
│  ├─ session/
│  ├─ context/
│  └─ events/
├─ tools/
│  ├─ contracts/
│  ├─ registry/
│  ├─ executor/
│  ├─ scheduler/
│  └─ builtin/
├─ sandbox/
├─ persistence/
│  ├─ session/
│  ├─ metadata/
│  └─ operation/
├─ artifacts/
├─ capabilities/
│  ├─ memory/
│  ├─ knowledge/
│  ├─ web/
│  ├─ skills/
│  ├─ mcp/
│  └─ subagent/
├─ orchestration/
│  └─ langgraph/     # optional
├─ observability/
├─ api/
├─ cli/
└─ web/
```

## 4. 关键数据结构

全系统 SHOULD 统一复用以下 ID，不得重复发明平行标识：

- `session_id`
- `run_id`
- `agent_id`
- `step_id`
- `tool_call_id`
- `operation_id`
- `checkpoint_id`
- `artifact_ref`
- `parent_session_id` / lineage info

## 5. 数据事实源

必须区分：

### SessionEvent Store
Agent 世界中已经提交的事实。

### Operation Ledger
真实外部副作用执行状态。

### Artifact Store
完整大对象、长输出、二进制文件等。

### Metadata Store
索引、引用、版本、映射、配置状态。

### Vector Store
语义检索索引；默认 Milvus Provider。

它们 MAY 使用同一数据库基础设施，但逻辑职责 MUST 分离。

## 6. 统一执行原则

任何模型可调用的能力：

```text
Local Coding Tool
Knowledge Tool
Web Tool
MCP Tool
Memory Tool（如需要）
SubAgent Delegation Tool
```

如果它以 Tool 形式暴露给模型，则 MUST：

```text
Tool Contract
→ Registry
→ Validation
→ Permission
→ Dependency Scheduler
→ Executor
→ Operation Ledger（需要时）
→ ToolResult
→ SessionEvent
```

不得因为某类 Tool 来自 MCP / LangGraph / SDK 就绕过这条链。

## 7. 可选编排

LangGraph 可以用于：
- Multi-Agent state orchestration；
- Conditional routing；
- Interrupt/resume；
- Subgraph。

但 MUST 将已有 `AgentRuntime.run()` 包装成 Node，不得反向重写 Agent Runtime。

Graph checkpoint 只恢复 Workflow State，MUST NOT 替代 Operation Ledger。

## 8. 架构不变量

测试中 SHOULD 加入不变量断言：

- 每个 `tool/call` 最终有匹配的 `tool/result` 或明确的 unresolved recovery 状态。
- 进入 Model Request 的重要动态 Context 必须可追溯到 SessionEvent / Context Provider output / Artifact Ref。
- `ToolExecutor` 之外不得出现第二套 Tool retry。
- Provider Adapter 不得篡改 Core Contract 的语义。
- Compaction 不删除 Persistent History。
- Fork 不修改父 Session。
- Resume 不重复已经确认成功的外部副作用。
