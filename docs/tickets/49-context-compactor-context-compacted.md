# #49 — Context Compactor 三层降级 + context/compacted 事件

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T06:01:48Z
- **Closed**: 2026-09-04T07:09:37Z
- **Parent**: #44
- **Blocked by**: #46
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/49

---

## Parent

Phase 5 Spec #44

## What to build

Compaction 的核心逻辑：三层降级链 + AIMessage 原子边界 + context/compacted 事件。ContextBuilder.build 集成 compaction——当 token 估算超 auto_compact_threshold 时触发，超 hard_guard_threshold 且降级失败时抛 ContextWindowExceededError。

三层降级：
1. LLM 结构化摘要——取早期完整 turns 送给 ModelProvider.ainvoke，产出保留 facts/decisions/constraints/failed_attempts/unresolved/artifact_refs/citations/tool outcomes 的 summary，注入为 SystemMessage
2. Deterministic 机械提取——HumanMessage 截断保留 / AIMessage 只留 tool_calls / ToolMessage 只留 tool_call_id + 截断 content
3. ContextWindowExceededError——两层降级后仍超 hard guard 则抛异常

AIMessage(tool_calls=[...]) + 紧跟的 ToolMessage 块为不可分割原子单元。

端到端：构造一个 token 超阈值的 session（多轮对话），ContextBuilder.build() 后返回的 messages 含结构化 summary 且 token 数在 auto 阈值以下；LLM 失败时走机械提取；都失败时抛异常。

## Acceptance criteria

- [ ] `ContextCompactor` 类：接收 messages + token 估算，返回 compacted messages
- [ ] AIMessage 原子边界：遍历 messages 时识别 "AIMessage(tool_calls) + 紧跟 ToolMessage 块" 为一个不可分割单元
- [ ] 第一层 LLM 摘要：调用 ModelProvider.ainvoke，prompt 要求结构化 summary，产出 SystemMessage 注入头部
- [ ] 第二层 deterministic fallback：LLM 失败/超时/格式错时机械提取
- [ ] 第三层 hard guard：两层降级后 token 仍超 hard_guard_threshold 抛 ContextWindowExceededError
- [ ] `context/compacted` 事件加入 EVENT_TYPES，data = {compacted_turn_count, summary_message_count, token_estimate, fallback_used: bool}
- [ ] ContextBuilder.build 集成 compaction（检测 → 压缩 → 返回安全 messages）
- [ ] 单元测试：(a) 未超阈值不压缩 (b) 超 auto 触发 LLM 摘要 (c) LLM 失败走机械提取 (d) 机械提取后仍超 hard guard 抛异常 (e) tool_call/ToolResult 配对不拆断

## Blocked by

- #46 (estimate_tokens + ContextBuilder base)
