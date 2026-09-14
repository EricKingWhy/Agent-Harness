"""TavilyWebSearchProvider 单元测试（T3, #78, ADR-0014）。

用 httpx.MockTransport 拦截请求——零网络依赖、零新依赖。
覆盖：成功、各错误分类、locale 忽略、空 query、降级缺席（空 key）。
"""

from __future__ import annotations

import json

import httpx
import pytest

from agent_harness.websearch.protocol import WebHit, WebSearchError
from agent_harness.websearch.tavily import TavilyWebSearchProvider


def _mock_transport(handler):
    """构造 httpx.MockTransport，让 provider 用它替代真实 AsyncClient。"""
    return httpx.MockTransport(handler)


def _make_provider(
    handler, api_key: str = "tvly-test-key", **kwargs,
) -> TavilyWebSearchProvider:
    """构造 provider 并注入 mock transport（monkey-patch AsyncClient）。"""
    transport = _mock_transport(handler)
    provider = TavilyWebSearchProvider(api_key=api_key, **kwargs)

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kw):
        kw["transport"] = transport
        original_init(self, *args, **kw)

    httpx.AsyncClient.__init__ = patched_init
    return provider, lambda: setattr(httpx.AsyncClient, "__init__", original_init)


class TestTavilyProvider:
    @pytest.mark.asyncio
    async def test_success_returns_webhits(self):
        def handler(request: httpx.Request):
            body = json.loads(request.content)
            assert body["query"] == "Python"
            assert body["max_results"] == 3
            return httpx.Response(200, json={
                "results": [
                    {"title": "Python", "url": "https://python.org",
                     "content": "Python 语言", "score": 0.9, "raw_content": "full text"},
                    {"title": "Docs", "url": "https://docs.python.org",
                     "content": "文档", "score": 0.7},
                ],
            })

        provider, restore = _make_provider(handler)
        try:
            hits = await provider.search("Python", k=3)
        finally:
            restore()
        assert len(hits) == 2
        assert isinstance(hits[0], WebHit)
        assert hits[0].title == "Python"
        assert hits[0].url == "https://python.org"
        assert hits[0].score == 0.9
        assert hits[0].raw_content == "full text"
        # 第二条无 raw_content → 空串
        assert hits[1].raw_content == ""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        provider = TavilyWebSearchProvider(api_key="k")
        hits = await provider.search("")
        assert hits == []

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_category(self):
        def handler(request):
            raise httpx.TimeoutException("timed out")

        provider, restore = _make_provider(handler)
        try:
            with pytest.raises(WebSearchError) as exc:
                await provider.search("x")
        finally:
            restore()
        assert exc.value.category == "timeout"

    @pytest.mark.asyncio
    async def test_connect_error_raises_unavailable(self):
        def handler(request):
            raise httpx.ConnectError("no route")

        provider, restore = _make_provider(handler)
        try:
            with pytest.raises(WebSearchError) as exc:
                await provider.search("x")
        finally:
            restore()
        assert exc.value.category == "unavailable"

    @pytest.mark.asyncio
    async def test_401_raises_authentication(self):
        def handler(request):
            return httpx.Response(401, json={"detail": "invalid key"})

        provider, restore = _make_provider(handler)
        try:
            with pytest.raises(WebSearchError) as exc:
                await provider.search("x")
        finally:
            restore()
        assert exc.value.category == "authentication"
        # 不暴露原始响应体
        assert "invalid key" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_429_raises_rate_limited(self):
        def handler(request):
            return httpx.Response(429)

        provider, restore = _make_provider(handler)
        try:
            with pytest.raises(WebSearchError) as exc:
                await provider.search("x")
        finally:
            restore()
        assert exc.value.category == "rate_limited"

    @pytest.mark.asyncio
    async def test_500_raises_server_error(self):
        def handler(request):
            return httpx.Response(500, text="internal error")

        provider, restore = _make_provider(handler)
        try:
            with pytest.raises(WebSearchError) as exc:
                await provider.search("x")
        finally:
            restore()
        assert exc.value.category == "server_error"

    @pytest.mark.asyncio
    async def test_418_raises_unknown(self):
        def handler(request):
            return httpx.Response(418, text="I'm a teapot")

        provider, restore = _make_provider(handler)
        try:
            with pytest.raises(WebSearchError) as exc:
                await provider.search("x")
        finally:
            restore()
        assert exc.value.category == "unknown"

    @pytest.mark.asyncio
    async def test_non_json_response_raises_unknown(self):
        def handler(request):
            return httpx.Response(200, text="<html>not json</html>")

        provider, restore = _make_provider(handler)
        try:
            with pytest.raises(WebSearchError) as exc:
                await provider.search("x")
        finally:
            restore()
        assert exc.value.category == "unknown"

    @pytest.mark.asyncio
    async def test_locale_params_ignored_with_warning(self, caplog):
        # 不发真实请求——_make_provider 已用 MockTransport 注入 handler。
        # locale 警告只在非空 query 时触发（空 query 先返回了）。
        with caplog.at_level("WARNING", logger="agent_harness.websearch.tavily"):
            def handler(request):
                return httpx.Response(200, json={"results": []})
            p, restore = _make_provider(handler)
            try:
                await p.search("x", gl="us", hl="en")
            finally:
                restore()
        assert any("locale" in rec.message.lower() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_results_without_url_skipped(self):
        def handler(request):
            return httpx.Response(200, json={
                "results": [
                    {"title": "ok", "url": "https://x", "content": "c"},
                    {"title": "no-url", "content": "c"},  # 无 url 跳过
                ],
            })

        provider, restore = _make_provider(handler)
        try:
            hits = await provider.search("x")
        finally:
            restore()
        assert len(hits) == 1
        assert hits[0].url == "https://x"

    def test_empty_api_key_raises_configuration(self):
        with pytest.raises(WebSearchError) as exc:
            TavilyWebSearchProvider(api_key="")
        assert exc.value.category == "configuration"

    def test_whitespace_api_key_raises_configuration(self):
        with pytest.raises(WebSearchError) as exc:
            TavilyWebSearchProvider(api_key="   ")
        assert exc.value.category == "configuration"
