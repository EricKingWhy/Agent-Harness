# #4 — Ticket 3: Coding Tools（read / write / bash）

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T07:40:10Z
- **Closed**: 2026-09-03T13:04:22Z
- **Parent**: #1
- **Blocked by**: #2
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/4

---

## Parent

#1 (Day05 切片 1：Sandbox 抽象 + read/write/bash Coding Tools)

## What to build

在 Sandbox 之上实现三个 Coding Tool，按现有 `Tool` 契约（`contract.py` 的 ABC：name / description / args_schema / execute / side_effect）。每个 Tool 构造时绑定一个 `Sandbox` 实例，execute 内调 Sandbox 方法并把结果包成 `ToolResult`。

三个工具：
- **ReadTool**（`side_effect = READ_ONLY`）：args_schema 含 `path: str`；调 `sandbox.read_text(path)`；成功返回 `ToolResult.success(data={"content": ..., "path": ...})`。
- **WriteTool**（`side_effect = MUTATING`）：args_schema 含 `path: str, content: str`；调 `sandbox.write_text(path, content)`；成功返回 `ToolResult.success(data={"path": ..., "bytes_written": ...})`。
- **BashTool**（`side_effect = MUTATING`）：args_schema 含 `command: str`；调 `sandbox.exec(command)`；**无论 exit_code 几**都返回 `ToolResult.ok=True`，`data = {exit_code, stdout, stderr, duration_ms}`（ADR-0002 不变量）。只有 Sandbox 本身抛异常（如 PermissionError / 容器崩）才返回 `ToolResult.failure`，PermissionError 映射成 `ErrorCode.PERMISSION_DENIED`。

新增模块：`src/agent_harness/tools/`（`read.py` / `write.py` / `bash.py` + `__init__.py` 导出）。

## Acceptance criteria

- [ ] ReadTool / WriteTool / BashTool 各自实现 Tool ABC 全部必填字段
- [ ] side_effect 分类正确：ReadTool=READ_ONLY，WriteTool/BashTool=MUTATING
- [ ] args_schema 是 Pydantic BaseModel，字段与 spec 一致
- [ ] ToolExecutor.execute(tool_call) 对三个工具都能正常驱动（校验 → execute → ToolResult）
- [ ] BashTool 非零 exit_code（如 pytest 失败）返回 ToolResult.ok=True 且 data 含 exit_code/stdout/stderr
- [ ] Sandbox 抛 PermissionError（路径越界）被 Tool 映射成 ToolResult.failure(error_code=PERMISSION_DENIED)
- [ ] 非法参数（缺字段 / 类型错）被 Executor 阶段 2 校验拦截，返回 INVALID_ARGUMENT
- [ ] 全套单元测试用 LocalSubprocessSandbox 做后端，纳入默认套且全绿
- [ ] ruff 通过

## Blocked by

- #2 (Ticket 1: Sandbox 契约 + LocalSubprocessSandbox)

