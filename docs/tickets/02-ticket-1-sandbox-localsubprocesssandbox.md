# #2 — Ticket 1: Sandbox 契约 + LocalSubprocessSandbox

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T07:39:04Z
- **Closed**: 2026-09-03T13:04:19Z
- **Parent**: #1
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/2

---

## Parent

#1 (Day05 切片 1：Sandbox 抽象 + read/write/bash Coding Tools)

## What to build

定义 `Sandbox` 抽象契约（6 方法：`ensure_started / exec / read_text / write_text / copy_in / stop`）和 `ExecResult` dataclass（`exit_code: int / stdout: str / stderr: str / duration_ms: float`）。实现第一个后端 `LocalSubprocessSandbox`：在本机子进程执行命令（`subprocess.run`），workspace_root 是本机一个真实目录。所有接受路径的方法（`read_text` / `write_text` / `copy_in`）把传入路径 `Path.resolve()` 后校验 `is_relative_to(workspace_root)`，越界抛 `PermissionError`。

交付后应能演示：`sandbox.exec("echo hello")` 返回 `ExecResult(exit_code=0, stdout="hello\n")`；`sandbox.read_text("../../etc/passwd")` 抛 `PermissionError`；`sandbox.write_text("a.txt","hi")` 后 `sandbox.read_text("a.txt")` 返回 `"hi"`。

新增模块：`src/agent_harness/sandbox/`（`base.py` 含 Sandbox ABC + ExecResult，`local.py` 含 LocalSubprocessSandbox）。

## Acceptance criteria

- [ ] `Sandbox` ABC 定义 6 个抽象方法，签名与 spec 一致
- [ ] `ExecResult` 是 dataclass，含 exit_code / stdout / stderr / duration_ms 四个字段
- [ ] `LocalSubprocessSandbox.exec` 用 subprocess.run 执行命令，正确捕获 exit_code / stdout / stderr / 计时 duration_ms
- [ ] `LocalSubprocessSandbox.read_text` / `write_text` 正常读写 workspace 内文件
- [ ] `LocalSubprocessSandbox.copy_in` 把宿主文件拷入 workspace 目录
- [ ] 路径越界（如 `../../etc/passwd`）被 resolve + is_relative_to 拒绝，抛 PermissionError
- [ ] `ensure_started` / `stop` 幂等（多次调用不报错）
- [ ] 全套契约测试用 LocalSubprocessSandbox，零 Docker 依赖，纳入默认套且全绿
- [ ] ruff 通过

## Blocked by

None (can start immediately)

