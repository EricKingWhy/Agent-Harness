"""BashTool：在 workspace 内执行 shell 命令的 Coding Tool。

MUTATING 副作用（保守默认）：即使命令本身是只读的（如 ls），也无法静态保证，
所以整批串行执行。

核心不变量（ADR-0002）：bash 工具的 ToolResult.ok 永远 True（除非 Sandbox 本身崩了）。
非零 exit_code（如 pytest 失败）不是 Tool Runtime 异常——exit_code/stdout/stderr
放进 data 供模型读取，模型据此决定下一步，而不是被 Executor 自动重试。
"""

from __future__ import annotations

import asyncio
import threading

from pydantic import BaseModel, Field

from agent_harness.sandbox import Sandbox, ShellFamily
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.result import ErrorCode


class _BashArgs(BaseModel):
    command: str = Field(..., description="要在 workspace 内执行的 shell 命令")


class BashTool(Tool):
    """bash 工具：在 workspace 内执行 shell 命令，返回 exit_code/stdout/stderr。

    名字是**历史名称**（OBS-012）：实际解释器由 Sandbox 后端决定，**不是 bash**——
    POSIX/容器为 `/bin/sh`，Windows 本机为 `cmd.exe`。模型可见描述据此声明真相。
    """

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        """模型可见描述——必须声明**实际** shell（OBS-012）。

        工具名 `bash` 是历史名称：没有任何后端真的调 bash（POSIX/容器是 `/bin/sh`，
        Windows 本机是 `cmd.exe`）。若描述暗示 bash，模型会写出该解释器不认的语法
        （本机实证：cmd.exe 对 bash 语法报「此时不应有 i。」）。解释器名取自 Sandbox
        的事实声明，**不用 `os.name` 猜**（宿主 Windows 时容器内仍是 sh）。
        """
        env = self._sandbox.shell_environment
        if env.family is ShellFamily.BASH:
            # 后端真的用 bash 时不否认（当前无此后端，但 API 允许——避免出现
            # 「实际解释器是 bash（不是 bash）」的自相矛盾）。
            lead = f"在 workspace 内执行 shell 命令。实际解释器是 {env.name}。"
        else:
            lead = (
                "在 workspace 内执行 shell 命令。注意：工具名 bash 是历史名称，"
                f"实际解释器是 {env.name}（不是 bash），请按该解释器的语法书写命令。"
            )
        parts = [lead]
        if env.family is ShellFamily.CMD:
            parts.append(
                "Windows cmd.exe 注意事项：单引号不是引用符、$VAR 不展开、"
                "cat/ls/grep 等 Unix 命令通常不可用（用 type/dir/findstr 代替）、"
                "Unix 风格重定向（如 2>/dev/null）无效。"
            )
        parts.append(
            "参数：command 为要执行的 shell 命令字符串。"
            "返回 exit_code、stdout、stderr——命令返回非零 exit_code 不代表工具调用失败，"
            "应读取 stdout/stderr 判断命令执行结果。"
        )
        return "".join(parts)

    @property
    def args_schema(self) -> type[BaseModel]:
        return _BashArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.MUTATING

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.DANGER

    async def execute(self, args: _BashArgs) -> ToolResult:
        """调 sandbox.exec；exit_code 无论几都返回 ok=True（ADR-0002）。

        sandbox.exec 是同步阻塞调用（子进程最长跑满超时），卸载到工作线程
        执行——否则 event loop 会被单条命令冻结整个异步服务器（D10）。
        执行期 stdout/stderr 经 sink 逐段流式（ADR-0016 §4.2）：sink 由
        ToolExecutor 在执行期放入 contextvar，asyncio.to_thread 复制 context
        使工作线程内可读；无 sink（纯执行场景）= None，sandbox 不回调。
        """
        from agent_harness.tooling.output_stream import tool_output_sink_var

        # 协作取消（C1）：asyncio 超时/断连只能取消 await，杀不掉已在
        # 工作线程里跑的子进程——通过 cancel_event 通知 sandbox 击杀进程树，
        # "超时/取消返回"之后命令不再继续改 workspace（R7-1 的执行层闭环）。
        cancel_event = threading.Event()
        sink = tool_output_sink_var.get()
        try:
            result = await asyncio.to_thread(
                self._sandbox.exec, args.command, cancel_event=cancel_event,
                on_output=(sink.push if sink is not None else None),
            )
        except asyncio.CancelledError:
            cancel_event.set()
            raise
        except PermissionError as e:
            return ToolResult.failure(
                message=str(e),
                error_code=ErrorCode.PERMISSION_DENIED,
            )
        except Exception as e:  # noqa: BLE001
            # Sandbox 本身崩了（如容器挂了、子进程底层故障）——这才是真正的工具失败。
            return ToolResult.failure(
                message=f"bash 执行环境异常: {type(e).__name__}: {e}",
                error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            )
        # 关键映射（ADR-0002）：命令业务失败（exit_code!=0）→ ok=True，
        # exit_code/stdout/stderr 在 data 里供模型读取。
        return ToolResult.success(
            message=f"命令已执行，exit_code={result.exit_code}。",
            data={
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_ms": result.duration_ms,
                **({"cancelled": True} if result.cancelled else {}),
            },
        )
