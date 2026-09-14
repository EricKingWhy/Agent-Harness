# ADR-0007: Context Compaction 三层降级 + tiktoken 精确计数

**Status**: Accepted  
**Date**: 2026-09-04  
**Phase**: 5 (Artifact + MinIO + Context Compaction)

## Context

规格 06 §5 要求 Compaction 在 `auto_compact_threshold` (0.70) 触发、`hard_guard_threshold` (0.85) 硬限，且"Summary LLM 失败时应有 deterministic fallback；hard guard 下 compaction 仍失败则阻止继续"。

两个子决策需要冻结：

### 子决策 1：Token 计数方式

四个候选：(a) tiktoken 精确、(b) 模型自带 tokenizer、(c) chars/4 粗估、(d) 绝对字符阈值。

### 子决策 2：摘要生成的降级策略

LLM 摘要可能失败（模型超时、格式不对、拒绝生成）。失败后怎么办？

## Decision

### 子决策 1：tiktoken cl100k_base 精确计数

`estimate_tokens(text: str) -> int` 用 `tiktoken` 的 `cl100k_base` 编码。

- `max_context_tokens` 默认 **200000**（覆盖 Claude 200K / GPT-4o 128K 的上界）
- auto_compact_threshold = 0.70 × 200000 = 140000 tokens
- hard_guard_threshold = 0.85 × 200000 = 170000 tokens

### 子决策 2：三层降级链

```
1. LLM 结构化摘要
   ↓ (LLM 失败/超时/格式错)
2. Deterministic 机械提取
   ↓ (机械提取后仍超 hard guard)
3. 抛 ContextWindowExceededError → Runtime 停止 loop
```

**第 1 层 — LLM 摘要**：取早期完整 turns，送给同一个 ModelProvider 的 `ainvoke()`，prompt 要求产出结构化 summary（至少保留 facts / decisions / constraints / failed_attempts / unresolved / artifact_refs / citations / important tool outcomes——spec §5 列举）。产出为一条 `SystemMessage` 注入 messages 头部。

**第 2 层 — Deterministic fallback**：不用 LLM。机械提取：
- HumanMessage → 原文截断保留（前 200 字符）
- AIMessage → 保留 tool_calls 列表（丢 content）
- ToolMessage → 保留 `tool_call_id` + content 截断（前 100 字符）
拼成一条 `SystemMessage` 注入头部。信息损失大但零失败面。

**第 3 层 — Hard guard 拒绝**：两层降级后 token 估算仍超 `hard_guard_threshold` → 抛 `ContextWindowExceededError`。Runtime 捕获后终止当前 run（spec §8："必须停止或要求用户处理"）。不继续发送超窗口请求。

## Rationale

### 为什么 tiktoken 而非 chars/4

- **200K 窗口下粗估不可接受**——chars/4 在大窗口下误差可能达 4 万 token。要么过早压缩浪费窗口，要么过晚压缩直接超限报错。生产级 coding agent（Claude Code / Codex）都用精确 tokenizer。
- **对非 OpenAI 模型是 ~10% 近似**——cl100k_base 对 Claude / DeepSeek 的 token 数是合理近似（偏保守方向）。未来换 Claude 原生 tokenizer 是 `estimate_tokens` 一行改动。
- **无厂商锁定**——`tiktoken` 是 OpenAI 开源的小包，不依赖任何 API。

### 为什么三层降级而非两层

- spec §5 同时要求"deterministic fallback"（第 2 层）和"hard guard 阻止"（第 3 层）。两层降级链只满足其中一个。
- 第 3 层是安全底线——不能让一个 LLM 摘要失败就把超大 context 发给模型（会直接 API 报错或截断）。

### 为什么 Compaction 以 AIMessage 为原子边界

- spec §5 硬约束："不能拆断 AI tool_call 与对应 ToolResult"。AIMessage(tool_calls=[...]) + 紧跟的连续 ToolMessage 块是一个不可分割单元——要么全压、要么全留。
- derive_messages 已经把 events 投影成配对好的 message 序列，Compaction 遍历这个序列按 AIMessage 边界切分即可，不需要重新做配对逻辑。

## Consequences

- `ContextBuilder` 构造参数：`model_provider` / `max_context_tokens=200_000` / `auto_compact_threshold=0.70` / `hard_guard_threshold=0.85`。
- 新增 `estimate_tokens()` 函数（tiktoken 封装）。
- 新增 `ContextWindowExceededError` 异常。
- 新增 `context/compacted` SessionEvent（记录 compaction 发生 + `fallback_used: bool`）。
- `tiktoken` 加入 `requirements`（核心依赖，非可选——Compaction 是 Core 能力）。
- Runtime loop 第 1 步从 `session.derive_messages()` 改为 `context_builder.build(session)`。
