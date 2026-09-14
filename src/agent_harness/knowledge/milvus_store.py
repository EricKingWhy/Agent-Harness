"""Knowledge 域的真实 Milvus provider（Phase 11 T2，ADR-0013 决策 3/4）。

独立 collection（knowledge_chunks，tenant partition key），与 memory collection
物理分开；复用 embeddings 工厂与 AsyncMilvusClient 接线模式（脱敏错误映射、
schema_mismatch 拒绝、懒加载 pymilvus memory extra 同款纪律）。
"""

import logging
import math

from langchain_core.embeddings import Embeddings

from agent_harness.config import Settings
from agent_harness.identity import IdentityContext
from agent_harness.knowledge.types import KnowledgeChunk, KnowledgeError

_FIELDS = ("source_id", "source_name", "chunk_index", "content_hash", "content")


class MilvusKnowledgeVectorStore:
    def __init__(
        self, settings: Settings, embeddings: Embeddings | None = None
    ) -> None:
        if not settings.milvus_uri or not settings.milvus_token.get_secret_value():
            raise KnowledgeError(
                "knowledge 向量库未配置：MILVUS_URI / MILVUS_TOKEN 缺失"
            )
        if not settings.knowledge_collection:
            raise KnowledgeError(
                "KNOWLEDGE_COLLECTION 未配置（必填无默认——不配 = capability "
                "缺席降级，绝不静默写默认库）"
            )
        self._settings = settings
        self._embeddings = embeddings
        self._client = None
        self.dimension: int | None = None
        self._created_collection: str | None = None

    @property
    def created_collection(self) -> bool:
        return self._created_collection is not None

    async def _call(self, operation: str, **kwargs):
        if self._client is None:
            raise KnowledgeError("not_connected")
        try:
            return await getattr(self._client, operation)(timeout=15, **kwargs)
        except Exception as error:  # noqa: BLE001 — SDK 异常不得携带凭证进入日志/事件。
            category = "unavailable"
            cause = error
            seen: set[int] = set()
            while cause is not None and id(cause) not in seen:
                seen.add(id(cause))
                code = getattr(cause, "code", None)
                code = code() if callable(code) else code
                category = {1800: "authentication", 100: "collection_not_found",
                            1100: "invalid_request"}.get(code, "unavailable") if isinstance(code, int) else {
                                "UNAUTHENTICATED": "authentication", "PERMISSION_DENIED": "permission_denied",
                            }.get(getattr(code, "name", None), "unavailable")
                if category != "unavailable":
                    break
                cause = cause.__cause__
            raise KnowledgeError(f"knowledge store {category}") from None

    async def connect(self) -> list[str]:
        """轻量连接检查，不创建 Collection、不调用 embedding。"""
        if self._client is None:
            try:
                from pymilvus import AsyncMilvusClient
            except ImportError:
                raise KnowledgeError(
                    "缺少 pymilvus：请安装 intelligence-agent[memory] extra"
                ) from None
            sdk_logger = logging.getLogger("pymilvus")
            sdk_logger.handlers = [logging.NullHandler()]
            sdk_logger.propagate = False
            try:
                self._client = AsyncMilvusClient(
                    uri=self._settings.milvus_uri,
                    token=self._settings.milvus_token.get_secret_value(), timeout=15)
            except Exception:  # noqa: BLE001
                raise KnowledgeError("knowledge store connection") from None
        return await self._call("list_collections")

    async def _embed(self, text: str, *, document: bool = False) -> list[float]:
        if self._embeddings is None:
            raise KnowledgeError("embedding 未配置")
        try:
            vector = ((await self._embeddings.aembed_documents([text]))[0] if document
                      else await self._embeddings.aembed_query(text))
        except Exception:  # noqa: BLE001
            raise KnowledgeError("embedding 服务不可用") from None
        if (len(vector) < 2 or any(not math.isfinite(v) for v in vector)
                or not any(vector) or (self.dimension is not None and len(vector) != self.dimension)):
            raise KnowledgeError("embedding 维度或取值非法")
        return vector

    async def initialize(self) -> None:
        collections = await self.connect()
        vector = await self._embed("knowledge index dimension probe")
        self.dimension = len(vector)
        collection = self._settings.knowledge_collection
        if collection in collections:
            description = await self._call("describe_collection", collection_name=collection)
            fields = {f["name"]: f for f in description["fields"]}
            if (not {"id", "source_id", "source_name", "chunk_index",
                     "content_hash", "content", "tenant_id", "vector"} <= fields.keys()
                    or int(fields["vector"].get("params", {}).get("dim", 0)) != self.dimension
                    or not fields["tenant_id"].get("is_partition_key")):
                raise KnowledgeError(
                    f"collection {collection!r} schema 与 knowledge 域不匹配"
                    "（schema_mismatch）——请检查是否与 memory 或旧数据混用"
                )
            return
        from pymilvus import DataType

        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("source_id", DataType.VARCHAR, max_length=64)
        schema.add_field("source_name", DataType.VARCHAR, max_length=2048)
        schema.add_field("chunk_index", DataType.INT64)
        schema.add_field("content_hash", DataType.VARCHAR, max_length=64)
        schema.add_field("content", DataType.VARCHAR, max_length=65535)
        schema.add_field("tenant_id", DataType.VARCHAR, max_length=2048,
                         is_partition_key=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dimension)
        index = self._client.prepare_index_params()
        index.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        await self._call("create_collection", collection_name=collection, schema=schema,
                         index_params=index, consistency_level="Strong")
        self._created_collection = collection

    @staticmethod
    def _tenant_filter(identity: IdentityContext) -> tuple[str, dict]:
        return "tenant_id == {tenant}", {"tenant": identity.tenant_id}

    async def upsert_chunks(
        self, chunks: list[KnowledgeChunk], identity: IdentityContext
    ) -> None:
        if not chunks:
            return
        rows = []
        for chunk in chunks:
            vector = await self._embed(chunk.content, document=True)
            rows.append({
                "id": f"{chunk.source_id}:{chunk.chunk_index}",
                "source_id": chunk.source_id,
                "source_name": chunk.source_name,
                "chunk_index": chunk.chunk_index,
                "content_hash": chunk.content_hash,
                "content": chunk.content,
                "tenant_id": identity.tenant_id,
                "vector": vector,
            })
        await self._call("upsert", collection_name=self._settings.knowledge_collection,
                         data=rows)

    async def delete_source(self, source_id: str, identity: IdentityContext) -> int:
        expression, params = self._tenant_filter(identity)
        expression += " AND source_id == {source}"
        params = {**params, "source": source_id}
        result = await self._call(
            "delete", collection_name=self._settings.knowledge_collection,
            filter=expression, filter_params=params,
        )
        return int(getattr(result, "delete_count", 0) or 0)

    async def search(
        self,
        query: str,
        identity: IdentityContext,
        *,
        limit: int,
        source_id: str | None = None,
    ) -> list[tuple[KnowledgeChunk, float]]:
        if not query or limit <= 0:
            return []
        expression, params = self._tenant_filter(identity)
        if source_id is not None:
            expression += " AND source_id == {source}"
            params = {**params, "source": source_id}
        vector = await self._embed(query)
        hits = await self._call(
            "search", collection_name=self._settings.knowledge_collection,
            data=[vector], anns_field="vector", filter=expression,
            filter_params=params, limit=limit,
            search_params={"metric_type": "COSINE"},
            output_fields=["source_id", "source_name", "chunk_index",
                           "content_hash", "content"],
            consistency_level="Strong",
        )
        return [(self._chunk(hit["entity"]), float(hit["distance"])) for hit in hits[0]]

    async def get_chunk(
        self, source_id: str, chunk_index: int, identity: IdentityContext
    ) -> KnowledgeChunk | None:
        expression, params = self._tenant_filter(identity)
        rows = await self._call(
            "query", collection_name=self._settings.knowledge_collection,
            filter=expression + " AND source_id == {source} AND chunk_index == {index}",
            filter_params={**params, "source": source_id, "index": chunk_index},
            output_fields=["source_id", "source_name", "chunk_index",
                           "content_hash", "content"],
            consistency_level="Strong",
        )
        return self._chunk(rows[0]) if rows else None

    @staticmethod
    def _chunk(entity: dict) -> KnowledgeChunk:
        return KnowledgeChunk(
            source_id=entity["source_id"], source_name=entity["source_name"],
            chunk_index=int(entity["chunk_index"]),
            content_hash=entity["content_hash"], content=entity["content"],
        )

    async def drop_created_collection(self) -> None:
        """显式清理：仅删除本 adapter 实例创建的 collection（gate 用）。"""
        if self._created_collection is not None:
            await self._call("drop_collection", collection_name=self._created_collection)
            self._created_collection = None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
