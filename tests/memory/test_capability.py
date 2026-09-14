"""MemoryCapability 可替换性，LangMem 真工具经过项目 BaseStore。"""

import pytest

from agent_harness.identity import (
    IdentityContext,
    identity_context_var,
    set_identity_context,
)
from agent_harness.memory.fake_capability import FakeMemoryCapability
from agent_harness.memory.fake_vector_store import FakeVectorStore
from agent_harness.memory.outbox_relay import OutboxRelay
from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
from agent_harness.memory.types import MemoryScope
from tests.langmem_doubles import ScriptedChatModel


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["fake", "langmem"])
async def test_capability_store_recall_and_identity_isolation(tmp_path, backend):
    relay = None
    if backend == "fake":
        capability = FakeMemoryCapability()
    else:
        pytest.importorskip("langmem")
        from agent_harness.memory.langmem_capability import LangMemMemoryCapability
        records = SqliteMemoryRecordStore(tmp_path / "memory.db")
        await records.initialize()
        vectors = FakeVectorStore()
        relay = OutboxRelay(records, vectors)
        capability = LangMemMemoryCapability(records, vectors)
    token = set_identity_context(IdentityContext("acme", "alice", ["user"]))
    try:
        memory_id = await capability.store(MemoryScope.USER, "I prefer TypeScript", {"importance": 0.8})
        if relay:
            await relay.flush()
        result = await capability.recall(MemoryScope.USER, "TypeScript", 2)
        assert len(result) == 1
        assert result[0].id == memory_id
        assert result[0].content == "I prefer TypeScript"
        assert result[0].metadata["importance"] == 0.8
        for other in (IdentityContext("acme", "bob", ["user"]), IdentityContext("other", "alice", ["user"])):
            other_token = set_identity_context(other)
            try:
                assert await capability.search(MemoryScope.USER, "TypeScript", 2) == []
            finally:
                identity_context_var.reset(other_token)
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["fake", "langmem"])
async def test_capability_update_and_forget_contract(tmp_path, backend):
    """AC1：`update`（按 id 覆盖写）与 `forget`（硬删）在两个可替换实现上同一套语义。

    `update` 是**机制**：同 namespace 内按 id 覆盖，last-write-wins；"该不该更新、
    更新哪一条"是冲突消解（#158）的策略。`forget` 对不存在的 id 是幂等 `False`。
    """
    relay = None
    if backend == "fake":
        capability = FakeMemoryCapability()
    else:
        pytest.importorskip("langmem")
        from agent_harness.memory.langmem_capability import LangMemMemoryCapability
        records = SqliteMemoryRecordStore(tmp_path / "memory.db")
        await records.initialize()
        vectors = FakeVectorStore()
        relay = OutboxRelay(records, vectors)
        capability = LangMemMemoryCapability(records, vectors)
    token = set_identity_context(IdentityContext("acme", "alice", ["user"]))
    try:
        memory_id = await capability.store(MemoryScope.USER, "I prefer Python", {"importance": 0.3})
        if relay:
            await relay.flush()

        assert await capability.update(memory_id, MemoryScope.USER,
                                       "I prefer TypeScript", {"importance": 0.9}) == memory_id
        if relay:
            await relay.flush()
        hits = await capability.search(MemoryScope.USER, "TypeScript", 5)
        assert [hit.id for hit in hits] == [memory_id]
        assert hits[0].content == "I prefer TypeScript"
        assert hits[0].metadata["importance"] == 0.9
        assert await capability.search(MemoryScope.USER, "Python", 5) == []

        assert await capability.forget(memory_id) is True
        assert await capability.forget(memory_id) is False  # 幂等
        if relay:
            await relay.flush()
        assert await capability.search(MemoryScope.USER, "TypeScript", 5) == []
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["fake", "langmem"])
async def test_capability_update_on_an_absent_id_creates_it(tmp_path, backend):
    """AC1 的语义面：`update` 是**按 id 的覆盖写（upsert by id）**——id 不存在时按新
    记忆写入，与 `store` 的唯一区别是 id 由调用方给定。

    契约原文如此，所以把实现改回"不存在就报错"必须让本用例变红：#158 的冲突消解要用
    同一个动词表达"更新我已定位到的那一条"，而它检索到的 id 理论上可能刚被别处删掉。
    """
    relay = None
    if backend == "fake":
        capability = FakeMemoryCapability()
    else:
        pytest.importorskip("langmem")
        from agent_harness.memory.langmem_capability import LangMemMemoryCapability
        records = SqliteMemoryRecordStore(tmp_path / "memory.db")
        await records.initialize()
        vectors = FakeVectorStore()
        relay = OutboxRelay(records, vectors)
        capability = LangMemMemoryCapability(records, vectors)
    token = set_identity_context(IdentityContext("acme", "alice", ["user"]))
    try:
        assert await capability.update("chosen-id", MemoryScope.USER, "记住这条", {"importance": 0.4}) == "chosen-id"
        if relay:
            await relay.flush()
        hits = await capability.search(MemoryScope.USER, "记住这条", 5)
        assert [hit.id for hit in hits] == ["chosen-id"]
        assert hits[0].content == "记住这条"
        assert hits[0].metadata["importance"] == 0.4

        assert await capability.forget("chosen-id") is True
        if relay:
            await relay.flush()
        assert await capability.search(MemoryScope.USER, "记住这条", 5) == []
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["fake", "langmem"])
async def test_capability_forget_cannot_cross_identity(tmp_path, backend):
    """AC2 从 capability 面看：别人的记忆删不掉。

    语义是 `PermissionError` 而不是静默 `False`——静默 False 会让调用方以为"忘了"，
    而那条记忆其实还在。
    """
    relay = None
    if backend == "fake":
        capability = FakeMemoryCapability()
    else:
        pytest.importorskip("langmem")
        from agent_harness.memory.langmem_capability import LangMemMemoryCapability
        records = SqliteMemoryRecordStore(tmp_path / "memory.db")
        await records.initialize()
        vectors = FakeVectorStore()
        relay = OutboxRelay(records, vectors)
        capability = LangMemMemoryCapability(records, vectors)
    owner_token = set_identity_context(IdentityContext("acme", "alice", ["user"]))
    try:
        memory_id = await capability.store(MemoryScope.USER, "alice 的偏好", {})
        if relay:
            await relay.flush()
    finally:
        identity_context_var.reset(owner_token)
    other_token = set_identity_context(IdentityContext("acme", "bob", ["user"]))
    try:
        with pytest.raises(PermissionError):
            await capability.forget(memory_id)
        assert await capability.search(MemoryScope.USER, "偏好", 5) == []
    finally:
        identity_context_var.reset(other_token)


@pytest.mark.asyncio
async def test_langmem_manager_forms_memory_through_owned_store(tmp_path):
    pytest.importorskip("langmem")
    from langchain_core.messages import AIMessage

    from agent_harness.memory.langmem_capability import LangMemMemoryCapability

    # 用共享替身：它按生产形状应答"生成检索 query"那次调用，让下面的 responses 只对应决策。
    model = ScriptedChatModel(responses=[AIMessage(content="", tool_calls=[{
        "name": "MemoryPayload", "args": {"content": "TypeScript preference", "metadata": {"importance": 0.8}},
        "id": "extract-one",
    }]), AIMessage(content="Existing preference is unchanged")])
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    vectors = FakeVectorStore()
    capability = LangMemMemoryCapability(records, vectors, model)
    memory_id = await capability.store(MemoryScope.USER, "I prefer TypeScript", {"importance": 0.8})
    from agent_harness.identity import get_identity_context
    assert (await records.get(memory_id, get_identity_context())).content == "TypeScript preference"
    assert await OutboxRelay(records, vectors).flush() == 1
    assert (await capability.recall(MemoryScope.USER, "TypeScript", 1))[0].id == memory_id
    assert await capability.store(MemoryScope.USER, "TypeScript preference", {"importance": 0.8}) == memory_id
    assert len(await records.list_by_scope(MemoryScope.USER, get_identity_context(), 10)) == 1


@pytest.mark.asyncio
async def test_basestore_rejects_foreign_namespace_and_ignores_untrusted_index_ids(tmp_path):
    pytest.importorskip("langmem")
    from agent_harness.memory.base_store_adapter import SqliteMilvusBaseStore
    from agent_harness.memory.types import MemoryEntry
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    await records.store(MemoryEntry(id="foreign", content="private", scope=MemoryScope.USER,
                                    created_at="2026-09-04"), IdentityContext("other", "bob", ["user"]))
    class UntrustedIndex(FakeVectorStore):
        async def search(self, *args):
            return [("foreign", 1.0)]
    adapter = SqliteMilvusBaseStore(records, UntrustedIndex())
    with pytest.raises(PermissionError):
        await adapter.aget(("memories", "other", "bob", "user"), "foreign")
    assert await adapter.asearch(("memories", "local", "local", "user"), query="private") == []


@pytest.mark.asyncio
async def test_nearest_memory_does_not_replace_a_different_new_candidate(tmp_path):
    pytest.importorskip("langmem")
    from langchain_core.messages import AIMessage

    from agent_harness.memory.langmem_capability import LangMemMemoryCapability
    class Nearest(FakeVectorStore):
        async def search(self, *args):
            return [(old_id, 0.1)]
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    vector = Nearest()
    capability = LangMemMemoryCapability(records, vector)
    old_id = await capability.store(MemoryScope.USER, "I prefer Python", {})
    capability = LangMemMemoryCapability(
        records, vector, ScriptedChatModel(responses=[AIMessage(content="No changes")]))
    new_id = await capability.store(MemoryScope.USER, "I prefer TypeScript", {})
    assert new_id != old_id


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["fake", "langmem"])
async def test_capability_list_entries_paginates_within_the_namespace(tmp_path, backend):
    """#159 AC5 的机制面：`list_entries` 是"按 namespace 分页列出"。

    与 `search` 的分工：它**不经过 embedding**，读权威记录，所以"列出来的就是全部"
    （而不是"最像的那几条"）。分页用 offset/limit 切片，别人的记忆一律看不见。
    """
    relay = None
    if backend == "fake":
        capability = FakeMemoryCapability()
    else:
        pytest.importorskip("langmem")
        from agent_harness.memory.langmem_capability import LangMemMemoryCapability
        records = SqliteMemoryRecordStore(tmp_path / "memory.db")
        await records.initialize()
        vectors = FakeVectorStore()
        relay = OutboxRelay(records, vectors)
        capability = LangMemMemoryCapability(records, vectors)

    bob_token = set_identity_context(IdentityContext("acme", "bob", ["user"]))
    try:
        await capability.store(MemoryScope.USER, "bob 的秘密", {})
    finally:
        identity_context_var.reset(bob_token)

    token = set_identity_context(IdentityContext("acme", "alice", ["user"]))
    try:
        ids = [await capability.store(MemoryScope.USER, f"alice 的第 {i} 条", {}) for i in range(3)]
        if relay:
            await relay.flush()
        listed = await capability.list_entries(MemoryScope.USER, 10)
        assert {entry.id for entry in listed} == set(ids)  # 只有这三条，且都是自己的
        # 倒序契约：created_at 单调不增（按 `created_at` 直接断言，不依赖同一微秒内的
        # id tie-break——那正是随机 uuid，靠它推出的顺序会变成偶发 flake）。
        stamps = [entry.created_at for entry in listed]
        assert stamps == sorted(stamps, reverse=True)
        # 分页 = **同一个口径**的连续切片。
        newest_first = [entry.id for entry in listed]
        assert [e.id for e in await capability.list_entries(MemoryScope.USER, 2)] == newest_first[:2]
        assert [e.id for e in await capability.list_entries(MemoryScope.USER, 2, 2)] == newest_first[2:]
        assert await capability.list_entries(MemoryScope.USER, 2, 10) == []
        assert await capability.list_entries(MemoryScope.USER, 0) == []
        # 对照：别人的记忆不在列表里（namespace 由身份解析，不是查询参数）。
        assert "bob 的秘密" not in {entry.content for entry in listed}
    finally:
        identity_context_var.reset(token)
