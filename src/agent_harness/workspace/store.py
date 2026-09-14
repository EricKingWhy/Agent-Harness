"""Workspace 实体 + 有序账本的 SQLite 持久层（ADR-0025 D4/D5）。

五张表（同一 `harness.db`）：
- `workspaces`         记录（id / 规范 path 唯一 / title / 时间戳）
- `workspace_order`    注册表顺序（position 0 = 最新，AC9"前插"）
- `workspace_sessions` 每个 workspace 的有序会话账本（position 0 = 最新）
- `workspace_changes`  **待定变更标记**（意图日志）
- `workspace_meta`     键值（bootstrap 完成标记等）

连接纪律照 `knowledge/registry.py` / `memory/sqlite_record_store.py`：每操作新连接 +
`journal_mode=WAL`（initialize 一次）+ `busy_timeout`（并发写等锁）+ 写走
`BEGIN IMMEDIATE`。

**本层只管持久化，不含语义**（缓存、成员资格过滤、bootstrap 在 `index.py`）。
一件事例外且刻意：`create` / `delete` 的**两次写入**（记录、顺序）分属两个事务，
中间靠 `workspace_changes` 的标记保证可恢复——这是 AC12/AC13 的形状，不是疏漏。
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from agent_harness.workspace.models import Workspace

_BUSY_TIMEOUT_MS = 10_000

_DDL = """
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_order (
    position INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS workspace_sessions (
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, session_id)
);

CREATE TABLE IF NOT EXISTS workspace_changes (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CHANGE_CREATE = "create"
CHANGE_DELETE = "delete"


class WorkspaceRegistryCorrupt(RuntimeError):
    """顺序/表不一致且**没有**待定变更标记（AC13）——大声失败，不静默修补。"""


class SqliteWorkspaceStore:
    """`harness.db` 上的 Workspace 持久层（无缓存、无语义）。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    # —— 连接 ——

    @asynccontextmanager
    async def _connect(self):
        connection = await aiosqlite.connect(self.database_path)
        try:
            connection.row_factory = aiosqlite.Row
            await connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        """幂等建表（WAL 只在这里设一次）。"""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._connect() as connection:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.executescript(_DDL)
            await connection.commit()

    # —— 读（初始载入用；运行期读走 index 的缓存）——

    async def load_workspaces(self) -> list[Workspace]:
        """按注册表顺序（新→旧）载入全部记录（不含会话账本）。"""
        async with self._connect() as connection:
            async with connection.execute(
                "SELECT workspace_id, path, title, created_at, updated_at "
                "FROM workspaces"
            ) as cursor:
                rows = await cursor.fetchall()
            async with connection.execute(
                "SELECT workspace_id, position FROM workspace_order ORDER BY position"
            ) as cursor:
                order_rows = await cursor.fetchall()

        by_id = {row["workspace_id"]: row for row in rows}
        ordered: list[Workspace] = []
        seen: set[str] = set()
        for order_row in order_rows:
            workspace_id = order_row["workspace_id"]
            row = by_id.get(workspace_id)
            if row is None or workspace_id in seen:
                continue
            seen.add(workspace_id)
            ordered.append(self._workspace(row))
        # 记录存在但**没有**顺序行的分叉：由调用方按 AC13 判定（有标记 → 解决；
        # 无标记 → 大声失败），所以这里把遗漏的按 id 顺序补在末尾，让上层看得见。
        for workspace_id, row in by_id.items():
            if workspace_id not in seen:
                ordered.append(self._workspace(row))
        return ordered

    async def load_session_ledger(self) -> dict[str, list[str]]:
        """workspace_id → 有序 session_id（新→旧）。"""
        async with self._connect() as connection, connection.execute(
            "SELECT workspace_id, session_id FROM workspace_sessions "
            "ORDER BY workspace_id, position"
        ) as cursor:
            rows = await cursor.fetchall()
        ledger: dict[str, list[str]] = {}
        for row in rows:
            ledger.setdefault(row["workspace_id"], []).append(row["session_id"])
        return ledger

    async def orphan_session_workspaces(self) -> list[str]:
        """有会话账本行、却没有对应记录的 workspace_id（只读诊断）。"""
        async with self._connect() as connection, connection.execute(
            "SELECT DISTINCT s.workspace_id AS wid FROM workspace_sessions s "
            "LEFT JOIN workspaces w ON w.workspace_id = s.workspace_id "
            "WHERE w.workspace_id IS NULL"
        ) as cursor:
            rows = await cursor.fetchall()
        return [row["wid"] for row in rows]

    async def missing_order_ids(self) -> list[str]:
        """有记录、却没有顺序行的 workspace_id（AC13 的分叉判据）。"""
        async with self._connect() as connection, connection.execute(
            "SELECT w.workspace_id AS wid FROM workspaces w "
            "LEFT JOIN workspace_order o ON o.workspace_id = w.workspace_id "
            "WHERE o.workspace_id IS NULL"
        ) as cursor:
            rows = await cursor.fetchall()
        return [row["wid"] for row in rows]

    async def dangling_order_ids(self) -> list[str]:
        """有顺序行、却没有记录的 workspace_id（AC13 的反向分叉）。"""
        async with self._connect() as connection, connection.execute(
            "SELECT o.workspace_id AS wid FROM workspace_order o "
            "LEFT JOIN workspaces w ON w.workspace_id = o.workspace_id "
            "WHERE w.workspace_id IS NULL"
        ) as cursor:
            rows = await cursor.fetchall()
        return [row["wid"] for row in rows]

    async def get_meta(self, key: str) -> str | None:
        async with self._connect() as connection, connection.execute(
            "SELECT value FROM workspace_meta WHERE key=?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        return row["value"] if row is not None else None

    # —— 待定变更标记（D5）——

    async def pending_changes(self) -> list[tuple[int, str, str]]:
        """→ [(change_id, kind, workspace_id)]，按写入顺序。"""
        async with self._connect() as connection, connection.execute(
            "SELECT change_id, kind, workspace_id FROM workspace_changes "
            "ORDER BY change_id"
        ) as cursor:
            rows = await cursor.fetchall()
        return [(row["change_id"], row["kind"], row["workspace_id"]) for row in rows]

    async def begin_change(self, kind: str, workspace_id: str, now: str) -> int:
        """第一次写入：持久写标记并提交（此后崩溃可被 `resolve_pending_change` 看见）。"""
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "INSERT INTO workspace_changes (kind, workspace_id, created_at) "
                "VALUES (?, ?, ?)",
                (kind, workspace_id, now),
            )
            change_id = int(cursor.lastrowid or 0)
            await connection.commit()
        return change_id

    async def write_record(self, workspace: Workspace) -> None:
        """第二次写入之一：记录行（与顺序行分属两个事务，见模块 docstring）。

        **纯 `INSERT`，不是 `INSERT OR REPLACE`**：规范路径上有唯一约束，正常路径上
        调用方已经确认"该路径尚未被拥有"（`index.create` 在写锁下判断）。若此时仍撞上
        路径冲突，说明有另一份写者（同进程外的实现错误，或缓存与库不同步），
        `OR REPLACE` 会把**对方那条记录**整行换成我们的 id、却留着对方在
        `workspace_order` 里的行——留下悬空顺序行，下次启动按 AC13 拒绝启动。
        让唯一约束在这里响亮报错，比静默改写别人的记录好。
        """
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "INSERT INTO workspaces "
                "(workspace_id, path, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    workspace.id,
                    workspace.path,
                    workspace.title,
                    workspace.created_at,
                    workspace.updated_at,
                ),
            )
            await connection.commit()

    async def prepend_record(self, workspace_id: str, change_id: int) -> None:
        """第二次写入之二：顺序行前插 + **同事务**清掉标记（关键，见 ADR D5）。"""
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await _prepend_workspace(connection, workspace_id)
            await connection.execute(
                "DELETE FROM workspace_changes WHERE change_id=?", (change_id,)
            )
            await connection.commit()

    async def append_record(self, workspace_id: str, change_id: int) -> None:
        """bootstrap 用：顺序行**追加到尾部** + 同事务清标记（初始顺序即最终顺序）。"""
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            async with connection.execute(
                "SELECT COUNT(*) AS n FROM workspace_order"
            ) as cursor:
                row = await cursor.fetchone()
            await connection.execute(
                "INSERT OR REPLACE INTO workspace_order (position, workspace_id) "
                "VALUES (?, ?)",
                (int(row["n"]), workspace_id),
            )
            await connection.execute(
                "DELETE FROM workspace_changes WHERE change_id=?", (change_id,)
            )
            await connection.commit()

    async def drop_record(self, workspace_id: str) -> None:
        """删除的记录行（第二写入之一；回滚 create 时也可用，幂等）。"""
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "DELETE FROM workspaces WHERE workspace_id=?", (workspace_id,)
            )
            await connection.commit()

    async def drop_order(self, workspace_id: str, change_id: int | None = None) -> None:
        """删除顺序行（+ 可选同事务清标记）。"""
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "DELETE FROM workspace_order WHERE workspace_id=?", (workspace_id,)
            )
            if change_id is not None:
                await connection.execute(
                    "DELETE FROM workspace_changes WHERE change_id=?", (change_id,)
                )
            await connection.commit()

    async def drop_sessions(self, workspace_id: str) -> None:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "DELETE FROM workspace_sessions WHERE workspace_id=?", (workspace_id,)
            )
            await connection.commit()

    # —— 语义写入（顺序/标题/会话账本）——

    async def set_title(self, workspace_id: str, title: str, now: str) -> None:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "UPDATE workspaces SET title=?, updated_at=? WHERE workspace_id=?",
                (title, now, workspace_id),
            )
            await connection.commit()

    async def touch(self, workspace_id: str, now: str) -> None:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "UPDATE workspaces SET updated_at=? WHERE workspace_id=?",
                (now, workspace_id),
            )
            await connection.commit()

    async def replace_session_order(
        self, workspace_id: str, session_ids: Sequence[str]
    ) -> None:
        """整表重写该 workspace 的会话顺序（position 0..n-1）。"""
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "DELETE FROM workspace_sessions WHERE workspace_id=?", (workspace_id,)
            )
            for position, session_id in enumerate(session_ids):
                await connection.execute(
                    "INSERT INTO workspace_sessions "
                    "(workspace_id, session_id, position) VALUES (?, ?, ?)",
                    (workspace_id, session_id, position),
                )
            await connection.commit()

    async def replace_workspace_order(self, workspace_ids: Sequence[str]) -> None:
        """整表重写注册表顺序（bootstrap 收尾用：顺序是新→旧的**纯函数**）。

        为什么需要它：引导中途崩溃后重跑时，先前那次已经把部分记录按"追加"落进
        顺序表；只靠"再追加"会把更旧的项目排到更新的前面（AC14 要求最新在前）。
        收尾时按本次算出的完整顺序重写一次，使"中断后重跑"与"一次跑完"结果相同
        （AC15 的"可安全续跑"要的是这个，而不只是不重复）。重编号是同一事务里的
        整体替换，记录↔顺序的一一对应在事务内外都成立。
        """
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute("DELETE FROM workspace_order")
            for position, workspace_id in enumerate(workspace_ids):
                await connection.execute(
                    "INSERT INTO workspace_order (position, workspace_id) VALUES (?, ?)",
                    (position, workspace_id),
                )
            await connection.commit()

    async def set_meta(self, key: str, value: str) -> None:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "INSERT INTO workspace_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await connection.commit()

    # —— 内部 ——

    @staticmethod
    def _workspace(row: aiosqlite.Row) -> Workspace:
        return Workspace(
            id=row["workspace_id"],
            path=row["path"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def require_existing_directory(path: str) -> None:
    """AC9：路径必须指向**已存在**的目录，否则原样传出 OS 错误。

    `os.stat` 而不是 `Path.is_dir()`：前者区分 `FileNotFoundError`（ENOENT）与
    `NotADirectoryError`（ENOTDIR），也让符号链接指向目录的情况自然成立（stat 跟随
    链接）。**不创建目录**——AC9 明确反对"顺带 mkdir"。
    """
    st = os.stat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise NotADirectoryError(errno.ENOTDIR, "不是目录", path)


async def _prepend_workspace(
    connection: aiosqlite.Connection, workspace_id: str
) -> None:
    """把 workspace 前插到注册表顺序最前，position 重编号为 0..n-1。

    position 用稠密整数表示，重排时整表重写：workspace 数量是几十的量级，
    显式重排是低频用户动作；稠密整数比小数插值可读，也不会精度耗尽。
    （同一个事务内先删后插，中间态不外泄。）
    """
    async with connection.execute(
        "SELECT workspace_id FROM workspace_order ORDER BY position"
    ) as cursor:
        existing = [row["workspace_id"] for row in await cursor.fetchall()]
    merged = [workspace_id, *(item for item in existing if item != workspace_id)]
    await connection.execute("DELETE FROM workspace_order")
    for position, item in enumerate(merged):
        await connection.execute(
            "INSERT INTO workspace_order (position, workspace_id) VALUES (?, ?)",
            (position, item),
        )
