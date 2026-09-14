# #45 — #45: ArtifactStore ABC + FakeArtifactStore + inspect_artifact Tool

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T05:59:37Z
- **Closed**: 2026-09-04T06:23:51Z
- **Parent**: #44
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/45

---

## Parent

Phase 5 Spec #44

## What to build

Artifact 的持久化边界和模型侧读取工具。定义 `ArtifactStore` ABC（content-hash 寻址），实现 `FakeArtifactStore`（内存 dict，测试用），实现 `InspectArtifactTool`（第 10 个 Coding Tool，构造注入 ArtifactStore 而非 Sandbox，READ_ONLY）。注册 inspect_artifact 到 ToolRegistry，让 ToolExecutor 能调度它。

端到端：ToolExecutor 里注册 InspectArtifactTool( FakeArtifactStore )，手工存一个 Artifact，模拟模型调用 inspect_artifact 拿回指定行范围的内容。

## Acceptance criteria

- [ ] `ArtifactStore` ABC 定义三个方法：`save(session_id, content, *, mime_type, source_tool, tool_call_id) -> Artifact` / `load(artifact_id) -> Artifact` / `inspect(artifact_id, *, start_line, end_line, keyword, max_lines) -> ArtifactSlice`
- [ ] `Artifact` 模型：artifact_id (content-hash) / session_id / size / mime_type / source_tool / tool_call_id / created_at / content (load 时填充)
- [ ] `ArtifactSlice` 模型：artifact_id / lines (list of {line_number, text}) / total_lines / returned_lines / truncated / query
- [ ] `FakeArtifactStore` 内存实现，通过全部契约测试
- [ ] `InspectArtifactTool`：构造注入 ArtifactStore，args = {artifact_id, start_line?, end_line?, keyword?, max_lines=200}，返回 ToolResult.success(data={lines, total_lines, ...})
- [ ] inspect_artifact 注册到 ToolExecutor 可被调度执行
- [ ] InspectArtifactTool.reconcile_hint 返回 verifiable=True（重读同一个 artifact 比对即可）
- [ ] 单元测试覆盖：save → load 往返、inspect 按行范围、inspect 按关键词、max_lines 截断

## Blocked by

None (can start immediately)
