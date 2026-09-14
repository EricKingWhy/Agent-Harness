"""ReadTool：读取 workspace 内文本文件的 Coding Tool。

READ_ONLY 副作用：不改变外部状态，可与同批其他 READ_ONLY 工具并发执行。
路径边界由 Sandbox 强制（ADR-0001），越界抛 PermissionError → 本工具映射成
ToolResult.failure(error_code=PERMISSION_DENIED)。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_harness.sandbox import Sandbox
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode

#: 输出预算（R8-2，厂商实测共识：pi-mono / Claude Code 均为 2000 行 + ~50KB）：
#: 先到为准；超出即截断并给"可执行的下一步"标记（offset 续读）。
#: 上下文保护是工具的领域语义，不依赖 OverflowHandler（那只在配置了 artifact
#: 存储时接线，且不检查大文件本身）。
_READ_MAX_LINES = 2000
_READ_MAX_BYTES = 50 * 1024


class _ReadArgs(BaseModel):
    path: str = Field(..., description="workspace 内的文件相对路径，如 'src/main.py'")
    offset: int = Field(
        default=1, ge=1,
        description="起始行号（1-based）。大文件续读用：截断标记会提示下一次的 offset。",
    )


class ReadTool(Tool):
    """read 工具：读取 workspace 内文本文件内容。"""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return (
            "读取 workspace 内的文本文件内容。"
            "参数：path 为 workspace 内的文件路径（相对路径或绝对路径，必须在 workspace 范围内）；"
            "offset 为起始行号（1-based，默认 1）。"
            f"单次最多返回 {_READ_MAX_LINES} 行或 {_READ_MAX_BYTES // 1024}KB（先到为准），"
            "超出时附 [Showing lines X-Y of N. Use offset=Y+1 to continue.] 标记，"
            "按提示传 offset 续读。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _ReadArgs

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
            suggested_action="重读目标路径，核对内容是否与预期一致（读操作无副作用，重读安全）。",
        )

    async def execute(self, args: _ReadArgs) -> ToolResult:
        """调 sandbox.read_text；文件不存在或路径越界映射成失败 ToolResult。"""
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
        # 输出预算（R8-2）：行数/字节双帽，先到为准；截断时给可续读标记。
        lines = content.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            # 空文件（0 字节）合法读取：返回空内容而非 INVALID_ARGUMENT——
            # offset 守卫在此之上，默认 offset=1 对 0 行文件会误报越界
            # （厂商行为一致：pi-mono / Claude Code 对空文件返回空内容）。
            return ToolResult.success(
                message=f"已读取 '{args.path}'（空文件）。",
                data={"path": args.path, "content": "", "total_lines": 0},
            )
        start = args.offset
        if start > total_lines:
            return ToolResult.failure(
                message=f"offset={start} 越过文件末尾（共 {total_lines} 行）。",
                error_code=ErrorCode.INVALID_ARGUMENT,
            )
        kept: list[str] = []
        bytes_used = 0
        truncated = False
        giant_line = False
        for line in lines[start - 1:]:
            if len(kept) >= _READ_MAX_LINES:
                truncated = True
                break
            line_bytes = len(line.encode("utf-8")) + 1
            if kept and bytes_used + line_bytes > _READ_MAX_BYTES:
                truncated = True
                break
            if not kept and line_bytes > _READ_MAX_BYTES:
                # 首行自身超字节帽：硬截该行（无法按行续读），标记里给模型一个
                # **解释器无关**的下一步（见下方 giant_line 分支）。
                kept.append(
                    line.encode("utf-8")[:_READ_MAX_BYTES].decode("utf-8", errors="replace")
                )
                bytes_used = _READ_MAX_BYTES
                giant_line = True
                truncated = True
                break
            kept.append(line)
            bytes_used += line_bytes
        if not truncated and start == 1:
            # 未截断且从头读：原样返回（字节级保真，不因窗口化改写行尾）。
            return ToolResult.success(
                message=f"已读取 '{args.path}'（{len(content)} 字符）。",
                data={"path": args.path, "content": content},
            )
        text = "\n".join(kept)
        end_line = start + len(kept) - 1
        if giant_line:
            # OBS-016：曾经教模型用 `sed -n … | head -c …` / `tail -c +N`——POSIX
            # 专有命令在本机（Windows → cmd.exe）不存在，模型照做会整次调用作废。
            # 改为点名**真实存在的工具标识符**（bash / grep），不点名任何命令：
            # 解释器与陷阱由各工具自己的描述声明（OBS-012）。
            # ⚠ 前缀 `[Line {n} truncated at {bytes} bytes` 与结尾 `]` 是前端
            # toolShapes.ts::LINE_TRUNCATED_RE 的解析契约，改措辞可以，改形状不行。
            text += (
                f"\n[Line {start} truncated at {_READ_MAX_BYTES} bytes. "
                "This single line alone exceeds the read limit, so it cannot be "
                "returned in full. Use the bash tool to read a further byte range, "
                "or the grep tool to locate the part you need.]"
            )
        elif truncated:
            text += (
                f"\n[Showing lines {start}-{end_line} of {total_lines}. "
                f"Use offset={end_line + 1} to continue.]"
            )
        return ToolResult.success(
            message=(
                f"已读取 '{args.path}' 行 {start}-{end_line}（共 {total_lines} 行）。"
            ),
            data={"path": args.path, "content": text, "total_lines": total_lines},
        )
