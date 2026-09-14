"""GlobTool：按 glob 模式列出 workspace 内匹配文件的 Coding Tool。

READ_ONLY 副作用：不改外部状态，可与同批其他 READ_ONLY 工具并发。
直接调 Sandbox.list_files，做 max_results 截断防上下文爆炸。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_harness.sandbox import Sandbox
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode


class _GlobArgs(BaseModel):
    pattern: str = Field(..., description="glob 模式，如 '**/*.py' 或 'src/test_*.py'")
    max_results: int = Field(default=100, ge=1, description="返回上限，防上下文爆炸")


class GlobTool(Tool):
    """glob 工具：按 glob 模式列出 workspace 内匹配的文件路径。"""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "按 glob 模式列出 workspace 内匹配的文件路径。"
            "参数：pattern glob 模式（如 '**/*.py'、'src/test_*.py'），"
            "max_results 返回上限（默认 100）。"
            "用于查找文件，不做内容搜索。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _GlobArgs

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
            suggested_action="重新执行同样的 glob 匹配，核对结果是否与预期一致（只读操作，重跑安全）。",
        )

    async def execute(self, args: _GlobArgs) -> ToolResult:
        """调 sandbox.list_files(pattern) → 截断到 max_results。"""
        try:
            matched = self._sandbox.list_files(args.pattern)
        except PermissionError as e:
            return ToolResult.failure(
                message=str(e),
                error_code=ErrorCode.PERMISSION_DENIED,
            )

        truncated = len(matched) > args.max_results
        paths = matched[:args.max_results]

        return ToolResult.success(
            message=f"匹配到 {len(matched)} 个文件"
                    + ("（已截断）" if truncated else "")
                    + "。",
            data={
                "paths": paths,
                "count": len(paths),
                "truncated": truncated,
            },
        )
