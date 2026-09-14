"""GrepTool：在 workspace 文件内容里做正则搜索的 Coding Tool。

READ_ONLY 副作用。调 Sandbox.list_files 枚举，对每个文件 read_text 逐行 re.search。
- 坏正则 → INVALID_ARGUMENT
- 二进制/编码失败文件 → 跳过（不算错误）
- max_results 截断防上下文爆炸
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from agent_harness.sandbox import Sandbox
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode

#: 单条匹配行的字符预算（R8-2）：matches 整体进 Context/JSONL/Ledger，
#: 无行上限时一条压缩 bundle 行即可撑爆三者。超出截断并显式标记
#: （模型可用 read 工具按行号看原文）。
_MAX_LINE_CHARS = 500


class _GrepArgs(BaseModel):
    pattern: str = Field(..., description="正则表达式")
    path: str = Field(default=".", description="搜索范围子目录，相对 workspace")
    include: str = Field(default="*", description="文件名 glob 过滤（如 '*.py'）")
    max_results: int = Field(default=100, ge=1, le=1000,
                             description="匹配上限（最多 1000），防上下文爆炸；命中过多请细化 pattern")


class GrepTool(Tool):
    """grep 工具：在 workspace 文件内容里做正则搜索，返回文件路径+行号+匹配行。"""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "在 workspace 文件内容里做正则搜索。"
            "参数：pattern 正则表达式，include 文件名 glob 过滤（如 '*.py'），"
            "超长匹配行截断到 500 字符（可用 read 按行号看原文），"
            "path 搜索范围子目录，max_results 匹配上限（默认 100）。"
            "返回匹配的文件路径、行号、行文本。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _GrepArgs

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
            suggested_action="重新执行同样的正则搜索，核对匹配结果是否与预期一致（只读操作，重跑安全）。",
        )

    async def execute(self, args: _GrepArgs) -> ToolResult:
        """re.compile → list_files → 逐文件逐行 search → 收集匹配。"""
        try:
            regex = re.compile(args.pattern)
        except re.error as e:
            return ToolResult.failure(
                message=f"无效的正则表达式 '{args.pattern}': {e}",
                error_code=ErrorCode.INVALID_ARGUMENT,
            )

        try:
            # 全量枚举 + 后面的子树前缀过滤：不能把 "path/" 当 glob 传下去——
            # _glob_match 对文件相对路径匹配 "src/" 恒为 False，path 非空时
            # 匹配数恒为 0（模型会静默得出"代码里没有"的错误结论）。
            candidates = self._sandbox.list_files("")
        except PermissionError as e:
            return ToolResult.failure(
                message=str(e),
                error_code=ErrorCode.PERMISSION_DENIED,
            )

        # 如果 path 不是 "."，过滤只保留该子树下的文件。
        # 分隔符归一：模型可能吐 win32 风格 "src\\sub"——不归一会回到
        # 静默零匹配（与本次修复同类失效）。
        if args.path and args.path != ".":
            prefix = args.path.replace("\\", "/").rstrip("/") + "/"
            candidates = [f for f in candidates if f.startswith(prefix)
                          or f == prefix.rstrip("/")]

        # include 文件名过滤
        if args.include and args.include != "*":
            candidates = [
                f for f in candidates if fnmatch.fnmatch(PurePosixPath(f).name, args.include)
            ]

        matches: list[dict] = []
        truncated = False
        for filepath in candidates:
            if len(matches) >= args.max_results:
                truncated = True
                break
            try:
                content = self._sandbox.read_text(filepath)
            except (FileNotFoundError, PermissionError, UnicodeDecodeError):
                # 二进制文件或编码失败 → 跳过
                continue

            for line_number, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    if len(line) > _MAX_LINE_CHARS:
                        line = line[:_MAX_LINE_CHARS] + "... [truncated]"
                    matches.append({
                        "path": filepath,
                        "line_number": line_number,
                        "line": line,
                    })
                    if len(matches) >= args.max_results:
                        truncated = True
                        break

        return ToolResult.success(
            message=f"找到 {len(matches)} 处匹配"
                    + ("（已截断）" if truncated else "")
                    + "。",
            data={
                "matches": matches,
                "count": len(matches),
                "truncated": truncated,
            },
        )
