"""SDK seam：schema、namespace filter、ID 映射及脱敏错误。"""

from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.embeddings import Embeddings

from agent_harness.config import Settings
from agent_harness.identity import IdentityContext
from agent_harness.memory.milvus_vector_store import MilvusVectorStore
from agent_harness.memory.types import MemoryScope
from agent_harness.memory.vector_store import VectorStoreError


class KnownEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[0.0, 1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_adapter_uses_embedding_dimension_and_identity_filter(monkeypatch):
    sdk = pytest.importorskip("pymilvus")
    client = Mock()
    client.list_collections = AsyncMock(return_value=[])
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    client.drop_collection = AsyncMock()
    client.search = AsyncMock(return_value=[[{"id": "storage-key", "distance": 0.97,
                                             "entity": {"memory_id": "m1"}}]])
    client.close = AsyncMock()
    client.create_schema = sdk.MilvusClient.create_schema
    client.prepare_index_params = sdk.MilvusClient.prepare_index_params
    monkeypatch.setattr(sdk, "AsyncMilvusClient", Mock(return_value=client))
    settings = Settings(_env_file=None, milvus_uri="https://example.test", milvus_token="test-only", milvus_collection="gate")
    vector = MilvusVectorStore(settings, KnownEmbeddings())
    assert await vector.connect() == []
    await vector.initialize()
    schema = client.create_collection.call_args.kwargs["schema"].to_dict()
    assert next(f for f in schema["fields"] if f["name"] == "vector")["params"]["dim"] == 3
    assert next(f for f in schema["fields"] if f["name"] == "tenant_id")["is_partition_key"]
    identity = IdentityContext('acme" OR true', "alice", ["user"])
    await vector.upsert("m1", "TypeScript", {"scope": "user", "user_id": "bob"}, identity)
    row = client.upsert.call_args.kwargs["data"][0]
    assert row["vector"] == [0.0, 1.0, 0.0]
    assert row["user_id"] == "alice" and row["memory_id"] == "m1"
    assert await vector.search("typescript", identity, MemoryScope.USER, 2) == [("m1", 0.97)]
    arguments = client.search.call_args.kwargs
    assert arguments["limit"] == 2
    assert arguments["filter_params"]["tenant"] == 'acme" OR true'
    assert arguments["filter_params"]["user"] == "alice"
    assert arguments["filter_params"]["scope"] == "user"
    assert arguments["search_params"]["metric_type"] == "COSINE"
    settings.milvus_collection = "existing_production_collection"
    await vector.drop_created_collection()
    assert client.drop_collection.call_args.kwargs["collection_name"] == "gate"
    await vector.close()


@pytest.mark.asyncio
async def test_sdk_error_does_not_leak_token(monkeypatch):
    sdk = pytest.importorskip("pymilvus")
    client = Mock(list_collections=AsyncMock(side_effect=sdk.MilvusException(code=1800, message="credential-secret")))
    monkeypatch.setattr(sdk, "AsyncMilvusClient", Mock(return_value=client))
    vector = MilvusVectorStore(Settings(_env_file=None, milvus_uri="https://example.test", milvus_token="credential-secret"))
    with pytest.raises(VectorStoreError) as error:
        await vector.connect()
    assert error.value.code == "authentication"
    assert "credential-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_wrapped_grpc_auth_error_is_mapped_without_message_parsing(monkeypatch):
    from types import SimpleNamespace

    sdk = pytest.importorskip("pymilvus")

    class AuthenticationError(Exception):
        def code(self):
            return SimpleNamespace(name="UNAUTHENTICATED")

    wrapper = sdk.MilvusException(code=2, message="generic connection error")
    wrapper.__cause__ = AuthenticationError("credential-secret")
    client = Mock(list_collections=AsyncMock(side_effect=wrapper))
    monkeypatch.setattr(sdk, "AsyncMilvusClient", Mock(return_value=client))
    vector = MilvusVectorStore(Settings(_env_file=None, milvus_uri="https://example.test", milvus_token="test-only"))
    with pytest.raises(VectorStoreError) as error:
        await vector.connect()
    assert error.value.code == "authentication"
    assert "credential-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_adapter_get_delete_keep_owner_filter_and_reject_schema(monkeypatch):
    sdk = pytest.importorskip("pymilvus")
    client = Mock()
    client.list_collections = AsyncMock(return_value=["gate"])
    client.describe_collection = AsyncMock(return_value={"fields": []})
    client.query = AsyncMock(return_value=[{"memory_id": "m1", "content": "value", "metadata": {"importance": 0.8}}])
    client.delete = AsyncMock()
    client.close = AsyncMock()
    monkeypatch.setattr(sdk, "AsyncMilvusClient", Mock(return_value=client))
    vector = MilvusVectorStore(Settings(_env_file=None, milvus_uri="https://example.test", milvus_token="test-only", milvus_collection="gate"), KnownEmbeddings())
    with pytest.raises(VectorStoreError, match="schema_mismatch"):
        await vector.initialize()
    identity = IdentityContext("acme", "alice", ["user"])
    assert (await vector.get("m1", identity, MemoryScope.USER))["metadata"] == {"importance": 0.8}
    await vector.delete("m1", identity, MemoryScope.USER)
    for method in (client.query, client.delete):
        params = method.call_args.kwargs["filter_params"]
        assert params == {"tenant": "acme", "user": "alice", "scope": "user", "session": "", "memory": "m1"}
    await vector.close()
