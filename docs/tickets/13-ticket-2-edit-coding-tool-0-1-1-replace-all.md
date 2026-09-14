# #13 — Ticket 2: edit Coding Tool（精确字符串替换，0/1/>1 三态 + replace_all）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:00:00Z
- **Closed**: 2026-09-03T13:26:42Z
- **Parent**: #11
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/13

---

## Parent

#11 — Phase 3 Spec: 剩余 6 个 Coding Tools

## What to build

实现 edit Coding Tool：精确字符串替换（exact old_string → new_string）。Agent 用它做小改而不必整体覆盖文件。核心是三态匹配语义：0 匹配失败（NOT_FOUND）、1 匹配成功、>1 匹配失败（AMBIGUOUS），以及 replace_all=true 时全替换。复用现有 Sandbox.read_text / write_text，不改 Sandbox 契约。由 ToolExecutor 以 Validation-first 三阶段驱动，与 read/write/bash 同一执行路径。

## Acceptance criteria

- [ ] EditTool 类继承 Tool 契约，name="edit"，构造时绑定 Sandbox。
- [ ] 参数 schema（Pydantic BaseModel）：`path: str`、`old_string: str`（min_length=1，空字符串 → schema 拒绝 → INVALID_ARGUMENT）、`new_string: str`、`replace_all: bool = False`。
- [ ] side_effect == MUTATING。
- [ ] execute 语义：read_text → `content.count(old_string)`：
  - replace_all=False：0 → failure(TOOL_EXECUTION_ERROR, message 说明未找到)；1 → success（单次替换）；>1 → failure(TOOL_EXECUTION_ERROR, message 说明 N 处匹配需更具体或 replace_all=true）。
  - replace_all=True：0 → failure(同上)；≥1 → success（`str.replace` 全替换）。
- [ ] 成功时 write_text 写入替换后内容；data 含 `{"path": <path>, "replacements": <N>}`。
- [ ] 路径越界（read_text 抛 PermissionError）→ PERMISSION_DENIED。
- [ ] 文件不存在（read_text 抛 FileNotFoundError）→ TOOL_EXECUTION_ERROR。
- [ ] 单元测试（通过 ToolExecutor 驱动，参照 test_coding_tools.py 风格）：side_effect 断言、单匹配成功 + 文件内容确实变了、0 匹配失败、>1 匹配失败、replace_all=True 全替换成功、replace_all=True 0 匹配失败、空 old_string → INVALID_ARGUMENT、路径越界 → PERMISSION_DENIED、文件不存在 → TOOL_EXECUTION_ERROR、参数类型错 → INVALID_ARGUMENT。
- [ ] 所有现有测试仍通过。

## Blocked by

None（can start immediately；只用已有 read_text / write_text）。

