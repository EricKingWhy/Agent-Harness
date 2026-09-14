# #50 — AgentRuntime 集成 ContextBuilder + Phase 5 端到端测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T06:02:18Z
- **Closed**: 2026-09-04T07:29:47Z
- **Parent**: #44
- **Blocked by**: #47, #48, #49
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/50

---

## Parent

Phase 5 Spec #44

## What to build

把 ContextBuilder 接入 AgentRuntime loop，完成 Phase 5 的端到端闭环。AgentRuntime 构造函数增加 context_builder 参数，loop 第 1 步从 `session.derive_messages()` 改为 `context_builder.build(session)`。

**端到端测试用真实 S3ArtifactStore（七牛云），不用 Fake。** 测试需要真实七牛云凭证（endpoint / bucket / access_key / secret_key），如果缺凭证请向用户索取。

端到端验证：
1. 大 ToolResult 自动溢出到七牛云对象存储，模型只拿到截断摘要 + artifact_ref
2. 多轮对话后 auto compaction 触发，早期 turns 被压缩成结构化 summary
3. inspect_artifact 能从七牛云读回溢出内容的局部细节
4. 持久化 SessionEvent 完整——compaction 不删除任何事件，artifact/created 和 context/compacted 都在事件流中
5. 刷新后从 SessionEvent 重建完整语义

## Acceptance criteria

- [ ] AgentRuntime 构造函数增加 `context_builder: ContextBuilder` 参数
- [ ] AgentRuntime loop 第 1 步改为 `messages = context_builder.build(session)`
- [ ] 现有 345 测试全部通过（不回归）
- [ ] 端到端测试：bash 大输出 → 自动溢出到真实七牛云 → inspect_artifact 读回
- [ ] 端到端测试：多轮对话 → auto compaction 触发 → context/compacted 事件持久化
- [ ] 端到端测试：SessionEvent 流完整重建（无丢失）
- [ ] Phase 5 Gate 达成：超大 stdout 不进完整 Context / raw data 可找回 / compaction 不删 SessionEvent

## Blocked by

- #47 (Overflow Handler + Executor 集成)
- #48 (S3ArtifactStore)
- #49 (Context Compactor)
