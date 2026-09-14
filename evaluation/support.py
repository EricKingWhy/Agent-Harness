"""评测域工具集（deterministic P0 用；与 tests/ 无依赖——runner 是项目代码）。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from agent_harness.recovery import ReconcileCallback, ReconcileVerdict
from agent_harness.tooling import Tool, ToolResult
from agent_harness.tooling.result import ErrorCode


class AddArgs(BaseModel):
    first_number: Annotated[float, Field(...)]
    second_number: Annotated[float, Field(...)]


class AddTool(Tool):
    """求和工具：tool_selection 场景的确定性目标工具。"""

    @property
    def name(self) -> str:
        return "add"

    @property
    def description(self) -> str:
        return "计算两个数之和。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return AddArgs

    async def execute(self, args: AddArgs) -> ToolResult:
        return ToolResult.success(
            message="ok", data={"sum": args.first_number + args.second_number},
        )


class FlakyAddTool(AddTool):
    """第一次调用返回可重试失败、第二次成功：recovery 场景的确定性故障注入。"""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, args: AddArgs) -> ToolResult:
        self.calls += 1
        if self.calls == 1:
            return ToolResult.failure(
                message="transient failure (deterministic)",
                error_code=ErrorCode.TIMEOUT,
                retryable=True,
            )
        return ToolResult.success(
            message="ok", data={"sum": args.first_number + args.second_number},
        )


class ModeledFailureAddTool(AddTool):
    """按参数指纹确定性失败（recovery 场景）：args==(1,2) 永远失败且不可重试，
    其余参数正常成功——模拟"模型换了策略才可能成功"的恢复语义。"""

    async def execute(self, args: AddArgs) -> ToolResult:
        if args.first_number == 1 and args.second_number == 2:
            return ToolResult.failure(
                message="deterministic modeled failure for (1, 2)",
                error_code=ErrorCode.TOOL_EXECUTION_ERROR,
                retryable=False,
            )
        return ToolResult.success(
            message="ok", data={"sum": args.first_number + args.second_number},
        )


class ScriptedReconcileCallback(ReconcileCallback):
    """测试/评测用的固定裁决回调（用户显式裁决的唯一来源语义不变）。"""

    def __init__(self, verdict: ReconcileVerdict) -> None:
        self._verdict = verdict

    async def resolve(self, operation, hint) -> ReconcileVerdict:
        return self._verdict
