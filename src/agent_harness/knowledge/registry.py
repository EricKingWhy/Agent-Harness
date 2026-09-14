"""KnowledgeSource 注册表（ADR-0013 决策 8）：SQLite harness.db 一等实体。

(tenant_id, name) 是自然键（同名重 ingest = 同一 source 重建，citation 稳定）；
source_id 稳定不换。连接纪律照 memory record store / storage/sqlite.py：
每操作新连接 + WAL（initialize 一次）+ busy_timeout（并发写等锁）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from agent_harness.knowledge.types import KnowledgeSource

_BUSY_TIMEOUT_MS = 10_000

_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_sources (
    source_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tenant_id, name)
);
"""


class SqliteKnowledgeSourceRegistry:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @asynccontextmanager
    async def _connect(self):
        connection = await aiosqlite.connect(self.database_path)
        try:
            await connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._connect() as connection:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.executescript(_DDL)
            await connection.commit()

    async def upsert(self, source: KnowledgeSource) -> None:
        """登记/更新 source；ON CONFLICT 保住稳定 source_id 与 created_at。"""
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                """
                INSERT INTO knowledge_sources
                    (source_id, tenant_id, name, content_hash, chunk_count,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, name) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    chunk_count=excluded.chunk_count,
                    updated_at=excluded.updated_at
                """,
                (source.source_id, source.tenant_id, source.name,
                 source.content_hash, source.chunk_count,
                 source.created_at, source.updated_at),
            )
            await connection.commit()

    async def get(self, source_id: str, tenant_id: str) -> KnowledgeSource | None:
        async with self._connect() as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                "SELECT * FROM knowledge_sources WHERE source_id=? AND tenant_id=?",
                (source_id, tenant_id),
            ) as cursor:
                row = await cursor.fetchone()
        return self._source(row) if row is not None else None

    async def get_by_name(self, tenant_id: str, name: str) -> KnowledgeSource | None:
        async with self._connect() as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                "SELECT * FROM knowledge_sources WHERE tenant_id=? AND name=?",
                (tenant_id, name),
            ) as cursor:
                row = await cursor.fetchone()
        return self._source(row) if row is not None else None

    async def delete(self, source_id: str, tenant_id: str) -> None:
        async with self._connect() as connection:
            await connection.execute(
                "DELETE FROM knowledge_sources WHERE source_id=? AND tenant_id=?",
                (source_id, tenant_id),
            )
            await connection.commit()

    async def list(self, tenant_id: str) -> list[KnowledgeSource]:
        async with self._connect() as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                "SELECT * FROM knowledge_sources WHERE tenant_id=? ORDER BY updated_at DESC",
                (tenant_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._source(row) for row in rows]

    @staticmethod
    def _source(row: aiosqlite.Row) -> KnowledgeSource:
        return KnowledgeSource(
            source_id=row["source_id"], tenant_id=row["tenant_id"],
            name=row["name"], content_hash=row["content_hash"],
            chunk_count=row["chunk_count"], created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
