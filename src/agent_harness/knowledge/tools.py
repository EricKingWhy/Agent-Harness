"""Knowledge 域工具（T3/T4，ADR-0013 决策 2/6/9/10/11）。

全部走统一 ToolExecutor（不变量 #7，零旁路）：retrieve/read 为 READ_ONLY，
ingest 为 MUTATING / WORKSPACE_WRITE（写语料等同写工作区产物）。检索结果是
数据不是指令（防注入框架，load_skill 同款声明）；块大小由切分器保证
（≤ chunk_size），输出天然有界，无需额外截断层。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_harness.identity import IdentityContext, get_identity_context
from agent_harness.knowledge.service import KnowledgeService
from agent_harness.knowledge.types import KnowledgeError
from agent_harness.memory.types import memory_session_var
from agent_harness.prompt import DEFAULT_REGISTRY
from agent_harness.sandbox import Sandbox, WorkspaceRegistry
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode


def _failure(error: KnowledgeError) -> ToolResult:
    return ToolResult.failure(
        message=str(error), error_code=ErrorCode.TOOL_EXECUTION_ERROR,
        retryable=False,
    )


def _identity() -> IdentityContext:
    return get_identity_context()


class _RetrieveArgs(BaseModel):
    query: str = Field(..., min_length=1, description="检索查询文本")
    k: int = Field(default=5, ge=1, le=20, description="返回的证据条数")
    source_id: str | None = Field(default=None, description="限定只在某个 source 内检索")


class RetrieveKnowledgeTool(Tool):
    """Agentic RAG 入口：模型自主判断何时检索知识语料（ADR-0013 决策 2）。"""

    def __init__(self, service: KnowledgeService) -> None:
        self._service = service

    @property
    def name(self) -> str:
        return "retrieve_knowledge"

    @property
    def description(self) -> str:
        return (
            "在知识语料库中检索文档证据（Agentic RAG：当你判断当前问题需要语料"
            "证据时才调用）。返回命中片段（含 citation 引用与相关分）与 "
            "is_sufficient 标记；is_sufficient=false 表示证据不足，回答时必须"
            "如实说明。用 read_knowledge_source 可按 citation 回读原文上下文。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _RetrieveArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    @property
    def timeout_seconds(self) -> float:
        return 15.0

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(
            verifiable=True,
            suggested_action="重复同一检索安全（只读），可换措辞复核证据。",
        )

    async def execute(self, args: _RetrieveArgs) -> ToolResult:
        try:
            result = await self._service.retrieve(
                query=args.query, identity=_identity(), k=args.k,
                source_id=args.source_id,
            )
        except KnowledgeError as error:
            return _failure(error)
        payload: dict[str, Any] = {
            "query": result.query,
            "is_sufficient": result.is_sufficient,
            "hits": [
                {"citation": hit.citation, "content": hit.content, "score": hit.score}
                for hit in result.hits
            ],
        }
        # Retrieval Fallback Policy（ADR-0014 决策 13）：证据不足时附 tool 侧
        # affordance——引导模型可调 web_search，但决策仍由模型做出（agentic）。
        # 这是 spec §8 的「轻量 Retrieval Fallback Policy」，非 Agent Loop 特判。
        if not result.is_sufficient:
            payload["hint"] = (
                "知识库证据不足，如需最新或外部信息可调用 web_search 工具。"
            )
        return ToolResult.success(
            message=f"{DEFAULT_REGISTRY.assemble('frame:untrusted_knowledge').fragment_text}"
                    f"命中 {len(result.hits)} 条，"
                    f"证据充分性：{'充分' if result.is_sufficient else '不足'}。",
            data={"output": json.dumps(payload, ensure_ascii=False)},
        )


class _ReadSourceArgs(BaseModel):
    citation: str = Field(..., description="检索结果返回的引用，形如 kb:<source>#<index>")
    with_context: bool = Field(default=False, description="附带前后各 1 chunk 的上下文")


class ReadKnowledgeSourceTool(Tool):
    def __init__(self, service: KnowledgeService) -> None:
        self._service = service

    @property
    def name(self) -> str:
        return "read_knowledge_source"

    @property
    def description(self) -> str:
        return (
            "按 citation 回读知识语料的原文 chunk（with_context=true 时附带前后"
            "各 1 块）。用于检索证据需要更多上下文时核实原文。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _ReadSourceArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    @property
    def timeout_seconds(self) -> float:
        return 15.0

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(
            verifiable=True,
            suggested_action="重复同一回读安全（只读）。",
        )

    async def execute(self, args: _ReadSourceArgs) -> ToolResult:
        try:
            result = await self._service.read_source(
                citation=args.citation, identity=_identity(),
                with_context=args.with_context,
            )
        except KnowledgeError as error:
            return _failure(error)
        payload = {
            "citation": args.citation,
            "match": {"content": result.match.content,
                      "chunk_index": result.match.chunk_index},
            "context": [{"chunk_index": c.chunk_index, "content": c.content}
                        for c in result.context],
        }
        return ToolResult.success(
            message=f"{DEFAULT_REGISTRY.assemble('frame:untrusted_knowledge').fragment_text}"
                    f"已回读 {result.source_name} 的原文块。",
            data={"output": json.dumps(payload, ensure_ascii=False)},
        )


class _IngestArgs(BaseModel):
    path: str | None = Field(default=None, description="workspace 内的文件相对路径")
    text: str | None = Field(default=None, description="直接摄入的文本内容")
    source_name: str | None = Field(
        default=None,
        description="语料来源名（citation 用）；path 模式缺省取文件名，text 模式必填",
    )


class IngestDocumentTool(Tool):
    """把文档收进知识语料库（ADR-0013 决策 6）：MUTATING，写语料 = 写产物。

    capability 工具是进程级的，而 sandbox 是每会话的：执行时经
    memory_session_var（runtime 会话帧内已绑定）从 WorkspaceRegistry 解析
    当前会话的 sandbox——路径边界仍由 sandbox 强制，不因注入方式改变。
    """

    def __init__(
        self, service: KnowledgeService, workspace_registry: WorkspaceRegistry,
    ) -> None:
        self._service = service
        self._workspace_registry = workspace_registry

    @property
    def name(self) -> str:
        return "ingest_document"

    @property
    def description(self) -> str:
        return (
            "把文档收进知识语料库供日后检索。两种输入二选一：path = workspace 内"
            "文件相对路径（推荐），或 text = 直接给出文本内容（此时 source_name "
            "必填）。仅支持 UTF-8 文本类文件；同名重复摄入时内容未变自动跳过、"
            "变更自动整篇重建。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _IngestArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.MUTATING

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.WORKSPACE_WRITE

    @property
    def timeout_seconds(self) -> float:
        return 30.0

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(verifiable=False)

    def _session_sandbox(self) -> Sandbox:
        session_id = memory_session_var.get()
        if not session_id:
            raise KnowledgeError(
                "ingest_document 只能在会话内使用（未找到当前会话）"
            )
        return self._workspace_registry.get(session_id)

    async def execute(self, args: _IngestArgs) -> ToolResult:
        if (args.path is None) == (args.text is None):
            return ToolResult.failure(
                message="path 与 text 必须二选一。",
                error_code=ErrorCode.INVALID_ARGUMENT,
            )
        try:
            if args.path is not None:
                content = self._session_sandbox().read_text(args.path)
                source_name = args.source_name or Path(args.path).name
            else:
                content = args.text or ""
                source_name = args.source_name
                if not source_name:
                    return ToolResult.failure(
                        message="text 模式必须提供 source_name。",
                        error_code=ErrorCode.INVALID_ARGUMENT,
                    )
            if "\x00" in content:
                return ToolResult.failure(
                    message="检测到二进制内容：知识语料 V1 仅支持 UTF-8 文本。",
                    error_code=ErrorCode.INVALID_ARGUMENT,
                )
            result = await self._service.ingest(
                text=content, source_name=source_name, identity=_identity(),
            )
        except PermissionError as error:
            return ToolResult.failure(
                message=str(error), error_code=ErrorCode.PERMISSION_DENIED,
            )
        except KnowledgeError as error:
            return _failure(error)
        return ToolResult.success(
            message=f"语料 '{result.source_name}' {result.status}："
                    f"{result.chunk_count} 个 chunk 已入索引。",
            data={"source_id": result.source_id, "source_name": result.source_name,
                  "chunk_count": result.chunk_count, "status": result.status},
        )
