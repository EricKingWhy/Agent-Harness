"""真实 Zilliz + SiliconFlow embedding 的 Knowledge Gate（Phase 11 T6，ADR-0013）。

三条 Gate（roadmap Phase 11）：
1. restart 后 persistent search（新 client 实例重连后检索命中）
2. 证据不足明确 false（真实分数分布顺带验证 KNOWLEDGE_MIN_SCORE=0.6）
3. citation 可追溯（kb:<source>#<idx> → source 元数据 → 原文）

专用 KNOWLEDGE_COLLECTION gate collection；凭证零泄漏。
"""

from uuid import uuid4

import pytest

from agent_harness.config import Settings
from agent_harness.identity import IdentityContext
from agent_harness.knowledge.milvus_store import MilvusKnowledgeVectorStore
from agent_harness.knowledge.registry import SqliteKnowledgeSourceRegistry
from agent_harness.knowledge.service import KnowledgeService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
def gate_settings():
    settings = Settings()
    if not settings.milvus_uri or not settings.milvus_token.get_secret_value():
        pytest.skip("Real Milvus connection is not configured")
    if not settings.embedding_model or not settings.embedding_api_key.get_secret_value():
        pytest.skip("Real embedding model is not configured")
    if settings.knowledge_collection != "knowledge_gate_test":
        pytest.skip("Gate requires the dedicated knowledge_gate_test collection")
    return settings


def _embeddings(settings):
    """Gate 专用嵌入客户端：验证记忆语义而非嵌入重试策略（与 Phase 6 同款）。"""
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=settings.embedding_model, base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key, check_embedding_ctx_length=False,
        dimensions=settings.embedding_dimensions, request_timeout=30, max_retries=3,
    )


PYTHON_DOC = "\n\n".join(
    f"第 {i} 节：python typing 与类型标注。这个项目统一使用 python typing 进行"
    f"类型标注，asyncio 异步优先贯穿 agent loop 与 tool runtime。"
    for i in range(8)
)

NOISE_DOC = "\n\n".join(
    f"观测 {i}：鲸鱼是海洋哺乳动物，使用声呐通信，迁徙路线跨越整个大洋盆地。"
    for i in range(4)
)


@pytest.mark.asyncio
async def test_real_knowledge_gate(gate_settings, tmp_path):
    service = KnowledgeService(
        store=MilvusKnowledgeVectorStore(gate_settings, _embeddings(gate_settings)),
        registry=SqliteKnowledgeSourceRegistry(tmp_path / "harness.db"),
    )
    await service._registry.initialize()
    await service._store.initialize()
    alice = IdentityContext("kb_gate_" + uuid4().hex, "alice", ["user"])
    scores_seen: list[float] = []
    active_store = service._store  # restart 后切换到新实例；清理始终用活跃实例
    try:
        # 1. ingest 两个 source
        created = await service.ingest(
            text=PYTHON_DOC, source_name="python-doc", identity=alice,
        )
        assert created.status == "created"
        await service.ingest(text=NOISE_DOC, source_name="whales-doc", identity=alice)

        # 2. 检索 + sufficient（真实向量语义）
        result = await service.retrieve(
            query="python typing 类型标注", identity=alice, k=5,
        )
        assert result.hits, "真实语料必须命中"
        scores_seen.extend(hit.score for hit in result.hits)
        assert result.hits[0].citation.startswith("kb:python-doc#"), \
            f"python 文档应排前：{[(h.citation, round(h.score, 3)) for h in result.hits]}"
        assert result.is_sufficient is True

        # 3. Gate 3 citation 可追溯：citation → 原文一致
        read = await service.read_source(
            citation=result.hits[0].citation, identity=alice, with_context=True,
        )
        assert read.match.content == result.hits[0].content
        assert read.source_name == "python-doc"

        # 4. Gate 2 证据不足明确 false：与语料无关的查询
        weak = await service.retrieve(
            query="量子纠缠态的希尔伯特空间测度不变性", identity=alice, k=3,
        )
        scores_seen.extend(hit.score for hit in weak.hits)
        assert weak.is_sufficient is False, (
            f"无关查询必须如实标记不足（真实 top 分数："
            f"{[round(h.score, 3) for h in weak.hits]}）"
        )

        # 5. Gate 1 restart persistent search：新 client 实例重连后检索仍命中
        await service._store.close()
        restarted = KnowledgeService(
            store=MilvusKnowledgeVectorStore(gate_settings, _embeddings(gate_settings)),
            registry=service._registry,
        )
        await restarted._store.initialize()
        active_store = restarted._store
        after_restart = await restarted.retrieve(
            query="python typing 类型标注", identity=alice, k=5,
        )
        assert after_restart.is_sufficient is True and after_restart.hits

        # 6. source 级增量：同内容重 ingest → skipped；变更 → rebuilt 且新内容可检
        again = await restarted.ingest(
            text=PYTHON_DOC, source_name="python-doc", identity=alice,
        )
        assert again.status == "skipped"
        changed = await restarted.ingest(
            text=PYTHON_DOC + "\n\n新增：rust 也是系统编程语言。", source_name="python-doc",
            identity=alice,
        )
        assert changed.status == "rebuilt"
        after_rebuild = await restarted.retrieve(
            query="rust 系统编程语言", identity=alice, k=3,
        )
        assert after_rebuild.hits, "重建后新增内容可检索"
        scores_seen.extend(hit.score for hit in after_rebuild.hits)
    finally:
        # 清理：逐 source 删除 + drop 本实例创建的 collection（用活跃 store 实例）
        try:
            for source in await service._registry.list(alice.tenant_id):
                await active_store.delete_source(source.source_id, alice)
                await service._registry.delete(source.source_id, alice.tenant_id)
        finally:
            created = active_store.created_collection
            if created:
                await active_store.drop_created_collection()
            await active_store.close()

    # 真实分数分布证据（阈值 0.6 合理性验证，写入 gate 文档）
    print("\n[knowledge gate] 真实分数分布：",
          sorted({round(s, 3) for s in scores_seen}, reverse=True))
