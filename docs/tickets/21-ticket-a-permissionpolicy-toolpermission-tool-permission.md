# #21 — Ticket A: PermissionPolicy + ToolPermission 枚举 + Tool 契约 permission 属性 + 各工具声明

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:43:20Z
- **Closed**: 2026-09-03T14:20:15Z
- **Parent**: #19
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/21

---

## Parent

#19 — Phase 3 Spec: Approval / REQUIRE_APPROVAL 机制

## What to build

新增 PermissionPolicy（read-only / workspace-write / danger-full-access）和 ToolPermission（read-only / workspace-write / danger）两个枚举，给 Tool ABC 扩展可选 `permission` 属性（默认 WORKSPACE_WRITE），让 9 个已有 Coding Tool 声明各自的 permission 级别。这是审批关卡的地基——ToolExecutor 需要知道每个工具的授权级别才能做策略检查。

## Acceptance criteria

- [ ] `PermissionPolicy` 枚举（READ_ONLY / WORKSPACE_WRITE / DANGER_FULL_ACCESS）在 `tooling/contract.py` 或新文件中定义。
- [ ] `ToolPermission` 枚举（READ_ONLY / WORKSPACE_WRITE / DANGER）定义。
- [ ] Tool ABC 新增可选属性 `permission`，默认返回 `ToolPermission.WORKSPACE_WRITE`。
- [ ] 各 Coding Tool 覆写 permission：read=READ_ONLY, grep=READ_ONLY, glob=READ_ONLY, git_status=READ_ONLY, git_diff=READ_ONLY, write=WORKSPACE_WRITE, edit=WORKSPACE_WRITE, apply_patch=WORKSPACE_WRITE, bash=DANGER。
- [ ] side_effect 和 permission 正交：side_effect 驱动调度，permission 驱动授权。
- [ ] 测试（`tests/tooling/test_permission.py`）：PermissionPolicy/ToolPermission 枚举值、Tool ABC 默认 permission、9 个工具的 permission 断言。
- [ ] 所有现有测试仍通过。

## Blocked by

None（can start immediately）。

