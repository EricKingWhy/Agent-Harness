"""Memory 权威记录契约，SQLite 与 Fake 使用同一组验收。"""

import pytest
import pytest_asyncio
from pydantic import ValidationError

from agent_harness.identity import IdentityContext
from agent_harness.memory.fake_record_store import FakeMemoryRecordStore
from agent_harness.memory.record_store import MemoryOperation, PendingMemory
from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
from agent_harness.memory.types import (
    MemoryEntry,
    MemoryScope,
    memory_session_var,
    scope_to_namespace,
)


@pytest_asyncio.fixture(params=["sqlite", "fake"])
async def store(request, tmp_path):
    store = (SqliteMemoryRecordStore(tmp_path / "memory.db")
             if request.param == "sqlite" else FakeMemoryRecordStore())
    await store.initialize()
    return store


def entry(memory_id="m1"):
    return MemoryEntry(id=memory_id, content="I prefer TypeScript", metadata={"importance": 0.8},
                       created_at="2026-09-04T00:00:00+00:00", scope=MemoryScope.USER)


def test_memory_id_cannot_be_empty():
    with pytest.raises(ValidationError):
        entry("")


@pytest.mark.asyncio
async def test_store_and_get_roundtrip(store):
    identity = IdentityContext("acme", "alice", ["user"])
    assert await store.store(entry(), identity) == "m1"
    assert await store.get("m1", identity) == entry()
    assert await store.list_by_scope(MemoryScope.USER, identity, 10) == [entry()]
    assert scope_to_namespace(MemoryScope.USER, identity) == ("memories", "acme", "alice", "user")


@pytest.mark.asyncio
@pytest.mark.parametrize("other", [IdentityContext("other", "alice", ["user"]),
                                  IdentityContext("acme", "bob", ["user"])])
async def test_identity_cannot_read_or_overwrite_another_owner(store, other):
    owner = IdentityContext("acme", "alice", ["user"])
    await store.store(entry(), owner)
    with pytest.raises(KeyError):
        await store.get("m1", other)
    assert await store.list_by_scope(MemoryScope.USER, other, 10) == []
    with pytest.raises(PermissionError):
        await store.store(entry(), other)
    assert await store.get("m1", owner) == entry()


@pytest.mark.asyncio
async def test_scope_permission_is_enforced(store):
    with pytest.raises(PermissionError):
        await store.store(entry(), IdentityContext("acme", "alice", []))
    with pytest.raises(NotImplementedError):
        await store.list_by_scope(MemoryScope.GLOBAL, IdentityContext("acme", "alice", ["global"]), 10)


@pytest.mark.asyncio
async def test_store_does_not_persist_query_score_or_trust_indexed_flag(store):
    identity = IdentityContext("acme", "alice", ["user"])
    await store.store(entry().model_copy(update={"score": 0.9, "indexed": True}), identity)
    stored = await store.get("m1", identity)
    assert stored.score is None
    assert stored.indexed is False


@pytest.mark.asyncio
async def test_sqlite_record_and_outbox_commit_atomically(tmp_path):
    import aiosqlite

    path = tmp_path / "memory.db"
    store = SqliteMemoryRecordStore(path)
    await store.initialize()
    identity = IdentityContext("acme", "alice", ["user"])
    # 数据库故障注入，验证权威记录不会在 outbox 写失败时单独提交。
    async with aiosqlite.connect(path) as db:
        await db.execute("""CREATE TRIGGER fail_outbox BEFORE INSERT ON memory_outbox
                         BEGIN SELECT RAISE(ABORT, 'outbox unavailable'); END""")
        await db.commit()
    with pytest.raises(aiosqlite.IntegrityError):
        await store.store(entry(), identity)
    with pytest.raises(KeyError):
        await store.get("m1", identity)
    async with aiosqlite.connect(path) as db:
        await db.execute("DROP TRIGGER fail_outbox")
        await db.commit()
    await store.store(entry(), identity)
    restarted = SqliteMemoryRecordStore(path)
    assert await restarted.get("m1", identity) == entry()
    async with (aiosqlite.connect(path) as db,
                db.execute("SELECT memory_id FROM memory_outbox") as cursor):
        assert await cursor.fetchall() == [("m1",)]


@pytest.mark.asyncio
async def test_updates_preserve_created_time_and_do_not_share_metadata(store):
    identity = IdentityContext("acme", "alice", ["user"])
    original = entry()
    await store.store(original, identity)
    original.metadata["importance"] = 0
    assert (await store.get("m1", identity)).metadata["importance"] == 0.8
    changed = entry().model_copy(update={"created_at": "2026-09-05T00:00:00+00:00", "content": "updated"})
    await store.store(changed, identity)
    stored = await store.get("m1", identity)
    assert stored.content == "updated"
    assert stored.created_at == "2026-09-04T00:00:00+00:00"


@pytest.mark.asyncio
async def test_session_scope_does_not_cross_sessions(store):
    owner = IdentityContext("acme", "alice", ["user", "session"])
    scoped = entry().model_copy(update={"scope": MemoryScope.SESSION})
    token = memory_session_var.set("session-a")
    try:
        await store.store(scoped, owner)
        assert await store.get("m1", owner) == scoped
        assert scope_to_namespace(MemoryScope.SESSION, owner) == (
            "memories", "acme", "alice", "session", "session-a",
        )
        other_token = memory_session_var.set("session-b")
        try:
            assert await store.list_by_scope(MemoryScope.SESSION, owner, 10) == []
            with pytest.raises(KeyError):
                await store.get("m1", owner)
            with pytest.raises(PermissionError):
                await store.store(scoped, owner)
        finally:
            memory_session_var.reset(other_token)
    finally:
        memory_session_var.reset(token)
    with pytest.raises(ValueError):
        await store.store(scoped, owner)


# ── #156 MEM-1：delete（硬删）契约——SQLite 与 Fake 同一组验收（AC2/AC7）──


@pytest.mark.asyncio
async def test_delete_removes_the_record(store):
    identity = IdentityContext("acme", "alice", ["user"])
    await store.store(entry(), identity)
    assert await store.delete("m1", identity) is True
    with pytest.raises(KeyError):
        await store.get("m1", identity)
    assert await store.list_by_scope(MemoryScope.USER, identity, 10) == []


@pytest.mark.asyncio
async def test_delete_of_an_unknown_id_is_idempotent(store):
    """幂等：忘了又忘不是错误（调用方重试不得变成失败）。"""
    identity = IdentityContext("acme", "alice", ["user"])
    assert await store.delete("never-existed", identity) is False
    await store.store(entry(), identity)
    assert await store.delete("m1", identity) is True
    assert await store.delete("m1", identity) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("other", [IdentityContext("other", "alice", ["user"]),
                                  IdentityContext("acme", "bob", ["user"])])
async def test_delete_cannot_remove_another_owners_memory(store, other):
    owner = IdentityContext("acme", "alice", ["user"])
    await store.store(entry(), owner)
    with pytest.raises(PermissionError):
        await store.delete("m1", other)
    assert await store.get("m1", owner) == entry()


@pytest.mark.asyncio
async def test_get_of_a_session_memory_uses_the_same_namespace_check(store):
    """`get` 与 `delete` 共用 `row_namespace_matches`，但**口径不同**：读路径把"不是你的"
    伪装成 `KeyError`（不泄露存在性），删除路径如实 `PermissionError`（见上一条用例）。

    这条同时钉住 #159 的改判：SESSION 行在**没有绑定**时，`get` 以前会抛 `ValueError`
    （解析不出那一行），现在归入"不是你的" → `KeyError`；不再是异常冒泡。
    """
    owner = IdentityContext("acme", "alice", ["user", "session"])
    scoped = entry().model_copy(update={"scope": MemoryScope.SESSION})
    token = memory_session_var.set("session-a")
    try:
        await store.store(scoped, owner)
    finally:
        memory_session_var.reset(token)
    with pytest.raises(KeyError):
        await store.get("m1", owner)  # 无绑定：解析不出这一行，与"不存在"同等对待
    token = memory_session_var.set("session-b")
    try:
        with pytest.raises(KeyError):
            await store.get("m1", owner)  # 绑到别的 session：不是你的
    finally:
        memory_session_var.reset(token)
    token = memory_session_var.set("session-a")
    try:
        assert (await store.get("m1", owner)).id == "m1"  # 绑定正确：读得到
    finally:
        memory_session_var.reset(token)


@pytest.mark.asyncio
async def test_delete_rejects_a_session_bound_from_another_session(store):
    """SESSION 绑定的记忆：绑定不上（无绑定、或绑到别的 session）→ PermissionError；
    绑定正确 → 删除。删除后同一个 id 的再次删除落回幂等 False（没有行可校验）。

    "无绑定"从 #159 起也归 PermissionError（原为 ValueError）：按 id 删除时，**行**的
    namespace 解析不出"这个调用方有权操作的那一个"就等同于"不是你的记忆"，与绑错 session
    同义——HTTP 入口没有可信会话绑定，按 id 删到会话记忆必须是明确拒绝而不是 500。
    调用方**自己**的 scope 解析不受影响：`store()` 缺绑定时依旧 ValueError（上一个用例），
    真正的上下文 bug 仍会就地炸出来。
    """
    owner = IdentityContext("acme", "alice", ["user", "session"])
    scoped = entry().model_copy(update={"scope": MemoryScope.SESSION})
    token = memory_session_var.set("session-a")
    try:
        await store.store(scoped, owner)
    finally:
        memory_session_var.reset(token)
    with pytest.raises(PermissionError):
        await store.delete("m1", owner)
    token = memory_session_var.set("session-b")
    try:
        with pytest.raises(PermissionError):
            await store.delete("m1", owner)
    finally:
        memory_session_var.reset(token)
    token = memory_session_var.set("session-a")
    try:
        assert await store.delete("m1", owner) is True
        assert await store.delete("m1", owner) is False
    finally:
        memory_session_var.reset(token)


@pytest.mark.asyncio
async def test_sqlite_delete_commits_record_removal_and_outbox_together(tmp_path):
    """删除的两次写入（摘记录行 + 记删除意图）必须同事务：outbox 写失败时
    记录行不许单独消失（否则既查不到、也修不好索引残留）。"""
    import aiosqlite

    path = tmp_path / "memory.db"
    store = SqliteMemoryRecordStore(path)
    await store.initialize()
    identity = IdentityContext("acme", "alice", ["user"])
    await store.store(entry(), identity)
    async with aiosqlite.connect(path) as db:
        await db.execute("""CREATE TRIGGER fail_outbox BEFORE INSERT ON memory_outbox
                         BEGIN SELECT RAISE(ABORT, 'outbox unavailable'); END""")
        await db.commit()
    with pytest.raises(aiosqlite.IntegrityError):
        await store.delete("m1", identity)
    assert await store.get("m1", identity) == entry()
    async with aiosqlite.connect(path) as db:
        await db.execute("DROP TRIGGER fail_outbox")
        await db.commit()
    assert await store.delete("m1", identity) is True
    assert [change.operation for change in await store.pending()] == [MemoryOperation.DELETE]


# ── Round 9 审计修复：连接级并发 PRAGMA（与 storage/sqlite.py R4-5 同款）──


@pytest.mark.asyncio
async def test_record_store_connect_sets_busy_timeout(tmp_path):
    """每操作新连接模式下 busy_timeout 必须随连接设置——writeback store 与
    relay 的 pending/ack 并发写（BEGIN IMMEDIATE）在默认 0 时立刻抛
    database is locked（WAL 是持久 PRAGMA，busy_timeout 不是）。"""
    from agent_harness.memory.sqlite_record_store import _connect

    async with _connect(tmp_path / "busy.db") as connection:
        cursor = await connection.execute("PRAGMA busy_timeout")
        (value,) = await cursor.fetchone()
    assert int(value) > 0


@pytest.mark.asyncio
async def test_record_store_methods_route_through_connect(tmp_path, monkeypatch):
    """Record store 的所有连接必须经 _connect 助手（busy_timeout 在其中设置）
    ——直接 aiosqlite.connect 会绕过并发保护。"""
    from contextlib import asynccontextmanager
    from pathlib import Path

    from agent_harness.memory import sqlite_record_store as mod

    used: list[Path] = []
    real_connect = mod._connect

    @asynccontextmanager
    async def spy_connect(path):
        used.append(Path(path))
        async with real_connect(path) as connection:
            yield connection

    monkeypatch.setattr(mod, "_connect", spy_connect)
    store = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await store.initialize()
    owner = IdentityContext("acme", "alice", ["user"])
    await store.store(entry(), owner)
    await store.get("m1", owner)
    await store.list_by_scope(MemoryScope.USER, owner, 5)
    await store.pending()
    assert len(used) >= 5, "所有连接必须经 _connect（busy_timeout 在其中设置）"


def test_pending_memory_rejects_inconsistent_shapes():
    """`PendingMemory` 的构造不变量：operation 与 entry 必须一致；upsert 的 entry 的
    scope 必须等于路由用的 scope。

    两个 scope 各自可写（内容带一个、路由带一个），错配"内容来自 A、索引写进 B"不会被
    类型系统拦下，也不会有任何现成用例自然覆盖——只能在这里明确拒绝。
    """
    identity = IdentityContext("acme", "alice", ["user"])
    with pytest.raises(ValueError, match="delete change must not carry an entry"):
        PendingMemory(operation=MemoryOperation.DELETE, memory_id="m1", identity=identity,
                      scope=MemoryScope.USER, session_id=None, revision="r", entry=entry())
    with pytest.raises(ValueError, match="upsert change requires an entry"):
        PendingMemory(operation=MemoryOperation.UPSERT, memory_id="m1", identity=identity,
                      scope=MemoryScope.USER, session_id=None, revision="r")
    with pytest.raises(ValueError, match="entry scope must match the routing scope"):
        PendingMemory(operation=MemoryOperation.UPSERT, memory_id="m1", identity=identity,
                      scope=MemoryScope.SESSION, session_id="s1", revision="r",
                      entry=entry())
