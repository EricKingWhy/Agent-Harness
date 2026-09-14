"""MEM-1（#156）记忆生命周期：硬删的索引传播 + outbox 作为"索引意图账本"。

这一层锁的不是单个方法的返回值，而是**跨两个存储**的性质：删除必须真的到达
向量索引（"忘不掉"是错的），且失败时不能静默丢失（不变量 #21）。

ticket 已定位的坑在这里被钉死：`pending()` 原先以 `memory_records JOIN
memory_outbox` 驱动，记录行一删，JOIN 就把这个 id 过滤掉——outbox 行还在，
relay 却永远看不见，向量索引留下永久残留。所以本文件的用例在**删掉记录行之后**
读 outbox，而不是只看 `delete()` 的返回值。
"""

import asyncio
import logging
import sqlite3

import pytest

from agent_harness.identity import IdentityContext
from agent_harness.memory.fake_vector_store import FakeVectorStore
from agent_harness.memory.outbox_relay import OutboxRelay
from agent_harness.memory.record_store import MemoryOperation
from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
from agent_harness.memory.types import MemoryEntry, MemoryScope, memory_session_var

ALICE = IdentityContext("acme", "alice", ["user", "session"])
RECORD_STORE_LOGGER = "agent_harness.memory.sqlite_record_store"

#: 迁移用例要用的**旧** schema 快照（不含 operation / 路由列）。刻意写死在测试里：
#: 它代表"升级前的磁盘形状"，不能跟着实现里的 DDL 一起漂移。
LEGACY_SCHEMA = """
CREATE TABLE memory_records (
    memory_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL, scope TEXT NOT NULL, namespace TEXT NOT NULL,
    content TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL,
    indexed BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE memory_outbox (memory_id TEXT PRIMARY KEY, revision TEXT NOT NULL);
"""


def entry(memory_id="m1", content="secret", scope=MemoryScope.USER) -> MemoryEntry:
    return MemoryEntry(id=memory_id, content=content, metadata={"importance": 0.5},
                       created_at="2026-09-04T00:00:00+00:00", scope=scope)


async def _store(tmp_path) -> SqliteMemoryRecordStore:
    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    return records


@pytest.mark.asyncio
async def test_hard_delete_reaches_the_index_after_the_record_row_is_gone(tmp_path):
    """AC3 的核心钉子：记录行删掉之后，relay 仍必须读到该变更并调 `vectors.delete`。"""
    records = await _store(tmp_path)
    vectors = FakeVectorStore()
    relay = OutboxRelay(records, vectors)
    await records.store(entry(), ALICE)
    assert await relay.flush() == 1
    assert await vectors.get("m1", ALICE, MemoryScope.USER) is not None

    assert await records.delete("m1", ALICE) is True

    changes = await records.pending()
    assert [change.operation for change in changes] == [MemoryOperation.DELETE]
    assert changes[0].memory_id == "m1"
    assert changes[0].entry is None  # 删除变更不携带内容（记录行已经不存在了）
    # 路由事实来自 outbox 自己：删掉记录行后仍能定位 tenant/user/scope/session
    # （identity 由这些列重建，scopes 只带该条记忆的 scope——不是调用方的完整 identity）
    assert (changes[0].identity.tenant_id, changes[0].identity.user_id) == ("acme", "alice")
    assert changes[0].scope is MemoryScope.USER
    assert changes[0].session_id is None

    assert await relay.flush() == 1
    assert await vectors.search("secret", ALICE, MemoryScope.USER, 5) == []  # 检索再也搜不到
    assert await vectors.get("m1", ALICE, MemoryScope.USER) is None  # 且确实无残留
    assert await records.pending() == []


@pytest.mark.asyncio
async def test_delete_is_idempotent_and_writes_no_index_intent_when_absent(tmp_path):
    """AC1：删不存在的 id 是幂等 `False`，且不产生索引意图。

    没有记录行就没有可用于路由的 namespace（删哪条向量？属于谁？），所以这里如实
    返回"什么都没发生"，而不是编一个空的删除意图——后者会让 relay 拿空 identity
    去调 Milvus。
    """
    records = await _store(tmp_path)
    assert await records.delete("ghost", ALICE) is False
    assert await records.pending() == []


@pytest.mark.asyncio
async def test_delete_cannot_cross_namespace(tmp_path):
    """AC2：存在但属于别的 tenant/user 的记忆 → PermissionError（与 store 同源），
    记录与 outbox 都不许被改动。"""
    records = await _store(tmp_path)
    await records.store(entry(), ALICE)
    for other in (IdentityContext("acme", "bob", ["user"]),
                  IdentityContext("other", "alice", ["user"])):
        with pytest.raises(PermissionError):
            await records.delete("m1", other)
    assert (await records.get("m1", ALICE)).content == "secret"
    assert [change.operation for change in await records.pending()] == [MemoryOperation.UPSERT]


@pytest.mark.asyncio
async def test_delete_requires_the_bound_session_for_session_scope(tmp_path):
    """AC2 的 scope 部分：SESSION 绑定的记忆只在绑定同一 session 的上下文里可删。

    AC2 要的是"按 namespace 校验归属、不得跨 tenant/user/scope 删"，所以**绑定不上**
    （无绑定、或绑到别的 session）都是 `PermissionError`：行确实存在，但它的 namespace
    解析不出"这个调用方有权操作的那一个"，就等同于"不是你的记忆"。

    "无绑定"从 #159 起由 `ValueError` 改判 `PermissionError`（`row_namespace_matches` 的
    既定语义）：HTTP 入口没有可信会话绑定，按 id 删到会话记忆必须得到明确拒绝而不是 500；
    顺带让模型工具也走"可读的拒绝结果"而不是把异常抛出执行器。调用方**自己**的 scope 解析
    不受影响——`store()` 缺绑定时依旧 `ValueError`。

    删除之后同一个 id 的再次删除落回幂等 `False`——没有行可校验时不再要求 binding
    （否则"忘了又忘"会变成报错）。
    """
    records = await _store(tmp_path)
    token = memory_session_var.set("session-a")
    try:
        await records.store(entry(scope=MemoryScope.SESSION), ALICE)
    finally:
        memory_session_var.reset(token)
    with pytest.raises(PermissionError):
        await records.delete("m1", ALICE)
    token = memory_session_var.set("session-b")
    try:
        with pytest.raises(PermissionError):
            await records.delete("m1", ALICE)
    finally:
        memory_session_var.reset(token)
    token = memory_session_var.set("session-a")
    try:
        assert await records.delete("m1", ALICE) is True
        assert await records.delete("m1", ALICE) is False
    finally:
        memory_session_var.reset(token)


@pytest.mark.asyncio
async def test_delete_failure_keeps_the_outbox_intent_for_retry(tmp_path):
    """AC5：索引删除失败不得静默丢失——outbox 保留待重试（不变量 #21），
    下一轮（索引恢复后）必须真的删掉。"""
    records = await _store(tmp_path)

    class NoDelete(FakeVectorStore):
        fail = False

        async def delete(self, memory_id, identity, scope):
            if self.fail:
                raise ConnectionError("milvus down")
            await super().delete(memory_id, identity, scope)

    vectors = NoDelete()
    relay = OutboxRelay(records, vectors)
    await records.store(entry(), ALICE)
    assert await relay.flush() == 1

    vectors.fail = True
    assert await records.delete("m1", ALICE) is True
    assert await relay.flush() == 0  # 删除失败 → 不计入 ack
    assert [change.operation for change in await records.pending()] == [MemoryOperation.DELETE]
    assert await vectors.get("m1", ALICE, MemoryScope.USER) is not None  # 索引里还在（如实）

    vectors.fail = False
    assert await relay.flush() == 1
    assert await vectors.get("m1", ALICE, MemoryScope.USER) is None


@pytest.mark.asyncio
async def test_persistent_delete_failures_reuse_the_dead_letter_budget(tmp_path, caplog):
    """AC5 的后半句：死信/连续失败语义沿用既有约定（连续 MAX 次后本进程不再重试，
    outbox 行保留可观察），删除变更与 upsert 用同一套预算。"""
    records = await _store(tmp_path)

    class NoDelete(FakeVectorStore):
        attempts = 0

        async def delete(self, *args):
            NoDelete.attempts += 1
            raise ValueError("permanent schema mismatch")

    vectors = NoDelete()
    relay = OutboxRelay(records, vectors)
    await records.store(entry(), ALICE)
    await relay.flush()  # 先把 upsert 做掉（这版 vector 的 upsert 正常）
    await records.delete("m1", ALICE)
    with caplog.at_level(logging.WARNING, logger="agent_harness.memory.outbox_relay"):
        for _ in range(OutboxRelay.MAX_CONSECUTIVE_FAILURES):
            await relay.flush()
        assert NoDelete.attempts == OutboxRelay.MAX_CONSECUTIVE_FAILURES
        assert "abandoned" in caplog.text
        assert await relay.flush() == 0  # 死信后不再空转
        assert NoDelete.attempts == OutboxRelay.MAX_CONSECUTIVE_FAILURES
    assert [change.operation for change in await records.pending()] == [MemoryOperation.DELETE]


@pytest.mark.asyncio
async def test_outbox_change_without_record_row_is_healed_as_delete(tmp_path):
    """自愈：outbox 说 upsert、记录行却已不在（升级前遗留 / 绕过契约的删除）。

    这种条目**不能**按 upsert 重放（没有内容可索引），而应作为删除把索引里的残留
    清掉——否则每次 flush 都会看到一条永远无法完成、也永远修不好的意图。构造上必须
    让 outbox 行**仍然挂着**（这里让 ack 失败一次），否则它早已被 ack 掉、无从观察。
    """

    class AckFailsOnce(SqliteMemoryRecordStore):
        fail = True

        async def acknowledge(self, change):
            if self.fail:
                self.fail = False
                raise RuntimeError("ack unavailable")
            return await super().acknowledge(change)

    records = AckFailsOnce(tmp_path / "memory.db")
    await records.initialize()
    vectors = FakeVectorStore()
    relay = OutboxRelay(records, vectors)
    await records.store(entry(), ALICE)
    assert await relay.flush() == 0  # 向量写成功、ack 失败 → outbox 行仍是 upsert
    assert await vectors.get("m1", ALICE, MemoryScope.USER) is not None
    assert [change.operation for change in await records.pending()] == [MemoryOperation.UPSERT]

    with sqlite3.connect(records.database_path) as db:  # 绕过契约的硬删
        db.execute("DELETE FROM memory_records WHERE memory_id='m1'")
        db.commit()

    changes = await records.pending()
    assert [change.operation for change in changes] == [MemoryOperation.DELETE]
    assert changes[0].entry is None
    assert await relay.flush() == 1
    assert await vectors.get("m1", ALICE, MemoryScope.USER) is None


@pytest.mark.asyncio
async def test_upsert_with_existing_id_overwrites_index_content(tmp_path):
    """AC6 的机制面：同 id 覆盖写（update 的实现路径）必须让索引收敛到**新**内容，
    旧内容不能再被检索到（`revision` 变化 → relay 重新同步）。"""
    records = await _store(tmp_path)
    vectors = FakeVectorStore()
    relay = OutboxRelay(records, vectors)
    await records.store(entry(content="old"), ALICE)
    assert await relay.flush() == 1

    await records.store(entry(content="new"), ALICE)
    assert await relay.flush() == 1
    assert (await vectors.get("m1", ALICE, MemoryScope.USER))["content"] == "new"
    assert await vectors.search("old", ALICE, MemoryScope.USER, 5) == []
    assert (await records.get("m1", ALICE)).created_at == "2026-09-04T00:00:00+00:00"


@pytest.mark.asyncio
async def test_acknowledge_only_clears_the_revision_it_synced(tmp_path):
    """AC6 的乐观并发令牌：relay 同步的是 r1，同步期间写者提交了 r2 →
    对 r1 的 ack 必须失败（outbox 行保留为 r2），下一轮把新内容同步进去。
    陈旧 ack 若能清掉新版本，索引就会永远停在被覆盖之前的内容上。"""
    records = await _store(tmp_path)
    await records.store(entry(content="old"), ALICE)
    stale = (await records.pending())[0]

    await records.store(entry(content="new"), ALICE)

    assert await records.acknowledge(stale) is False
    current = await records.pending()
    assert len(current) == 1 and current[0].revision != stale.revision
    assert current[0].entry is not None and current[0].entry.content == "new"


@pytest.mark.asyncio
async def test_concurrent_writers_converge_on_one_row_and_one_index_state(tmp_path):
    """AC6 的并发面：同一 id 的两个并发写者（不是"陈旧 ack"那半边）。

    冻结语义（record_store 模块文档）：内容在 namespace 内 last-write-wins——
    SQLite 单写者 + `BEGIN IMMEDIATE` 把两个事务串行化，输家不留半个更新；outbox 每个
    memory_id 只有**一行**（它是"索引期望状态"而不是历史），relay 收敛后索引内容必须
    等于权威记录里的那一个赢家，输家的内容不可被检索到（否则就是"两条记忆"）。
    """
    records = await _store(tmp_path)
    vectors = FakeVectorStore()
    relay = OutboxRelay(records, vectors)

    await asyncio.gather(records.store(entry(content="first"), ALICE),
                         records.store(entry(content="second"), ALICE))

    assert len(await records.list_by_scope(MemoryScope.USER, ALICE, 10)) == 1
    changes = await records.pending()
    assert [change.memory_id for change in changes] == ["m1"]  # 一行，不重放历史
    winner = (await records.get("m1", ALICE)).content
    assert winner in {"first", "second"}

    assert await relay.flush() == 1
    assert (await vectors.get("m1", ALICE, MemoryScope.USER))["content"] == winner
    loser = "second" if winner == "first" else "first"
    assert await vectors.search(loser, ALICE, MemoryScope.USER, 5) == []
    assert await vectors.search(winner, ALICE, MemoryScope.USER, 5) == [("m1", 1.0)]
    assert await records.pending() == []


@pytest.mark.asyncio
async def test_initialize_migrates_legacy_outbox_and_backfills_routing_facts(tmp_path, caplog):
    """升级路径：老库的 `memory_outbox` 只有 (memory_id, revision)。

    `initialize()` 必须就地迁移：把路由事实（tenant/user/scope/namespace）从记录行
    回填进 outbox——否则新代码读不出一条老变更。无法回填的孤儿行（记录行已不在）
    只能丢弃并告警：留着会让 `pending()` 每轮都失败（它没有 identity 可以路由）。
    """
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute("INSERT INTO memory_records VALUES (?,?,?,?,?,?,?,?,FALSE)",
                   ("m1", "acme", "alice", "user", '["memories", "acme", "alice", "user"]',
                    "secret", '{"importance": 0.5}', "2026-09-04T00:00:00+00:00"))
        db.execute("INSERT INTO memory_outbox VALUES ('m1', 'rev-1')")
        db.execute("INSERT INTO memory_outbox VALUES ('ghost', 'rev-2')")
        db.commit()

    records = SqliteMemoryRecordStore(path)
    with caplog.at_level(logging.WARNING, logger=RECORD_STORE_LOGGER):
        await records.initialize()

    changes = await records.pending()
    assert [change.memory_id for change in changes] == ["m1"]
    assert changes[0].operation is MemoryOperation.UPSERT
    assert (changes[0].identity.tenant_id, changes[0].identity.user_id) == ("acme", "alice")
    assert changes[0].scope is MemoryScope.USER
    assert changes[0].revision == "rev-1"
    assert changes[0].entry is not None and changes[0].entry.content == "secret"
    assert "ghost" in caplog.text  # 不可路由的孤儿行被丢弃并留痕

    # 迁移后的库与新建库同约束：`ADD COLUMN` 上的 CHECK 是真的生效的，不是装饰
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO memory_outbox (memory_id, revision, operation)"
                   " VALUES ('x', 'rev-x', 'bogus')")

    # 迁移后照常工作：ack + 新的删除变更都走新 schema
    assert await records.acknowledge(changes[0]) is True
    assert await records.delete("m1", ALICE) is True
    assert [change.operation for change in await records.pending()] == [MemoryOperation.DELETE]


@pytest.mark.asyncio
async def test_initialize_completes_a_half_migrated_outbox(tmp_path, caplog):
    """迁移本身必须可重入：SQLite 的 DDL 逐条提交，"加完 operation 列、还没回填"时
    进程被杀就是这个形状（legacy schema + 只有 operation 列）。

    旧的哨兵（`if "operation" in columns: return`）会永久跳过这种库 → 四个路由列全是
    NULL → 此后每次 `pending()` 都在 `MemoryNamespace(json.loads(None))` 上抛错，而
    relay 把异常当作"索引不可用"咽掉，表现成"索引永远不更新"。所以断言分两半：
    迁移要补齐并回填，且重复 `initialize()` 不得破坏已迁移的库。
    """
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute("ALTER TABLE memory_outbox ADD COLUMN operation TEXT NOT NULL"
                   " DEFAULT 'upsert'")
        db.execute("INSERT INTO memory_records VALUES (?,?,?,?,?,?,?,?,FALSE)",
                   ("m1", "acme", "alice", "user", '["memories", "acme", "alice", "user"]',
                    "secret", '{"importance": 0.5}', "2026-09-04T00:00:00+00:00"))
        db.execute("INSERT INTO memory_outbox (memory_id, revision, operation)"
                   " VALUES ('m1', 'rev-1', 'upsert')")
        db.commit()

    records = SqliteMemoryRecordStore(path)
    await records.initialize()
    await records.initialize()  # 可重入：第二次不得丢列、丢行或重复告警

    changes = await records.pending()
    assert [change.memory_id for change in changes] == ["m1"]
    assert (changes[0].identity.tenant_id, changes[0].identity.user_id) == ("acme", "alice")
    assert changes[0].scope is MemoryScope.USER
    assert changes[0].revision == "rev-1"
    assert changes[0].entry is not None and changes[0].entry.content == "secret"
    assert await records.acknowledge(changes[0]) is True

    # 这条路径**补不上** CHECK（SQLite 不支持给既有列追加约束，见 `_migrate_outbox`），
    # 所以约束缺席时的兜底是 `_parse_operation` 的自愈：脏值不得让 `pending()` 每轮抛错
    # （那会被 relay 当"outbox 不可用"咽掉 → 索引静默停止收敛）。方向必须是**非破坏性
    # 的 upsert**：记录行还在，就按权威内容把索引写回去。按删除处理会先清掉索引里的
    # 正确内容，随后 `acknowledge` 又给残留的记录行写上 `indexed=TRUE` 并移除 outbox 行
    # ——记忆搜不到、还声称已索引、且没有任何待办意图去修（静默丢失）。
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO memory_outbox"
                   " (memory_id, revision, operation, tenant_id, user_id, scope, namespace)"
                   " VALUES ('m1', 'rev-2', 'bogus', 'acme', 'alice', 'user',"
                   "         '[\"memories\", \"acme\", \"alice\", \"user\"]')")
        db.commit()
    with caplog.at_level(logging.WARNING, logger=RECORD_STORE_LOGGER):
        healed = await records.pending()
    assert [change.operation for change in healed] == [MemoryOperation.UPSERT]
    assert healed[0].entry is not None and healed[0].entry.content == "secret"
    assert "unknown operation" in caplog.text and "m1" in caplog.text
    assert (await records.get("m1", ALICE)).content == "secret"  # 记录行不受脏值影响

    # 走一遍 relay，证明自愈真的是"重新索引"而不是"清掉"：索引里有内容、记录行未被
    # 谎报为已索引（按删除自愈过的实现会在这里变成 search 空 + indexed=TRUE）。
    vectors = FakeVectorStore()
    assert await OutboxRelay(records, vectors).flush() == 1
    assert await vectors.search("secret", ALICE, MemoryScope.USER, 5) == [("m1", 1.0)]
