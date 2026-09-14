"""KnowledgeVectorStore 协议与进程内 fake（ADR-0013 决策 3/4）。

协议是 Knowledge 域专用：不泛化 memory 的 VectorIndexStore——两个小协议
好过一个胖协议（memory 已过真实验收的接口不动）。CI 用 Fake；真实 Milvus
provider 见 T2（共享 embeddings 工厂与部署，schema 独立）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_harness.identity import IdentityContext
from agent_harness.knowledge.types import KnowledgeChunk


@runtime_checkable
class KnowledgeVectorStore(Protocol):
    """Knowledge 域向量存储契约：chunk 形状、tenant 隔离、citation 邻查。"""

    async def upsert_chunks(
        self, chunks: list[KnowledgeChunk], identity: IdentityContext
    ) -> None: ...

    async def delete_source(self, source_id: str, identity: IdentityContext) -> int: ...

    async def search(
        self,
        query: str,
        identity: IdentityContext,
        *,
        limit: int,
        source_id: str | None = None,
    ) -> list[tuple[KnowledgeChunk, float]]: ...

    async def get_chunk(
        self, source_id: str, chunk_index: int, identity: IdentityContext
    ) -> KnowledgeChunk | None: ...


class FakeKnowledgeVectorStore:
    """进程内实现：确定性 term-overlap 评分（无需 embeddings），CI 零依赖。

    chunk_id 确定性 = f"{source_id}:{chunk_index}"——upsert 幂等覆盖同索引；
    评分 = query 词与 chunk 词的交集比例（白空格分词），0..1。生产语义
    （真实向量相似度）由 T2 的 Milvus provider 承担，fake 只承担领域语义。
    """

    def __init__(self) -> None:
        self._chunks: dict[tuple[str, str], KnowledgeChunk] = {}
        self.upsert_calls = 0
        self.delete_calls = 0

    async def upsert_chunks(
        self, chunks: list[KnowledgeChunk], identity: IdentityContext
    ) -> None:
        self.upsert_calls += 1
        for chunk in chunks:
            self._chunks[(identity.tenant_id, self._key(chunk))] = chunk

    async def delete_source(
        self, source_id: str, identity: IdentityContext
    ) -> int:
        self.delete_calls += 1
        doomed = [
            key for key, chunk in self._chunks.items()
            if key[0] == identity.tenant_id and chunk.source_id == source_id
        ]
        for key in doomed:
            del self._chunks[key]
        return len(doomed)

    async def search(
        self,
        query: str,
        identity: IdentityContext,
        *,
        limit: int,
        source_id: str | None = None,
    ) -> list[tuple[KnowledgeChunk, float]]:
        scored: list[tuple[KnowledgeChunk, float]] = []
        for (tenant, _key), chunk in self._chunks.items():
            if tenant != identity.tenant_id:
                continue
            if source_id is not None and chunk.source_id != source_id:
                continue
            scored.append((chunk, self._score(query, chunk.content)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[: max(0, limit)]

    async def get_chunk(
        self, source_id: str, chunk_index: int, identity: IdentityContext
    ) -> KnowledgeChunk | None:
        key = (identity.tenant_id, f"{source_id}:{chunk_index}")
        return self._chunks.get(key)

    def all_chunks(self, tenant_id: str) -> list[KnowledgeChunk]:
        """测试观察口：某租户当前全部 chunk。"""
        return [
            chunk for (tenant, _key), chunk in self._chunks.items()
            if tenant == tenant_id
        ]

    @staticmethod
    def _key(chunk: KnowledgeChunk) -> str:
        return f"{chunk.source_id}:{chunk.chunk_index}"

    @staticmethod
    def _score(query: str, content: str) -> float:
        """确定性词项包含评分：query 词项在 chunk 内容中的子串命中率（0..1）。

        用子串而非白空格分词交集——中英混排文本没有可靠的空白分词，
        子串包含对 CJK 是稳定的词法包含近似。
        """
        query_terms = query.split()
        if not query_terms:
            return 0.0
        return sum(1 for term in query_terms if term in content) / len(query_terms)
