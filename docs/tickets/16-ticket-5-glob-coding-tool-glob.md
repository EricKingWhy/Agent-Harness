# #16 — Ticket 5: glob Coding Tool（glob 模式文件匹配 + 截断）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:01:40Z
- **Closed**: 2026-09-03T13:26:53Z
- **Parent**: #11
- **Blocked by**: #12
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/16

---

## Parent

#11 — Phase 3 Spec: 剩余 6 个 Coding Tools

## What to build

实现 glob Coding Tool：按 glob 模式列出 workspace 内匹配的文件路径。Agent 用它找"所有 .py 文件"或"src 下的 test_*.py"。直接调 Sandbox.list_files（Ticket 1 提供），做 max_results 截断防上下文爆炸。READ_ONLY，可与同批其他 READ_ONLY 工具并发。

## Acceptance criteria

- [ ] GlobTool 类：name="glob"，构造时绑定 Sandbox。
- [ ] 参数 schema：`pattern: str`（glob 模式，如 `"**/*.py"`、`"src/test_*.py"`）、`max_results: int = 100`（ge=1）。
- [ ] side_effect == READ_ONLY。
- [ ] execute 语义：调 `sandbox.list_files(pattern)`，截断到 max_results 条，标记 truncated。
- [ ] 成功时 data 含 `{"paths": [...], "count": N, "truncated": bool}`。
- [ ] 路径越界（list_files 抛 PermissionError）→ PERMISSION_DENIED。
- [ ] 单元测试（参照 test_coding_tools.py 风格，通过 ToolExecutor 驱动）：
  - side_effect == READ_ONLY。
  - 基础匹配：workspace 有 a.py / b.txt / c.py → pattern="*.py" 返回 [a.py, c.py]。
  - 递归 `**`：嵌套子目录里的文件被匹配。
  - 无匹配返回空列表、count=0、truncated=False。
  - max_results 截断：匹配数 > max_results 时 truncated=True 且 count==max_results。
  - 路径越界 → PERMISSION_DENIED。
  - 参数类型错（pattern 非 str）→ INVALID_ARGUMENT。
- [ ] 所有现有测试仍通过。

## Blocked by

- #12（Ticket 1：Sandbox list_files 方法必须先落地，glob 直接依赖它）。

