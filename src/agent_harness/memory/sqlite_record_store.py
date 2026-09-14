"""SQLite 权威记录。记录与 outbox 在同一事务中提交。"""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import aiosqlite

from agent_harness.identity import IdentityContext
from agent_harness.memory.record_store import MemoryOperation, PendingMemory
from agent_harness.memory.types import (
    MemoryEntry,
    MemoryNamespace,
    MemoryScope,
    row_namespace_matches,
)

logger = logging.getLogger(__name__)

#: 每操作新连接模式下的连接级 PRAGMA（与 storage/sqlite.py R4-5 同款）：
#: writeback 的 store 与 relay 的 pending/ack 并发写（BEGIN IMMEDIATE），
#: 默认 busy_timeout=0 会立刻抛 "database is locked" 而不是等锁。
_BUSY_TIMEOUT_MS = 10_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_records (
    memory_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL, scope TEXT NOT NULL, namespace TEXT NOT NULL,
    content TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL,
    indexed BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS memory_owner
    ON memory_records(tenant_id, user_id, scope);
CREATE TABLE IF NOT EXISTS memory_outbox (
    memory_id TEXT PRIMARY KEY, revision TEXT NOT NULL,
    operation TEXT NOT NULL DEFAULT 'upsert'
        CHECK (operation IN ('upsert', 'delete')),
    tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
    scope TEXT NOT NULL, namespace TEXT NOT NULL
);
"""

#: `memory_outbox` 在 #156 之前只有 (memory_id, revision)。升级时按需补列 + 回填。
_OUTBOX_ROUTING_COLUMNS = ("tenant_id", "user_id", "scope", "namespace")

#: 迁移回填的完成判据：四个路由列全非空。半迁移（DDL 逐条提交、进程被杀）过的库
#: 会命中它，从而重跑回填 / 清理。
_UNROUTED = " OR ".join(f"{column} IS NULL" for column in _OUTBOX_ROUTING_COLUMNS)


@asynccontextmanager
async def _connect(database_path: Path):
    """打开一个带 busy_timeout 的连接（close 随 CM 退出）。"""
    connection = await aiosqlite.connect(database_path)
    try:
        await connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        yield connection
    finally:
        await connection.close()


def _enqueue(entry_id: str, revision: str, operation: MemoryOperation, *,
             tenant_id: str, user_id: str, scope: str, namespace: str) -> tuple[str, tuple]:
    """outbox 的写入语句：**每个 memory_id 一行**，表达"该 id 的索引期望状态"。

    同 id 后来的写覆盖前一版本（含 upsert↔delete 互相覆盖）——索引只需收敛到最新
    期望，不必重放历史；`revision` 变化同时是 relay 的重试预算重置信号。
    """
    return ("""
        INSERT INTO memory_outbox
            (memory_id, revision, operation, tenant_id, user_id, scope, namespace)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(memory_id) DO UPDATE SET revision=excluded.revision,
            operation=excluded.operation, tenant_id=excluded.tenant_id,
            user_id=excluded.user_id, scope=excluded.scope, namespace=excluded.namespace
    """, (entry_id, revision, operation.value, tenant_id, user_id, scope, namespace))


def _namespace_matches(namespace_json: str, scope: str, identity: IdentityContext) -> bool:
    """记录行上的 namespace 是否就是 identity 授权的那个（比较语义见 `row_namespace_matches`）。

    只在"行确实存在"时调用。`get`/`delete` 共用它，且比较本身也收在一处——写成两套序列化
    比较（一边比 json 串、一边比解析后的 list）在 `as_json` 有任何改动时会静默分叉。
    """
    return row_namespace_matches(tuple(json.loads(namespace_json)), MemoryScope(scope), identity)


def _parse_operation(row: aiosqlite.Row) -> MemoryOperation:
    """outbox 的 operation 列 → 枚举；不认识的值按 **UPSERT** 处理（非破坏性方向）。

    不能假设磁盘上的值一定合法（见 `_migrate_outbox` 的 CHECK 说明）：这里直接抛错会
    让 `pending()` 每轮都失败，而 relay 把异常当"outbox 不可用"咽掉——索引静默停止收敛。
    脏值先告警，再**按记录行的权威内容重新索引**：

    - 记录行还在 → 索引被写回正确内容，自愈（唯一受损的是"这个值看不懂"这件事本身）；
    - 记录行已不在 → `_change` 既有的 "content is None → DELETE" 路径照旧收敛为删除。

    刻意**不**按删除处理：对一条还活着的记录，删除会先清掉索引里的正确内容，随后
    `acknowledge` 又对残留的记录行写上 `indexed=TRUE` 并移除 outbox 行——记忆变得既搜不到
    又声称已索引、且没有任何待办意图去修，那是静默丢失，比"停在一个看得见的坏状态"糟。
    """
    try:
        return MemoryOperation(row["operation"])
    except ValueError:
        logger.warning("Memory outbox entry %s has unknown operation %r; treating as upsert",
                       row["memory_id"], row["operation"])
        return MemoryOperation.UPSERT


def _routing_identity(row: aiosqlite.Row) -> IdentityContext:
    """outbox 行 → relay 用的身份。

    relay 只把 (tenant_id, user_id) 交给存储后端；`scopes` 用这条变更自己的 scope 填充，
    它是写入时已完成的那次授权校验的副本，不是在这里重新授权。
    """
    return IdentityContext(row["tenant_id"], row["user_id"], [row["scope"]])


class SqliteMemoryRecordStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with _connect(self.database_path) as connection:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.executescript(_SCHEMA)
            await self._migrate_outbox(connection)
            await connection.commit()

    @staticmethod
    async def _migrate_outbox(connection: aiosqlite.Connection) -> None:
        """把 #156 之前的 outbox（只有 memory_id/revision）就地升到带操作类型与路由列。

        必须**可重入**：SQLite 的 DDL 不参与驱动事务（每条 `ALTER TABLE` 各自提交），
        所以"看到 operation 列就认为迁移完了"的哨兵会让"加完第一列、还没回填"时被杀的
        进程永久停在半迁移状态——路由列全 NULL，此后 `pending()` 每轮都失败。这里逐列
        补齐缺的列，并且只要还有路由列为空的行就重跑回填与清理；重复执行幂等。

        旧行的路由事实只能来自它对应的记录行；记录行已不在的孤儿行**不可路由**
        （没有 tenant/user/scope 可用于调 `vectors.delete`），留着会让 `pending()`
        每轮都失败——迁移期丢弃并告警（`indexed` 对一个不存在的记录行也无意义）。

        列可空性：迁移来的列可空（`ALTER TABLE ADD COLUMN` 没法"先空后填"再收紧），
        新建库不可空——新库只由本模块写入，永远有真实值。操作类型的 CHECK 只在**这一
        次**补列时装上（SQLite 允许 `ADD COLUMN` 带 CHECK 并真的执行它）；已经带着一个
        无 CHECK 的 operation 列的库补不上约束——SQLite 不支持给既有列追加 CHECK，重建
        整张表来装一个防自己写错的约束不值得。那条路径的兜底是 `_parse_operation` 的
        自愈 + 告警，不是约束。
        """
        async with connection.execute("PRAGMA table_info(memory_outbox)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        if "operation" not in columns:
            await connection.execute(
                "ALTER TABLE memory_outbox ADD COLUMN operation TEXT NOT NULL DEFAULT 'upsert'"
                " CHECK (operation IN ('upsert', 'delete'))")
        for column in _OUTBOX_ROUTING_COLUMNS:
            if column not in columns:
                await connection.execute(f"ALTER TABLE memory_outbox ADD COLUMN {column} TEXT")
        async with connection.execute(
            f"SELECT COUNT(*) FROM memory_outbox WHERE {_UNROUTED}"
        ) as cursor:
            (unrouted,) = await cursor.fetchone()
        if not unrouted:
            return
        # 单条 UPDATE 是原子的：不会留下"填了一半路由列"的行。
        await connection.execute(f"""
            UPDATE memory_outbox SET
                tenant_id=(SELECT tenant_id FROM memory_records WHERE memory_id=memory_outbox.memory_id),
                user_id=(SELECT user_id FROM memory_records WHERE memory_id=memory_outbox.memory_id),
                scope=(SELECT scope FROM memory_records WHERE memory_id=memory_outbox.memory_id),
                namespace=(SELECT namespace FROM memory_records WHERE memory_id=memory_outbox.memory_id)
            WHERE {_UNROUTED}
        """)
        async with connection.execute(
            f"SELECT memory_id FROM memory_outbox WHERE {_UNROUTED}"
        ) as cursor:
            orphans = [row[0] for row in await cursor.fetchall()]
        if orphans:
            await connection.execute(f"DELETE FROM memory_outbox WHERE {_UNROUTED}")
            # 留痕带 id（只报数量无法对账；截断到 20 个避免单行日志过长）。
            listed = ", ".join(orphans[:20]) + (" …" if len(orphans) > 20 else "")
            logger.warning("Dropped %d unroutable legacy memory outbox row(s) "
                           "(no record row to derive tenant/user/scope): %s", len(orphans), listed)

    async def store(self, entry: MemoryEntry, identity: IdentityContext) -> str:
        namespace = MemoryNamespace.of(entry.scope, identity).as_json()
        async with _connect(self.database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            async with connection.execute("SELECT namespace FROM memory_records WHERE memory_id=?", (entry.id,)) as cursor:
                previous = await cursor.fetchone()
            if previous and previous[0] != namespace:
                raise PermissionError("Memory belongs to a different namespace")
            await connection.execute("""
                INSERT INTO memory_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, FALSE)
                ON CONFLICT(memory_id) DO UPDATE SET content=excluded.content,
                    metadata=excluded.metadata, indexed=FALSE
            """, (entry.id, identity.tenant_id, identity.user_id, entry.scope.value, namespace,
                  entry.content, json.dumps(entry.metadata, ensure_ascii=False), entry.created_at))
            await connection.execute(*_enqueue(
                entry.id, str(uuid4()), MemoryOperation.UPSERT, tenant_id=identity.tenant_id,
                user_id=identity.user_id, scope=entry.scope.value, namespace=namespace))
            await connection.commit()
        return entry.id

    async def delete(self, memory_id: str, identity: IdentityContext) -> bool:
        """硬删：摘记录行 + 记一条 `DELETE` 索引意图，同事务（契约见 Protocol）。"""
        async with _connect(self.database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            connection.row_factory = aiosqlite.Row
            async with connection.execute(
                "SELECT scope, namespace FROM memory_records WHERE memory_id=?", (memory_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                await connection.commit()  # 无写操作；幂等地报告"没有这条"
                return False
            if not _namespace_matches(row["namespace"], row["scope"], identity):
                raise PermissionError("Memory belongs to a different namespace")
            await connection.execute("DELETE FROM memory_records WHERE memory_id=?", (memory_id,))
            await connection.execute(*_enqueue(
                memory_id, str(uuid4()), MemoryOperation.DELETE, tenant_id=identity.tenant_id,
                user_id=identity.user_id, scope=row["scope"], namespace=row["namespace"]))
            await connection.commit()
        return True

    async def get(self, memory_id: str, identity: IdentityContext) -> MemoryEntry:
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute("""
                SELECT * FROM memory_records WHERE memory_id=? AND tenant_id=? AND user_id=?
            """, (memory_id, identity.tenant_id, identity.user_id)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            raise KeyError(memory_id)
        if not _namespace_matches(row["namespace"], row["scope"], identity):
            raise KeyError(memory_id)
        return self._entry(row)

    async def list_by_scope(
        self, scope: MemoryScope, identity: IdentityContext, limit: int,
    ) -> list[MemoryEntry]:
        namespace = MemoryNamespace.of(scope, identity).as_json()
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute("""
                SELECT * FROM memory_records WHERE tenant_id=? AND user_id=? AND namespace=?
                ORDER BY created_at DESC, memory_id DESC LIMIT ?
            """, (identity.tenant_id, identity.user_id, namespace, max(0, limit))) as cursor:
                return [self._entry(row) for row in await cursor.fetchall()]

    @staticmethod
    def _entry(row: aiosqlite.Row) -> MemoryEntry:
        return MemoryEntry(id=row["memory_id"], content=row["content"], metadata=json.loads(row["metadata"]),
                           created_at=row["created_at"], scope=row["scope"], indexed=bool(row["indexed"]))

    async def pending(self, limit: int = 100, after_id: str = "") -> list[PendingMemory]:
        """仅 relay 调用的系统级 outbox 读取，不暴露给模型/请求。

        **以 outbox 为驱动表**（`LEFT JOIN` 记录行）：删除变更没有记录行可依赖，
        以记录行为驱动会把刚删掉的 id 直接过滤掉——变更永远到不了索引。路由事实
        全部读 outbox 自己的列。
        """
        async with _connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            async with connection.execute("""
                SELECT o.memory_id AS memory_id, o.revision AS revision, o.operation AS operation,
                       o.tenant_id AS tenant_id, o.user_id AS user_id, o.scope AS scope,
                       o.namespace AS namespace, r.content AS content, r.metadata AS metadata,
                       r.created_at AS created_at, r.indexed AS indexed
                FROM memory_outbox o LEFT JOIN memory_records r ON r.memory_id = o.memory_id
                WHERE o.memory_id > ? ORDER BY o.memory_id LIMIT ?
            """, (after_id, max(0, limit))) as cursor:
                rows = await cursor.fetchall()
        return [self._change(row) for row in rows]

    @staticmethod
    def _change(row: aiosqlite.Row) -> PendingMemory:
        namespace = MemoryNamespace(tuple(json.loads(row["namespace"])))
        operation = _parse_operation(row)
        entry = None
        if operation is MemoryOperation.UPSERT:
            if row["content"] is None:
                # 记录行已不在（升级前遗留 / 绕过契约的删除）：没有内容可索引，但索引里
                # 可能留着残留——按"期望状态 = 不存在"处理，把残留清掉。
                logger.warning("Memory outbox entry %s has no record row; treating as delete",
                               row["memory_id"])
                operation = MemoryOperation.DELETE
            else:
                entry = MemoryEntry(id=row["memory_id"], content=row["content"],
                                    metadata=json.loads(row["metadata"]), created_at=row["created_at"],
                                    scope=namespace.scope, indexed=bool(row["indexed"]))
        return PendingMemory(operation=operation, memory_id=row["memory_id"],
                             identity=_routing_identity(row), scope=namespace.scope,
                             session_id=namespace.session_id,
                             revision=str(row["revision"]), entry=entry)

    async def acknowledge(self, change: PendingMemory) -> bool:
        async with _connect(self.database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute("DELETE FROM memory_outbox WHERE memory_id=? AND revision=?",
                                              (change.memory_id, change.revision))
            matched = cursor.rowcount == 1
            if matched:
                # 删除变更此时已无记录行 → 这条 UPDATE 命中 0 行（幂等）。
                await connection.execute("UPDATE memory_records SET indexed=TRUE WHERE memory_id=?",
                                         (change.memory_id,))
            await connection.commit()
        return matched
