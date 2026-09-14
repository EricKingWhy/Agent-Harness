# #12 — Ticket 1: Sandbox list_files 方法 + LocalSubprocessSandbox/DockerSandbox 实现 + 契约测试

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T12:59:25Z
- **Closed**: 2026-09-03T13:26:39Z
- **Parent**: #11
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/12

---

## Parent

#11 — Phase 3 Spec: 剩余 6 个 Coding Tools

## What to build

给 Sandbox ABC 扩展一个最小新方法 `list_files(pattern) -> list[str]`，让 grep / glob 工具能跨后端可移植地枚举 workspace 文件。LocalSubprocessSandbox 用 `os.walk` + `fnmatch` 实现递归匹配，返回 workspace 相对路径（POSIX 风格，排序）。DockerSandbox 用 `exec("find . -type f")` + Python 侧 fnmatch 过滤实现。这是后续 glob / grep 工具的地基——没有它，grep/glob 要么只支持 Local 后端、要么每个工具各自实现枚举逻辑。

## Acceptance criteria

- [ ] Sandbox ABC 新增抽象方法 `list_files(self, pattern: str) -> list[str]`，docstring 说明语义（枚举 workspace 内匹配 glob 的文件、仅文件不目录、相对路径、排序、越界抛 PermissionError）。
- [ ] LocalSubprocessSandbox.list_files 实现：`os.walk(workspace_root)` + `fnmatch.fnmatch` / `fnmatch.translate` 做递归 `**` glob 匹配；返回相对 workspace_root 的 POSIX 风格路径（正斜杠）；结果排序；仅文件不目录。
- [ ] DockerSandbox.list_files 实现：`exec("find . -type f -printf '%P\n'")` 拿文件列表后 Python 侧 fnmatch 过滤；返回容器内相对 `/workspace` 路径；排序。
- [ ] pattern 为空字符串或 `"*"` 时返回 workspace 内所有文件。
- [ ] 单元测试（LocalSubprocessSandbox）：基础 `*.py` 匹配、递归 `**/*.py` 匹配嵌套子目录、空 workspace 返回空列表、只返回文件不返回目录、结果排序、多扩展名混合。
- [ ] DockerSandbox.list_files 集成测试标记 `@pytest.mark.integration` + skipif Docker 不可用（与现有 DockerSandbox 测试一致）。
- [ ] 所有现有测试仍通过（`pytest -q`）。

## Blocked by

None（can start immediately）。

