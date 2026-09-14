"""MilvusKnowledgeVectorStore 的 SDK seam 测试（Phase 11 T2，mock-client 模式）。

CI 零外部依赖：AsyncMilvusClient 打桩；真实 Zilliz Gate 归 T6。
"""

from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.embeddings import Embeddings

from agent_harness.config import Settings
from agent_harness.identity import IdentityContext
from agent_harness.knowledge.milvus_store import MilvusKnowledgeVectorStore
from agent_harness.knowledge.types import KnowledgeChunk, KnowledgeError

ALICE = IdentityContext("acme", "alice", ["user"])


class KnownEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[0.0, 1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


def _settings(**overrides) -> Settings:
    values = {"milvus_uri": "https://example.test", "milvus_token": "test-only",
              "knowledge_collection": "knowledge_gate_test"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _store(monkeypatch, settings=None) -> tuple[MilvusKnowledgeVectorStore, Mock]:
    sdk = pytest.importorskip("pymilvus")
    client = Mock()
    client.list_collections = AsyncMock(return_value=[])
    client.describe_collection = AsyncMock(return_value={"fields": []})
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    client.search = AsyncMock(return_value=[[
        {"id": "s1:0", "distance": 0.92,
         "entity": {"source_id": "s1", "source_name": "guide", "chunk_index": 0,
                    "content_hash": "h0", "content": "python typing"}},
    ]])
    client.query = AsyncMock(return_value=[
        {"source_id": "s1", "source_name": "guide", "chunk_index": 1,
         "content_hash": "h1", "content": "chunk one"},
    ])
    client.delete = AsyncMock(return_value=Mock(delete_count=3))
    client.close = AsyncMock()
    client.create_schema = sdk.MilvusClient.create_schema
    client.prepare_index_params = sdk.MilvusClient.prepare_index_params
    monkeypatch.setattr("pymilvus.AsyncMilvusClient", Mock(return_value=client))
    store = MilvusKnowledgeVectorStore(settings or _settings(), KnownEmbeddings())
    return store, client


def _chunk(index: int = 0) -> KnowledgeChunk:
    return KnowledgeChunk(source_id="s1", source_name="guide", chunk_index=index,
                          content_hash="h", content="python typing 内容")


@pytest.mark.asyncio
async def test_initialize_creates_collection_with_dimension_and_partition(monkeypatch):
    store, client = _store(monkeypatch)
    assert await store.connect() == []
    await store.initialize()
    assert store.dimension == 3
    schema = client.create_collection.call_args.kwargs["schema"].to_dict()
    assert next(f for f in schema["fields"] if f["name"] == "vector")["params"]["dim"] == 3
    assert next(f for f in schema["fields"] if f["name"] == "tenant_id")["is_partition_key"]
    assert store.created_collection is True


@pytest.mark.asyncio
async def test_upsert_chunks_writes_tenant_and_deterministic_ids(monkeypatch):
    store, client = _store(monkeypatch)
    await store.initialize()
    await store.upsert_chunks([_chunk(0), _chunk(1)], ALICE)
    rows = client.upsert.call_args.kwargs["data"]
    assert [row["id"] for row in rows] == ["s1:0", "s1:1"]
    assert rows[0]["tenant_id"] == "acme"
    assert rows[0]["vector"] == [0.0, 1.0, 0.0]
    assert rows[0]["content_hash"] == "h"


@pytest.mark.asyncio
async def test_search_returns_chunks_with_scores_and_filter(monkeypatch):
    store, client = _store(monkeypatch)
    await store.initialize()
    hits = await store.search("python", ALICE, limit=5, source_id="s1")
    (chunk, score), = hits
    assert isinstance(chunk, KnowledgeChunk)
    assert chunk.source_id == "s1" and chunk.chunk_index == 0
    assert score == pytest.approx(0.92)
    kwargs = client.search.call_args.kwargs
    assert kwargs["filter_params"]["tenant"] == "acme"
    assert "source_id == {source}" in kwargs["filter"]
    assert kwargs["filter_params"]["source"] == "s1"
    assert kwargs["limit"] == 5


@pytest.mark.asyncio
async def test_get_chunk_queries_by_index_and_delete_uses_tenant_filter(monkeypatch):
    store, client = _store(monkeypatch)
    await store.initialize()
    chunk = await store.get_chunk("s1", 1, ALICE)
    assert chunk is not None and chunk.chunk_index == 1
    params = client.query.call_args.kwargs["filter_params"]
    assert params == {"tenant": "acme", "source": "s1", "index": 1}

    removed = await store.delete_source("s1", ALICE)
    assert removed == 3
    delete_params = client.delete.call_args.kwargs["filter_params"]
    assert delete_params == {"tenant": "acme", "source": "s1"}


@pytest.mark.asyncio
async def test_schema_mismatch_is_rejected(monkeypatch):
    store, client = _store(monkeypatch)
    client.list_collections = AsyncMock(return_value=["knowledge_gate_test"])
    client.describe_collection = AsyncMock(return_value={"fields": [
        {"name": "id", "type": "VarChar"},
        {"name": "vector", "params": {"dim": 3}},
        # tenant_id 非 partition key → 拒绝
    ]})
    await store.connect()
    with pytest.raises(KnowledgeError, match="schema"):
        await store.initialize()


@pytest.mark.asyncio
async def test_sdk_error_does_not_leak_token(monkeypatch):
    sdk = pytest.importorskip("pymilvus")
    client = Mock(list_collections=AsyncMock(
        side_effect=sdk.MilvusException(code=1800, message="credential-secret")))
    monkeypatch.setattr("pymilvus.AsyncMilvusClient", Mock(return_value=client))
    store = MilvusKnowledgeVectorStore(_settings(), KnownEmbeddings())
    with pytest.raises(KnowledgeError) as error:
        await store.connect()
    assert "authentication" in str(error.value)
    assert "credential-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_missing_configuration_fails_loud():
    with pytest.raises(KnowledgeError, match="MILVUS_URI"):
        MilvusKnowledgeVectorStore(Settings(_env_file=None, knowledge_collection="k"))
    with pytest.raises(KnowledgeError, match="KNOWLEDGE_COLLECTION"):
        MilvusKnowledgeVectorStore(Settings(
            _env_file=None, milvus_uri="https://example.test",
            milvus_token="tok", ))
