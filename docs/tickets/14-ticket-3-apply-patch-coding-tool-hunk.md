# #14 — Ticket 3: apply_patch Coding Tool（多 hunk 原子补丁）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:00:37Z
- **Closed**: 2026-09-03T13:26:46Z
- **Parent**: #11
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/14

---

## Parent

#11 — Phase 3 Spec: 剩余 6 个 Coding Tools

## What to build

实现 apply_patch Coding Tool：对单个文件原子地应用多个 old_string→new_string 补丁块。Agent 用它做多处相关修改时一次调用搞定，而不是串行调多次 edit。核心不变量是原子性——任意一个 hunk 匹配失败（0 或 >1），整个 apply_patch 失败，文件不被改动（不留半改状态）。复用现有 read_text / write_text，in-memory 应用全部 hunk 后才写盘。

## Acceptance criteria

- [ ] ApplyPatchTool 类继承 Tool 契约，name="apply_patch"，构造时绑定 Sandbox。
- [ ] 参数 schema：`path: str`、`hunks: list[Hunk]`，其中 Hunk 是 Pydantic 模型 `{old_string: str (min_length=1), new_string: str}`。空 hunks 列表 → schema 拒绝 → INVALID_ARGUMENT（min_items=1）。
- [ ] side_effect == MUTATING。
- [ ] execute 语义（原子）：
  1. read_text 拿原始内容，赋给本地变量 `current`。
  2. 逐 hunk：校验 `current.count(hunk.old_string)`；≠1 → 立即返回 failure(TOOL_EXECUTION_ERROR, message 说明第 K 个 hunk 匹配数为 N)，**不调 write_text**。
  3. =1 → 在 `current` 上做单次替换，继续下一 hunk。
  4. 全部 hunk 通过 → write_text(current)；data 含 `{"path": <path>, "hunks_applied": <N>}`。
- [ ] 路径越界 → PERMISSION_DENIED；文件不存在 → TOOL_EXECUTION_ERROR。
- [ ] 单元测试：多 hunk 全成功 + 文件最终内容正确、第 1 个 hunk 0 匹配 → 失败且文件未被任何改动（原子性）、非首 hunk 0 匹配 → 失败且文件未改（验证前面 hunk 的改动也没落盘）、任意 hunk >1 匹配 → 失败且文件未改、空 old_string → INVALID_ARGUMENT、空 hunks 列表 → INVALID_ARGUMENT、路径越界 → PERMISSION_DENIED、文件不存在 → TOOL_EXECUTION_ERROR、参数类型错 → INVALID_ARGUMENT。
- [ ] 所有现有测试仍通过。

## Blocked by

None（can start immediately；只用已有 read_text / write_text）。

