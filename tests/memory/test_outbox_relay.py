"""SQLite 权威记录到向量索引的可重试同步。"""

import asyncio
import logging

import pytest

from agent_harness.identity import IdentityContext
from agent_harness.memory.fake_vector_store import FakeVectorStore
from agent_harness.memory.outbox_relay import OutboxRelay
from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
from agent_harness.memory.types import MemoryEntry, MemoryScope, memory_session_var

RELAY_LOGGER = "agent_harness.memory.outbox_relay"


class AckFailed(RuntimeError):
    """模拟 acknowledge（SQLite 写）持久失败。"""


class AckBrokenStore(SqliteMemoryRecordStore):
    async def acknowledge(self, change):
        raise AckFailed("ack write unavailable")


class CountingVector(FakeVectorStore):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    async def upsert(self, *args):
        self.attempts += 1
        await super().upsert(*args)


@pytest.mark.asyncio
async def test_poison_entry_is_dead_lettered_after_consecutive_failures(tmp_path):
    """持续失败的条目在连续 MAX 失败后被本进程死信跳过：不再尝试 upsert，
    outbox 行保留（indexed=FALSE 可观察，SQLite 仍是权威），新条目不受影响。"""
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["user"])
    for entry_id in ("bad", "good"):
        await store.store(MemoryEntry(id=entry_id, content="c", scope=MemoryScope.USER,
                                      created_at="2026-09-04"), alice)

    class Poisoned(FakeVectorStore):
        def __init__(self):
            super().__init__()
            self.bad_attempts = 0

        async def upsert(self, memory_id, *args):
            if memory_id == "bad":
                self.bad_attempts += 1
                raise ValueError("permanent schema mismatch")
            await super().upsert(memory_id, *args)

    vector = Poisoned()
    relay = OutboxRelay(store, vector)
    for _ in range(OutboxRelay.MAX_CONSECUTIVE_FAILURES):
        await relay.flush()
    assert vector.bad_attempts == OutboxRelay.MAX_CONSECUTIVE_FAILURES
    # 死信后不再重试毒丸（flush 返回 0 且 attempts 不再增长）；good 首轮已照常同步。
    assert await relay.flush() == 0
    assert vector.bad_attempts == OutboxRelay.MAX_CONSECUTIVE_FAILURES
    assert (await store.get("good", alice)).indexed
    bad = await store.get("bad", alice)
    assert not bad.indexed and await store.pending()


@pytest.mark.asyncio
async def test_failure_counter_resets_after_success(tmp_path):
    """间歇性失败不触发死信：一次成功把连续失败计数清零，重新计满才死信。"""
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["user"])
    await store.store(MemoryEntry(id="flaky", content="c", scope=MemoryScope.USER,
                                  created_at="2026-09-04"), alice)

    class SometimesFailing(FakeVectorStore):
        def __init__(self):
            super().__init__()
            self.fail = True

        async def upsert(self, *args):
            if self.fail:
                self.fail = False
                raise ConnectionError("offline")
            await super().upsert(*args)

    vector = SometimesFailing()
    relay = OutboxRelay(store, vector)
    for _ in range(OutboxRelay.MAX_CONSECUTIVE_FAILURES - 1):
        await relay.flush()
        vector.fail = True  # 恢复失败态，模拟每次都差一点的间歇故障
    assert await store.pending()  # 仍未同步，但计数未达死信阈值
    vector.fail = False
    assert await relay.flush() == 1
    assert (await store.get("flaky", alice)).indexed


@pytest.mark.asyncio
async def test_outbox_failure_retries_and_restarts_without_losing_record(tmp_path):
    class Flaky(FakeVectorStore):
        fail = True

        async def upsert(self, *args):
            if self.fail:
                self.fail = False
                raise ConnectionError("offline")
            await super().upsert(*args)

    path = tmp_path / "memory.db"
    store = SqliteMemoryRecordStore(path)
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["user"])
    entry = MemoryEntry(id="one", content="TypeScript", scope=MemoryScope.USER, created_at="2026-09-04")
    await store.store(entry, alice)
    vector = Flaky()
    relay = OutboxRelay(store, vector)
    assert await relay.flush() == 0
    assert not (await store.get("one", alice)).indexed
    restarted = OutboxRelay(SqliteMemoryRecordStore(path), vector)
    assert await restarted.flush() == 1
    assert (await store.get("one", alice)).indexed
    assert await restarted.flush() == 0
    assert await vector.search("TypeScript", alice, MemoryScope.USER, 5) == [("one", 1.0)]


@pytest.mark.asyncio
async def test_relay_retains_concurrent_update_and_restores_session_identity(tmp_path):
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["session"])
    entry = MemoryEntry(id="one", content="old", scope=MemoryScope.SESSION, created_at="2026-09-04")
    token = memory_session_var.set("one-session")
    try:
        await store.store(entry, alice)
    finally:
        memory_session_var.reset(token)

    class Updating(FakeVectorStore):
        once = True

        async def upsert(self, *args):
            await super().upsert(*args)
            if self.once:
                self.once = False
                await store.store(entry.model_copy(update={"content": "new"}), alice)

    vector = Updating()
    relay = OutboxRelay(store, vector, poll_interval_seconds=0.01)
    assert await relay.flush() == 0
    assert memory_session_var.get() is None
    relay.start()
    try:
        async with asyncio.timeout(2):
            while await store.pending():
                await asyncio.sleep(0.01)
    finally:
        await relay.stop()
    token = memory_session_var.set("one-session")
    try:
        assert await vector.search("new", alice, MemoryScope.SESSION, 1) == [("one", 1.0)]
        assert (await store.get("one", alice)).indexed
    finally:
        memory_session_var.reset(token)


@pytest.mark.asyncio
async def test_failed_page_does_not_starve_later_records(tmp_path):
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    owner = IdentityContext("acme", "alice", ["user"])
    for number in range(101):
        await store.store(MemoryEntry(id=f"{number:03}", content="record", scope=MemoryScope.USER,
                                      created_at="2026-09-04"), owner)

    class Poisoned(FakeVectorStore):
        async def upsert(self, memory_id, *args):
            if memory_id != "100":
                raise ValueError("invalid record")
            await super().upsert(memory_id, *args)

    relay = OutboxRelay(store, Poisoned())
    assert await relay.flush() == 1
    assert (await store.get("100", owner)).indexed


@pytest.mark.asyncio
async def test_acknowledge_failure_is_attributed_to_ack_stage(tmp_path, caplog):
    """向量写入成功但 acknowledge（SQLite 写）失败时，失败按 ack 阶段归因记录，
    不得与 vector 失败混同；条目仍计入连续失败，outbox 行保留、下轮重试。"""
    store = AckBrokenStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["user"])
    await store.store(MemoryEntry(id="acked", content="c", scope=MemoryScope.USER,
                                  created_at="2026-09-04"), alice)

    vector = CountingVector()
    relay = OutboxRelay(store, vector)
    with caplog.at_level(logging.WARNING, logger=RELAY_LOGGER):
        await relay.flush()
    assert vector.attempts == 1  # 向量写入本身成功
    assert "ack: AckFailed" in caplog.text  # 归因到 ack 阶段
    assert "vector:" not in caplog.text  # 不得误报为 vector 失败
    assert await store.pending()  # outbox 行保留，等待下轮重试


@pytest.mark.asyncio
async def test_delete_change_calls_vectors_delete_not_upsert(tmp_path):
    """AC3 从 relay 面看：`DELETE` 变更必须调 `vectors.delete`，不得被当成 upsert
    （upsert 会把删掉的内容**写回**索引——语义上"忘不掉"的最坏形态）。"""
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["user"])
    await store.store(MemoryEntry(id="gone", content="secret", scope=MemoryScope.USER,
                                  created_at="2026-09-04"), alice)

    class Counting(FakeVectorStore):
        deletes = 0

        async def delete(self, *args):
            Counting.deletes += 1
            await super().delete(*args)

    vector = Counting()
    relay = OutboxRelay(store, vector)
    assert await relay.flush() == 1
    await store.delete("gone", alice)
    assert await relay.flush() == 1
    assert Counting.deletes == 1
    assert await vector.search("secret", alice, MemoryScope.USER, 5) == []
    assert await vector.get("gone", alice, MemoryScope.USER) is None


@pytest.mark.asyncio
async def test_delete_change_restores_session_binding_for_the_index(tmp_path):
    """SESSION 绑定的删除同样要把 session 上下文还原给向量层——否则真实 adapter
    的 namespace filter 会拿错 session（删不掉 / 删错 namespace）。"""
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["session"])
    token = memory_session_var.set("one-session")
    try:
        await store.store(MemoryEntry(id="s1", content="local", scope=MemoryScope.SESSION,
                                      created_at="2026-09-04"), alice)
        relay = OutboxRelay(store, FakeVectorStore())
        assert await relay.flush() == 1
        await store.delete("s1", alice)
    finally:
        memory_session_var.reset(token)

    assert memory_session_var.get() is None
    vector = FakeVectorStore()
    relay = OutboxRelay(store, vector)
    assert await relay.flush() == 1
    assert memory_session_var.get() is None  # relay 用完即复位
    token = memory_session_var.set("one-session")
    try:
        assert await vector.get("s1", alice, MemoryScope.SESSION) is None
    finally:
        memory_session_var.reset(token)


@pytest.mark.asyncio
async def test_vector_failure_reason_names_vector_stage(tmp_path, caplog):
    """vector upsert 失败时，失败原因按 vector 阶段归因记录（含异常类型）。"""
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["user"])
    await store.store(MemoryEntry(id="vfail", content="c", scope=MemoryScope.USER,
                                  created_at="2026-09-04"), alice)

    class Failing(FakeVectorStore):
        async def upsert(self, *args):
            raise ConnectionError("offline")

    relay = OutboxRelay(store, Failing())
    with caplog.at_level(logging.WARNING, logger=RELAY_LOGGER):
        await relay.flush()
    assert "vector: ConnectionError" in caplog.text
    assert "ack:" not in caplog.text
    assert await store.pending()


@pytest.mark.asyncio
async def test_persistent_ack_failures_still_dead_letter(tmp_path, caplog):
    """持续 ack 失败同样计入连续失败：满 MAX 次后死信跳过，
    不会每轮重复 upsert（毒丸不回归），outbox 行保留可观察。"""
    store = AckBrokenStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["user"])
    await store.store(MemoryEntry(id="stuck", content="c", scope=MemoryScope.USER,
                                  created_at="2026-09-04"), alice)

    vector = CountingVector()
    relay = OutboxRelay(store, vector)
    with caplog.at_level(logging.WARNING, logger=RELAY_LOGGER):
        for _ in range(OutboxRelay.MAX_CONSECUTIVE_FAILURES):
            await relay.flush()
        assert vector.attempts == OutboxRelay.MAX_CONSECUTIVE_FAILURES
        assert "ack: AckFailed" in caplog.text
        assert "abandoned" in caplog.text  # 第 MAX 次连续失败进入死信
        assert await relay.flush() == 0
        assert vector.attempts == OutboxRelay.MAX_CONSECUTIVE_FAILURES  # 死信后不再重试
    assert await store.pending()



@pytest.mark.asyncio
async def test_restored_memory_re_arms_dead_lettered_entry(tmp_path):
    """内容被重新 store（revision 更新）时必须重置死信跳过。

    此前死信按 memory_id 在进程内永久生效：Milvus 故障超过 ~25s（5 次 × 5s
    轮询）期间写入的记忆全部死信，之后对该记忆的任何更新（新版本内容）也
    永远不再被索引——静默丢失直到进程重启。新 revision 是"新内容、可能已
    可同步"的证据：重置重试预算；SQLite outbox 行仍是权威（indexed=FALSE
    直至 ack 成功）。
    """
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    alice = IdentityContext("acme", "alice", ["user"])

    class Poisoned(FakeVectorStore):
        def __init__(self):
            super().__init__()
            self.fail = True

        async def upsert(self, *args):
            if self.fail:
                raise ValueError("milvus down")
            await super().upsert(*args)

    vector = Poisoned()
    relay = OutboxRelay(store, vector)
    await store.store(MemoryEntry(id="m1", content="old", scope=MemoryScope.USER,
                                  created_at="2026-09-04"), alice)
    for _ in range(OutboxRelay.MAX_CONSECUTIVE_FAILURES):
        await relay.flush()
    assert await relay.flush() == 0  # 已死信，不再尝试

    vector.fail = False  # Milvus 恢复
    await store.store(MemoryEntry(id="m1", content="new", scope=MemoryScope.USER,
                                  created_at="2026-09-05"), alice)  # 更新 → 新 revision
    assert await relay.flush() == 1  # 重臂：新版本重新同步
    assert (await store.get("m1", alice)).indexed
