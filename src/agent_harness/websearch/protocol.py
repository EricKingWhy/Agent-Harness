"""统一检索协议 + Web Search 域专用协议（ADR-0014 决策 7-10）。

RetrievalProvider 是 Knowledge 与 Web 共享的窄协议：
- 只含 search；KB 额外保留 chunk 生命周期方法（不污染通用契约）。
- 替换 provider = 替换策略类；调用方不感知底层（不变量：加搜索方式只加策略类）。

WebSearchProvider 继承窄协议；WebHit 是 Web 域返回形状。
错误统一 WebSearchError(category)——脱敏不含请求参数（同 MilvusKnowledgeVectorStore）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RetrievalHit:
    """统一检索证据：citation 可追溯，content 是模型可见摘要，metadata 域特定。

    - KB 域 metadata: {source_id, chunk_index}（source 名已含于 citation
      `kb:<name>#<index>`，不重复携带）
    - Web 域 metadata: {url, title, raw_content?}
    """

    citation: str
    content: str
    score: float
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class RetrievalProvider(Protocol):
    """Knowledge 与 Web 共享的窄检索协议。"""

    async def search(
        self,
        query: str,
        *,
        k: int = 5,
        gl: str | None = None,
        hl: str | None = None,
        freshness: str | None = None,
    ) -> list[RetrievalHit]: ...


@dataclass(frozen=True)
class WebHit:
    """Web 搜索单条结果（adapter 内部形状；转成 RetrievalHit 对外）。

    snippet = 最佳可用摘要（Tavily content / Serper snippet / Brave description）。
    raw_content 可选全文（默认空串 = provider 未给）。
    """

    title: str
    url: str
    snippet: str
    score: float = 0.0
    raw_content: str = ""

    def to_retrieval_hit(self) -> RetrievalHit:
        """转成统一 RetrievalHit——citation = web:<url>（ADR-0014 决策 12）。"""
        return RetrievalHit(
            citation=f"web:{self.url}",
            content=self.snippet,
            score=self.score,
            metadata={"url": self.url, "title": self.title, "raw_content": self.raw_content},
        )


class WebSearchError(Exception):
    """Web Search adapter 显式错误（脱敏分类，不含请求参数）。"""

    def __init__(self, category: str, message: str = "") -> None:
        self.category = category
        super().__init__(message or category)


@runtime_checkable
class WebSearchProvider(Protocol):
    """Web 域专用协议：实现 RetrievalProvider.search，返回 WebHit 列表。

    adapter 各自处理 HTTP verb / auth / locale 映射；调用方不感知。
    """

    async def search(
        self,
        query: str,
        *,
        k: int = 5,
        gl: str | None = None,
        hl: str | None = None,
        freshness: str | None = None,
    ) -> list[WebHit]: ...
