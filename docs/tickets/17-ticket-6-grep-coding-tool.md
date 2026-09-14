# #17 — Ticket 6: grep Coding Tool（正则内容搜索 + 截断 + 二进制跳过）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T13:02:20Z
- **Closed**: 2026-09-03T13:26:57Z
- **Parent**: #11
- **Blocked by**: #12
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/17

---

## Parent

#11 — Phase 3 Spec: 剩余 6 个 Coding Tools

## What to build

实现 grep Coding Tool：在 workspace 文件内容里做正则搜索，返回文件路径、行号、匹配行文本。Agent 用它定位函数定义、TODO、错误信息等。调 Sandbox.list_files 枚举（Ticket 1），对每个文件 read_text 逐行 `re.search`，收集匹配。支持 include glob 过滤文件名、path 子树限定范围、max_results 截断防爆炸。坏正则映射 INVALID_ARGUMENT；二进制/编码失败文件跳过不算错。READ_ONLY。

## Acceptance criteria

- [ ] GrepTool 类：name="grep"，构造时绑定 Sandbox。
- [ ] 参数 schema：`pattern: str`（正则）、`path: str = "."`（搜索范围子目录，相对 workspace）、`include: str = "*"`（文件名 glob 过滤）、`max_results: int = 100`（ge=1）。
- [ ] side_effect == READ_ONLY。
- [ ] execute 语义：
  1. `re.compile(pattern)`——坏正则抛异常 → failure(INVALID_ARGUMENT)。
  2. 调 `sandbox.list_files("**/" + include)`（或限定 path 子树），拿到候选文件列表。
  3. 对每个文件 read_text，逐行 `regex.search(line)`，收集 `{path, line_number, line}`。
  4. read_text 抛 UnicodeDecodeError（二进制文件）→ 跳过该文件，不算错误。
  5. 匹配数达 max_results → 停止扫描，truncated=True。
- [ ] 成功时 data 含 `{"matches": [{path, line_number, line}, ...], "count": N, "truncated": bool}`。
- [ ] 路径越界（list_files 抛 PermissionError）→ PERMISSION_DENIED。
- [ ] 单元测试（参照 test_coding_tools.py 风格，通过 ToolExecutor 驱动）：
  - side_effect == READ_ONLY。
  - 基础正则搜索：workspace 有文件含 "def foo(" → pattern="def (\w+)" 匹配，返回含 path/line_number/line。
  - 多文件多匹配：行号正确、line 是匹配行全文。
  - include 过滤：pattern 匹配但 include="*.py" 时 .txt 文件被跳过。
  - path 子树限定：只在指定子目录里搜。
  - 坏正则（如 `[unclosed`）→ INVALID_ARGUMENT。
  - max_results 截断：构造 >100 匹配，count==100 且 truncated=True。
  - 空 workspace → count=0、matches=[]、truncated=False。
  - 二进制文件（写些不可解码字节）→ 被跳过，不影响其他文件匹配、不报错。
  - 参数类型错 → INVALID_ARGUMENT。
- [ ] 所有现有测试仍通过。

## Blocked by

- #12（Ticket 1：Sandbox list_files 方法必须先落地，grep 直接依赖它枚举文件）。

