"""FakeWebSearchProvider：进程内确定性实现（CI 零网络依赖）。

同 Knowledge 域 FakeKnowledgeVectorStore 风格：
- 预置文档按 substring 命中评分（CJK 安全）；
- 返回 WebHit（snippet = 命中段落），无 raw_content；
- 测试可注入自定义语料；默认带几条 demo 文档。
"""

from __future__ import annotations

from agent_harness.websearch.protocol import WebHit


class FakeWebSearchProvider:
    """确定性 substring 命中评分的假 Web 搜索（实现 WebSearchProvider）。"""

    def __init__(self, documents: list[dict] | None = None) -> None:
        # 每条文档：{"title": str, "url": str, "content": str}
        self._documents = documents if documents is not None else _default_documents()
        self.search_calls = 0

    async def search(
        self,
        query: str,
        *,
        k: int = 5,
        gl: str | None = None,
        hl: str | None = None,
        freshness: str | None = None,
    ) -> list[WebHit]:
        self.search_calls += 1
        if not query:
            return []
        scored: list[tuple[dict, float]] = []
        for doc in self._documents:
            score = _score(query, doc["content"])
            if score > 0:
                scored.append((doc, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            WebHit(
                title=doc["title"],
                url=doc["url"],
                snippet=doc["content"],
                score=score,
            )
            for doc, score in scored[: max(0, k)]
        ]


def _score(query: str, content: str) -> float:
    """query 词项在 content 中的子串命中率（0..1，同 FakeKnowledgeVectorStore）。"""
    query_terms = query.split()
    if not query_terms:
        return 0.0
    return sum(1 for term in query_terms if term in content) / len(query_terms)


def _default_documents() -> list[dict]:
    return [
        {
            "title": "Python 官方文档",
            "url": "https://docs.python.org/3/",
            "content": "Python 是一种流行的高级编程语言，强调可读性与简洁语法。",
        },
        {
            "title": "FastAPI 文档",
            "url": "https://fastapi.tiangolo.com/",
            "content": "FastAPI 是一个现代、快速的 Python Web 框架，基于标准类型提示。",
        },
        {
            "title": "Milvus 向量数据库",
            "url": "https://milvus.io/",
            "content": "Milvus 是开源的云原生向量数据库，专为相似度搜索设计。",
        },
    ]
