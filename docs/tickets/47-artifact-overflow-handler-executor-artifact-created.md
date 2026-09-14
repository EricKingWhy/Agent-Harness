# #47 — Artifact Overflow Handler + Executor 集成 + artifact/created 事件

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T06:01:08Z
- **Closed**: 2026-09-04T06:50:59Z
- **Parent**: #44
- **Blocked by**: #45
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/47

---

## Parent

Phase 5 Spec #44

## What to build

ToolResult 大输出自动溢出到 ArtifactStore。定义 `OverflowHandler` ABC 和 `ArtifactOverflowHandler` 实现——检测 ToolResult 主输出字段字符数是否超阈值，超了就调 ArtifactStore.save + 截断替换 + 返回带 artifact_ref 的新 ToolResult。集成到 ToolExecutor 的执行路径（tool.execute 成功返回后、Ledger.update_state 之前）。追加 `artifact/created` SessionEvent。

端到端：一个 bash Tool 返回 5000 行 stdout，Executor 自动溢出存到 FakeArtifactStore，Ledger 记录的 result_json 是截断版 + artifact_ref，session 事件流含 artifact/created。

## Acceptance criteria

- [ ] `OverflowHandler` ABC：`async maybe_overflow(session, tool_call_id, tool_name, result: ToolResult) -> ToolResult`，不溢出时原样返回
- [ ] `ArtifactOverflowHandler`：构造注入 ArtifactStore + overflow_chars 阈值（默认 2000）
- [ ] 溢出检测逻辑：提取 ToolResult 的主输出字段（data["output"] 或 data["content"] 或 message），字符数超阈值则溢出
- [ ] 截断格式：前 N 行 + "... [truncated, {total} lines total, use inspect_artifact({artifact_id}) to view]" + 后 N 行
- [ ] 溢出后 ToolResult.artifact_ref 填入 artifact_id
- [ ] ToolExecutor 增加可选 overflow_handler 参数，在 tool.execute 返回后、Ledger.update_state 之前调用
- [ ] `artifact/created` 事件加入 EVENT_TYPES，data = {artifact_id, session_id, source_tool, tool_call_id, size, mime_type}
- [ ] 单元测试：(a) 未超阈值原样返回 (b) 超阈值截断 + artifact_ref 正确 (c) artifact/created 事件 append (d) Ledger result_json 含截断内容

## Blocked by

- #45 (ArtifactStore ABC + FakeArtifactStore)
