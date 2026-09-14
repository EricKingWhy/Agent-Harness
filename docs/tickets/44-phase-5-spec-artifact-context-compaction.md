# #44 — Phase 5 Spec — Artifact + Context Compaction

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T05:42:08Z
- **Closed**: 2026-09-04T07:29:50Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/44

---

## Problem Statement

当 Tool 产出大输出（如 bash 跑出 5000 行日志、read 一个大文件），当前实现把完整内容直接灌进 `tool/result` 事件和 derive_messages 投影——模型 context window 被单个工具输出撑爆，后续轮次要么超限报错要么丢失早期重要上下文。没有 Artifact 存储意味着大输出无处安放，没有 Compaction 意味着长对话无法在有限窗口内持续。

## Solution

引入 Artifact Store（七牛云 Kodo S3 兼容）自动溢出大 ToolResult 到对象存储，模型只拿截断摘要 + artifact_ref；引入 ContextBuilder 作为 Runtime loop 的单一 context 入口，内含 token 估算和三层降级 Compaction（LLM 摘要 → 机械提取 → 拒绝），在对话增长时自动压缩早期 turns 为结构化 summary。新增 `inspect_artifact` Tool 让模型按需局部读取 Artifact 细节。

## User Stories

1. 作为 Agent Runtime，我想要 ToolResult 输出超过阈值时自动溢出到对象存储，这样模型 context 不被单个大输出撑爆。
2. 作为 Agent Runtime，我想要溢出后模型拿到截断摘要 + artifact_ref 而非完整内容，这样模型知道输出存在但不会窗口溢出。
3. 作为模型，我想要通过 inspect_artifact 工具按行局部读取已溢出的 Artifact，这样我能按需找回大输出的细节。
4. 作为 Agent Runtime，我想要每轮 loop 开头检测 context token 占用，这样我能在超阈值时自动压缩。
5. 作为 Agent Runtime，我想要 Compaction 在 auto_compact_threshold (0.70) 时自动触发，这样长对话能在窗口内持续。
6. 作为 Agent Runtime，我想要 Compaction 优先用 LLM 生成结构化摘要，这样压缩后的 context 保留最多语义信息。
7. 作为 Agent Runtime，我想要 LLM 摘要失败时走 deterministic 机械提取兜底，这样 compaction 永不因 LLM 故障而完全失败。
8. 作为 Agent Runtime，我想要机械提取后仍超 hard_guard_threshold (0.85) 时停止 loop，这样不会发送超窗口请求。
9. 作为 Agent Runtime，我想要 Compaction 以 AIMessage + 其 ToolMessage 块为原子边界，这样不会拆断 tool_call/ToolResult 配对。
10. 作为开发者，我想要 ArtifactStore 是 ABC 且测试用 FakeArtifactStore，这样我不需要真实七牛云凭证就能跑单元测试。
11. 作为开发者，我想要 S3ArtifactStore 用 aioboto3 对接七牛云 S3 兼容端点，这样生产部署只用云端对象存储。
12. 作为开发者，我想要 ContextBuilder 预留 ContextProvider Protocol 扩展点，这样 Phase 6 Memory 能无缝注入。
13. 作为运维者，我想要 artifact/created 和 context/compacted 进 SessionEvent 流，这样 replay 和 fork 能重建完整语义。
14. 作为开发者，我想要 tiktoken 做精确 token 估算，这样 Compaction 阈值判断在生产 200K 窗口下足够准确。
15. 作为开发者，我想要 max_context_tokens / auto_compact_threshold / hard_guard_threshold 都可配置，这样不同模型窗口能适配。
16. 作为 Agent Runtime，我想要 Compaction 不删除持久化 SessionEvent，这样完整保存 ≠ 完整注入的不变量守住。

## Implementation Decisions

### 模块新建

- **ArtifactStore ABC** (`storage/artifact.py`)：`save(session_id, content, *, mime_type, source_tool, tool_call_id) -> Artifact` / `load(artifact_id) -> Artifact` / `inspect(artifact_id, *, start_line, end_line, keyword, max_lines) -> ArtifactSlice`。Artifact = content-hash 寻址（artifact_id = 内容哈希）。
- **S3ArtifactStore** (`storage/s3_artifact.py`)：用 `aioboto3` 对接七牛云 Kodo S3 兼容端点。endpoint/bucket/access_key/secret 走 Settings。
- **FakeArtifactStore** (`storage/artifact.py` 同文件)：内存 dict 实现，给测试用。
- **ArtifactOverflowHandler** (`tooling/overflow.py`)：实现 `OverflowHandler` 接口。检测 ToolResult 主输出字段字符数是否超阈值，超了就调 ArtifactStore.save + 截断替换 + 返回新 ToolResult（带 artifact_ref）。
- **ContextBuilder** (`context/builder.py`)：`build(session) -> list[AnyMessage]`。内部调 derive_messages → 估 token → 按需 compact → 返回安全 messages。
- **estimate_tokens** (`context/tokens.py`)：`tiktoken cl100k_base` 封装。
- **ContextCompactor** (`context/compactor.py`)：三层降级逻辑。LLM 摘要（用 ModelProvider.ainvoke）→ 机械提取 → ContextWindowExceededError。以 AIMessage 为原子边界。
- **ContextProvider** (`context/provider.py`)：Protocol 定义（3 行），Phase 5 不实现。
- **ContextWindowExceededError** (`context/builder.py`)：异常类。
- **InspectArtifactTool** (`tools/inspect_artifact.py`)：构造注入 ArtifactStore，READ_ONLY，不经 Sandbox。

### 模块修改

- **ToolExecutor** (`tooling/executor.py`)：增加可选 `overflow_handler: OverflowHandler | None`。在 tool.execute 成功返回后、Ledger.update_state 之前调 `overflow_handler.maybe_overflow(session, tool_call_id, tool_name, result)`。
- **AgentRuntime** (`agent/runtime.py`)：loop 第 1 步从 `session.derive_messages()` 改为 `context_builder.build(session)`。构造函数增加 `context_builder: ContextBuilder` 参数。
- **SessionEvent** (`session/event.py`)：EVENT_TYPES 增加 `artifact/created` 和 `context/compacted`。
- **Session.append**：支持 append 新事件类型（已有通用 append，无需改）。
- **Settings** (`config.py`)：增加 `artifact_store_endpoint` / `artifact_store_bucket` / `artifact_store_access_key` / `artifact_store_secret_key` / `artifact_store_region` / `max_context_tokens` (default 200000) / `auto_compact_threshold` (0.70) / `hard_guard_threshold` (0.85) / `artifact_overflow_chars` (2000)。

### 接口契约

- `OverflowHandler` ABC：`async maybe_overflow(session, tool_call_id, tool_name, result: ToolResult) -> ToolResult`。不溢出时原样返回。
- 溢出截断格式：前 N 行 + `"... [truncated, {total} lines total, use inspect_artifact({artifact_id}) to view]"` + 后 N 行。
- `context/compacted` 事件 data：`{compacted_turn_count, summary_message_count, token_estimate, fallback_used: bool}`。
- `artifact/created` 事件 data：`{artifact_id, session_id, source_tool, tool_call_id, size, mime_type}`。

### 依赖

- `tiktoken`：核心依赖（Compaction 是 Core 能力）。
- `aioboto3`：可选依赖（`optional-dependencies` 下 `artifact` 组）。

## Testing Decisions

### 测试 seam

- **ArtifactStore**：单元测试用 FakeArtifactStore（内存），验证 save/load/inspect 契约。S3ArtifactStore 单元测试 mock aioboto3 client，验证 S3 调用参数。集成测试标 `@pytest.mark.qiniu` 默认 skip。
- **ArtifactOverflowHandler**：单元测试用 FakeArtifactStore，验证 (a) 未超阈值原样返回 (b) 超阈值后截断 + artifact_ref 正确 (c) artifact/created 事件被 append。
- **ContextBuilder + Compactor**：单元测试用 FakeModelProvider（已有），验证 (a) 未超阈值直接返回 derive_messages (b) 超 auto 阈值触发 LLM 摘要 (c) LLM 失败走机械提取 (d) 机械提取后超 hard guard 抛异常 (e) AIMessage 原子边界不可拆断。
- **AgentRuntime 集成**：用 FakeModel 模拟长对话，验证 (a) 大 ToolResult 自动溢出 (b) 多轮后 auto compaction 触发 (c) 持久化 SessionEvent 完整（compaction 不删事件）。
- **InspectArtifactTool**：单元测试用 FakeArtifactStore，验证按行范围和关键词读取。
- **estimate_tokens**：单元测试已知文本的 token 数。

### 测试风格

外部行为测试，不测内部实现。已有的测试模式参考：`tests/tooling/test_executor.py`（ToolExecutor 行为）、`tests/agent/test_agent_loop.py`（Runtime loop 行为）、`tests/recovery/test_recovery_coordinator.py`（协调器行为）。

## Out of Scope

- **Phase 6 Memory**：MemoryCapability / MemoryContextProvider / LangMemProvider 全部不做。ContextProvider Protocol 只定义不实现。
- **MinIO / Local 文件 Provider**：不做。只有 S3ArtifactStore（七牛云）+ FakeArtifactStore。
- **Artifact 流式读取**：不做。save/load/inspect 都是全量/局部读取。
- **Tool 显式声明 Artifact**：Tool 不知道 Artifact 的存在，不做。
- **Compaction 的跨 session 摘要缓存**：每次 compaction 独立计算，不做缓存。
- **Token 估算的 Claude 原生 tokenizer**：Phase 5 用 tiktoken cl100k_base 近似，未来换。

## Further Notes

- Phase 5 与 Phase 6 (Memory) 的边界：Phase 5 只做 Artifact + Compaction + ContextBuilder。ContextBuilder 预留 ContextProvider Protocol 扩展点（空列表），Phase 6 填 MemoryContextProvider。
- 七牛云 Kodo S3 兼容端点的具体配置（endpoint URL / bucket name）由用户在 .env 中提供，不在代码里硬编码。
- tiktoken cl100k_base 对非 OpenAI 模型（Claude / DeepSeek）是 ~10% 近似，偏保守方向（低估意味着提前压缩）。
- 规格 06 §1-5 + §8-9 是 Phase 5 的依据；§6-7 (Memory) 属于 Phase 6。
