# #24 — Ticket D: DockerSandbox 确定性命名 + WorkspaceRegistry Docker 后端 + 恢复测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:44:36Z
- **Closed**: 2026-09-03T14:20:25Z
- **Parent**: #20
- **Blocked by**: #23
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/24

---

## Parent

#20 — Phase 3 Spec: Session-scoped Sandbox 生命周期

## What to build

给 WorkspaceRegistry 增加 DockerSandbox 后端支持，并把 DockerSandbox 的容器名/volume 名从随机 uuid 改为基于 session_id 的确定性命名。这样 Docker 后端的 workspace 也能跨进程恢复——容器停了但 volume 在，resume 时用确定性名字重启容器即可恢复 workspace。

## Acceptance criteria

- [ ] DockerSandbox.__init__ 支持确定性命名：当 WorkspaceRegistry 创建时传入基于 session_id 的 container_name 和 volume_name（如 `agent-harness-{session_id}`），不再随机 uuid。直接构造（不经 Registry）仍保留随机 fallback。
- [ ] WorkspaceRegistry.create(session_id, backend='docker') → 创建确定性命名的 DockerSandbox + 写映射 JSON。
- [ ] WorkspaceRegistry.get(session_id) docker 后端 → 重建 DockerSandbox（用映射 JSON 里的容器名/volume 名）+ ensure_started（重启已停容器）。
- [ ] WorkspaceRegistry.stop(session_id) docker → 容器 stop（不删 volume）。
- [ ] workspace 恢复（docker）：create → write 文件 → stop → get → 文件还在（volume 持久性）。
- [ ] 测试（`tests/sandbox/test_workspace_registry_docker.py`，@integration + skipif Docker 不可用）：
  - 确定性命名：同一 session_id 的容器名一致。
  - workspace 恢复：write → stop → get → read 文件正确。
  - 映射 JSON 含 container_name / volume_name。
- [ ] 所有现有测试仍通过（Docker 测试默认 skip）。

## Blocked by

- #23（Ticket C：WorkspaceRegistry 必须先实现 LocalSubprocess 版本）

