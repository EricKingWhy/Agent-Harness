"""TavilyWebSearchProvider：手写 httpx 到 Tavily search API（ADR-0014 决策 9）。

零新依赖（httpx 已是 langchain-openai 传递依赖）。
错误分类同 MilvusKnowledgeVectorStore._call 风格：
- timeout / authentication / rate_limited / server_error / unavailable / unknown
- 脱敏不含请求参数（SDK 异常可能含敏感数据）。

Tavily API：POST https://api.tavily.com/search
- Header: Authorization: Bearer tvly-...
- Body: {query, max_results, search_depth, include_raw_content, topic}
- Response: {results: [{title, url, content, score, raw_content}], answer?}
- 无 locale（gl/hl）支持——静默忽略 + warning 日志。
"""

from __future__ import annotations

import logging

import httpx

from agent_harness.websearch.protocol import WebHit, WebSearchError

logger = logging.getLogger(__name__)

_TAVILY_ENDPOINT = "https://api.tavily.com/search"
#: 各错误分类的 HTTP 状态映射（同 Milvus _call 风格——分类在 adapter 内）。
_HTTP_STATUS_CATEGORY: dict[int, str] = {
    401: "authentication",
    403: "permission_denied",
    429: "rate_limited",
}
_SERVER_ERROR_RANGE = range(500, 600)


class TavilyWebSearchProvider:
    """Tavily 默认 WebSearchProvider 实现（手写 httpx，零 SDK 依赖）。"""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 30.0,
        search_depth: str = "basic",
        endpoint: str = _TAVILY_ENDPOINT,
    ) -> None:
        if not api_key.strip():
            raise WebSearchError("configuration", "Tavily API key 为空")
        self._api_key = api_key
        self._timeout = timeout
        self._search_depth = search_depth
        self._endpoint = endpoint

    async def search(
        self,
        query: str,
        *,
        k: int = 5,
        gl: str | None = None,
        hl: str | None = None,
        freshness: str | None = None,
    ) -> list[WebHit]:
        if gl is not None or hl is not None:
            logger.warning(
                "Tavily 不支持 locale 参数（gl=%r, hl=%r），已忽略", gl, hl,
            )
        if not query:
            return []
        body = {
            "query": query,
            "max_results": max(1, min(k, 20)),
            "search_depth": self._search_depth,
            "include_raw_content": True,
            "topic": "general",
        }
        # 真实时间过滤：Tavily 原生 time_range 枚举（day/week/month/year）与
        # 工具层 recency 语义一一对应——不是 query 文本拼接（那只是提示词，
        # 过滤不了结果）。
        if freshness:
            body["time_range"] = freshness
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._endpoint, json=body, headers=headers,
                )
        except httpx.TimeoutException:
            raise WebSearchError("timeout") from None
        except httpx.ConnectError:
            raise WebSearchError("unavailable", "Tavily 连接失败") from None
        except httpx.HTTPError as error:
            # 其它 httpx 错误（ProtocolError 等）归类为不可用。
            raise WebSearchError("unavailable", str(error)) from None

        if response.status_code != 200:
            category = _HTTP_STATUS_CATEGORY.get(response.status_code)
            if category is None:
                if response.status_code in _SERVER_ERROR_RANGE:
                    category = "server_error"
                else:
                    category = "unknown"
            # 错误响应体可能含请求参数——不暴露原文，只带分类。
            raise WebSearchError(category, f"HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError:
            raise WebSearchError("unknown", "Tavily 响应非 JSON") from None

        results = data.get("results", [])
        hits: list[WebHit] = []
        for item in results:
            url = item.get("url", "")
            if not url:
                continue
            hits.append(
                WebHit(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                    raw_content=item.get("raw_content", "") or "",
                )
            )
        return hits
