"""ApplyPatchTool：对单个文件原子地应用多个 old_string→new_string 补丁块。

原子性不变量：任意一个 hunk 匹配失败（0 或 >1），整个 apply_patch 失败，
文件不被改动（in-memory 应用，全部成功才 write_text）。

MUTATING 副作用。复用 Sandbox.read_text / write_text。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_harness.sandbox import Sandbox
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.result import ErrorCode
from agent_harness.tools._diff_data import diff_data


class _Hunk(BaseModel):
    old_string: str = Field(..., min_length=1, description="要被替换的确切字符串（不能为空）")
    new_string: str = Field(..., description="替换后的新字符串")


class _ApplyPatchArgs(BaseModel):
    path: str = Field(..., description="workspace 内的文件相对路径")
    hunks: list[_Hunk] = Field(..., min_length=1, description="有序补丁块列表，至少 1 块")


class ApplyPatchTool(Tool):
    """apply_patch 工具：多 hunk 原子补丁，任一失败则整体回滚。"""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "对单个文件原子地应用多个补丁块（hunks）。"
            "参数：path 文件路径，hunks 是一个有序列表，每项含 old_string 和 new_string。"
            "任意一块匹配失败（0 或多于 1 处）则整个操作失败、文件不被改动。"
            "适合对同一文件做多处相关修改。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _ApplyPatchArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.MUTATING

    async def execute(self, args: _ApplyPatchArgs) -> ToolResult:
        """read_text → 逐 hunk 校验+应用（in-memory）→ 全成功才 write_text。"""
        try:
            content = self._sandbox.read_text(args.path)
        except PermissionError as e:
            return ToolResult.failure(
                message=str(e),
                error_code=ErrorCode.PERMISSION_DENIED,
            )
        except FileNotFoundError:
            return ToolResult.failure(
                message=f"文件 '{args.path}' 不存在。",
                error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            )

        current = content
        for idx, hunk in enumerate(args.hunks, start=1):
            count = current.count(hunk.old_string)
            if count == 0:
                return ToolResult.failure(
                    message=f"第 {idx} 块补丁在 '{args.path}' 中未找到匹配。",
                    error_code=ErrorCode.TOOL_EXECUTION_ERROR,
                )
            if count > 1:
                return ToolResult.failure(
                    message=(
                        f"第 {idx} 块补丁在 '{args.path}' 中找到 {count} 处匹配，"
                        f"需缩小 old_string 范围。"
                    ),
                    error_code=ErrorCode.TOOL_EXECUTION_ERROR,
                )
            current = current.replace(hunk.old_string, hunk.new_string, 1)

        try:
            self._sandbox.write_text(args.path, current)
        except PermissionError as e:
            return ToolResult.failure(
                message=str(e),
                error_code=ErrorCode.PERMISSION_DENIED,
            )

        return ToolResult.success(
            message=f"已在 '{args.path}' 中应用 {len(args.hunks)} 块补丁。",
            data={
                "path": args.path,
                "hunks_applied": len(args.hunks),
                **diff_data(content, current),
            },
        )
