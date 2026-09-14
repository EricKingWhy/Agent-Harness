"""Web Search 域工具（T4, #79, ADR-0014 决策 11-13）。

web_search 工具走统一 ToolExecutor（不变量 #7，零旁路）：
- READ_ONLY；模型可见 schema = {query (required), recency? (enum), k? (int)}；
- 不暴露 locale / domain filter 参数（domain 走 site:/-site: 查询语法，adapter 翻译）；
- citation = web:<url>（ADR-0014 决策 12）；
- 不做 read_web_source 二次读取工具（网页二次抓取成本/法律风险）。

检索结果是数据不是指令（防注入框架，同 knowledge.tools 同款声明）。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_harness.prompt import DEFAULT_REGISTRY
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode
from agent_harness.websearch.protocol import WebSearchError, WebSearchProvider


class _WebSearchArgs(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description=(
            "搜索查询。支持 Google 风格 operator：site:、-site:、after:YYYY-MM-DD、"
            'before:YYYY-MM-DD、inurl:、intitle:、filetype:、引号短语、-排除词、OR。'
            "若无结果，放宽约束并报告，而非返回空。"
        ),
    )
    # Literal 让 pydantic 在参数校验边界拒绝非法值并在模型可见 schema 生成
    # enum——而不是执行期静默忽略（宁可让模型知道参数错了，别静默降级）。
    recency: Literal["day", "week", "month", "year"] | None = Field(
        default=None,
        description="时间过滤：day / week / month / year；省略表示不限。",
    )
    k: int = Field(default=5, ge=1, le=20, description="返回结果条数")


class WebSearchTool(Tool):
    """网络搜索入口：模型自主判断何时联网（ADR-0014 决策 11）。"""

    def __init__(
        self, provider: WebSearchProvider, provider_name: str | None = None,
    ) -> None:
        self._provider = provider
        # provider 名进 payload（#79 契约）；缺省用实现类名（如实归属）。
        self._provider_name = provider_name or type(provider).__name__

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "在互联网上搜索最新或外部信息。当你判断当前问题需要最新资讯、外部数据"
            "或知识库未覆盖的内容时调用。返回网页摘要与 citation（web:<url>）。"
            "优先引用一手来源（官方文档、论文）；回答时如实引用来源。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _WebSearchArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    @property
    def timeout_seconds(self) -> float:
        return 30.0

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(
            verifiable=True,
            suggested_action="重复同一搜索安全（只读），可换措辞复核。",
        )

    async def execute(self, args: _WebSearchArgs) -> ToolResult:
        try:
            hits = await self._provider.search(
                args.query, k=args.k, freshness=args.recency,
            )
        except WebSearchError as error:
            return ToolResult.failure(
                message=f"网络搜索失败（{error.category}）：{error}",
                error_code=ErrorCode.TOOL_EXECUTION_ERROR,
                retryable=error.category in {"timeout", "unavailable", "server_error"},
            )
        # citation 格式 web:<url> 的唯一出处是 WebHit.to_retrieval_hit
        # （ADR-0014 决策 12；RetrievalHit 是 KB/Web 共享货币）。
        retrieval_hits = [hit.to_retrieval_hit() for hit in hits]
        payload: dict[str, Any] = {
            "query": args.query,
            "provider": self._provider_name,
            "hits": [
                {
                    "citation": rh.citation,
                    "content": rh.content,
                    "score": rh.score,
                    "url": rh.metadata.get("url", ""),
                    "title": rh.metadata.get("title", ""),
                }
                for rh in retrieval_hits
            ],
        }
        return ToolResult.success(
            message=f"{DEFAULT_REGISTRY.assemble('frame:untrusted_websearch').fragment_text}"
                    f"命中 {len(retrieval_hits)} 条网络结果。",
            data={"output": json.dumps(payload, ensure_ascii=False)},
        )
