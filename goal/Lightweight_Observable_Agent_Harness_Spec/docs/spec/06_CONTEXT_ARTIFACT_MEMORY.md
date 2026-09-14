# 06 — Context + Artifact + Memory

## 1. 三个基础概念

### Persistent History
完整事实记录，不能因模型窗口不足而删除。

### Runtime Context
某一次 Model Call 实际发送给模型的信息。

### Artifact
完整保存、但默认不直接注入模型的大对象/大输出。

核心原则：

> **完整保存 ≠ 完整注入。**

## 2. Context Builder

建议组合：

```text
System
+ active AgentProfile
+ selected Skills
+ structured session summary
+ recent complete turns
+ relevant artifact refs
+ Knowledge evidence
+ Memory Context Provider output
+ task-specific refs
```

禁止简单：

```python
messages = messages[-20:]
```

因为可能丢用户约束、Tool Result、恢复信息、历史决策。

## 3. Artifact Store

大输出流程：

```text
Raw Tool Output / Large File / Dataset
→ ArtifactStore.save()
→ Local or MinIO Provider
→ metadata/hash/type/size/ref
→ compact summary + artifact_ref
→ Model Context
```

默认 Provider：
- Local filesystem：开发/小型部署；
- MinIO：正式大文件、大量对象。

接口 SHOULD 保持对象存储抽象，未来可换 S3。

## 4. inspect_artifact

作为 READ_ONLY Tool：

```text
artifact_ref
start/end lines?
keyword?
range?
query?
```

模型按需重新读取局部细节。

大 Artifact 不允许每次完整灌回 Context。

## 5. Compaction

```text
early complete turns
→ preserve tool interaction boundaries
→ structured summary
→ replace only runtime projection
→ persistent SessionEvent unchanged
```

Summary 至少保留：
- facts
- decisions
- constraints
- failed_attempts
- unresolved
- artifact_refs
- citations
- important tool outcomes

不能拆断 AI tool_call 与对应 ToolResult。

默认配置：
- `auto_compact_threshold = 0.70`
- `hard_guard_threshold = 0.85`

必须可配置。

Summary LLM 失败时应有 deterministic fallback；hard guard 下 compaction 仍失败则阻止继续无脑撑爆窗口。

## 6. Memory：Capability / Context Provider

### 冻结决定

Memory MUST 暴露成：

```text
MemoryCapability
     +
MemoryContextProvider
```

Core 不直接依赖 LangMem、Mem0 或自研实现。

### Provider

默认：

```text
MemoryProvider
├─ LangMemProvider   # V1 default
├─ Mem0Provider      # future
└─ CustomProvider    # future
```

建议抽象能力：

```text
extract_candidates()
store()
update()
delete()
recall()
search()
```

但 Core Runtime 不要求所有 Provider 内部算法一致。

### Context Provider

模型调用前：

```text
task/session/user context
→ MemoryContextProvider.select(...)
→ compact memory entries
→ ContextBuilder
```

Memory Context Provider 应负责：
- scope filter
- relevance
- recency
- importance
- token budget
- citation/reference metadata（如适用）

### Memory Tool

若需要让模型显式操作 Memory，可额外暴露 Tool，但这不是唯一入口。自动 recall 更适合作为 Context Provider。

## 7. Memory Scope

至少支持抽象 Scope：
- user
- project
- task
- agent

Memory 的存储实现不应改变 Agent Core。

## 8. Failure Semantics

- Memory Provider 不可用：Core SHOULD graceful degrade，不阻塞基础 Agent。
- Artifact Store 上传失败：不能伪造 artifact_ref。
- Summary 失败：保存 raw artifact，走 fallback summary。
- Compaction 拆断 tool pair：拒绝结果。
- Context hard guard：必须停止或要求用户处理，不能继续发送超窗口请求。

## 9. Acceptance Criteria

- 大 Tool Output 完整保存；
- Model 默认只收到 summary + ref；
- `inspect_artifact` 能找回细节；
- MinIO Provider 可替换 Local Provider；
- Compaction 后历史不删除；
- Memory 可使用 LangMem；
- 替换成 Fake/Mem0 Provider 时 Agent Core 无需修改；
- Memory Provider 故障时基础 Agent 仍能工作。
