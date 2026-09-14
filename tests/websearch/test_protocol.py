"""RetrievalProvider / WebSearchProvider / FakeWebSearchProvider 测试（T2, #77）。"""

from __future__ import annotations

import pytest

from agent_harness.websearch import (
    RetrievalHit,
    WebHit,
    WebSearchError,
    WebSearchProvider,
)
from agent_harness.websearch.fake import FakeWebSearchProvider


class TestProtocolShapes:
    def test_webhit_to_retrieval_hit(self):
        hit = WebHit(
            title="Python 文档", url="https://docs.python.org",
            snippet="Python 语言", score=0.9, raw_content="全文",
        )
        r = hit.to_retrieval_hit()
        assert r.citation == "web:https://docs.python.org"
        assert r.content == "Python 语言"
        assert r.score == 0.9
        assert r.metadata == {
            "url": "https://docs.python.org",
            "title": "Python 文档",
            "raw_content": "全文",
        }

    def test_webhit_default_raw_content_empty(self):
        hit = WebHit(title="t", url="u", snippet="s")
        assert hit.raw_content == ""

    def test_web_search_error_default_message(self):
        err = WebSearchError("timeout")
        assert err.category == "timeout"
        assert str(err) == "timeout"

    def test_web_search_error_custom_message(self):
        err = WebSearchError("authentication", "Tavily 401")
        assert err.category == "authentication"
        assert "Tavily 401" in str(err)

    def test_fake_is_web_search_provider(self):
        fake = FakeWebSearchProvider()
        assert isinstance(fake, WebSearchProvider)

    def test_retrieval_hit_is_frozen(self):
        import dataclasses

        r = RetrievalHit(citation="c", content="x", score=0.5)
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.citation = "other"  # type: ignore[misc]


class TestFakeWebSearchProvider:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        fake = FakeWebSearchProvider()
        hits = await fake.search("")
        assert hits == []

    @pytest.mark.asyncio
    async def test_substring_match_returns_hit(self):
        fake = FakeWebSearchProvider()
        hits = await fake.search("Python")
        assert len(hits) >= 1
        assert all(h.title for h in hits)
        assert all(h.url.startswith("http") for h in hits)

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        fake = FakeWebSearchProvider()
        hits = await fake.search("量子力学非定域性纠缠")
        assert hits == []

    @pytest.mark.asyncio
    async def test_k_limits_results(self):
        fake = FakeWebSearchProvider()
        hits = await fake.search("Python", k=1)
        assert len(hits) <= 1

    @pytest.mark.asyncio
    async def test_results_sorted_by_score_desc(self):
        # 多词 query 才能产生不同命中率（单词只能 0 或 1）。
        docs = [
            {"title": "弱匹配", "url": "https://a", "content": "python 文档"},
            {"title": "强匹配", "url": "https://b", "content": "python 编程 语言 文档 教程"},
        ]
        fake = FakeWebSearchProvider(docs)
        hits = await fake.search("python 语言 文档", k=5)
        assert len(hits) == 2
        assert hits[0].score >= hits[1].score
        assert hits[0].title == "强匹配"

    @pytest.mark.asyncio
    async def test_search_call_counter(self):
        fake = FakeWebSearchProvider()
        assert fake.search_calls == 0
        await fake.search("x")
        await fake.search("y")
        assert fake.search_calls == 2

    @pytest.mark.asyncio
    async def test_cjk_query_substring_match(self):
        docs = [{"title": "中文", "url": "https://c", "content": "知识库检索是核心能力"}]
        fake = FakeWebSearchProvider(docs)
        hits = await fake.search("知识库检索")
        assert len(hits) == 1

    @pytest.mark.asyncio
    async def test_custom_documents(self):
        docs = [{"title": "自定义", "url": "https://x", "content": "alpha beta"}]
        fake = FakeWebSearchProvider(docs)
        hits = await fake.search("alpha")
        assert len(hits) == 1
        assert hits[0].title == "自定义"
