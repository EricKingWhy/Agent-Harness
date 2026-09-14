"""SessionMeta lineage 扩列（Phase 14 T1, #107, ADR-0017 决策 7）。

双层 lineage 的索引层：SessionMeta 增加 parent_session_id / origin /
fork_point_seq 三个可空列（NULL = root）；SQLite 实现向后兼容加列迁移
（存量库幂等迁移，旧数据零丢失）。事件 = 真相、meta = 索引的分工见 ADR。
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest
from pydantic import ValidationError

from agent_harness.storage.session_meta import SessionMeta
from agent_harness.storage.sqlite import SqliteSessionMetaStore

pytestmark = pytest.mark.asyncio

_LEGACY_DDL = """
CREATE TABLE IF NOT EXISTS session_meta (
    session_id          TEXT PRIMARY KEY,
    created_at          TEXT NOT NULL,
    agent_id            TEXT,
    last_checkpoint_seq INTEGER,
    archived            BOOLEAN DEFAULT 0
)
"""


def _meta(**overrides: object) -> SessionMeta:
    fields: dict = {"session_id": "s1", "created_at": "2026-09-06T00:00:00Z"}
    fields.update(overrides)
    return SessionMeta(**fields)


async def test_session_meta_lineage_fields_roundtrip(tmp_path: Path) -> None:
    store = SqliteSessionMetaStore(tmp_path / "harness.db")
    await store.initialize()
    written = await store.upsert(
        _meta(
            parent_session_id="parent-1",
            origin="fork",
            fork_point_seq=7,
        )
    )
    assert written.parent_session_id == "parent-1"
    assert written.origin == "fork"
    assert written.fork_point_seq == 7
    loaded = await store.get("s1")
    assert loaded is not None
    assert (loaded.parent_session_id, loaded.origin, loaded.fork_point_seq) == (
        "parent-1",
        "fork",
        7,
    )


async def test_session_meta_lineage_defaults_null(tmp_path: Path) -> None:
    """无 lineage 字段 = root 语义（NULL），既有调用方零感知。"""
    store = SqliteSessionMetaStore(tmp_path / "harness.db")
    await store.initialize()
    await store.upsert(_meta())
    loaded = await store.get("s1")
    assert loaded is not None
    assert loaded.parent_session_id is None
    assert loaded.origin is None
    assert loaded.fork_point_seq is None


async def test_session_meta_origin_is_closed_vocabulary(tmp_path: Path) -> None:
    """origin 只接受 fork | delegation（ADR-0017 决策 7：两类边统一建模）。"""
    store = SqliteSessionMetaStore(tmp_path / "harness.db")
    await store.initialize()
    with pytest.raises(ValidationError):
        _meta(origin="clone")
    await store.upsert(_meta(parent_session_id="p", origin="delegation"))
    loaded = await store.get("s1")
    assert loaded is not None
    assert loaded.origin == "delegation"


async def test_clear_delegation_parent_unlinks_only_delegation_rows(
    tmp_path: Path,
) -> None:
    """硬删父会话时的补偿（#172 / ADR-0029 D5）：清委派子行的父链接，别的一律不动。

    不清的话子行会指着一个已删的会话——`build_lineage_tree` 渲染成
    `(parent missing)`，而那条边随父日志消失后**永远无法自愈**。
    """
    store = SqliteSessionMetaStore(tmp_path / "harness.db")
    await store.initialize()
    await store.upsert(_meta(session_id="p"))
    await store.upsert(_meta(session_id="d1", parent_session_id="p", origin="delegation"))
    await store.upsert(_meta(session_id="d2", parent_session_id="p", origin="delegation"))
    # 反向样本：不是委派的、以及父不是 p 的，都不该被这次清理碰到
    await store.upsert(_meta(session_id="other", parent_session_id="p", origin="fork"))
    await store.upsert(_meta(session_id="d3", parent_session_id="q", origin="delegation"))

    assert await store.clear_delegation_parent("p") == 2
    assert await store.clear_delegation_parent("p") == 0  # 幂等：重跑没有可修的行

    for sid in ("d1", "d2"):
        row = await store.get(sid)
        assert row is not None and (row.parent_session_id, row.origin) == (None, None)
    keeper = await store.get("other")
    assert keeper is not None and keeper.parent_session_id == "p"  # fork 行不归它管
    untouched = await store.get("d3")
    assert untouched is not None and untouched.parent_session_id == "q"


async def test_upsert_conflict_refreshes_lineage_fields(tmp_path: Path) -> None:
    """完整 upsert 的 ON CONFLICT 分支必须刷新 lineage 三列（可修正归属）。"""
    store = SqliteSessionMetaStore(tmp_path / "harness.db")
    await store.initialize()
    await store.upsert(_meta())
    await store.upsert(_meta(parent_session_id="p2", origin="fork", fork_point_seq=3))
    loaded = await store.get("s1")
    assert loaded is not None
    assert (loaded.parent_session_id, loaded.origin, loaded.fork_point_seq) == (
        "p2",
        "fork",
        3,
    )


async def test_legacy_schema_auto_migrates_and_is_idempotent(tmp_path: Path) -> None:
    """存量库（无 lineage 列）打开时自动加列：旧行读回 NULL=root，重复迁移幂等。"""
    db = tmp_path / "harness.db"
    async with aiosqlite.connect(db) as connection:
        await connection.execute(_LEGACY_DDL)
        await connection.execute(
            "INSERT INTO session_meta (session_id, created_at, agent_id,"
            " last_checkpoint_seq, archived) VALUES ('old-1', '2026-09-01T00:00:00Z',"
            " 'default', 5, 0)"
        )
        await connection.commit()

    store = SqliteSessionMetaStore(db)
    await store.initialize()
    await store.initialize()  # 幂等：二次迁移不抛错不加重复列

    legacy = await store.get("old-1")
    assert legacy is not None
    assert legacy.last_checkpoint_seq == 5
    assert legacy.parent_session_id is None
    assert legacy.origin is None
    assert legacy.fork_point_seq is None

    # 迁移后的库可正常写入 lineage 行
    await store.upsert(
        _meta(session_id="new-1", parent_session_id="old-1", origin="fork",
              fork_point_seq=9)
    )
    fresh = await store.get("new-1")
    assert fresh is not None
    assert fresh.parent_session_id == "old-1"
