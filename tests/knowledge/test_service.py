"""Knowledge 域服务与 fake 栈（Phase 11 T1，ADR-0013）。

不经 Milvus、不经工具层：领域语义（source 级增量、citation、sufficient、
防呆上限、回读上下文）全部在本文件对 fake store + 真 SQLite 注册表钉死。
"""

import pytest
import pytest_asyncio

from agent_harness.identity import IdentityContext
from agent_harness.knowledge.registry import SqliteKnowledgeSourceRegistry
from agent_harness.knowledge.service import KnowledgeService
from agent_harness.knowledge.store import FakeKnowledgeVectorStore
from agent_harness.knowledge.types import KnowledgeError

ALICE = IdentityContext("acme", "alice", ["user", "session"])


@pytest_asyncio.fixture
async def service(tmp_path):
    store = FakeKnowledgeVectorStore()
    registry = SqliteKnowledgeSourceRegistry(tmp_path / "harness.db")
    await registry.initialize()
    return KnowledgeService(store=store, registry=registry)


LONG_TEXT = "\n\n".join(
    f"第 {i} 段：python typing 是这个项目的核心语言特性，类型标注贯穿全部模块。"
    + "补充设计背景：异步优先与显式装配贯穿整个代码库。" * 5
    for i in range(6)
)


async def _ingest_python_doc(service) -> str:
    result = await service.ingest(
        text=LONG_TEXT, source_name="python-guide", identity=ALICE,
    )
    assert result.status in ("created", "rebuilt")
    return result.source_id


# ── ingest：创建 / 跳过 / 重建 ──


@pytest.mark.asyncio
async def test_ingest_new_source_creates_chunks_and_registry_row(service):
    result = await service.ingest(
        text=LONG_TEXT, source_name="python-guide", identity=ALICE,
    )
    assert result.status == "created"
    assert result.chunk_count >= 2, "多段落文本应切出多个 chunk"
    source = await service._registry.get_by_name("acme", "python-guide")
    assert source is not None and source.source_id == result.source_id
    assert source.chunk_count == result.chunk_count


@pytest.mark.asyncio
async def test_reingest_same_content_skips_store_writes(service):
    result = await service.ingest(
        text=LONG_TEXT, source_name="python-guide", identity=ALICE,
    )
    store = service._store
    upserts_before = store.upsert_calls

    again = await service.ingest(
        text=LONG_TEXT, source_name="python-guide", identity=ALICE,
    )
    assert again.status == "skipped"
    assert again.source_id == result.source_id
    assert store.upsert_calls == upserts_before, "hash 未变不得重写向量库"


@pytest.mark.asyncio
async def test_reingest_changed_content_rebuilds_and_removes_stale(service):
    await service.ingest(text=LONG_TEXT, source_name="guide", identity=ALICE)
    changed = LONG_TEXT + "\n\n新增结尾段落：rust 也是系统语言。"

    result = await service.ingest(text=changed, source_name="guide", identity=ALICE)

    assert result.status == "rebuilt"
    store = service._store
    assert store.delete_calls >= 1, "变更 source 必须先删旧 chunk"
    chunks = [c for c in store.all_chunks("acme") if c.source_name == "guide"]
    assert len(chunks) == result.chunk_count, "重建后 chunk 数与登记一致"
    assert any("新增结尾段落" in c.content for c in chunks), "重建后新内容在库"
    source = await service._registry.get_by_name("acme", "guide")
    assert source.chunk_count == result.chunk_count
    # 稳定 source_id：重建不换 id（citation 不失效）
    assert result.source_id == (await service._registry.get_by_name("acme", "guide")).source_id


@pytest.mark.asyncio
async def test_same_name_is_natural_key_per_tenant(service):
    """同名 source 在同租户下是同一个实体（citation 稳定的前提）。"""
    await service.ingest(text="文档 A 内容", source_name="doc", identity=ALICE)
    bob = IdentityContext("other-tenant", "bob", ["user"])
    result = await service.ingest(text="Bob 的文档内容", source_name="doc", identity=bob)
    assert result.status == "created", "跨租户同名互不干扰"
    assert await service._registry.get_by_name("acme", "doc") is not None
    assert await service._registry.get_by_name("other-tenant", "doc") is not None


@pytest.mark.asyncio
async def test_ingest_rejects_hash_in_source_name(service):
    with pytest.raises(KnowledgeError, match="source_name"):
        await service.ingest(text="x", source_name="a#b", identity=ALICE)


# ── 防呆上限 ──


@pytest.mark.asyncio
async def test_ingest_enforces_size_limit(service, monkeypatch):
    monkeypatch.setattr(service, "_max_source_chars", 100)
    with pytest.raises(KnowledgeError, match="2 MB|字符"):
        await service.ingest(text="x" * 101, source_name="big", identity=ALICE)
    assert await service._registry.get_by_name("acme", "big") is None, "被拒请求零痕迹"


@pytest.mark.asyncio
async def test_ingest_enforces_chunk_limit(service, monkeypatch):
    monkeypatch.setattr(service, "_max_chunks", 2)
    monkeypatch.setattr(service, "_chunk_size", 60)
    monkeypatch.setattr(service, "_overlap", 10)
    with pytest.raises(KnowledgeError, match="chunk"):
        await service.ingest(text=LONG_TEXT, source_name="wide", identity=ALICE)


# ── retrieve：排序 / sufficient / 过滤 ──


@pytest.mark.asyncio
async def test_retrieve_orders_hits_and_marks_sufficient(service):
    await service.ingest(text=LONG_TEXT, source_name="python-guide", identity=ALICE)
    await service.ingest(text="鲸鱼是海洋哺乳动物。", source_name="whales", identity=ALICE)

    result = await service.retrieve(query="python typing 语言特性", identity=ALICE, k=5)

    assert result.query == "python typing 语言特性"
    assert result.hits, "有相关语料时必须命中"
    assert all(h.citation.startswith("kb:python-guide#") for h in result.hits
               if h.content.startswith("第")), "citation 格式 kb:<source>#<idx>"
    assert result.is_sufficient is True, "term 全命中（overlap=1.0）必须 sufficient"
    scores = [h.score for h in result.hits]
    assert scores == sorted(scores, reverse=True), "hits 按分数降序"


@pytest.mark.asyncio
async def test_retrieve_insufficient_marks_false_but_returns_hits(service):
    await service.ingest(text=LONG_TEXT, source_name="python-guide", identity=ALICE)
    service._min_score = 0.99  # 阈值抬到不可达：标记语义与 hits 返回解耦

    result = await service.retrieve(query="python quantum", identity=ALICE, k=5)
    assert result.hits, "阈值以下是证据质量信号，不是结果开关"
    assert result.is_sufficient is False, "部分命中 0.5 < 0.99：如实标记不足"


@pytest.mark.asyncio
async def test_retrieve_empty_store_is_insufficient_with_no_hits(service):
    result = await service.retrieve(query="任何问题", identity=ALICE, k=5)
    assert result.hits == [] and result.is_sufficient is False


@pytest.mark.asyncio
async def test_retrieve_passes_source_filter_and_k(service):
    await service.ingest(text=LONG_TEXT, source_name="python-guide", identity=ALICE)
    whales_id = (await service.ingest(
        text="鲸鱼是海洋哺乳动物。", source_name="whales", identity=ALICE)).source_id

    result = await service.retrieve(
        query="语言 python typing", identity=ALICE, k=1, source_id=whales_id,
    )
    assert len(result.hits) <= 1
    assert all(not h.content.startswith("第") for h in result.hits), "过滤后不命中其他 source"


@pytest.mark.asyncio
async def test_retrieve_rejects_invalid_k(service):
    with pytest.raises(KnowledgeError, match="k"):
        await service.retrieve(query="x", identity=ALICE, k=0)
    with pytest.raises(KnowledgeError, match="k"):
        await service.retrieve(query="x", identity=ALICE, k=21)


# ── read_source：citation 解析与上下文 ──


@pytest.mark.asyncio
async def test_read_source_single_chunk(service):
    await service.ingest(text=LONG_TEXT, source_name="python-guide", identity=ALICE)
    result = await service.read_source(citation="kb:python-guide#0", identity=ALICE)
    assert result.match.chunk_index == 0
    assert result.match.source_name == "python-guide"
    assert result.context == []


MANY_CHUNK_TEXT = "\n\n".join(
    f"第 {i} 段：专题 {i} 的详细展开说明，包含足够的长度让切分器产生多个块。"
    for i in range(90)
)


@pytest.mark.asyncio
async def test_read_source_with_context_returns_neighbors(service):
    await service.ingest(text=MANY_CHUNK_TEXT, source_name="long-doc", identity=ALICE)
    result = await service.read_source(
        citation="kb:long-doc#1", identity=ALICE, with_context=True,
    )
    assert result.match.chunk_index == 1
    indices = [c.chunk_index for c in result.context]
    assert indices == [0, 2], "with_context = 前后各 1 chunk，按位置有序"


@pytest.mark.asyncio
async def test_read_source_context_clamps_at_boundaries(service):
    await service.ingest(text=MANY_CHUNK_TEXT, source_name="long-doc", identity=ALICE)
    head = await service.read_source(
        citation="kb:long-doc#0", identity=ALICE, with_context=True)
    assert [c.chunk_index for c in head.context] == [1], "首块只有后邻"


@pytest.mark.asyncio
async def test_read_source_error_paths(service):
    await service.ingest(text=LONG_TEXT, source_name="python-guide", identity=ALICE)
    with pytest.raises(KnowledgeError, match="citation"):
        await service.read_source(citation="not-a-citation", identity=ALICE)
    with pytest.raises(KnowledgeError, match="citation"):
        await service.read_source(citation="kb:ghost#0", identity=ALICE)
    with pytest.raises(KnowledgeError, match="citation"):
        await service.read_source(citation="kb:python-guide#999", identity=ALICE)


# ── 切分器 ──


def test_splitter_respects_size_and_overlap():
    from agent_harness.knowledge.splitter import split_text

    text = "\n\n".join(f"段落 {i}：" + "内容句子。" * 30 for i in range(20))
    chunks = split_text(text, chunk_size=800, overlap=100)
    assert chunks and all(chunk.strip() for chunk in chunks), "无空块"
    assert all(len(chunk) <= 800 for chunk in chunks), "块大小上限"
    assert len(chunks) >= 3
    # overlap：相邻块共享尾部/头部内容
    assert chunks[1][-100:] and chunks[0][-50:] in chunks[1] or \
        chunks[0][-100:] and chunks[0][-100:][:50] in chunks[1], "相邻块有 overlap"


def test_splitter_single_paragraph_hard_split():
    from agent_harness.knowledge.splitter import split_text

    chunks = split_text("x" * 2500, chunk_size=800, overlap=100)
    assert len(chunks) == 4, "无分隔符的长文按字符硬切"
    assert all(len(chunk) <= 800 for chunk in chunks)


# ── RetrievalProvider 窄接口视图（ADR-0014 决策 7，Phase 12 #77）──


@pytest.mark.asyncio
async def test_as_retrieval_provider_returns_unified_hits(service):
    """KB 落在统一检索协议上：RetrievalHit + source_id/chunk_index 走 metadata。

    identity 从 contextvar 继承（Runtime 会话帧内已绑定）——adapter 不传
    identity 参数，租户隔离语义不因注入方式改变。
    """
    from agent_harness.identity import identity_context_var
    from agent_harness.websearch.protocol import RetrievalHit, RetrievalProvider

    source_id = await _ingest_python_doc(service)
    provider = service.as_retrieval_provider()

    # 结构化落在统一协议上（isinstance 过 runtime_checkable 检查）
    assert isinstance(provider, RetrievalProvider)
    token = identity_context_var.set(ALICE)
    try:
        hits = await provider.search("python typing", k=3)
    finally:
        identity_context_var.reset(token)

    assert hits and all(isinstance(h, RetrievalHit) for h in hits)
    first = hits[0]
    assert first.citation.startswith("kb:")
    assert first.citation.split("#")[0] == "kb:python-guide"
    assert first.content
    assert isinstance(first.score, float)
    assert first.metadata["source_id"] == source_id
    assert isinstance(first.metadata["chunk_index"], int)


@pytest.mark.asyncio
async def test_as_retrieval_provider_k_clamped_and_gl_hl_ignored(service):
    """gl/hl/freshness 对本地语料无意义即忽略；k 超界钳制不炸。"""
    await _ingest_python_doc(service)
    provider = service.as_retrieval_provider()

    from agent_harness.identity import identity_context_var

    token = identity_context_var.set(ALICE)
    try:
        hits = await provider.search(
            "python typing", k=999, gl="us", hl="en", freshness="week",
        )
    finally:
        identity_context_var.reset(token)
    assert hits and len(hits) <= 20
