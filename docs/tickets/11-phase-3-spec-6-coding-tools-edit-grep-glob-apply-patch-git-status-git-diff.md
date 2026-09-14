# #11 — Phase 3 Spec: 剩余 6 个 Coding Tools（edit / grep / glob / apply_patch / git_status / git_diff）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T12:57:41Z
- **Closed**: 2026-09-03T13:27:04Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/11

---

## Problem Statement

Phase 3（Docker Sandbox + Coding Tools）目前已落地 read / write / bash 三个 Coding Tool（commit `76049d0`），但 `05_SANDBOX_CODING_TOOLS.md` 规格要求 V1 Coding Tools 共 9 个。剩余 6 个（edit / grep / glob / apply_patch / git_status / git_diff）尚未实现，Agent 当前无法做精确字符串替换、内容搜索、文件名匹配、多块补丁、或只读 git 查询——这些是 Coding Agent 日常工作的核心操作。没有它们，Agent 只能用 write 整体覆盖文件、用 bash 盲搜，效率低且容易破坏未改动区域。

## Solution

按现有 Tool 契约（`contract.py`）和 Sandbox 边界（`base.py`）实现 6 个新 Coding Tool，全部构造时绑定一个 Sandbox 实例，由 ToolExecutor 以标准 Validation-first 三阶段驱动，不感知 Sandbox 具体后端。同时给 Sandbox ABC 扩展一个最小新方法 `list_files(pattern) -> list[str]`，让 grep / glob 能跨后端（LocalSubprocess + Docker）可移植地枚举 workspace 文件。

完成后 Agent 可以：精确替换文件中的一段字符串（edit）；在 workspace 文件内容里做正则搜索（grep）；按 glob 模式找文件（glob）；对单个文件原子地应用多块补丁（apply_patch）；以及跑只读 git status / git diff 查询仓库状态——所有操作都被 Sandbox 路径边界保护，越界访问统一映射成 PERMISSION_DENIED。

## User Stories

1. 作为 Agent，我想把文件里的一段确切字符串替换成新字符串，这样修小改时就不用整体覆盖重写整个文件。
2. 作为 Agent，当文件里没有匹配到我要替换的字符串时，我想收到一个明确的"未找到匹配"失败结果，这样我能知道是文件变了还是我记错了内容。
3. 作为 Agent，当文件里有多处匹配同一字符串时，我想收到一个明确的"多个匹配"失败结果，这样我不会无意中改错地方。
4. 作为 Agent，当我明确想替换所有匹配时，我想传一个 replace_all 标志把所有匹配都替换掉。
5. 作为 Agent，我想在 workspace 的文件内容里做正则搜索，这样我能快速定位包含某个模式（如函数定义、TODO、错误信息）的代码行。
6. 作为 Agent，当 grep 找到匹配时，我想看到文件路径、行号、和匹配行的文本，这样我能直接定位到要改的位置。
7. 作为 Agent，当 grep 匹配很多时，我想结果有一个合理的上限并被截断，这样巨大的输出不会撑爆模型上下文。
8. 作为 Agent，我想按 glob 模式列出 workspace 里匹配的文件路径，这样我能找到"所有 .py 文件"或"src 下的所有 test_*.py"。
9. 作为 Agent，当 glob 匹配很多时，我想结果有一个合理的上限并被截断，与 grep 同理。
10. 作为 Agent，当我想对单个文件做多处修改时，我想用 apply_patch 一次性应用多个 old_string→new_string 补丁块，而不是串行调很多次 edit。
11. 作为 Agent，当 apply_patch 的任意一块补丁匹配失败（0 或 >1）时，我想整个 apply_patch 原子失败、文件不被改动，这样我不会留下半改的文件。
12. 作为 Agent，当 apply_patch 全部补丁块成功时，我想文件被一次性写入最终内容。
13. 作为 Agent，我想跑 `git status` 看 workspace 里有哪些文件被改了、新增了、删了，这样我了解当前改动范围。
14. 作为 Agent，我想跑 `git diff` 看具体改了什么内容（可选只看暂存区或某个路径），这样我能在提交前 review 改动。
15. 作为 Agent，当我调 git_status / git_diff 时，工具只跑只读 git 子命令，我无法通过它 commit / push / reset。
16. 作为 Agent，当我尝试访问 workspace 边界外的路径时（如 `../../etc/passwd`），任何 Coding Tool 都拒绝并返回 PERMISSION_DENIED。
17. 作为 Agent，当 grep / glob 模式不合法（坏正则、坏 glob）时，我想收到 INVALID_ARGUMENT 而不是崩溃。
18. 作为 Agent，当我传给 edit / apply_patch / git_diff 的参数类型不对（如 path 不是字符串）时，Executor 在执行前拦截并返回 INVALID_ARGUMENT。
19. 作为开发者，我想 grep / glob 在 LocalSubprocessSandbox 和 DockerSandbox 上都能工作，这样 Coding Tool 不绑定到某一个后端。
20. 作为开发者，我想所有新工具的 side_effect 正确分类（READ_ONLY vs MUTATING），这样批次调度能正确决定并发或串行。
21. 作为开发者，我想所有新工具复用现有 Tool 契约和 ToolResult 语义，不引入新的结果类型或新错误码（除非不可省略）。
22. 作为开发者，当 ToolExecutor 跑这些新工具时，它们的 tool_call_id 配对、重试语义、批次调度行为和 read / write / bash 完全一致。

## Implementation Decisions

### 新增 Sandbox ABC 方法：`list_files`

Sandbox ABC（`sandbox/base.py`）新增一个抽象方法：

```python
@abstractmethod
def list_files(self, pattern: str) -> list[str]:
    """枚举 workspace 内匹配 glob 模式的文件，返回 workspace 相对路径列表。
    越界访问（pattern 解析出 workspace 外）抛 PermissionError。
    仅返回文件，不返回目录。结果按路径排序。
    """
```

- **LocalSubprocessSandbox**：用 `os.walk(workspace_root)` + `fnmatch` 实现递归匹配，返回相对 workspace_root 的 POSIX 风格相对路径。
- **DockerSandbox**：用 `exec("find . -type f")` 拿到文件列表后在 Python 里做 fnmatch 过滤，返回容器内相对 `/workspace` 的路径。
- pattern 为空字符串或 `"*"` 时返回 workspace 内所有文件。
- 此方法是所有 6 个新工具里唯一需要改 Sandbox 契约的地方；edit / apply_patch 只用已有的 read_text / write_text，git_status / git_diff 只用已有的 exec。

### edit 工具

- **参数 schema**：`path: str`、`old_string: str`、`new_string: str`、`replace_all: bool = False`。
- **语义**：read_text → 用 `str.count(old_string)` 计数匹配：
  - `replace_all=False`：0 match → failure(TOOL_EXECUTION_ERROR, "未找到匹配的字符串")；1 match → success（替换）；>1 match → failure(TOOL_EXECUTION_ERROR, "找到 N 处匹配，需更具体或传 replace_all=true")。
  - `replace_all=True`：0 match → 同上 failure；≥1 match → success（用 `str.replace` 全替换）。
- **不变量**：old_string 不能为空字符串（schema 校验拦截 → INVALID_ARGUMENT）。
- **side_effect**：MUTATING（改文件）。
- **路径越界**：read_text 抛 PermissionError → 映射 PERMISSION_DENIED。
- **文件不存在**：read_text 抛 FileNotFoundError → 映射 TOOL_EXECUTION_ERROR。
- 成功时 data 含 `{"path": ..., "replacements": N}`。

### grep 工具

- **参数 schema**：`pattern: str`（正则）、`path: str = "."`（搜索范围子目录，相对 workspace）、`include: str = "*"`（文件名 glob 过滤）、`max_results: int = 100`（上限，防上下文爆炸）。
- **语义**：用 `sandbox.list_files("**/" + include)` 枚举（或限定 path 子树），对每个文件 read_text，逐行 `re.search(pattern)`，收集 `{path, line_number, line}`。
- **坏正则**：`re.compile` 抛异常 → 映射 INVALID_ARGUMENT。
- **二进制 / 编码失败文件**：read_text 抛 UnicodeDecodeError → 跳过该文件（不算错误）。
- **截断**：匹配数达到 max_results 时停止，在 data 里标 `truncated: True`。
- **side_effect**：READ_ONLY。
- 成功时 data 含 `{"matches": [{path, line_number, line}, ...], "count": N, "truncated": bool}`。

### glob 工具

- **参数 schema**：`pattern: str`（glob 模式，如 `"**/*.py"`、`"src/test_*.py"`）、`max_results: int = 100`。
- **语义**：调 `sandbox.list_files(pattern)`，截断到 max_results。
- **side_effect**：READ_ONLY。
- 成功时 data 含 `{"paths": [...], "count": N, "truncated": bool}`。

### apply_patch 工具

- **参数 schema**：`path: str`、`hunks: list[{old_string: str, new_string: str}]`（有序补丁块列表）。
- **语义（原子）**：
  1. read_text 拿到原始内容。
  2. 对每个 hunk：校验 old_string 在当前（已应用前面 hunk 的）内容里恰好匹配 1 次；0 或 >1 → 立即整体失败，不写文件。
  3. 全部 hunk 校验+应用通过后，write_text 写入最终内容。
  4. 用一个本地变量做 in-memory 应用，只有全部成功才调 write_text——保证原子性。
- **任意 hunk old_string 为空**：schema 校验拦截 → INVALID_ARGUMENT。
- **side_effect**：MUTATING。
- **路径越界 / 文件不存在**：映射同 edit。
- 成功时 data 含 `{"path": ..., "hunks_applied": N}`。

### git_status 工具

- **参数 schema**：`pathspec: str = ""`（可选路径过滤）。
- **语义**：调 `sandbox.exec(f"git status --porcelain=v1 {shlex.quote(pathspec)}")`。
- **只读保证**：命令是硬编码的 `git status`，不接受用户自定义子命令；模型无法通过此工具 commit / push / reset。
- **side_effect**：READ_ONLY。
- **ADR-0002 适用**：exit_code 非零（如不是 git 仓库）仍是 ok=True，stdout/stderr 在 data 里供模型判断。
- 成功时 data 含 `{"exit_code": ..., "stdout": ..., "stderr": ...}`。

### git_diff 工具

- **参数 schema**：`staged: bool = False`（是否看暂存区）、`path: str = ""`（可选路径过滤）。
- **语义**：调 `sandbox.exec("git diff " + ("--staged " if staged else "") + shlex.quote(path))`。
- **只读保证**：同 git_status——硬编码 `git diff`，不接受子命令。
- **side_effect**：READ_ONLY。
- **ADR-0002 适用**：exit_code 非零仍是 ok=True。
- 成功时 data 含 `{"exit_code": ..., "stdout": ..., "stderr": ...}`。

### 工具注册与导出

- 6 个新工具类在 `tools/__init__.py` 导出。
- 集成测试的 `_make_runtime` fixture 注册全部 9 个 Coding Tools（read/write/bash + 6 个新）。

### Approval（REQUIRE_APPROVAL）——本 Spec 不实现

`05_SANDBOX_CODING_TOOLS.md` 提到的 Permission Policy 分层（read-only / workspace-write / danger-full-access）和 REQUIRE_APPROVAL 机制属于 Capability / Permission 系统（Phase 7），不在本 Spec 实现范围。当前 bash 的 MUTATING side_effect 已让批次调度串行执行它；Sandbox 路径边界已防止越界。Approval 作为 Phase 3 内独立后续 spec 处理。

### Session-scoped Sandbox 生命周期——本 Spec 不实现

Session 绑定 Sandbox 实例、resume 时恢复 workspace 的生命周期管理，属于 Storage + Recovery（Phase 4），不在本 Spec 范围。本 Spec 的工具只要求构造时传入一个已就绪的 Sandbox 实例。

## Testing Decisions

### 测试缝（Seam）

复用现有唯一测试缝：`LocalSubprocessSandbox(tmp_path)` + `ToolRegistry`（注册工具）+ `ToolExecutor.execute(tool_call dict)` + 断言 `ToolResult` 形状。这正是 `tests/tools/test_coding_tools.py` 已建立的模式。新工具的测试追加到同一文件或同目录新文件，不引入新缝。

Sandbox 新方法 `list_files` 的契约测试追加到 `tests/sandbox/`，匹配现有 Sandbox 契约测试风格（LocalSubprocessSandbox 真目录 + 断言返回值；DockerSandbox 用 `@pytest.mark.integration` + skipif Docker 不可用）。

### 什么算好测试

- **只测外部行为**：通过 ToolExecutor 驱动工具、断言 ToolResult 字段（ok / data / error_code），不测私有方法。
- **不变量优先**：edit 的 0/1/>1 三态、apply_patch 的原子性（失败时文件不变）、git 的只读保证（硬编码命令）、路径越界 → PERMISSION_DENIED、ADR-0002（git exit_code 非零仍 ok=True）。
- **边界用例**：空 old_string、坏正则、坏 glob、空 workspace、max_results 截断、二进制文件跳过、pathspec 转义。
- **side_effect 断言**：每个工具测 `tool.side_effect == 期望值`。
- **先例**：完全参照 `test_coding_tools.py` 里 `TestReadTool` / `TestWriteTool` / `TestBashTool` 的结构（side_effect 断言 + happy path + 错误映射 + Validation）。

### 具体测试模块

- `tests/tools/test_edit_tool.py`：0/1/>1 三态、replace_all、空 old_string、路径越界、文件不存在、覆盖写生效。
- `tests/tools/test_grep_tool.py`：基础正则搜索、行号+文本返回、include 过滤、path 子树限定、坏正则 → INVALID_ARGUMENT、max_results 截断、空 workspace、二进制文件跳过。
- `tests/tools/test_glob_tool.py`：基础 glob 匹配、递归 `**` 模式、max_results 截断、无匹配返回空列表、坏模式不崩溃。
- `tests/tools/test_apply_patch_tool.py`：多 hunk 全成功、任意 hunk 0 匹配 → 原子失败文件不变、任意 hunk >1 匹配 → 原子失败、空 old_string、路径越界、文件不存在。
- `tests/tools/test_git_tools.py`：git_status happy path（在 tmp_path init git）、git_diff happy path、staged 选项、非 git 仓库 → exit_code 非零但 ok=True（ADR-0002）、只读保证（命令硬编码无法注入子命令）。
- `tests/sandbox/test_list_files.py`（或追加到现有 sandbox 测试）：LocalSubprocessSandbox list_files 基础匹配、递归 `**`、空 workspace、只返回文件不返回目录、路径排序。
- `tests/tools/test_coding_tools.py`：批次调度测试追加——纯 READ_ONLY 批（如多个 glob）可并发、MUTATING + READ_ONLY 混批串行（已有此测试模式，追加新工具的 side_effect 分类断言即可）。

## Out of Scope

- **Approval / REQUIRE_APPROVAL 机制**：属 Capability / Permission 系统（Phase 7），本 Spec 不实现。后续单独 spec。
- **Session-scoped Sandbox 生命周期**：Session 绑定 Sandbox、resume 时 workspace 恢复，属 Storage + Recovery（Phase 4）。
- **DockerSandbox 的 list_files 集成测试**：实现 DockerSandbox.list_files 但集成测试标记 `@pytest.mark.integration` + skipif Docker 不可用；CI 默认只跑 LocalSubprocessSandbox 路径。
- **Unified diff 格式解析**：apply_patch V1 用结构化 hunks（list of {old_string, new_string}），不解析标准 unified diff。后者作为未来增强。
- **ripgrep / 高级搜索引擎集成**：grep V1 用 Python `re` 逐文件逐行搜索，不接入 ripgrep。Reuse First 评估结论：V1 量级不需要。
- **新 ErrorCode**：不为 edit 的 NOT_FOUND / AMBIGUOUS 新增 ErrorCode 枚举值——映射到现有 TOOL_EXECUTION_ERROR 并在 message 里说明状态。保持错误词汇表稳定。

## Further Notes

- **Reuse First 检查（`13_OPEN_SOURCE_REUSE_MATRIX.md`）**：Coding Tools 的 edit/grep/glob/apply_patch 是轻量文件操作，标准库（re / fnmatch / pathlib / os.walk）已足够，不需要引入外部库。git_status / git_diff 只是 exec 硬编码只读命令。结论：BUILD，但建立在已有 Sandbox 抽象上，零新依赖。
- **架构不变量守护**：
  - 工具只用统一 ToolExecutor 路径执行（不变量 #7）。
  - 无新 Retry 语义——工具失败走现有 ErrorCode 分类（不变量 #8）。
  - Sandbox 是 Runtime 安全边界，路径越界在 Sandbox 层强制，不靠 prompt（不变量 #11）。
  - 新工具不改 ToolResult 形状、不改 Tool 契约、不改 ToolExecutor 行为。
- **ADR-0002 适用范围**：git_status / git_diff 和 bash 一样遵循"命令 exit_code 非零 ≠ Tool 失败"——exit_code / stdout / stderr 在 data 里供模型判断。edit / grep / glob / apply_patch 不走 exec，不受 ADR-0002 影响，它们的失败是真正的 Tool 失败（ok=False）。
- **依赖关系**：本 Spec 不依赖 Phase 1 SessionEvent（工具是 Stateless 的，由 Runtime 传入 Sandbox）。可在 Phase 1 完成后或并行实现。

