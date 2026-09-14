# #23 — Ticket C: WorkspaceRegistry + LocalSubprocess 后端 + 映射持久化 + 契约测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:44:33Z
- **Closed**: 2026-09-03T14:20:22Z
- **Parent**: #20
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/23

---

## Parent

#20 — Phase 3 Spec: Session-scoped Sandbox 生命周期

## What to build

实现 WorkspaceRegistry——Session↔Sandbox 映射表的持久化管理。支持 LocalSubprocessSandbox 后端：create 为新 session 创建 workspace 目录 + 写映射 JSON，get 查回/重建 Sandbox（workspace 是真实目录天然持久），stop/delete 清理。映射存为 `<root>/workspaces/<session_id>.json`。这是 Session-scoped Sandbox 生命周期的基础——让进程重启后能根据 session_id 找回 workspace。

## Acceptance criteria

- [ ] WorkspaceRegistry 类在 `sandbox/registry.py` 定义，构造接受 `root: Path` 和 `backend: str = "local"`。
- [ ] create(session_id) → 创建 workspace 目录 + 写映射 JSON + 返回已 ensure_started 的 Sandbox。
- [ ] get(session_id) → 返回 Sandbox 实例（同进程内缓存；不存在时从 JSON 重建）。
- [ ] exists(session_id) → bool。
- [ ] stop(session_id) → 停止 Sandbox（LocalSubprocess 是 no-op），幂等。
- [ ] delete(session_id) → 删映射 JSON + 可选删 workspace 目录，幂等。
- [ ] 映射 JSON 格式：session_id / backend / workspace_root / container_name / volume_name / created_at。
- [ ] 测试（`tests/sandbox/test_workspace_registry.py`，LocalSubprocess 后端）：
  - create → Sandbox 实例 + workspace_root 存在 + JSON 文件存在。
  - get（同实例）→ 同一 Sandbox。
  - get（新实例，模拟重启）→ 重建 Sandbox，workspace_root 一致。
  - workspace 恢复：create → write 文件 → 新 Registry get → 文件还在。
  - exists / stop 幂等 / delete 幂等。
  - backend='local' → LocalSubprocessSandbox 实例。
- [ ] 所有现有测试仍通过。

## Blocked by

None（can start immediately）。

