"""SqliteCheckpointStore + SqliteSessionMetaStore contract tests (#28)."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from agent_harness.storage import (
    Checkpoint,
    CheckpointBoundary,
    SessionMeta,
    SqliteCheckpointStore,
    SqliteOperationLedger,
    SqliteSessionMetaStore,
)


@pytest.mark.asyncio
async def test_checkpoints_schema_matches_frozen_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    store = SqliteCheckpointStore(database_path)
    await store.initialize()

    async with aiosqlite.connect(database_path) as connection:
        cursor = await connection.execute("PRAGMA table_info(checkpoints)")
        columns = {row[1]: row for row in await cursor.fetchall()}

    assert set(columns) == {
        "session_id",
        "boundary_type",
        "event_seq",
        "payload_json",
        "created_at",
    }
    pk = await _primary_key_of(database_path, "checkpoints")
    assert pk == ["session_id", "boundary_type", "event_seq"]


@pytest.mark.asyncio
async def test_session_meta_schema_matches_frozen_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "state.db"
    store = SqliteSessionMetaStore(database_path)
    await store.initialize()

    async with aiosqlite.connect(database_path) as connection:
        cursor = await connection.execute("PRAGMA table_info(session_meta)")
        columns = {row[1]: row for row in await cursor.fetchall()}

    # ADR-0017 决策 7（Phase 14 T1）：lineage 三列并入冻结 schema
    # （NULL = root；origin ∈ {fork, delegation} 封闭词汇）。
    assert set(columns) == {
        "session_id",
        "created_at",
        "agent_id",
        "last_checkpoint_seq",
        "archived",
        "parent_session_id",
        "origin",
        "fork_point_seq",
    }
    pk = await _primary_key_of(database_path, "session_meta")
    assert pk == ["session_id"]
    # archived 列声明为 BOOLEAN DEFAULT 0（核对 dflt_value + 类型）。
    archived_col = columns["archived"]
    assert archived_col[4] == "0"  # dflt_value
    # type 字段是列声明类型——核对为 BOOLEAN（去掉空格也不改变判断）。
    assert str(archived_col[2]).strip().upper() == "BOOLEAN"

    # 退回 sqlite_master 核对 DDL 含 DEFAULT 0 字面量（忽略列名与类型间的空格）。
    async with aiosqlite.connect(database_path) as connection:
        cursor = await connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='session_meta'"
        )
        ddl = (await cursor.fetchone())[0]
    ddl_flat = " ".join(ddl.split())
    assert "archived BOOLEAN DEFAULT 0" in ddl_flat


@pytest.mark.asyncio
async def test_checkpoint_save_and_list_in_order(tmp_path: Path) -> None:
    store = SqliteCheckpointStore(tmp_path / "state.db")
    await store.initialize()
    for seq, boundary in (
        (0, CheckpointBoundary.USER_ACCEPTED),
        (1, CheckpointBoundary.MODEL_COMPLETED),
        (3, CheckpointBoundary.TOOL_BATCH_COMPLETED),
    ):
        await store.save(
            Checkpoint(
                session_id="s1",
                boundary_type=boundary,
                event_seq=seq,
                created_at="2026-09-04T00:00:00+00:00",
            )
        )

    checkpoints = await store.list_for_session("s1")

    assert [c.event_seq for c in checkpoints] == [0, 1, 3]
    assert {c.boundary_type for c in checkpoints} == {
        CheckpointBoundary.USER_ACCEPTED,
        CheckpointBoundary.MODEL_COMPLETED,
        CheckpointBoundary.TOOL_BATCH_COMPLETED,
    }

    latest = await store.latest("s1")
    assert latest is not None
    assert latest.event_seq == 3
    assert latest.boundary_type is CheckpointBoundary.TOOL_BATCH_COMPLETED

    assert await store.latest("missing") is None


@pytest.mark.asyncio
async def test_checkpoint_primary_key_rejects_duplicate(tmp_path: Path) -> None:
    store = SqliteCheckpointStore(tmp_path / "state.db")
    await store.initialize()
    checkpoint = Checkpoint(
        session_id="s1",
        boundary_type=CheckpointBoundary.MODEL_COMPLETED,
        event_seq=5,
        created_at="2026-09-04T00:00:00+00:00",
    )
    await store.save(checkpoint)

    with pytest.raises(aiosqlite.IntegrityError):
        await store.save(checkpoint)


@pytest.mark.asyncio
async def test_three_stores_share_one_database_file(tmp_path: Path) -> None:
    """07 §2 / ADR-0004 Round 3：operations / checkpoints / session_meta 三张表
    共享同一 SQLite 文件，独立 contract。"""
    database_path = tmp_path / "shared.db"
    ledger = SqliteOperationLedger(database_path)
    checkpoint_store = SqliteCheckpointStore(database_path)
    meta_store = SqliteSessionMetaStore(database_path)

    await ledger.initialize()
    await checkpoint_store.initialize()
    await meta_store.initialize()

    async with aiosqlite.connect(database_path) as connection:
        cursor = await connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in await cursor.fetchall()}

    assert {"operations", "checkpoints", "session_meta"}.issubset(tables)


@pytest.mark.asyncio
async def test_session_meta_upsert_and_get(tmp_path: Path) -> None:
    store = SqliteSessionMetaStore(tmp_path / "state.db")
    await store.initialize()
    meta = SessionMeta(
        session_id="s1",
        created_at="2026-09-04T00:00:00+00:00",
        agent_id="default",
    )

    saved = await store.upsert(meta)
    assert saved.session_id == "s1"
    assert saved.archived is False

    loaded = await store.get("s1")
    assert loaded == saved

    # upsert 更新已有行。
    updated = await store.upsert(meta.model_copy(update={"last_checkpoint_seq": 7}))
    assert updated.last_checkpoint_seq == 7
    again = await store.get("s1")
    assert again.last_checkpoint_seq == 7


@pytest.mark.asyncio
async def test_session_meta_archived_flag(tmp_path: Path) -> None:
    store = SqliteSessionMetaStore(tmp_path / "state.db")
    await store.initialize()
    await store.upsert(
        SessionMeta(
            session_id="s1",
            created_at="2026-09-04T00:00:00+00:00",
        )
    )

    archived = await store.set_archived("s1", archived=True)
    assert archived.archived is True
    assert (await store.get("s1")).archived is True

    unarchived = await store.set_archived("s1", archived=False)
    assert unarchived.archived is False

    with pytest.raises(KeyError):
        await store.set_archived("missing")


@pytest.mark.asyncio
async def test_session_meta_update_last_checkpoint_seq(tmp_path: Path) -> None:
    store = SqliteSessionMetaStore(tmp_path / "state.db")
    await store.initialize()
    await store.upsert(
        SessionMeta(
            session_id="s1",
            created_at="2026-09-04T00:00:00+00:00",
        )
    )

    updated = await store.update_last_checkpoint_seq("s1", 42)
    assert updated.last_checkpoint_seq == 42

    with pytest.raises(KeyError):
        await store.update_last_checkpoint_seq("missing", 1)


@pytest.mark.asyncio
async def test_session_meta_cleanup_deletes_row(tmp_path: Path) -> None:
    store = SqliteSessionMetaStore(tmp_path / "state.db")
    await store.initialize()
    await store.upsert(
        SessionMeta(
            session_id="s1",
            created_at="2026-09-04T00:00:00+00:00",
        )
    )

    await store.cleanup("s1")
    assert await store.get("s1") is None
    # cleanup 幂等：删除不存在的行不抛。
    await store.cleanup("s1")


@pytest.mark.asyncio
async def test_checkpoint_payload_round_trip(tmp_path: Path) -> None:
    store = SqliteCheckpointStore(tmp_path / "state.db")
    await store.initialize()
    await store.save(
        Checkpoint(
            session_id="s1",
            boundary_type=CheckpointBoundary.FINAL_COMPLETED,
            event_seq=9,
            payload_json='{"final_text":"done"}',
            created_at="2026-09-04T00:00:00+00:00",
        )
    )

    latest = await store.latest("s1")
    assert latest is not None
    assert latest.payload_json == '{"final_text":"done"}'


# ── helpers ──


async def _primary_key_of(database_path: Path, table: str) -> list[str]:
    async with aiosqlite.connect(database_path) as connection:
        cursor = await connection.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
    # 复合主键：pk 列（索引 5）返回每个列在 PK 中的 1-based 序号（1,2,3...），
    # 单主键返回 1，非主键列返回 0。按序号排序得到 PK 列的声明顺序。
    pk_cols = [(row[5], row[1]) for row in rows if row[5] != 0]
    pk_cols.sort()
    return [name for _seq, name in pk_cols]
