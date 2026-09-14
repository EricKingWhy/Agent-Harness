"""ReadArtifactTool: model reads externalized large tool results by ref.

Phase Multiturn T5 (#135): when a tool result exceeds the overflow threshold,
the raw content is externalized and the session keeps only a truncated
summary + ``artifact_ref``. This tool lets the model read back local slices
of the externalized artifact by ``artifact_ref`` (from ``ToolResult.artifact_ref``
or the ``ARTIFACT_EXTERNALIZED`` event).

与哪个 store 配对由 `storage/artifact_select.py` 决定（选 store 的地方同时定它与哪个
读回工具配对）：本工具服务 T5 **外置链路**所用的 store —— MinIO（#135）与 Local
（#192，spec 06 §3 的默认 Provider）。

Distinct from ``InspectArtifactTool`` (which pairs with the generic
``S3ArtifactStore``): 两者最终都调 ``ArtifactStore.inspect``，所以这个分工是历史配对，
不是能力差异。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_harness.storage.artifact import ArtifactStore
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode


class _ReadArgs(BaseModel):
    artifact_ref: str = Field(
        ...,
        description="要读取的外置产物 ID（从工具结果的 artifact_ref 或 ARTIFACT_EXTERNALIZED 事件获得）",
    )
    start_line: int | None = Field(default=None, ge=1, description="起始行号（1-based）")
    end_line: int | None = Field(default=None, ge=1, description="结束行（含）")
    keyword: str | None = Field(default=None, description="关键词过滤，只返回含此关键词的行")
    max_lines: int = Field(default=200, ge=1, le=1000, description="返回行数上限（默认 200，最大 1000）")
    max_chars_per_line: int = Field(
        default=2000, ge=1, le=20000,
        description="单行字符上限（默认 2000）。单行被截断时返回体携带 truncated 与 full_length，"
                    "可放宽本参数重新读取更长片段。",
    )


class ReadArtifactTool(Tool):
    """read_artifact: 从外置对象存储局部读取大产物的细节。"""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._store = artifact_store

    @property
    def name(self) -> str:
        return "read_artifact"

    @property
    def description(self) -> str:
        return (
            "读取之前被自动保存为外置产物的大输出（如 bash 的长 stdout）的局部内容。"
            "参数：artifact_ref（从工具结果的 artifact_ref 获得），"
            "start_line/end_line 按行范围读取，keyword 按关键词过滤，"
            "max_lines 返回行数上限（默认 200），"
            "max_chars_per_line 单行字符上限（默认 2000，超限可放宽）。"
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
            suggested_action="重新执行同样的 read_artifact 调用，核对返回的行内容是否一致（只读操作，重跑安全）。",
        )

    async def execute(self, args: _ReadArgs) -> ToolResult:
        try:
            result = await self._store.inspect(
                args.artifact_ref,
                start_line=args.start_line,
                end_line=args.end_line,
                keyword=args.keyword,
                max_lines=args.max_lines,
                max_chars_per_line=args.max_chars_per_line,
            )
        except KeyError as e:
            return ToolResult.failure(
                message=str(e),
                error_code=ErrorCode.INVALID_ARGUMENT,
            )
        return ToolResult.success(
            message=f"读取外置产物 {args.artifact_ref}：返回 {result.returned_lines} 行"
                    + ("（已截断）" if result.truncated else "")
                    + f"，共 {result.total_lines} 行。",
            data={
                "artifact_ref": result.artifact_id,
                "lines": result.lines,
                "total_lines": result.total_lines,
                "returned_lines": result.returned_lines,
                "truncated": result.truncated,
                "query": result.query,
            },
        )
