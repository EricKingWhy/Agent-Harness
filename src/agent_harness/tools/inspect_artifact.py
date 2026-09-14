"""InspectArtifactTool：模型按需局部读取已溢出 Artifact 的 Coding Tool。

第 10 个 Coding Tool，但与其余 9 个不同：
- 操作的是 Runtime 域存储（ArtifactStore）而非 Sandbox 内的 Workspace；
- 构造注入 ArtifactStore（不是 Sandbox）；
- READ_ONLY 但不经 Sandbox 权限检查。

模型通过 artifact_ref（从 ToolResult 获得）按行局部读取大输出细节，
大 Artifact 永远不完整灌回 Context（spec 06 §4）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_harness.storage.artifact import ArtifactStore
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode


class _InspectArgs(BaseModel):
    artifact_id: str = Field(..., description="要读取的 artifact ID（从 ToolResult.artifact_ref 获得）")
    start_line: int | None = Field(default=None, ge=1, description="起始行号（1-based）")
    end_line: int | None = Field(default=None, ge=1, description="结束行（含）")
    keyword: str | None = Field(default=None, description="关键词过滤，只返回含此关键词的行")
    max_lines: int = Field(default=200, ge=1, le=1000, description="返回行数上限（默认 200，最大 1000）")
    max_chars_per_line: int = Field(
        default=2000, ge=1, le=20000,
        description="单行字符上限（默认 2000）。单行被截断时返回体携带 truncated 与 full_length，"
                    "可放宽本参数重新读取更长片段。",
    )


class InspectArtifactTool(Tool):
    """inspect_artifact：从 ArtifactStore 局部读取大输出的细节。"""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._store = artifact_store

    @property
    def name(self) -> str:
        return "inspect_artifact"

    @property
    def description(self) -> str:
        return (
            "读取之前被自动保存为 artifact 的大输出（如 bash 的长 stdout）的局部内容。"
            "参数：artifact_id（从工具结果的 artifact_ref 获得），"
            "start_line/end_line 按行范围读取，keyword 按关键词过滤，"
            "max_lines 返回行数上限（默认 200），"
            "max_chars_per_line 单行字符上限（默认 2000，单行超限时可放宽）。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _InspectArgs

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
            suggested_action="重新执行同样的 inspect_artifact 调用，核对返回的行内容是否一致（只读操作，重跑安全）。",
        )

    async def execute(self, args: _InspectArgs) -> ToolResult:
        try:
            result = await self._store.inspect(
                args.artifact_id,
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
            message=f"读取 artifact {args.artifact_id}：返回 {result.returned_lines} 行"
                    + ("（已截断）" if result.truncated else "")
                    + f"，共 {result.total_lines} 行。",
            data={
                "artifact_id": result.artifact_id,
                "lines": result.lines,
                "total_lines": result.total_lines,
                "returned_lines": result.returned_lines,
                "truncated": result.truncated,
                "query": result.query,
            },
        )
