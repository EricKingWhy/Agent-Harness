"""SQLite persistence adapters.

三个 Store（OperationLedger / CheckpointStore / SessionMetaStore）物理上共享同一
SQLite 文件，逻辑上各自独立 contract（ADR-0004 Round 3 §三张表）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from agent_harness.storage.checkpoint import (
    Checkpoint,
    CheckpointStore,
)
from agent_harness.storage.operation import (
    Operation,
    OperationLedger,
    OperationState,
)
from agent_harness.storage.session_meta import SessionMeta, SessionMetaStore

#: 每操作新连接模式下的连接级 PRAGMA：busy_timeout 让并发写等锁而不是立刻抛
#: "database is locked"（aiosqlite/sqlite3 默认 5s，多 Store 共享同一文件时不够）。
#: journal_mode=WAL 在 initialize 设置一次即可持久；busy_timeout 是 per-connection
#: 的，必须随每个新连接设置（R4-5）。
_BUSY_TIMEOUT_MS = 10_000


@asynccontextmanager
async def _connect(database_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(database_path)
    try:
        await connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        yield connection
    finally:
        await connection.close()


_OPERATIONS_DDL = """
CREATE TABLE IF NOT EXISTS operations (
    tool_call_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    run_id TEXT,
    agent_id TEXT,
    tool_name TEXT NOT NULL,
    args_identity TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED',
        'UNKNOWN', 'NEED_RECONCILE'
    )),
    result_json TEXT,
    artifact_ref TEXT,
    started_at TEXT,
    finished_at TEXT,
    reconcile_meta TEXT,
    PRIMARY KEY (session_id, tool_call_id)
)
"""

_ALLOWED_TRANSITIONS: dict[OperationState, frozenset[OperationState]] = {
    OperationState.PENDING: frozenset(
        {OperationState.RUNNING, OperationState.CANCELLED}
    ),
    OperationState.RUNNING: frozenset(
        {
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.CANCELLED,
            # 崩溃恢复语义（07 §4）：RUNNING 先进 UNKNOWN，不允许跳步直达
            # NEED_RECONCILE——两步链由状态机强制（#30）。
            OperationState.UNKNOWN,
        }
    ),
    # UNKNOWN 只能进入待裁决态；终态必须经 ReconcileCallback 裁决后从
    # NEED_RECONCILE 达成（#30：UNKNOWN 与 NEED_RECONCILE 始终询问用户）。
    OperationState.UNKNOWN: frozenset({OperationState.NEED_RECONCILE}),
    OperationState.NEED_RECONCILE: frozenset(
        {
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.CANCELLED,
        }
    ),
}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class SqliteOperationLedger(OperationLedger):
    """Default local Operation Ledger backed by one SQLite database file."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with _connect(self.database_path) as connection:
            await connection.execute("PRAGMA journal_mode=WAL")
            await self._reject_legacy_schema(connection)
            await connection.execute(_OPERATIONS_DDL)
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operations_session "
                "ON operations(session_id, started_at)"
            )
            await connection.commit()

    @staticmethod
    async def _reject_legacy_schema(connection: aiosqlite.Connection) -> None:
        """升级哨兵：C5 把主键改为 (session_id, tool_call_id) 复合键。

        CREATE TABLE IF NOT EXISTS 不会迁移旧库——旧 schema（tool_call_id 单列
        主键）的 harness.db 若继续使用，跨会话复用 tool_call_id 会以难解的
        UNIQUE IntegrityError 爆掉。这里显式检测并 fail-loud，提示删除旧库
        （ledger 是可重建的恢复辅助状态，不是唯一真相源，事件 JSONL 才是）。
        """
        cursor = await connection.execute("PRAGMA table_info(operations)")
        columns = {row[1]: row[5] for row in await cursor.fetchall()}
        if columns and columns.get("tool_call_id") == 1 and columns.get("session_id") != 1:
            raise RuntimeError(
                f"{connection} 的 operations 表是 C5 之前的旧 schema"
                "（tool_call_id 单列主键）。请删除旧的 harness.db 后重启"
                "（Ledger 是可重建的恢复辅助状态；事件 JSONL 不受影响）。"
            )

    async def create(self, operation: Operation) -> None:
        if operation.state is not OperationState.PENDING:
            raise ValueError("A new Operation must start in PENDING")
        async with _connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO operations (
                    tool_call_id, session_id, run_id, agent_id, tool_name,
                    args_identity, state, result_json, artifact_ref, started_at,
                    finished_at, reconcile_meta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation.tool_call_id,
                    operation.session_id,
                    operation.run_id,
                    operation.agent_id,
                    operation.tool_name,
                    operation.args_identity,
                    operation.state.value,
                    operation.result_json,
                    operation.artifact_ref,
                    operation.started_at,
                    operation.finished_at,
                    operation.reconcile_meta,
                ),
            )
            await connection.commit()

    async def get(self, session_id: str, tool_call_id: str) -> Operation | None:
        """按 (session_id, tool_call_id) 复合主键取 Operation（C5）。

        tool_call_id 由模型生成、只在会话内保证唯一——跨会话复用同一 id
        （"call_1" 是高频模型输出）时单列主键会互相覆盖/撞键。
        """
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM operations WHERE session_id = ? AND tool_call_id = ?",
                (session_id, tool_call_id),
            )
            row = await cursor.fetchone()
        return self._to_operation(row) if row is not None else None

    async def update_state(
        self,
        session_id: str,
        tool_call_id: str,
        state: OperationState,
        *,
        result_json: str | None = None,
        artifact_ref: str | None = None,
        reconcile_meta: str | None = None,
    ) -> Operation:
        current = await self.get(session_id, tool_call_id)
        if current is None:
            raise KeyError(f"Operation '{tool_call_id}' does not exist")
        if state not in _ALLOWED_TRANSITIONS.get(current.state, frozenset()):
            raise ValueError(
                f"Invalid Operation transition: {current.state.value} -> {state.value}"
            )

        finished_at = (
            _utc_now_iso()
            if state
            in {
                OperationState.SUCCEEDED,
                OperationState.FAILED,
                OperationState.CANCELLED,
            }
            else None
        )
        async with _connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                UPDATE operations
                SET state = ?, result_json = COALESCE(?, result_json),
                    artifact_ref = COALESCE(?, artifact_ref),
                    finished_at = COALESCE(?, finished_at),
                    reconcile_meta = COALESCE(?, reconcile_meta)
                WHERE session_id = ? AND tool_call_id = ? AND state = ?
                """,
                (
                    state.value,
                    result_json,
                    artifact_ref,
                    finished_at,
                    reconcile_meta,
                    session_id,
                    tool_call_id,
                    current.state.value,
                ),
            )
            await connection.commit()
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Operation '{tool_call_id}' changed concurrently"
                )
        updated = await self.get(session_id, tool_call_id)
        assert updated is not None
        return updated

    async def list_for_session(self, session_id: str) -> list[Operation]:
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT * FROM operations
                WHERE session_id = ?
                ORDER BY started_at, tool_call_id
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()
        return [self._to_operation(row) for row in rows]

    async def delete_for_session(self, session_id: str) -> int:
        async with _connect(self.database_path) as connection:
            cursor = await connection.execute(
                "DELETE FROM operations WHERE session_id = ?", (session_id,)
            )
            removed = cursor.rowcount or 0
            await connection.commit()
        return removed

    @staticmethod
    def _to_operation(row: aiosqlite.Row) -> Operation:
        return Operation.model_validate(dict(row))


# ── Checkpoint / SessionMeta schema（共享同一 .db 文件，独立 contract）──

_CHECKPOINTS_DDL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    session_id    TEXT NOT NULL,
    boundary_type TEXT NOT NULL CHECK (boundary_type IN (
        'USER_ACCEPTED', 'MODEL_COMPLETED', 'TOOL_BATCH_COMPLETED', 'FINAL_COMPLETED'
    )),
    event_seq     INTEGER NOT NULL,
    payload_json  TEXT,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (session_id, boundary_type, event_seq)
)
"""

_SESSION_META_DDL = """
CREATE TABLE IF NOT EXISTS session_meta (
    session_id          TEXT PRIMARY KEY,
    created_at          TEXT NOT NULL,
    agent_id            TEXT,
    last_checkpoint_seq INTEGER,
    archived            BOOLEAN DEFAULT 0,
    parent_session_id   TEXT,
    origin              TEXT,
    fork_point_seq      INTEGER
)
"""

#: lineage 三列（Phase 14 T1, ADR-0017 决策 7）：存量库加列迁移用。
#: CREATE TABLE IF NOT EXISTS 只惠及新库——旧 schema 的库靠这里逐列补齐，
#: 按列名判存（幂等），旧行三列 NULL = root 语义。
_LINEAGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("parent_session_id", "TEXT"),
    ("origin", "TEXT"),
    ("fork_point_seq", "INTEGER"),
)


class SqliteCheckpointStore(CheckpointStore):
    """默认本地 Checkpoint Store，与 Operation Ledger 共享同一个 SQLite 文件。

    schema 与 #26 冻结一致：PRIMARY KEY (session_id, boundary_type, event_seq)。
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with _connect(self.database_path) as connection:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute(_CHECKPOINTS_DDL)
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_checkpoints_session "
                "ON checkpoints(session_id, event_seq)"
            )
            await connection.commit()

    async def save(self, checkpoint: Checkpoint) -> None:
        async with _connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO checkpoints (
                    session_id, boundary_type, event_seq, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.session_id,
                    checkpoint.boundary_type.value,
                    checkpoint.event_seq,
                    checkpoint.payload_json,
                    checkpoint.created_at,
                ),
            )
            await connection.commit()

    async def list_for_session(self, session_id: str) -> list[Checkpoint]:
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT * FROM checkpoints
                WHERE session_id = ?
                ORDER BY event_seq
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()
        return [self._to_checkpoint(row) for row in rows]

    async def delete_for_session(self, session_id: str) -> int:
        async with _connect(self.database_path) as connection:
            cursor = await connection.execute(
                "DELETE FROM checkpoints WHERE session_id = ?", (session_id,)
            )
            removed = cursor.rowcount or 0
            await connection.commit()
        return removed

    async def latest(self, session_id: str) -> Checkpoint | None:
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT * FROM checkpoints
                WHERE session_id = ?
                ORDER BY event_seq DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
        return self._to_checkpoint(row) if row is not None else None

    @staticmethod
    def _to_checkpoint(row: aiosqlite.Row) -> Checkpoint:
        return Checkpoint.model_validate(
            {**dict(row), "boundary_type": row["boundary_type"]}
        )


class SqliteSessionMetaStore(SessionMetaStore):
    """默认本地 Session Metadata Store，与其它 Store 共享同一个 SQLite 文件。

    schema 与 #26 冻结一致；支持 archived 标记 + 显式 cleanup（不自动 TTL）。
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with _connect(self.database_path) as connection:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute(_SESSION_META_DDL)
            await self._ensure_lineage_columns(connection)
            await connection.commit()

    @staticmethod
    async def _ensure_lineage_columns(connection: aiosqlite.Connection) -> None:
        """存量库加列迁移（幂等）：缺哪列补哪列，旧行 NULL = root。"""
        cursor = await connection.execute("PRAGMA table_info(session_meta)")
        existing = {row[1] for row in await cursor.fetchall()}
        for name, col_type in _LINEAGE_COLUMNS:
            if name not in existing:
                await connection.execute(
                    f"ALTER TABLE session_meta ADD COLUMN {name} {col_type}"
                )

    async def upsert(self, meta: SessionMeta) -> SessionMeta:
        async with _connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO session_meta (
                    session_id, created_at, agent_id, last_checkpoint_seq, archived,
                    parent_session_id, origin, fork_point_seq
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    last_checkpoint_seq = excluded.last_checkpoint_seq,
                    archived = excluded.archived,
                    parent_session_id = excluded.parent_session_id,
                    origin = excluded.origin,
                    fork_point_seq = excluded.fork_point_seq
                """,
                (
                    meta.session_id,
                    meta.created_at,
                    meta.agent_id,
                    meta.last_checkpoint_seq,
                    1 if meta.archived else 0,
                    meta.parent_session_id,
                    meta.origin,
                    meta.fork_point_seq,
                ),
            )
            await connection.commit()
        loaded = await self.get(meta.session_id)
        assert loaded is not None
        return loaded

    async def get(self, session_id: str) -> SessionMeta | None:
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM session_meta WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
        return self._to_meta(row) if row is not None else None

    async def list_all(self) -> list[SessionMeta]:
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM session_meta ORDER BY created_at, session_id"
            )
            rows = await cursor.fetchall()
        return [self._to_meta(row) for row in rows]

    async def set_archived(self, session_id: str, archived: bool = True) -> SessionMeta:
        async with _connect(self.database_path) as connection:
            cursor = await connection.execute(
                "UPDATE session_meta SET archived = ? WHERE session_id = ?",
                (1 if archived else 0, session_id),
            )
            await connection.commit()
            if cursor.rowcount != 1:
                raise KeyError(f"SessionMeta '{session_id}' does not exist")
        loaded = await self.get(session_id)
        assert loaded is not None
        return loaded

    async def update_last_checkpoint_seq(
        self, session_id: str, event_seq: int
    ) -> SessionMeta:
        async with _connect(self.database_path) as connection:
            cursor = await connection.execute(
                "UPDATE session_meta SET last_checkpoint_seq = ? WHERE session_id = ?",
                (event_seq, session_id),
            )
            await connection.commit()
            if cursor.rowcount != 1:
                raise KeyError(f"SessionMeta '{session_id}' does not exist")
        loaded = await self.get(session_id)
        assert loaded is not None
        return loaded

    async def clear_delegation_parent(self, parent_session_id: str) -> int:
        """见 `SessionMetaStore.clear_delegation_parent`（#172 / ADR-0029 D5）。"""
        async with _connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                UPDATE session_meta
                SET parent_session_id = NULL, origin = NULL
                WHERE parent_session_id = ? AND origin = 'delegation'
                """,
                (parent_session_id,),
            )
            repaired = cursor.rowcount or 0
            await connection.commit()
        return repaired

    async def cleanup(self, session_id: str) -> None:
        async with _connect(self.database_path) as connection:
            await connection.execute(
                "DELETE FROM session_meta WHERE session_id = ?",
                (session_id,),
            )
            await connection.commit()

    @staticmethod
    def _to_meta(row: aiosqlite.Row) -> SessionMeta:
        return SessionMeta.model_validate(
            {**dict(row), "archived": bool(row["archived"])}
        )
