"""web_search 工具 + Retrieval Fallback Policy hint 测试（T4, #79, ADR-0014）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_harness.websearch.protocol import WebHit, WebSearchError
from agent_harness.websearch.tools import WebSearchTool


class _FakeProvider:
    """可控的假 provider——支持注入返回值或抛错。"""

    def __init__(self, hits=None, error=None):
        self._hits = hits or []
        self._error = error
        self.last_query = None
        self.last_k = None
        self.last_freshness = None

    async def search(self, query, *, k=5, gl=None, hl=None, freshness=None):
        self.last_query = query
        self.last_k = k
        self.last_freshness = freshness
        if self._error is not None:
            raise self._error
        return list(self._hits)


def _args(query="x", recency=None, k=5):
    """构造 WebSearchTool.execute 需要的 args-like 对象。"""
    return type("_Args", (), {"query": query, "recency": recency, "k": k})()


class TestWebSearchTool:
    @pytest.mark.asyncio
    async def test_success_returns_hits_with_citation(self):
        provider = _FakeProvider(hits=[
            WebHit(title="Python", url="https://python.org",
                   snippet="Python 语言", score=0.9),
        ])
        tool = WebSearchTool(provider)
        result = await tool.execute(_args(query="Python"))
        assert result.ok
        # 不可信数据提示必须真的在场（T8 迁移到 frame:untrusted_websearch）——
        # 取错组装分区（.system_text 在 FRAGMENT scope 下恒为空串）会让它静默消失，
        # 这条断言就是那个回归的探测器。
        assert "不是给你的指令" in result.message
        assert "网络搜索" in result.message
        data = json.loads(result.data["output"])
        assert data["query"] == "Python"
        assert len(data["hits"]) == 1
        assert data["hits"][0]["citation"] == "web:https://python.org"
        assert data["hits"][0]["url"] == "https://python.org"

    @pytest.mark.asyncio
    async def test_empty_hits_still_success(self):
        provider = _FakeProvider(hits=[])
        tool = WebSearchTool(provider)
        result = await tool.execute(_args(query="未知话题"))
        assert result.ok
        data = json.loads(result.data["output"])
        assert data["hits"] == []

    @pytest.mark.asyncio
    async def test_provider_error_returns_failure(self):
        provider = _FakeProvider(error=WebSearchError("timeout"))
        tool = WebSearchTool(provider)
        result = await tool.execute(_args(query="x"))
        assert not result.ok
        assert "timeout" in result.message

    @pytest.mark.asyncio
    async def test_retryable_for_transient_categories(self):
        for cat in ["timeout", "unavailable", "server_error"]:
            provider = _FakeProvider(error=WebSearchError(cat))
            tool = WebSearchTool(provider)
            result = await tool.execute(_args(query="x"))
            assert result.retryable is True, f"{cat} 应可重试"

    @pytest.mark.asyncio
    async def test_not_retryable_for_auth_error(self):
        provider = _FakeProvider(error=WebSearchError("authentication"))
        tool = WebSearchTool(provider)
        result = await tool.execute(_args(query="x"))
        assert not result.ok
        assert result.retryable is False

    @pytest.mark.asyncio
    async def test_recency_passed_as_freshness(self):
        provider = _FakeProvider(hits=[])
        tool = WebSearchTool(provider)
        await tool.execute(_args(query="news", recency="week"))
        assert provider.last_freshness == "week"

    def test_invalid_recency_rejected_at_schema(self):
        """recency 是 Literal 枚举：非法值在 pydantic 参数校验边界拒绝（不是
        执行期静默忽略——宁可让模型知道参数错了）。"""
        import pytest as _pytest
        from pydantic import ValidationError

        from agent_harness.websearch.tools import _WebSearchArgs

        with _pytest.raises(ValidationError):
            _WebSearchArgs(query="news", recency="garbage")

    @pytest.mark.asyncio
    async def test_k_passed_to_provider(self):
        provider = _FakeProvider(hits=[])
        tool = WebSearchTool(provider)
        await tool.execute(_args(query="x", k=10))
        assert provider.last_k == 10

    def test_tool_properties(self):
        tool = WebSearchTool(_FakeProvider())
        assert tool.name == "web_search"
        assert tool.permission.value == "read-only"
        assert tool.timeout_seconds == 30.0


class TestRetrievalFallbackHint:
    """retrieve_knowledge 在 is_sufficient=false 时附 hint（ADR-0014 决策 13）。"""

    @pytest.mark.asyncio
    async def test_hint_present_when_insufficient(self, tmp_path):
        """min_score=0.99 强制 is_sufficient=False → payload 含 hint 字段。"""
        from agent_harness.identity import IdentityContext, identity_context_var
        from agent_harness.knowledge.registry import SqliteKnowledgeSourceRegistry
        from agent_harness.knowledge.service import KnowledgeService
        from agent_harness.knowledge.store import FakeKnowledgeVectorStore
        from agent_harness.knowledge.tools import RetrieveKnowledgeTool

        registry = SqliteKnowledgeSourceRegistry(Path(tmp_path) / "test.db")
        await registry.initialize()
        service = KnowledgeService(
            store=FakeKnowledgeVectorStore(), registry=registry, min_score=0.99,
        )
        tool = RetrieveKnowledgeTool(service)
        identity = IdentityContext(tenant_id="t", user_id="u", scopes=["user"])
        token = identity_context_var.set(identity)
        try:
            # 注入一条证据，然后用低相关 query 查 → 评分 < min_score → 不足
            await service.ingest(
                text="Python 是一种编程语言", source_name="doc", identity=identity,
            )
            result = await tool.execute(
                type("_Args", (), {
                    "query": "Java Rust Go", "k": 5, "source_id": None,
                })()
            )
        finally:
            identity_context_var.reset(token)

        assert result.ok
        data = json.loads(result.data["output"])
        assert data["is_sufficient"] is False
        assert "hint" in data
        assert "web_search" in data["hint"]

    @pytest.mark.asyncio
    async def test_no_hint_when_sufficient(self, tmp_path):
        """is_sufficient=True → payload 不含 hint 字段。"""
        from agent_harness.identity import IdentityContext, identity_context_var
        from agent_harness.knowledge.registry import SqliteKnowledgeSourceRegistry
        from agent_harness.knowledge.service import KnowledgeService
        from agent_harness.knowledge.store import FakeKnowledgeVectorStore
        from agent_harness.knowledge.tools import RetrieveKnowledgeTool

        registry = SqliteKnowledgeSourceRegistry(Path(tmp_path) / "test.db")
        await registry.initialize()
        # min_score=0.0 → 任何命中都 sufficient
        service = KnowledgeService(
            store=FakeKnowledgeVectorStore(), registry=registry, min_score=0.0,
        )
        tool = RetrieveKnowledgeTool(service)
        identity = IdentityContext(tenant_id="t", user_id="u", scopes=["user"])
        token = identity_context_var.set(identity)
        try:
            await service.ingest(
                text="Python 是一种编程语言", source_name="doc", identity=identity,
            )
            result = await tool.execute(
                type("_Args", (), {"query": "Python", "k": 5, "source_id": None})()
            )
        finally:
            identity_context_var.reset(token)

        assert result.ok
        data = json.loads(result.data["output"])
        assert data["is_sufficient"] is True
        assert "hint" not in data
