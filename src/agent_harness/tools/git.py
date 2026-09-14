"""GitStatusTool + GitDiffTool：只读 git 查询 Coding Tools。

V1 仅 status / diff 等只读能力（05_SANDBOX_CODING_TOOLS.md）：
MUST NOT 自动 commit / push / reset --hard。

命令硬编码 + pathspec 白名单校验 → 模型无法注入子命令。注意：sandbox.exec
走 shell=True，win32 上是 cmd.exe——cmd 不认 shlex 单引号，仅靠 shlex.quote
挡不住 "&" 拆命令（READ_ONLY 工具会绕过审批门与串行语义）。白名单之外的
pathspec 一律 INVALID_ARGUMENT 拒绝（跨 shell 安全）。
遵循 ADR-0002：exit_code 非零（如不是 git 仓库）仍 ok=True。

READ_ONLY 副作用：不改外部状态，可与同批其他 READ_ONLY 工具并发。
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, Field

from agent_harness.sandbox import ExecResult, Sandbox
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode

#: pathspec/path 白名单：文件路径的合法字符（字母数字、空格、/ . _ -）。
#: shell 元字符（& | < > ^ % " ' ` ! \\ 换行等）一律拒绝——cmd.exe 与 POSIX 的
#: 元字符集不同，白名单是唯一跨 shell 安全的拦法。\\ 也在拒绝之列：工具契约的
#: 路径是 workspace 相对 POSIX 风格（/ 分隔），且裸 \ 在双引号内语义因 shell 而异。
#: 空格在白名单内：插值时统一加双引号（见 execute），元字符已被白名单排除，
#: 双引号在 cmd.exe 与 POSIX sh 中都安全。
_SAFE_PATHSPEC = re.compile(r"^[\w /.\-]+$", re.UNICODE)


def _checked_pathspec(value: str) -> str:
    """校验 pathspec/path 是纯路径段；非法即抛 ValueError（调用方映射 INVALID_ARGUMENT）。"""
    if not _SAFE_PATHSPEC.fullmatch(value):
        raise ValueError(
            f"pathspec 含非法字符，只接受纯文件路径（字母/数字/空格/.-_/，"
            "不支持通配符与 pathspec magic）："
            f"{value!r}"
        )
    return value


def _quoted(value: str) -> str:
    """白名单内的 pathspec 统一双引号包裹：空格路径不再被 shell 拆成多个参数。"""
    return f'"{value}"' if value else ""


# ── 命令构造与执行：**工具与 Web 路由的唯一一份**（#191）──
#
# `GET .../workspace/git/status` / `.../git/diff` 要"复用 git_status/git_diff 的既有
# 语义，不要另写一套"（票面 AC3）。所以命令字符串、白名单校验、以及"同步 exec 卸载到
# 工作线程"这三件事都收在这里，工具与路由各自调这三个函数——校验放行面只有一处，
# 不存在"路由那条忘了校验 shell 元字符"的可能。


def git_status_command(pathspec: str = "", *, scope: str = "") -> str:
    """`git status --porcelain=v1 [-- scope] [pathspec]`。pathspec 非法抛 ValueError。

    `scope` 是给调用方的**路径围栏**（#191）：git 的操作范围是**仓库**，而仓库可能比
    workspace 大——workspace 嵌在一个更大的仓库里时（默认布局 `<workspace_dir>/workspaces/<sid>`
    只要 `workspace_dir` 本身在某个仓库内就是这种情形），裸 `git status` 会列出 workspace
    **以外**的文件。Web 路由传 `scope="."`（cwd 即 workspace）把输出围回子树。
    多个 pathspec 是**并集**，所以 scope 必须涵盖 pathspec——调用方必须先保证 pathspec
    在 workspace 内（越过 Sandbox 的 `resolve_within_workspace`），否则围栏形同虚设。
    工具不传 scope：Agent 侧的命令语义逐字不变。
    """
    checked = _checked_pathspec(pathspec) if pathspec else ""
    command = "git status --porcelain=v1"
    return _with_pathspecs(command, scope=scope, pathspec=checked)


def git_diff_command(*, staged: bool = False, path: str = "", scope: str = "") -> str:
    """`git diff [--staged] [-- scope] [path]`。path 非法抛 ValueError（`scope` 同 `git_status_command`）。"""
    checked = _checked_pathspec(path) if path else ""
    command = "git diff --staged" if staged else "git diff"
    return _with_pathspecs(command, scope=scope, pathspec=checked)


def _with_pathspecs(command: str, *, scope: str, pathspec: str) -> str:
    """拼 `-- <pathspec>...`。

    无 pathspec 时**逐字保持**旧形态（工具侧命令不变）；有任何一个才加 `--` 分隔符
    （scope 是内部固定 token，加分隔符是为了让"这是 pathspec 不是 revision"对 git 无歧义）。
    """
    if not scope and not pathspec:
        return command
    parts = [command, "--"]
    if scope:
        parts.append(_quoted(scope))
    if pathspec:
        parts.append(_quoted(pathspec))
    return " ".join(parts)


async def run_git_command(sandbox: Sandbox, command: str) -> ExecResult:
    """执行一条已构造好的 git 命令（同步 `sandbox.exec` 卸载到工作线程，D10 同款）。"""
    return await asyncio.to_thread(sandbox.exec, command)


class _GitStatusArgs(BaseModel):
    pathspec: str = Field(default="", description="可选路径过滤，如 'src/' 或 'README.md'（纯路径，不支持通配符与 pathspec magic）")


class GitStatusTool(Tool):
    """git_status 工具：只读查询 workspace git 状态（porcelain 格式）。"""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return (
            "查询 workspace 的 git 状态（只读）。返回 porcelain 格式的改动文件列表。"
            "参数：pathspec 可选路径过滤。不会执行 commit / push / reset 等写操作。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _GitStatusArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(
            verifiable=True,
            suggested_action="重新运行 git status，核对工作区状态是否与预期一致（只读查询，重跑安全）。",
        )

    async def execute(self, args: _GitStatusArgs) -> ToolResult:
        """exec 硬编码 git status；ADR-0002：exit_code 非零仍 ok=True。"""
        try:
            command = git_status_command(args.pathspec)
        except ValueError as error:
            return ToolResult.failure(
                message=str(error),
                error_code=ErrorCode.INVALID_ARGUMENT,
            )
        result = await run_git_command(self._sandbox, command)
        return ToolResult.success(
            message=f"git status 已执行，exit_code={result.exit_code}。",
            data={
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )


class _GitDiffArgs(BaseModel):
    staged: bool = Field(default=False, description="True 时查看暂存区差异（git diff --staged）")
    path: str = Field(default="", description="可选路径过滤（纯路径，不支持通配符）")


class GitDiffTool(Tool):
    """git_diff 工具：只读查询 workspace git 差异内容。"""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return (
            "查询 workspace 的 git 差异（只读）。"
            "参数：staged=True 看暂存区差异，path 可选路径过滤。"
            "不会执行 commit / push / reset 等写操作。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _GitDiffArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(
            verifiable=True,
            suggested_action="重新运行 git diff，核对变更内容是否与预期一致（只读查询，重跑安全）。",
        )

    async def execute(self, args: _GitDiffArgs) -> ToolResult:
        """exec 硬编码 git diff；ADR-0002：exit_code 非零仍 ok=True。"""
        try:
            command = git_diff_command(staged=args.staged, path=args.path)
        except ValueError as error:
            return ToolResult.failure(
                message=str(error),
                error_code=ErrorCode.INVALID_ARGUMENT,
            )
        result = await run_git_command(self._sandbox, command)
        return ToolResult.success(
            message=f"git diff 已执行，exit_code={result.exit_code}。",
            data={
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
