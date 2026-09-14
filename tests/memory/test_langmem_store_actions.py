"""MEM-2（#157）解禁 LangMem 的 update/delete：adapter 的 PutOp 分支 + manager 真动作。

上游本来就有删除能力，是我们关了四处；MEM-1（#156）铺好权威层机制（`update`/`forget` 动词、
outbox 操作类型、硬删端到端）之后，本票只做**接线**，让 LangMem 自己的 Compare&Update /
Remove 真的落到记录库与向量索引上。

本文件钉两类事：
1. **adapter 层的形状映射**（确定性，不依赖 trustcall）：LangGraph 的 `store.adelete(ns, key)`
   就是 `PutOp(namespace, key, None)`，必须映射到 `MemoryRecordStore.delete` 而不是
   `NotImplementedError`；`ttl` 仍拒绝（另一套语义，不顺手实现）；跨 namespace 删除必须被拒。
2. **manager 层的真实动作**（脚本化模型 + 真 trustcall/langmem）：模型发起 delete →
   记录行消失 + 向量消失 + 检索不到；模型发起 update → 同 id 覆盖、`indexed` 重置、重新入 outbox；
   以及"provider 的删除碰不到别人的记忆"这条隔离性。

判定"删除真的发生了"用记录行 / outbox 意图 / 向量 / 检索四处**独立**证据，而不是"方法没报错"
——后者在把 `NotImplementedError` 换成静默 `pass` 的实现下同样成立。
"""

import logging

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from langgraph.store.base import PutOp
from pydantic import Field

from agent_harness.identity import (
    IdentityContext,
    identity_context_var,
    set_identity_context,
)
from agent_harness.memory.base_store_adapter import SqliteMilvusBaseStore
from agent_harness.memory.fake_vector_store import FakeVectorStore
from agent_harness.memory.outbox_relay import OutboxRelay
from agent_harness.memory.record_store import MemoryOperation
from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
from agent_harness.memory.types import (
    MemoryEntry,
    MemoryNamespace,
    MemoryScope,
)
from tests.langmem_doubles import AlwaysHitVectorStore, ScriptedChatModel, stable_doc_id

ALICE = IdentityContext("acme", "alice", ["user", "session"])
BOB = IdentityContext("acme", "bob", ["user"])
OTHER_TENANT = IdentityContext("other", "alice", ["user"])
ADAPTER_LOGGER = "agent_harness.memory.base_store_adapter"


def entry(memory_id: str, content: str) -> MemoryEntry:
    return MemoryEntry(id=memory_id, content=content, metadata={"importance": 0.5},
                       created_at="2026-09-04T00:00:00+00:00", scope=MemoryScope.USER)


def payload(content: str, importance: float = 0.5) -> dict:
    return {"kind": "MemoryPayload", "content": {"content": content,
                                                 "metadata": {"importance": importance}}}


def namespace_of(identity: IdentityContext = ALICE) -> tuple[str, ...]:
    return MemoryNamespace.of(MemoryScope.USER, identity).as_tuple()


def stable_id(memory_id: str, identity: IdentityContext = ALICE) -> str:
    """LangMem 认的文档 id（`MemoryStoreManager._stable_id` 的同一公式，见共享模块）。"""
    return stable_doc_id(memory_id, namespace_of(identity))


class ScriptedModel(ScriptedChatModel):
    """按序吐脚本化响应的假模型（trustcall 形状见 `tests.langmem_doubles`）。"""


@pytest_asyncio.fixture
async def rig(tmp_path):
    """记录库 + 向量替身 + adapter，全程在 alice 的身份上下文里（adapter 依赖它取授权）。"""
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    vectors = FakeVectorStore()
    adapter = SqliteMilvusBaseStore(records, vectors)
    token = set_identity_context(ALICE)
    try:
        yield records, vectors, adapter
    finally:
        identity_context_var.reset(token)


class TestPutOpShapeMapping:
    """AC1：`PutOp(value=None)` 是删除，不是"未实现"。"""

    @pytest.mark.asyncio
    async def test_none_value_hard_deletes_and_propagates_to_the_index(self, rig):
        records, vectors, adapter = rig
        await adapter.abatch([PutOp(namespace_of(), "m1", payload("secret"))])
        assert await OutboxRelay(records, vectors).flush() == 1
        assert (await vectors.get("m1", ALICE, MemoryScope.USER))["content"] == "secret"

        assert await adapter.abatch([PutOp(namespace_of(), "m1", None)]) == [None]

        assert [c.operation for c in await records.pending()] == [MemoryOperation.DELETE]
        with pytest.raises(KeyError):
            await records.get("m1", ALICE)
        assert await OutboxRelay(records, vectors).flush() == 1
        assert await vectors.search("secret", ALICE, MemoryScope.USER, 5) == []
        assert await vectors.get("m1", ALICE, MemoryScope.USER) is None

    @pytest.mark.asyncio
    async def test_delete_of_an_absent_key_is_a_logged_no_op(self, rig, caplog):
        """幂等但不静默：没命中任何记录行时留下告警（BUG-012 的"不得静默"契约）。

        也不得因此产生一条空的删除意图——没有记录行就没有可路由的 namespace。
        """
        records, _, adapter = rig
        with caplog.at_level(logging.WARNING, logger=ADAPTER_LOGGER):
            assert await adapter.abatch([PutOp(namespace_of(), "ghost", None)]) == [None]
        assert await records.pending() == []
        assert "ghost" in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("foreign", "secret"), [
        (BOB, "bob 的秘密"),
        (OTHER_TENANT, "另一个租户的秘密"),
    ], ids=["other-user-same-tenant", "other-tenant"])
    async def test_delete_cannot_cross_namespace(self, rig, foreign, secret):
        """AC2 的隔离面：provider 的删除动作碰不到别的 tenant/user 的记忆。

        直接以"外来 namespace + 别人的 key"构造最坏形状：授权校验必须拒绝，
        且对方记录与向量**都还在**（对照断言，防"拒绝了但已经删掉"）。

        两个形状都要试：换 user 与换 tenant 都走 `MemoryNamespace.authorize`，但过滤表达式
        不同（tenant_id 也在 filter 里），只测其中一个等于放过另一段。
        """
        records, vectors, adapter = rig
        await records.store(entry("m1", secret), foreign)  # 尚未 flush：outbox 里留着 UPSERT
        assert [c.operation for c in await records.pending()] == [MemoryOperation.UPSERT]

        with pytest.raises(PermissionError):
            await adapter.abatch([PutOp(namespace_of(foreign), "m1", None)])

        # 被拒的删除**什么都没动**：outbox 仍是那条 UPSERT（没被替换成 DELETE）。
        assert [c.operation for c in await records.pending()] == [MemoryOperation.UPSERT]
        assert (await records.get("m1", foreign)).content == secret
        await OutboxRelay(records, vectors).flush()
        assert (await vectors.get("m1", foreign, MemoryScope.USER))["content"] == secret

    @pytest.mark.asyncio
    async def test_ttl_is_still_rejected(self, rig):
        """AC1 的判定项：TTL 仍拒绝（**有意**）。

        TTL 是"到点自动过期"的另一套语义，本票不实现；静默忽略会产出一个我们永远不会兑现的
        承诺（记忆声称会过期却永不消失）。今天它事实上也不可达——LangGraph 在
        `supports_ttl=False` 时于公开 API 就拒绝带 TTL 的写入，这里是防御性边界。
        """
        _, _, adapter = rig
        with pytest.raises(NotImplementedError, match="TTL"):
            await adapter.abatch([PutOp(namespace_of(), "m1", payload("secret"), ttl=60)])

    @pytest.mark.asyncio
    async def test_delete_shape_with_a_ttl_is_rejected_and_has_no_side_effect(self, rig):
        """畸形组合 `value=None, ttl=...`（既删又过期）也必须被拒——分支顺序与文档一致。

        公开 API 不可达（`supports_ttl=False` + `adelete` 传 `ttl=None`），但 `abatch` 是公开
        方法，边界检查就该盖住整个边界：一个"先判 value 再判 ttl"的实现会把它当成普通删除静默
        放行，于是"带 TTL 的写入一律拒绝"这条契约在**组合形状**上被绕过。
        """
        records, _, adapter = rig
        await adapter.abatch([PutOp(namespace_of(), "m1", payload("secret"))])

        with pytest.raises(NotImplementedError, match="TTL"):
            await adapter.abatch([PutOp(namespace_of(), "m1", None, ttl=60)])

        # 更关键的一层：被拒的畸形 op 不得已经造成副作用（那才是"静默删除"的真实伤害）。
        assert (await records.get("m1", ALICE)).content == "secret"
        assert [c.operation for c in await records.pending()] == [MemoryOperation.UPSERT]

    @pytest.mark.asyncio
    async def test_value_at_an_existing_key_is_an_update_not_a_new_row(self, rig):
        """AC4 的 update 面（adapter 层）：同 key 覆盖 → 内容为新值、`indexed` 重置、重新入 outbox。

        这条正是 manager 的 `final_puts`（命中既有 doc）走的路：LangMem 判"要更新"之后
        落到的就是这个 `PutOp(value=...)`。
        """
        records, vectors, adapter = rig
        await adapter.abatch([PutOp(namespace_of(), "m1", payload("旧内容"))])
        stale = (await records.pending())[0]
        assert await OutboxRelay(records, vectors).flush() == 1

        await adapter.abatch([PutOp(namespace_of(), "m1", payload("新内容"))])
        changes = await records.pending()
        assert [c.memory_id for c in changes] == ["m1"]  # 仍是一行
        assert changes[0].revision != stale.revision  # 新意图（不是被 ack 掉的那条）
        assert changes[0].entry is not None and changes[0].entry.content == "新内容"
        assert (await records.get("m1", ALICE)).indexed is False
        assert await OutboxRelay(records, vectors).flush() == 1
        assert (await vectors.get("m1", ALICE, MemoryScope.USER))["content"] == "新内容"
        assert await vectors.search("旧内容", ALICE, MemoryScope.USER, 5) == []


async def _langmem_capability(tmp_path, vectors, responses):
    """用给定向量替身与脚本化模型构造 capability（身份上下文由调用方设置）。"""
    pytest.importorskip("langmem")
    from agent_harness.memory.langmem_capability import LangMemMemoryCapability

    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    capability = LangMemMemoryCapability(records, vectors, ScriptedModel(responses=responses))
    return records, capability


def _tool_name(tool) -> str:
    if isinstance(tool, dict):  # 提取阶段会把 schema 以字典形式交给模型
        return tool.get("function", {}).get("name") or tool.get("name") or str(tool)
    return getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))


class ToolRecordingModel(ScriptedChatModel):
    """额外记录每次 `bind_tools` 施加上来的工具名——两个开关改的正是这个工具面。"""

    bound_tool_names: list[list[str]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names.append([_tool_name(tool) for tool in tools])
        return self


class TestManagerActions:
    """AC2/AC4：模型（manager）发起的 create/update/delete 真的落到存储与索引。"""

    @pytest.mark.asyncio
    async def test_manager_delete_removes_record_index_and_retrieval(self, tmp_path):
        """真删除：outbox 出现 DELETE 意图 + 记录行消失 + 向量消失 + 检索不到。"""
        vectors = AlwaysHitVectorStore()
        records, capability = await _langmem_capability(tmp_path, vectors, [
            AIMessage(content="", tool_calls=[{
                "name": "MemoryPayload",
                "args": {"content": "alice 喜欢 TypeScript", "metadata": {"importance": 0.8}},
                "id": "create-one"}]),
        ])
        token = set_identity_context(ALICE)
        try:
            memory_id = await capability.store(MemoryScope.USER, "alice 喜欢 TypeScript",
                                               {"importance": 0.8})
            assert await OutboxRelay(records, vectors).flush() == 1
            assert (await vectors.get(memory_id, ALICE, MemoryScope.USER)) is not None
        finally:
            identity_context_var.reset(token)

        # 第二条响应要引用"manager 认的稳定 id"，只能等记忆写进去之后才知道 —— 所以换模型重建。
        from agent_harness.memory.langmem_capability import LangMemMemoryCapability
        capability = LangMemMemoryCapability(records, vectors, ScriptedModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "RemoveDoc", "args": {"json_doc_id": stable_id(memory_id)},
                "id": "remove-one"}])]))
        token = set_identity_context(ALICE)
        try:
            # 第二个候选内容与"被删的那条"不同（真实形状：模型删掉过时记忆、同时写入新事实），
            # 否则 `store()` 的兜底会因为"同内容已存在"而把刚删掉的 id 又还回去。
            await capability.store(MemoryScope.USER, "alice 现在用 Rust", {"importance": 0.5})
        finally:
            identity_context_var.reset(token)

        # 两个意图：manager 删掉旧记忆（DELETE）+ `store()` 的兜底把本次候选写成新记忆（UPSERT）
        # —— 这正是生产里的真实形状（"这条过时了"与"同时学到新事实"发生在同一次写入里）。
        operations = {(c.memory_id, c.operation) for c in await records.pending()}
        assert (memory_id, MemoryOperation.DELETE) in operations
        with pytest.raises(KeyError):
            await records.get(memory_id, ALICE)
        assert await OutboxRelay(records, vectors).flush() == len(operations)  # 两条意图都应用
        assert await records.pending() == []
        assert await vectors.get(memory_id, ALICE, MemoryScope.USER) is None
        # 判定"无残留"只能按 id 成员断言：本替身（以及真实 embedding 检索）会返回最近的若干条，
        # 兜底新建的那条记忆同样在该 namespace 里，所以"检索为空"不是正确的期望形状。
        hits = await vectors.search("TypeScript", ALICE, MemoryScope.USER, 5)
        assert memory_id not in {key for key, _ in hits}

    @pytest.mark.asyncio
    async def test_manager_update_overwrites_content_and_resets_indexing(self, tmp_path):
        """真更新：同 id 覆盖为新内容、`indexed` 重置、重新入 outbox（revision 变化）。"""
        vectors = AlwaysHitVectorStore()
        from langchain_core.messages import AIMessage as Message

        records, capability = await _langmem_capability(tmp_path, vectors, [
            Message(content="", tool_calls=[{
                "name": "MemoryPayload",
                "args": {"content": "alice 喜欢 Python", "metadata": {"importance": 0.3}},
                "id": "create-one"}]),
        ])
        token = set_identity_context(ALICE)
        try:
            memory_id = await capability.store(MemoryScope.USER, "alice 喜欢 Python",
                                               {"importance": 0.3})
            assert await OutboxRelay(records, vectors).flush() == 1
        finally:
            identity_context_var.reset(token)

        from agent_harness.memory.langmem_capability import LangMemMemoryCapability
        capability = LangMemMemoryCapability(records, vectors, ScriptedModel(responses=[
            Message(content="", tool_calls=[{
                "name": "PatchDoc",
                "args": {"json_doc_id": stable_id(memory_id),
                         "planned_edits": "把偏好从 Python 改成 TypeScript",
                         "patches": [{"op": "replace", "path": "/content",
                                      "value": "alice 喜欢 TypeScript"}]},
                "id": "patch-one"}])]))
        token = set_identity_context(ALICE)
        try:
            await capability.store(MemoryScope.USER, "alice 喜欢 TypeScript", {"importance": 0.3})
        finally:
            identity_context_var.reset(token)

        stored = await records.get(memory_id, ALICE)
        assert stored.content == "alice 喜欢 TypeScript"
        assert stored.indexed is False  # 被改过 → 必须重新同步索引
        changes = await records.pending()
        assert [c.memory_id for c in changes] == [memory_id]
        assert changes[0].operation is MemoryOperation.UPSERT
        assert changes[0].entry is not None and changes[0].entry.content == "alice 喜欢 TypeScript"
        assert await OutboxRelay(records, vectors).flush() == 1
        assert (await vectors.get(memory_id, ALICE, MemoryScope.USER))["content"] == "alice 喜欢 TypeScript"

    @pytest.mark.asyncio
    async def test_manager_delete_leaves_another_identity_memory_untouched(self, tmp_path):
        """AC2 的隔离面（端到端）：删自己的那条，别人的记录与向量都得原样在。

        对照组用**同内容、不同 id、不同 namespace** 的记忆：内容一样，才能证明"没被删"是
        隔离起了作用而不是"检索没命中所以顺手没动"。记忆 id 是全局主键，同一 id 只属于一个
        namespace（#156 的 store 会拒绝跨归属覆盖），所以对照组必须换 id。
        """
        vectors = AlwaysHitVectorStore()
        records, capability = await _langmem_capability(tmp_path, vectors, [])
        await records.store(entry("alice-mine", "喜欢 TypeScript"), ALICE)
        await records.store(entry("bob-mine", "喜欢 TypeScript"), BOB)
        await OutboxRelay(records, vectors).flush()

        from agent_harness.memory.langmem_capability import LangMemMemoryCapability
        capability = LangMemMemoryCapability(records, vectors, ScriptedModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "RemoveDoc", "args": {"json_doc_id": stable_id("alice-mine")},
                "id": "remove-one"}])]))
        token = set_identity_context(ALICE)
        try:
            # 候选内容与两条既有记忆都不同：只考察"删除落在了谁身上"。
            await capability.store(MemoryScope.USER, "换用 Rust 了", {})
        finally:
            identity_context_var.reset(token)
        await OutboxRelay(records, vectors).flush()

        with pytest.raises(KeyError):
            await records.get("alice-mine", ALICE)
        assert (await records.get("bob-mine", BOB)).content == "喜欢 TypeScript"
        assert (await vectors.get("bob-mine", BOB, MemoryScope.USER))["content"] == "喜欢 TypeScript"
        assert await vectors.get("alice-mine", ALICE, MemoryScope.USER) is None

    @pytest.mark.asyncio
    async def test_removal_without_an_existing_memory_is_inert(self, tmp_path):
        """上游组合语义（`enable_inserts`/`enable_deletes` 都开）：没有既有记忆时，
        `RemoveDoc` 连工具都不会被绑定 —— 孤立的一次删除请求不得产生"幽灵删除"。

        这里钉的是**没有删除意图**这半边：记录库为空 → 不能出现 DELETE 行，也不得报错。
        """
        vectors = AlwaysHitVectorStore()
        records, capability = await _langmem_capability(tmp_path, vectors, [
            AIMessage(content="", tool_calls=[{
                "name": "RemoveDoc", "args": {"json_doc_id": stable_id("ghost")},
                "id": "remove-one"}]),
        ])
        token = set_identity_context(ALICE)
        try:
            await capability.store(MemoryScope.USER, "任何内容", {})
        finally:
            identity_context_var.reset(token)

        changes = await records.pending()
        # 关键：**不得出现幽灵删除**。断言 `!= [DELETE]` 是假的——这条路径总会退回
        # "照常写入"，于是 changes 里必有一个 UPSERT，该断言永远成立。
        assert MemoryOperation.DELETE not in {c.operation for c in changes}
        # 上游此路径退回"照常写入"（fallback 到 manage 工具），记录行确实存在。
        assert len(await records.list_by_scope(MemoryScope.USER, ALICE, 10)) == 1


class TestSwitchCombinations:
    """AC4：`enable_inserts` / `enable_deletes` 是两个**独立**开关（上游默认都开，我们此前关了删除）。

    capability 在生产上永远全开、不暴露开关，所以组合语义只能直接钉在 manager 上。
    实测语义（先跑探针再写断言）：两个开关改的是**施加给模型的工具面**（`bind_tools`），
    而不是写路径上的强制——把 insert 关掉之后，一个"仍然发出插入工具调用"的模型照样会被 manager
    接受写入。所以"关掉 insert 就等于不会新增记忆"不是上游保证，不能写成断言；这里只钉两个可被
    证伪的事实：工具面差异，以及删除行为本身。
    """

    async def _run(self, tmp_path, *, enable_inserts, enable_deletes, script):
        """真 manager + 真 adapter + 真 trustcall：预置一条既有记忆，跑一次脚本化动作。

        返回（记录库, 向量, 模型, manager 的返回值）。
        """
        pytest.importorskip("langmem")
        from langmem import create_memory_store_manager

        from agent_harness.memory.langmem_capability import MemoryPayload

        records = SqliteMemoryRecordStore(tmp_path / "memory.db")
        await records.initialize()
        vectors = AlwaysHitVectorStore()
        adapter = SqliteMilvusBaseStore(records, vectors)
        model = ToolRecordingModel(responses=script)
        manager = create_memory_store_manager(
            model, schemas=[MemoryPayload], namespace=namespace_of(), store=adapter,
            enable_inserts=enable_inserts, enable_deletes=enable_deletes)
        token = set_identity_context(ALICE)
        try:
            await records.store(entry("m1", "alice 喜欢 Python"), ALICE)
            assert await OutboxRelay(records, vectors).flush() == 1
            outcome = await manager.ainvoke(
                {"messages": [{"role": "user", "content": "把过时的偏好删掉"}], "max_steps": 1})
        finally:
            identity_context_var.reset(token)
        return records, vectors, model, outcome

    @staticmethod
    def _remove_existing() -> list[AIMessage]:
        return [AIMessage(content="", tool_calls=[{
            "name": "RemoveDoc", "args": {"json_doc_id": stable_id("m1")}, "id": "remove-one"}])]

    @pytest.mark.asyncio
    async def test_delete_survives_disabled_inserts(self, tmp_path):
        """关掉插入不得连坐删除：`enable_inserts=False` + `enable_deletes=True` 下，
        对既有记忆的 RemoveDoc 照常落到记录行。"""
        records, _, model, outcome = await self._run(
            tmp_path, enable_inserts=False, enable_deletes=True, script=self._remove_existing())

        assert outcome == []  # 删除意图没有被回吐成写入
        assert await records.list_by_scope(MemoryScope.USER, ALICE, 10) == []
        with pytest.raises(KeyError):
            await records.get("m1", ALICE)
        # 工具面就是开关的作用面：提供 RemoveDoc 的那次 bind 里不再有插入工具，而删除工具仍在。
        manage = next(names for names in model.bound_tool_names if "RemoveDoc" in names)
        assert "MemoryPayload" not in manage

    @pytest.mark.asyncio
    async def test_disabled_deletes_turn_a_removal_into_a_no_op(self, tmp_path):
        """反向组合：`enable_inserts=True` + `enable_deletes=False` 时，模型发出的删除请求被安全
        忽略——既有记忆还在，且不抛异常。关掉删除既不能变成报错，也不能变成"照样删"。"""
        records, _, model, outcome = await self._run(
            tmp_path, enable_inserts=True, enable_deletes=False, script=self._remove_existing())

        assert outcome == []
        assert (await records.get("m1", ALICE)).content == "alice 喜欢 Python"
        assert not any("RemoveDoc" in names for names in model.bound_tool_names)

    @pytest.mark.asyncio
    async def test_both_switches_on_offer_insert_and_delete_together(self, tmp_path):
        """对照组（上游默认组合）：插入与删除工具出现在同一个工具面上，且删除真的生效。"""
        records, _, model, _ = await self._run(
            tmp_path, enable_inserts=True, enable_deletes=True, script=self._remove_existing())

        manage = next(names for names in model.bound_tool_names if "RemoveDoc" in names)
        assert "MemoryPayload" in manage
        assert await records.list_by_scope(MemoryScope.USER, ALICE, 10) == []


class TestSearchTolerance:
    @pytest.mark.asyncio
    async def test_search_skips_a_row_whose_record_vanished(self, tmp_path):
        """provider 删除被解禁后新出现的窗口：索引里还有、记录行已不在。

        删除先落记录行、向量由 relay 异步收敛，所以"检索返回之后、读记录行之前"这一瞬是可达的
        （TOCTOU）。能力层的检索必须跳过这类行——adapter 的 SearchOp 分支一直这么容忍，
        能力层不该比它更脆。这里用一个"asearch 直接返回已消失 id"的 store 把窗口固定下来。
        """
        from datetime import UTC, datetime

        from langgraph.store.base import SearchItem

        pytest.importorskip("langmem")
        from agent_harness.memory.langmem_capability import LangMemMemoryCapability

        class VanishingStore(SqliteMilvusBaseStore):
            async def asearch(self, namespace_prefix, **kwargs):
                now = datetime.now(UTC)
                return [SearchItem(namespace=tuple(namespace_prefix), key="gone",
                                   value={"kind": "MemoryPayload",
                                          "content": {"content": "已经不在了", "metadata": {}}},
                                   created_at=now, updated_at=now, score=1.0)]

        records = SqliteMemoryRecordStore(tmp_path / "memory.db")
        await records.initialize()
        vectors = FakeVectorStore()
        capability = LangMemMemoryCapability(records, vectors, ScriptedModel(responses=[]))
        capability._store = VanishingStore(records, vectors)

        token = set_identity_context(ALICE)
        try:
            assert await capability.search(MemoryScope.USER, "已经不在了", 5) == []
        finally:
            identity_context_var.reset(token)


class TestManageToolContract:
    @pytest.mark.asyncio
    async def test_capability_hands_upstream_default_actions_to_the_manage_tool(self, tmp_path, monkeypatch):
        """AC2：不再对外声称一个被我们收窄的能力。

        `actions_permitted` 同时决定工具描述与 `action` 参数的可选值域，所以"我们传了什么"
        是契约的一部分；而本处调用只传 `content`（`action` 默认 create），所以放宽之后
        这条直调仍然是**非破坏性**的——本用例同时钉这两件事。
        """
        pytest.importorskip("langmem")
        from agent_harness.memory.langmem_capability import LangMemMemoryCapability

        vectors = AlwaysHitVectorStore()
        records = SqliteMemoryRecordStore(tmp_path / "memory.db")
        await records.initialize()
        # 不带模型：`store()` 直走 manage 工具（不走 manager），正是要观察的那条调用。
        capability = LangMemMemoryCapability(records, vectors)
        seen: dict = {}
        real_manage = capability._manage

        def spy_manage(**kwargs):
            seen.update(kwargs)
            return real_manage(**kwargs)

        monkeypatch.setattr(capability, "_manage", spy_manage)
        token = set_identity_context(ALICE)
        try:
            memory_id = await capability.store(MemoryScope.USER, "直调仍应创建", {})
        finally:
            identity_context_var.reset(token)

        assert seen["actions_permitted"] == ("create", "update", "delete")
        # 非破坏性：直调没有传 action/id → 默认 create（记录行确实被创建）。
        assert (await records.get(memory_id, ALICE)).content == "直调仍应创建"
