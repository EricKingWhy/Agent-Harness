# #15 — Ticket 4: git_status + git_diff 只读 Coding Tools

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:01:12Z
- **Closed**: 2026-09-03T13:26:50Z
- **Parent**: #11
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/15

---

## Parent

#11 — Phase 3 Spec: 剩余 6 个 Coding Tools

## What to build

实现 git_status 和 git_diff 两个只读 Coding Tool。它们让 Agent 查看 workspace 的 git 改动状态（status）和具体差异内容（diff），但不能 commit / push / reset。两者都通过 Sandbox.exec 跑硬编码的只读 git 子命令，模型无法注入自定义子命令。遵循 ADR-0002：命令 exit_code 非零（如 workspace 不是 git 仓库）仍是 ok=True，stdout/stderr 在 data 里供模型判断。

## Acceptance criteria

- [ ] GitStatusTool 类：name="git_status"，参数 schema `pathspec: str = ""`，side_effect == READ_ONLY。execute 调 `sandbox.exec("git status --porcelain=v1 " + shlex.quote(pathspec))`；命令硬编码，pathspec 用 `shlex.quote` 转义防注入。返回 ToolResult.success，data 含 `{"exit_code": ..., "stdout": ..., "stderr": ...}`。ADR-0002：exit_code 非零仍 ok=True。
- [ ] GitDiffTool 类：name="git_diff"，参数 schema `staged: bool = False`、`path: str = ""`，side_effect == READ_ONLY。execute 调 `sandbox.exec("git diff " + ("--staged " if staged else "") + shlex.quote(path))`；命令硬编码。返回结构同 git_status。
- [ ] 两者路径越界不适用（无 workspace 路径参数走 Sandbox 路径校验；pathspec/path 是 git 内部路径，由 git 自己限定在 workspace）。
- [ ] 单元测试（在 tmp_path 里 `git init` + 写文件 + `git add` 构造真实仓库状态）：
  - git_status：有改动时 stdout 含 porcelain 行、exit_code=0、ok=True。
  - git_status：非 git 仓库（干净 tmp_path 不 init）→ exit_code 非零、ok=True（ADR-0002 关键断言）。
  - git_status：pathspec 过滤生效。
  - git_diff：有未暂存改动时 stdout 含 diff 内容。
  - git_diff：staged=True 看暂存区（先 git add 再 diff --staged）。
  - git_diff：非 git 仓库 → exit_code 非零、ok=True。
  - 两者 side_effect 断言 READ_ONLY。
  - 参数类型错 → INVALID_ARGUMENT。
- [ ] 所有现有测试仍通过。

## Blocked by

None（can start immediately；只用已有 exec）。

