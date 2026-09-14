"""Real Zilliz + embedding Gate; simulated conversation, real storage/provider path."""

import asyncio
from uuid import uuid4

import pytest
from pydantic import SecretStr

from agent_harness.config import Settings
from agent_harness.identity import IdentityContext
from agent_harness.memory.milvus_vector_store import MilvusVectorStore
from agent_harness.memory.types import MemoryScope
from agent_harness.memory.vector_store import VectorStoreError

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
def gate_settings():
    settings = Settings()
    if not settings.milvus_uri or not settings.milvus_token.get_secret_value():
        pytest.skip("Real Milvus connection is not configured")
    if settings.milvus_collection != "memory_gate_test":
        pytest.skip("Gate requires the dedicated memory_gate_test collection")
    return settings


async def _drain(relay, records) -> int:
    """真实 embedding 服务有瞬态失败；outbox 的保证是"失败保留、下轮重试"，
    所以按该保证重试排空（同时也在验证这条保证本身）。返回本轮确认的总条数。"""
    acknowledged = 0
    async with asyncio.timeout(240):
        while True:
            acknowledged += await relay.flush()
            if not await records.pending():
                return acknowledged
            await asyncio.sleep(2)


async def _real_count(vectors, gate_settings, memory_id: str, identity: IdentityContext,
                      scope: MemoryScope = MemoryScope.USER) -> int:
    """查询一条记忆在当前 filter 下的**真实**行数（Strong 一致性，不用 stats）。

    这个查询是"无残留"这类断言的证据本身（`get_collection_stats` 是惰性陈旧值），
    所以只留这一份实现——两份副本一旦漂移，等于悄悄改掉验收断言的语义。
    """
    expression, params = MilvusVectorStore._filter(identity, scope)
    rows = await vectors._call(
        "query", collection_name=gate_settings.milvus_collection,
        filter=expression + " AND memory_id == {memory}",
        filter_params={**params, "memory": memory_id},
        output_fields=["count(*)"], consistency_level="Strong")
    return int(rows[0]["count(*)"])


async def test_real_connection_and_missing_collection(gate_settings):
    vectors = MilvusVectorStore(gate_settings)
    try:
        collections = await vectors.connect()
        assert isinstance(collections, list)
    finally:
        await vectors.close()

    # A unique missing name verifies query error mapping without mutating any collection.
    missing = gate_settings.model_copy(update={"milvus_collection": "memory_gate_absent_" + uuid4().hex})
    vectors = MilvusVectorStore(missing)
    try:
        await vectors.connect()
        with pytest.raises(VectorStoreError) as error:
            await vectors.get("gate-no-record", IdentityContext("gate", "alice", ["user"]), MemoryScope.USER)
        assert error.value.code == "collection_not_found"
    finally:
        await vectors.close()


async def test_real_invalid_token_is_mapped(gate_settings):
    # Never modify the actual token or put it into assertions / exception messages.
    invalid = gate_settings.model_copy(update={"milvus_token": SecretStr("gate-deliberately-invalid-token")})
    vectors = MilvusVectorStore(invalid)
    try:
        with pytest.raises(VectorStoreError) as error:
            await vectors.connect()
        assert error.value.code == "authentication"
    finally:
        await vectors.close()


async def test_real_memory_runtime_semantics_and_cleanup(gate_settings, tmp_path):
    from langchain_core.messages import AIMessage

    from agent_harness.agent import AgentRuntime
    from agent_harness.identity import identity_context_var, set_identity_context
    from agent_harness.memory.context_provider import MemoryContextProvider
    from agent_harness.memory.extractor import MemoryExtractor
    from agent_harness.memory.langmem_capability import LangMemMemoryCapability
    from agent_harness.memory.outbox_relay import OutboxRelay
    from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
    from agent_harness.memory.types import memory_session_var
    from agent_harness.memory.writeback import MemoryWriteback
    from agent_harness.session import USER_MESSAGE
    from agent_harness.tooling import ToolExecutor, ToolRegistry
    from tests.conftest import make_session
    from tests.scripted_model import ScriptedModel

    if not gate_settings.embedding_api_key.get_secret_value() or not gate_settings.embedding_model:
        pytest.skip("Real embedding model is not configured")

    def gate_embeddings(settings):
        """Gate 专用嵌入客户端：真实云厂商存在负载波动，本测试验证的是记忆语义
        而非嵌入重试策略（生产保持快失败 + 降级事件，见 embeddings.py）。"""
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=settings.embedding_model, base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key, check_embedding_ctx_length=False,
            dimensions=settings.embedding_dimensions, request_timeout=30, max_retries=3,
        )

    vectors = MilvusVectorStore(gate_settings, gate_embeddings(gate_settings))
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    capability = LangMemMemoryCapability(records, vectors)
    relay = OutboxRelay(records, vectors)
    session = make_session(tmp_path / "sessions")
    alice = IdentityContext("gate_" + uuid4().hex, "alice", ["user", "session"])
    identity_token = set_identity_context(alice)
    session_token = memory_session_var.set(session.session_id)
    # Control conversation outputs so this gate tests storage and semantic retrieval,
    # independently of nondeterministic chat-model wording. Extractor itself is real.
    extractor = MemoryExtractor(ScriptedModel([AIMessage(content=
        '[{"scope":"user","content":"我喜欢使用 TypeScript 开发应用。","importance":0.9}]')]))
    writer = MemoryWriteback(capability, extractor)
    try:
        await vectors.initialize()
        assert vectors.dimension == gate_settings.embedding_dimensions
        registry = ToolRegistry()
        runtime = AgentRuntime(ScriptedModel([AIMessage(content="已记录你的偏好。")]), registry,
                               ToolExecutor(registry), memory_writer=writer)
        await runtime.run(session, "我喜欢 TypeScript")
        await writer.drain()
        assert not any(e.type == "memory/degraded" for e in session.events)
        preference = (await records.list_by_scope(MemoryScope.USER, alice, 20))[0]
        other_id = await capability.store(MemoryScope.USER, "鲸鱼是生活在海洋中的哺乳动物。", {"importance": 0.2})
        # 真实 embedding 服务存在瞬态失败；outbox 语义保证失败条目被保留、
        # 下轮 flush 重新 upsert。这里按该保证重试排空——同时验证持久 outbox 本身。
        acknowledged = await _drain(relay, records)
        assert acknowledged == 2
        assert await records.pending() == []
        stored = await vectors.get(preference.id, alice, MemoryScope.USER)
        assert stored["memory_id"] == preference.id and "TypeScript" in stored["content"]
        assert stored["metadata"]["importance"] == 0.9
        hits = await capability.search(MemoryScope.USER, "我偏好的编程语言是什么？", 2)
        assert len(hits) == 2
        assert hits[0].id == preference.id and hits[1].id == other_id
        assert hits[0].score > hits[1].score
        assert -1.001 <= hits[1].score <= hits[0].score <= 1.001
        assert len(await capability.search(MemoryScope.USER, "编程语言偏好", 1)) == 1

        second = make_session(tmp_path / "sessions")
        second.append(USER_MESSAGE, {"content": "我偏好的编程语言是什么？"})
        context = MemoryContextProvider(capability, timeout_seconds=60)
        messages = await context.select(second, 1000)
        assert len(messages) == 1 and "TypeScript" in messages[0].content
        for identity in (IdentityContext(alice.tenant_id, "bob", ["user"]),
                         IdentityContext(alice.tenant_id + "_other", "alice", ["user"])):
            token = set_identity_context(identity)
            try:
                assert await capability.search(MemoryScope.USER, "编程语言", 20) == []
                assert await vectors.get(preference.id, identity, MemoryScope.USER) is None
                assert await context.select(second, 1000) == []
            finally:
                identity_context_var.reset(token)

        # A genuine alternate supported output dimension must reject the existing schema.
        mismatched_embeddings = gate_embeddings(gate_settings)
        mismatched_embeddings.dimensions = 64 if vectors.dimension != 64 else 128
        mismatch = MilvusVectorStore(gate_settings, mismatched_embeddings)
        try:
            with pytest.raises(VectorStoreError, match="schema_mismatch"):
                await mismatch.initialize()
        finally:
            await mismatch.close()
    finally:
        await writer.close()
        await relay.stop()
        try:
            for entry in await records.list_by_scope(MemoryScope.USER, alice, 100):
                await vectors.delete(entry.id, alice, MemoryScope.USER)
                assert await vectors.get(entry.id, alice, MemoryScope.USER) is None
            created = vectors.created_collection
            await vectors.drop_created_collection()
            if created:
                assert gate_settings.milvus_collection not in await vectors.connect()
        finally:
            await vectors.close()
            memory_session_var.reset(session_token)
            identity_context_var.reset(identity_token)


async def test_real_forget_propagates_to_milvus_and_a_real_count_confirms_no_residue(gate_settings, tmp_path):
    """MEM-1（#156）AC4 的真实后端验收：`forget` 必须真的从向量索引里消失。

    三个容易骗过自己的点，所以断言按"不能骗自己"的方式写：
    1. `search` 检索不到 **不等于** 没有残留（命中受相似度/limit 影响）——判定残留用
       `query(output_fields=["count(*)"])` 的**真实 count**，不用
       `get_collection_stats`（它是惰性陈旧值）；
    2. 单独一个 0 不能证明 filter 写对了——所以留一条**对照组**记忆，它必须一直是 1；
    3. USER 全绿不能代替 SESSION：带 session_id 的那段 filter 是另一条路由，所以再加
       一组 SESSION 记忆（对照组 + 跨 session 的删除必须被拒）。
    """
    from langchain_openai import OpenAIEmbeddings

    from agent_harness.identity import identity_context_var, set_identity_context
    from agent_harness.memory.langmem_capability import LangMemMemoryCapability
    from agent_harness.memory.outbox_relay import OutboxRelay
    from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
    from agent_harness.memory.types import memory_session_var

    if not gate_settings.embedding_api_key.get_secret_value() or not gate_settings.embedding_model:
        pytest.skip("Real embedding model is not configured")

    embeddings = OpenAIEmbeddings(
        model=gate_settings.embedding_model, base_url=gate_settings.embedding_base_url,
        api_key=gate_settings.embedding_api_key, check_embedding_ctx_length=False,
        dimensions=gate_settings.embedding_dimensions, request_timeout=30, max_retries=3,
    )
    vectors = MilvusVectorStore(gate_settings, embeddings)
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    capability = LangMemMemoryCapability(records, vectors)
    relay = OutboxRelay(records, vectors)
    alice = IdentityContext("gate_forget_" + uuid4().hex, "alice", ["user", "session"])
    token = set_identity_context(alice)
    session_a = "gate_session_a_" + uuid4().hex
    session_b = "gate_session_b_" + uuid4().hex

    async def drain() -> int:
        return await _drain(relay, records)

    async def real_count(memory_id: str, scope: MemoryScope) -> int:
        return await _real_count(vectors, gate_settings, memory_id, alice, scope)

    try:
        await vectors.initialize()
        doomed = await capability.store(MemoryScope.USER, "我喜欢用 Rust 写解析器。", {"importance": 0.7})
        control = await capability.store(MemoryScope.USER, "鲸鱼是生活在海洋中的哺乳动物。", {"importance": 0.1})
        await drain()
        assert await records.pending() == []
        assert await real_count(doomed, MemoryScope.USER) == 1
        assert await real_count(control, MemoryScope.USER) == 1
        # 真实向量检索返回的是 `limit` 个最近邻、**没有相似度下限**：两条记忆都在索引里，
        # 于是这一问会同时返回两条（目标在前、对照在后）。所以"命中"只能按 id 成员断言，
        # 不能假设"不相关的那条不会被返回"。
        hits = await capability.search(MemoryScope.USER, "Rust 解析器", 5)
        assert hits[0].id == doomed and {hit.id for hit in hits} == {doomed, control}

        assert await capability.forget(doomed) is True
        await drain()
        assert await records.pending() == []

        assert await vectors.get(doomed, alice, MemoryScope.USER) is None
        remaining = await capability.search(MemoryScope.USER, "Rust 解析器", 5)
        assert [hit.id for hit in remaining] == [control]  # 目标不再出现在检索结果里
        assert await real_count(doomed, MemoryScope.USER) == 0  # 真值：索引里这一条已不存在
        assert await real_count(control, MemoryScope.USER) == 1  # filter 与清理范围都正确
        assert await capability.forget(doomed) is False  # 幂等

        # SESSION scope：另一条路由（filter 里多了 session_id 段），单独验一遍。
        session_token = memory_session_var.set(session_a)
        try:
            doomed_s = await capability.store(MemoryScope.SESSION, "会话内临时偏好：解析器用 Rust 写。",
                                              {"importance": 0.6})
            control_s = await capability.store(MemoryScope.SESSION, "会话内临时事实：鲸鱼是哺乳动物。",
                                               {"importance": 0.1})
            await drain()
            assert await real_count(doomed_s, MemoryScope.SESSION) == 1
            assert await real_count(control_s, MemoryScope.SESSION) == 1

            # 绑到别的 session 的上下文里：这条记忆既不可见，也不可删（跨 namespace）。
            memory_session_var.set(session_b)
            assert await capability.search(MemoryScope.SESSION, "Rust", 5) == []
            with pytest.raises(PermissionError):
                await capability.forget(doomed_s)

            memory_session_var.set(session_a)
            assert await real_count(doomed_s, MemoryScope.SESSION) == 1  # 被拒的删除没改动任何东西
            assert await capability.forget(doomed_s) is True
            await drain()
            assert await vectors.get(doomed_s, alice, MemoryScope.SESSION) is None
            assert await real_count(doomed_s, MemoryScope.SESSION) == 0
            assert await real_count(control_s, MemoryScope.SESSION) == 1
        finally:
            memory_session_var.reset(session_token)
    finally:
        try:
            for entry in await records.list_by_scope(MemoryScope.USER, alice, 100):
                await capability.forget(entry.id)
            session_token = memory_session_var.set(session_a)
            try:
                for entry in await records.list_by_scope(MemoryScope.SESSION, alice, 100):
                    await capability.forget(entry.id)
            finally:
                memory_session_var.reset(session_token)
            await drain()
            created = vectors.created_collection
            await vectors.drop_created_collection()
            if created:
                assert gate_settings.milvus_collection not in await vectors.connect()
        finally:
            await relay.stop()
            await vectors.close()
            identity_context_var.reset(token)


async def test_real_langmem_manager_delete_and_update_reach_milvus(gate_settings, tmp_path):
    """MEM-2（#157）AC2/AC4 的真实后端验收：**上游 manager 的删除/更新**真的改到真索引。

    与 #156 那条（走项目自己的 `forget`/`update` 动词）分工不同：这条验的是**上游路径**——
    脚本化模型发 `RemoveDoc` / `PatchDoc`（真 trustcall 绑定与校验）→ 真 adapter → 真记录库 →
    outbox/relay → 真 Milvus。只有"模型决定删哪条/改成什么"是脚本化的（真模型决策不确定，
    脚本化才能断言）；而"检索得到既有记忆"靠**真实 embedding 语义匹配**成立——这正是删除/更新
    路径的前提，也是 `FakeVectorStore` 的字面匹配盖不住的那一段。

    隔离性用最坏形状：指名道姓去删**别人**的文档 id。两道边界都必须守住：trustcall 的校验器只
    接受"它自己检索回来的那些 id"，adapter 还有一道 namespace 授权。
    """
    from langchain_core.messages import AIMessage
    from langchain_openai import OpenAIEmbeddings

    from agent_harness.identity import identity_context_var, set_identity_context
    from agent_harness.memory.langmem_capability import LangMemMemoryCapability
    from agent_harness.memory.outbox_relay import OutboxRelay
    from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
    from agent_harness.memory.types import MemoryNamespace
    from tests.langmem_doubles import ScriptedChatModel, stable_doc_id

    if not gate_settings.embedding_api_key.get_secret_value() or not gate_settings.embedding_model:
        pytest.skip("Real embedding model is not configured")

    embeddings = OpenAIEmbeddings(
        model=gate_settings.embedding_model, base_url=gate_settings.embedding_base_url,
        api_key=gate_settings.embedding_api_key, check_embedding_ctx_length=False,
        dimensions=gate_settings.embedding_dimensions, request_timeout=30, max_retries=3,
    )
    vectors = MilvusVectorStore(gate_settings, embeddings)
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    relay = OutboxRelay(records, vectors)
    alice = IdentityContext("gate_langmem_" + uuid4().hex, "alice", ["user"])
    bob = IdentityContext(alice.tenant_id, "bob", ["user"])
    token = set_identity_context(alice)

    def capability(script):
        return LangMemMemoryCapability(records, vectors, ScriptedChatModel(responses=script))

    def doc_id(memory_id: str, identity: IdentityContext) -> str:
        return stable_doc_id(memory_id, MemoryNamespace.of(MemoryScope.USER, identity).as_tuple())

    async def drain() -> None:
        await _drain(relay, records)

    async def real_count(memory_id: str, identity: IdentityContext) -> int:
        return await _real_count(vectors, gate_settings, memory_id, identity)

    try:
        await vectors.initialize()

        creator = capability([AIMessage(content="", tool_calls=[{
            "name": "MemoryPayload",
            "args": {"content": "alice 喜欢用 Python 写数据处理脚本",
                     "metadata": {"importance": 0.7}},
            "id": "create-target"}])])
        target = await creator.store(MemoryScope.USER, "alice 喜欢用 Python 写数据处理脚本",
                                     {"importance": 0.7})
        control = await creator.store(MemoryScope.USER, "鲸鱼是生活在海洋中的哺乳动物",
                                      {"importance": 0.1})
        bob_token = set_identity_context(bob)
        try:
            bob_memory = await LangMemMemoryCapability(records, vectors).store(
                MemoryScope.USER, "bob 的私人偏好：喜欢用 C++", {"importance": 0.5})
        finally:
            identity_context_var.reset(bob_token)
        await drain()
        assert await real_count(target, alice) == 1
        assert await real_count(control, alice) == 1
        assert await real_count(bob_memory, bob) == 1  # 隔离性的对照组

        # 真删除（上游路径）：模型发 RemoveDoc，删的是它**检索回来**的那条 id。
        remover = capability([AIMessage(content="", tool_calls=[{
            "name": "RemoveDoc", "args": {"json_doc_id": doc_id(target, alice)},
            "id": "remove-target"}])])
        await remover.store(MemoryScope.USER, "alice 改用 Rust 重写了脚本", {"importance": 0.6})
        await drain()
        assert await records.pending() == []
        with pytest.raises(KeyError):
            await records.get(target, alice)
        assert await vectors.get(target, alice, MemoryScope.USER) is None
        assert await real_count(target, alice) == 0  # 真值：索引里这条已不存在
        assert await real_count(control, alice) == 1  # 删对了那一条
        assert target not in {hit.id for hit in await remover.search(
            MemoryScope.USER, "Python 数据处理", 5)}

        # 真更新（上游路径）：PatchDoc 落到同一个 id 上，indexed 重置后由 relay 收敛。
        patcher = capability([AIMessage(content="", tool_calls=[{
            "name": "PatchDoc",
            "args": {"json_doc_id": doc_id(control, alice),
                     "planned_edits": "把对照记忆改写为更精确的表述",
                     "patches": [{"op": "replace", "path": "/content",
                                  "value": "鲸鱼是生活在海洋中的哺乳动物，用肺呼吸"}]},
            "id": "patch-control"}])])
        await patcher.store(MemoryScope.USER, "鲸鱼用肺呼吸", {"importance": 0.1})
        stored = await records.get(control, alice)
        assert stored.content == "鲸鱼是生活在海洋中的哺乳动物，用肺呼吸"
        assert stored.indexed is False  # 被改过 → 必须重新同步索引
        await drain()
        row = await vectors.get(control, alice, MemoryScope.USER)
        assert row is not None and "用肺呼吸" in row["content"]
        assert await real_count(control, alice) == 1  # 更新不是删除

        # 隔离性：指名要删 bob 的文档 id —— 既碰不到记录行，也碰不到索引。
        attacker = capability([AIMessage(content="", tool_calls=[{
            "name": "RemoveDoc", "args": {"json_doc_id": doc_id(bob_memory, bob)},
            "id": "remove-foreign"}])])
        await attacker.store(MemoryScope.USER, "alice 的一次无关写入", {"importance": 0.2})
        await drain()
        assert (await records.get(bob_memory, bob)).content == "bob 的私人偏好：喜欢用 C++"
        assert await real_count(bob_memory, bob) == 1
    finally:
        try:
            for entry in await records.list_by_scope(MemoryScope.USER, alice, 100):
                await records.delete(entry.id, alice)
            for entry in await records.list_by_scope(MemoryScope.USER, bob, 100):
                await records.delete(entry.id, bob)
            await drain()
            created = vectors.created_collection
            await vectors.drop_created_collection()
            if created:
                assert gate_settings.milvus_collection not in await vectors.connect()
        finally:
            await relay.stop()
            await vectors.close()
            identity_context_var.reset(token)


async def test_real_forget_tool_reaches_milvus_and_listing_sees_the_authority(
    gate_settings, tmp_path
):
    """MEM-4（#159）真实验收：遗忘**工具**真的改到真索引，`list_entries` 读的是权威记录。

    分工说明：#159 的用户 API 用真 uvicorn + 真 HTTP 的 gate 脚本验收
    （`.scratch/run_forget_entry_gate.py`）；这里钉的是**不用起服务**也能跑的那半——
    工具的审批闸门 + 真删除 + 真实 count（AC9 的口径：`query(count(*))`，不用
    `get_collection_stats`），以及契约方法 `list_entries` 在真 provider 上的行为。
    """
    from langchain_openai import OpenAIEmbeddings

    from agent_harness.identity import identity_context_var, set_identity_context
    from agent_harness.memory.langmem_capability import LangMemMemoryCapability
    from agent_harness.memory.outbox_relay import OutboxRelay
    from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
    from agent_harness.memory.tools import ForgetMemoryTool, _ForgetMemoryArgs
    from agent_harness.tooling import (
        ApprovalRequest,
        ApprovalResponse,
        ErrorCode,
        PermissionPolicy,
        ToolExecutor,
        ToolRegistry,
    )

    if not gate_settings.embedding_api_key.get_secret_value() or not gate_settings.embedding_model:
        pytest.skip("Real embedding model is not configured")

    embeddings = OpenAIEmbeddings(
        model=gate_settings.embedding_model, base_url=gate_settings.embedding_base_url,
        api_key=gate_settings.embedding_api_key, check_embedding_ctx_length=False,
        dimensions=gate_settings.embedding_dimensions, request_timeout=30, max_retries=3,
    )
    vectors = MilvusVectorStore(gate_settings, embeddings)
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    relay = OutboxRelay(records, vectors)
    capability = LangMemMemoryCapability(records, vectors)
    alice = IdentityContext("gate_forget_tool_" + uuid4().hex, "alice", ["user"])
    token = set_identity_context(alice)
    registry = ToolRegistry()
    registry.register(ForgetMemoryTool(capability))

    async def approved(_req: ApprovalRequest) -> ApprovalResponse:
        return ApprovalResponse(approved=True, reason="gate")

    try:
        await vectors.initialize()
        doomed = await capability.store(MemoryScope.USER, "alice 的旧偏好：喜欢用 Python", {})
        control = await capability.store(MemoryScope.USER, "鲸鱼是生活在海洋中的哺乳动物", {})
        await _drain(relay, records)
        assert await _real_count(vectors, gate_settings, doomed, alice) == 1

        # `list_entries` 读权威记录（不走 embedding）：两条都在，属于自己。
        listed = await capability.list_entries(MemoryScope.USER, 10)
        assert {entry.id for entry in listed} == {doomed, control}
        # 分页参数在真 provider 上也成立：limit=1 只返回一条（`!= []` 会漏掉"忽略 limit"）。
        assert len(await capability.list_entries(MemoryScope.USER, 1)) == 1

        # 没有审批回调 → DANGER 工具被拒（安全默认值），真实 count 不变。
        denied = (await ToolExecutor(registry, policy=PermissionPolicy.WORKSPACE_WRITE)
                  .execute({"id": "c1", "name": "forget_memory", "args": {"memory_id": doomed}})).result
        assert denied.ok is False and denied.error_code is ErrorCode.PERMISSION_DENIED
        assert await _real_count(vectors, gate_settings, doomed, alice) == 1

        # 审批通过 → 工具真的删：真实 count 1 → 0，对照组仍是 1。
        executor = ToolExecutor(registry, policy=PermissionPolicy.WORKSPACE_WRITE,
                                approval_callback=approved)
        result = (await executor.execute(
            {"id": "c2", "name": "forget_memory", "args": {"memory_id": doomed}})).result
        assert result.ok is True and result.data["forgotten"] is True
        await _drain(relay, records)
        assert await _real_count(vectors, gate_settings, doomed, alice) == 0
        assert await _real_count(vectors, gate_settings, control, alice) == 1
        assert doomed not in {entry.id for entry in await capability.list_entries(MemoryScope.USER, 10)}

        # 幂等：再忘一次说的是"不存在"，不是错误。
        again = await ForgetMemoryTool(capability).execute(_ForgetMemoryArgs(memory_id=doomed))
        assert again.ok is True and again.data["forgotten"] is False
    finally:
        try:
            for entry in await records.list_by_scope(MemoryScope.USER, alice, 100):
                await records.delete(entry.id, alice)
            await _drain(relay, records)
            created = vectors.created_collection
            await vectors.drop_created_collection()
            if created:
                assert gate_settings.milvus_collection not in await vectors.connect()
        finally:
            await relay.stop()
            await vectors.close()
            identity_context_var.reset(token)
