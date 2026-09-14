"""WS-2 / issue #152：Workspace 实体 + 有序会话账本 + 原子性 + 首次引导。

覆盖 AC1–AC16 的**行为**面。三处判定值得单独指出，因为它们是本票的设计核心而非实现细节：

1. **成员资格是双向的（AC6）**：账本有 id **且** 会话 header 的规范 cwd 逐字符等于
   `workspace.path`；不匹配的候选**永不返回**，并在下一次被接受的变更时被**持久修剪**。
2. **原子性是"意图日志"（AC12/AC13）**：`create`/`delete` 的记录与顺序分属两个事务，
   中间崩溃靠待定标记恢复；**没有**标记的不一致是损坏，必须大声失败。
3. **引导绝不读事件正文（AC14）**：只允许读第一条 `session/started`——本文件用一个
   "读第 2 行就报错"的文件包装器把这条钉死，而不是靠"看起来很快"。
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from agent_harness.sandbox import canonical_workspace_path
from agent_harness.session import Session
from agent_harness.session.header import StartedHeader
from agent_harness.session.store import JsonlSessionStore
from agent_harness.workspace import (
    SqliteWorkspaceStore,
    UnknownLedgerEntry,
    UnknownWorkspace,
    Workspace,
    WorkspaceError,
    WorkspaceIndex,
    WorkspaceRegistryCorrupt,
)

# —— 测试替身与工具 ——


class _FakeHeaders:
    """dict 支撑的 header 来源（`SessionHeaders` 结构化实现）。"""

    def __init__(self) -> None:
        self.headers: dict[str, StartedHeader] = {}
        self.order: list[str] = []
        self.reads: list[str] = []
        self.unreadable: set[str] = set()

    def add(
        self,
        session_id: str,
        cwd: str | None,
        created_at: str | None = "2026-01-01T00:00:00+00:00",
        agent_id: str | None = None,
    ) -> None:
        self.headers[session_id] = StartedHeader(
            session_id=session_id, cwd=cwd, created_at=created_at, agent_id=agent_id
        )
        if session_id not in self.order:
            self.order.append(session_id)

    def list_session_ids(self) -> list[str]:
        return list(self.order)

    def read_started_header(self, session_id: str) -> StartedHeader | None:
        self.reads.append(session_id)
        if session_id in self.unreadable:
            raise OSError(f"模拟不可读的会话日志：{session_id}")
        return self.headers.get(session_id)


def _store(tmp_path: Path) -> SqliteWorkspaceStore:
    return SqliteWorkspaceStore(tmp_path / "harness.db")


def _index(tmp_path: Path, headers: _FakeHeaders) -> WorkspaceIndex:
    return WorkspaceIndex(_store(tmp_path), headers)


def _project(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _canon(path: Path) -> str:
    return canonical_workspace_path(path)


def _make_directory_link(link: Path, target: Path) -> bool:
    """建目录链接（符号链接 → Windows 目录联接回退）；做不到返回 False。"""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt":
        return False
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return completed.returncode == 0


class _CrashAfterRecordStore(SqliteWorkspaceStore):
    """在"记录已写、顺序未写（标记仍在）"处模拟崩溃。"""

    def __init__(self, database_path: Path, *, kind: str = "create") -> None:
        super().__init__(database_path)
        self.kind = kind
        self.armed = True

    async def prepend_record(self, workspace_id: str, change_id: int) -> None:
        if self.armed and self.kind == "create":
            raise RuntimeError("模拟崩溃：记录已写，顺序未写")
        await super().prepend_record(workspace_id, change_id)

    async def drop_order(self, workspace_id: str, change_id: int | None = None) -> None:
        if self.armed and self.kind == "delete":
            raise RuntimeError("模拟崩溃：记录已删，顺序未删")
        await super().drop_order(workspace_id, change_id)


class _GateAfterRecordStore(SqliteWorkspaceStore):
    """把"记录已写、顺序未写"这个窗口撑开，让第二个请求有机会插进来（F1 复现位点）。

    记录**已经提交**（`super().write_record` 返回后），所以第二个 `create` 无论何时
    进入 `write_record` 都会撞上 path 唯一约束——没有写锁时它在 `gather` 里响亮报错，
    有写锁时它根本进不来（先拿到锁的那个已经把缓存也更新了 → 幂等返回）。

    `armed=False`（默认）时不拦：测试的前置 `create` 也要走 `write_record`，一直拦
    会把测试自己的准备步骤挂死。
    """

    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.armed = False
        self.record_written = asyncio.Event()
        self.release = asyncio.Event()

    async def write_record(self, workspace: Workspace) -> None:
        await super().write_record(workspace)
        if not self.armed:
            return
        self.record_written.set()
        await self.release.wait()

    async def begin_change(self, kind: str, workspace_id: str, now: str) -> int:
        """另一个写者若在窗口期真的进了 store，就**响亮失败**。

        这是"锁是否共享"的**确定性**判据：各方法各拿一把锁时，`delete` 会立刻走到
        这里并抛错；共用一把锁时，它先在 `WorkspaceIndex` 的锁上排队，根本到不了。
        比"睡若干轮再看任务有没有完成"可靠——那种断言只差一个线程往返就会假通过。
        """
        if self.armed and self.record_written.is_set() and not self.release.is_set():
            raise AssertionError("写者在第一个请求仍在临界区时进入了 store（写锁没共享）")
        return await super().begin_change(kind, workspace_id, now)


class _GateFirstLedgerStore(SqliteWorkspaceStore):
    """只撑开**第一次**账本写入：复现"两个 attach 各自基于同一份旧账本写库"。"""

    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.armed = False
        self.first_entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def replace_session_order(self, workspace_id: str, session_ids) -> None:  # type: ignore[override]
        self.calls += 1
        if self.armed and self.calls == 1:
            self.first_entered.set()
            await self.release.wait()
        await super().replace_session_order(workspace_id, session_ids)


class _FailTouchStore(SqliteWorkspaceStore):
    """账本写入成功、`updated_at` 更新失败（元数据失败不该把缓存写成旧值）。"""

    async def touch(self, workspace_id: str, now: str) -> None:
        raise RuntimeError("模拟 touch 失败（busy timeout / 磁盘错误）")


# —— AC9/AC10：实体与注册表 ——


@pytest.mark.asyncio
class TestEntity:
    async def test_create_registers_existing_directory(self, tmp_path: Path) -> None:
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()

        project = _project(tmp_path, "myproj")
        workspace = await index.create(project)

        assert workspace.path == _canon(project)
        assert workspace.title == "myproj"
        assert workspace.created_at and workspace.updated_at
        assert index.get(workspace.id) is not None
        assert [w.id for w in index.list()] == [workspace.id]

    async def test_create_requires_existing_directory(self, tmp_path: Path) -> None:
        """AC9：不存在 → 原样传出 ENOENT；不是目录 → ENOTDIR。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()

        with pytest.raises(FileNotFoundError):
            await index.create(tmp_path / "nope")

        file_path = tmp_path / "a-file.txt"
        file_path.write_text("x", encoding="utf-8")
        with pytest.raises(NotADirectoryError):
            await index.create(file_path)

    async def test_create_is_idempotent_for_same_canonical_path(
        self, tmp_path: Path
    ) -> None:
        """AC9/AC2：同一物理目录（等价写法）只应有一个实体。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "proj")

        first = await index.create(project)
        second = await index.create(f"{project}{os.sep}.")
        third = await index.create(_canon(project))

        assert first.id == second.id == third.id
        assert len(index.list()) == 1

    async def test_symlinked_directory_conflicts_with_its_target(
        self, tmp_path: Path
    ) -> None:
        """AC2：唯一性 = 规范路径字符串相等 → 链接指向已被拥有的目录 = 同一实体。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "real-proj")
        link = tmp_path / "alias-proj"
        if not _make_directory_link(link, project):
            pytest.skip("当前环境既不能建符号链接也不能建目录联接")

        first = await index.create(project)
        second = await index.create(link)
        assert first.id == second.id
        assert len(index.list()) == 1

    async def test_path_is_never_rewritten_when_directory_disappears(
        self, tmp_path: Path
    ) -> None:
        """AC2/AC8：目录消失不改写记录，只把 status 报成 missing-dir。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "gone")
        workspace = await index.create(project)
        original_path = workspace.path

        import shutil

        shutil.rmtree(project)

        reloaded = index.get(workspace.id)
        assert reloaded is not None
        assert reloaded.path == original_path
        assert reloaded.status() == "missing-dir"

    async def test_status_is_ok_for_existing_directory(self, tmp_path: Path) -> None:
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        workspace = await index.create(_project(tmp_path, "alive"))
        assert workspace.status() == "ok"

    async def test_title_defaults_and_can_be_set(self, tmp_path: Path) -> None:
        """AC3：缺省取末段路径；允许重名；setTitle 持久化。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()

        first = await index.create(_project(tmp_path, "one"), title="同名")
        second = await index.create(_project(tmp_path, "two"), title="同名")
        assert first.title == second.title == "同名"

        renamed = await index.set_title(first.id, "改过的名字")
        assert renamed.title == "改过的名字"
        assert index.get(first.id).title == "改过的名字"  # type: ignore[union-attr]

    async def test_set_title_unknown_id_raises(self, tmp_path: Path) -> None:
        index = _index(tmp_path, _FakeHeaders())
        await index.initialize()
        with pytest.raises(UnknownWorkspace):
            await index.set_title("nope", "x")

    async def test_resolve_by_path_does_not_create(self, tmp_path: Path) -> None:
        """AC10：resolveByPath 用同一套 realpath 规范但**不创建**。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "resolvable")
        assert index.resolve_by_path(project) is None

        workspace = await index.create(project)
        assert index.resolve_by_path(f"{project}{os.sep}.").id == workspace.id  # type: ignore[union-attr]
        assert index.resolve_by_path(tmp_path / "never-created") is None

    async def test_reads_come_from_cache_not_disk(self, tmp_path: Path) -> None:
        """AC10：`get` / `list` 是**同步缓存读**——把库文件毁掉也照样读得出来。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        workspace = await index.create(_project(tmp_path, "cached"))

        (tmp_path / "harness.db").write_bytes(b"")  # 破坏库文件

        assert index.get(workspace.id).path == workspace.path  # type: ignore[union-attr]
        assert [w.id for w in index.list()] == [workspace.id]
        assert index.resolve_by_path(workspace.path).id == workspace.id  # type: ignore[union-attr]

    async def test_title_default_for_root_path(self, tmp_path: Path) -> None:
        """AC3：无末段（根路径）→ 用根路径拼写，不回空标题。"""
        root = tmp_path.anchor  # Windows: "C:\\"；POSIX: "/"
        assert Workspace.default_title(root) == str(Path(root))

    async def test_list_order_is_newest_first(self, tmp_path: Path) -> None:
        """AC9"前插进持久注册表顺序"：后建的项目排在最前。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        first = await index.create(_project(tmp_path, "p1"))
        second = await index.create(_project(tmp_path, "p2"))
        assert [w.id for w in index.list()] == [second.id, first.id]

    async def test_soft_delete_keeps_directory_and_logs(self, tmp_path: Path) -> None:
        """AC11：软删除只摘注册记录 + 顺序 + 会话账本；目录与已落盘日志不动。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        store = JsonlSessionStore(tmp_path / "sessions")
        project = _project(tmp_path, "keepme")
        workspace = await index.create(project)
        Session.start(store, session_id="s-keep", cwd=project)
        headers.add("s-keep", _canon(project))
        await index.attach_session("s-keep")
        events_path = tmp_path / "sessions" / "s-keep" / "events.jsonl"
        before = events_path.read_bytes()

        assert await index.delete(workspace.id) is True

        assert index.get(workspace.id) is None
        assert index.resolve_by_path(project) is None
        assert project.is_dir(), "目录被删了——AC11 明令不动"
        assert events_path.read_bytes() == before, "已落盘日志被改了"

    async def test_soft_delete_unknown_id_returns_false(self, tmp_path: Path) -> None:
        index = _index(tmp_path, _FakeHeaders())
        await index.initialize()
        assert await index.delete("nope") is False

    async def test_state_survives_restart(self, tmp_path: Path) -> None:
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "persisted")
        workspace = await index.create(project, title="持久")
        headers.add("sess-1", _canon(project))
        await index.attach_session("sess-1")

        reborn = _index(tmp_path, headers)
        await reborn.initialize()

        reloaded = reborn.get(workspace.id)
        assert reloaded is not None
        assert reloaded.title == "持久"
        assert reloaded.session_ids == ("sess-1",)


# —— AC5/AC6/AC7：有序账本与成员资格 ——


@pytest.mark.asyncio
class TestLedger:
    async def test_attach_prepends(self, tmp_path: Path) -> None:
        """AC5：新会话 attach 时**前插**（新→旧）。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "proj")
        workspace = await index.create(project)
        for sid in ("s1", "s2", "s3"):
            headers.add(sid, _canon(project))
            await index.attach_session(sid)

        assert index.get(workspace.id).session_ids == ("s3", "s2", "s1")  # type: ignore[union-attr]

    async def test_attach_without_matching_workspace_returns_none(
        self, tmp_path: Path
    ) -> None:
        """只加入**已注册**的项目：默认会话的目录不注册 → 天然 Ungrouped。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        headers.add("lonely", str(tmp_path / "not-a-project"))
        assert await index.attach_session("lonely") is None
        assert index.list() == []

    async def test_attach_without_cwd_returns_none(self, tmp_path: Path) -> None:
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        headers.add("legacy", None)
        assert await index.attach_session("legacy") is None

    async def test_attach_matching_keeps_members_with_unreadable_header(
        self, tmp_path: Path
    ) -> None:
        """#169 批次审查 P2：**暂时读不到** header 的既有成员不能被顺手剪掉。

        账本位置一旦丢了就再也回不来（`_visible_ids` 只看账本）——会话会静默永久变成
        Ungrouped。AC6 只要求"缺 header 的候选**本次**不算成员"，不是"除名"。
        """
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "proj")
        workspace = await index.create(project)
        for sid in ("s1", "s2"):
            headers.add(sid, _canon(project))
            await index.attach_session(sid)

        headers.add("s3", _canon(project))
        headers.add("s4", _canon(project))
        headers.unreadable.add("s2")  # 模拟日志被占用：这次读不到

        adopted = await index.attach_matching_sessions(workspace.id)
        assert adopted == 2, "只该归入 s3/s4；s2 这次读不到，不算成员也不算新归入"

        headers.unreadable.discard("s2")  # 恢复可读
        assert set(index.get(workspace.id).session_ids) == {"s1", "s2", "s3", "s4"}

    async def test_membership_requires_matching_header_cwd(self, tmp_path: Path) -> None:
        """AC6：账本有 id 但 header cwd 不匹配 → **永不返回**。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "proj")
        workspace = await index.create(project)
        headers.add("s1", _canon(project))
        await index.attach_session("s1")

        headers.headers["s1"] = StartedHeader(
            session_id="s1", cwd=_canon(_project(tmp_path, "elsewhere")),
            created_at="2026-01-01T00:00:00+00:00",
        )

        assert index.get(workspace.id).session_ids == ()  # type: ignore[union-attr]

    async def test_mismatched_candidate_is_pruned_on_next_change(
        self, tmp_path: Path
    ) -> None:
        """AC6：不匹配的候选在下一次被接受的变更时被**持久修剪**。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "proj")
        workspace = await index.create(project)
        headers.add("stale", _canon(project))
        headers.add("fresh", _canon(project))
        await index.attach_session("stale")
        await index.attach_session("fresh")

        headers.headers["stale"] = StartedHeader(
            session_id="stale", cwd=_canon(_project(tmp_path, "other")),
            created_at="2026-01-01T00:00:00+00:00",
        )
        headers.add("third", _canon(project))
        await index.attach_session("third")

        with sqlite3.connect(tmp_path / "harness.db") as connection:
            rows = connection.execute(
                "SELECT session_id FROM workspace_sessions WHERE workspace_id=? "
                "ORDER BY position",
                (workspace.id,),
            ).fetchall()
        assert [row[0] for row in rows] == ["third", "fresh"], "剪枝没有落盘"

    async def test_detach_is_idempotent(self, tmp_path: Path) -> None:
        """AC7：移除幂等；不在账本上是无写操作。

        返回值是 #172 硬删回执的计数源，一并钉住：**实际摘掉了几个账本**（第一次 1、
        第二次 0）——`list()` 给的是可见成员视图，用它自己再数一遍会得到近似值。
        """
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "proj")
        workspace = await index.create(project)
        headers.add("s1", _canon(project))
        await index.attach_session("s1")

        assert await index.detach_session("s1") == 1
        assert index.get(workspace.id).session_ids == ()  # type: ignore[union-attr]

        marker = (tmp_path / "harness.db").stat().st_mtime_ns
        assert await index.detach_session("s1") == 0  # 第二次：无写操作
        assert (tmp_path / "harness.db").stat().st_mtime_ns == marker

    async def test_insert_session_before_reorders(self, tmp_path: Path) -> None:
        """AC5：DOM insertBefore 语义（锚点前插入 / 无锚点追加尾部）。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "proj")
        workspace = await index.create(project)
        for sid in ("a", "b", "c"):
            headers.add(sid, _canon(project))
            await index.attach_session(sid)
        assert index.get(workspace.id).session_ids == ("c", "b", "a")  # type: ignore[union-attr]

        await index.insert_session_before("a", "c")
        assert index.get(workspace.id).session_ids == ("a", "c", "b")  # type: ignore[union-attr]

        await index.insert_session_before("b")
        assert index.get(workspace.id).session_ids == ("a", "c", "b")  # type: ignore[union-attr]

    async def test_insert_session_before_unknown_anchor_raises(
        self, tmp_path: Path
    ) -> None:
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        project = _project(tmp_path, "proj")
        await index.create(project)
        headers.add("a", _canon(project))
        await index.attach_session("a")

        with pytest.raises(UnknownLedgerEntry):
            await index.insert_session_before("a", "not-in-ledger")

    async def test_insert_session_before_unknown_session_raises(
        self, tmp_path: Path
    ) -> None:
        index = _index(tmp_path, _FakeHeaders())
        await index.initialize()
        with pytest.raises(UnknownLedgerEntry):
            await index.insert_session_before("never-attached")

    async def test_detach_never_touches_session_log(self, tmp_path: Path) -> None:
        """AC7：detach **永不触碰会话自身的日志**。"""
        headers = _FakeHeaders()
        index = WorkspaceIndex(_store(tmp_path), headers)
        await index.initialize()
        store = JsonlSessionStore(tmp_path / "sessions")
        project = _project(tmp_path, "proj")
        await index.create(project)
        Session.start(store, session_id="s-log", cwd=project)
        headers.add("s-log", _canon(project))
        await index.attach_session("s-log")
        events_path = tmp_path / "sessions" / "s-log" / "events.jsonl"
        before = events_path.read_bytes()

        await index.detach_session("s-log")

        assert events_path.read_bytes() == before


# —— AC12/AC13：意图日志原子性 ——


@pytest.mark.asyncio
class TestAtomicity:
    async def test_interrupted_create_is_rolled_back_on_startup(
        self, tmp_path: Path
    ) -> None:
        """AC12：create 中断（记录已写、顺序未写）→ 启动时**回滚**。"""
        headers = _FakeHeaders()
        crashing = _CrashAfterRecordStore(tmp_path / "harness.db", kind="create")
        broken = WorkspaceIndex(crashing, headers)
        await broken.initialize()

        with pytest.raises(RuntimeError):
            await broken.create(_project(tmp_path, "half-baked"))

        assert await crashing.pending_changes(), "崩溃前必须已写下标记"

        reborn = _index(tmp_path, headers)
        await reborn.initialize()

        assert reborn.list() == [], "被中断的 create 应当回滚"
        assert await crashing.pending_changes() == []

    async def test_interrupted_delete_is_completed_on_startup(
        self, tmp_path: Path
    ) -> None:
        """AC12：delete 中断（记录已删、顺序未删）→ 启动时**补完**。"""
        headers = _FakeHeaders()
        healthy = _index(tmp_path, headers)
        await healthy.initialize()
        workspace = await healthy.create(_project(tmp_path, "doomed"))

        crashing = _CrashAfterRecordStore(tmp_path / "harness.db", kind="delete")
        broken = WorkspaceIndex(crashing, headers)
        await broken.initialize()
        with pytest.raises(RuntimeError):
            await broken.delete(workspace.id)
        assert await crashing.pending_changes()

        reborn = _index(tmp_path, headers)
        await reborn.initialize()

        assert reborn.list() == []
        assert await crashing.pending_changes() == []
        with sqlite3.connect(tmp_path / "harness.db") as connection:
            leftovers = connection.execute("SELECT COUNT(*) FROM workspace_order").fetchone()
        assert leftovers[0] == 0, "顺序行没被补完删除"

    async def test_more_than_one_marker_is_loud_corruption(self, tmp_path: Path) -> None:
        """AC12：单写者模型下出现第二个标记 = 不变量已破 → 大声失败。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        store = _store(tmp_path)
        await store.begin_change("create", "a", "2026-01-01T00:00:00+00:00")
        await store.begin_change("delete", "b", "2026-01-01T00:00:00+00:00")

        with pytest.raises(WorkspaceRegistryCorrupt):
            await index.initialize()

    async def test_order_without_record_and_no_marker_is_loud_corruption(
        self, tmp_path: Path
    ) -> None:
        """AC13：没有标记的顺序/表不一致 → 大声失败，不静默修补。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        with sqlite3.connect(tmp_path / "harness.db") as connection:
            connection.execute(
                "INSERT INTO workspace_order (position, workspace_id) VALUES (0, 'ghost')"
            )
            connection.commit()

        with pytest.raises(WorkspaceRegistryCorrupt):
            await index.initialize()

    async def test_record_without_order_and_no_marker_is_loud_corruption(
        self, tmp_path: Path
    ) -> None:
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        with sqlite3.connect(tmp_path / "harness.db") as connection:
            connection.execute(
                "INSERT INTO workspaces (workspace_id, path, title, created_at, updated_at) "
                "VALUES ('ghost', 'X:/ghost', 'ghost', 'now', 'now')"
            )
            connection.commit()

        with pytest.raises(WorkspaceRegistryCorrupt):
            await index.initialize()

    async def test_unknown_change_kind_is_loud_corruption(self, tmp_path: Path) -> None:
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        store = _store(tmp_path)
        await store.begin_change("rename", "x", "2026-01-01T00:00:00+00:00")
        with pytest.raises(WorkspaceRegistryCorrupt):
            await index.initialize()

    async def test_ledger_without_record_is_loud_corruption(self, tmp_path: Path) -> None:
        """AC13：有会话账本行、却没有记录 → 同样是"表不一致"，不许静默丢弃。"""
        headers = _FakeHeaders()
        index = _index(tmp_path, headers)
        await index.initialize()
        with sqlite3.connect(tmp_path / "harness.db") as connection:
            connection.execute(
                "INSERT INTO workspace_sessions (workspace_id, session_id, position) "
                "VALUES ('ghost', 's1', 0)"
            )
            connection.commit()

        with pytest.raises(WorkspaceRegistryCorrupt):
            await index.initialize()


# —— 并发（F1）：写路径必须串行 ——


@pytest.mark.asyncio
class TestConcurrency:
    """写方法是"读缓存 → 判断 → 写库 → 改缓存"的复合操作，中间有 `await`。

    HTTP 端点在同一进程里并发进入（双击提交 / 两个标签页同名 workspace），
    `InstanceLock` 只保证**跨进程**互斥，不覆盖同进程请求并发——所以串行化必须在
    `WorkspaceIndex` 这一层。下面两个测试各自把一个写入窗口撑开，让第二个请求
    在窗口中间进入：有写锁 → 串行、结果合并；没有写锁 → 记录冲突 / 会话从索引里
    静默消失。
    """

    async def test_concurrent_create_of_same_path_yields_one_record(
        self, tmp_path: Path
    ) -> None:
        headers = _FakeHeaders()
        gated = _GateAfterRecordStore(tmp_path / "harness.db")
        index = WorkspaceIndex(gated, headers)
        await index.initialize()
        project = _project(tmp_path, "same")

        gated.armed = True
        first = asyncio.create_task(index.create(project))
        await gated.record_written.wait()  # 第一个已写下记录、停在顺序之前
        second = asyncio.create_task(index.create(project))
        for _ in range(20):  # 给第二个请求插进来的机会（没有锁时它就会插进来）
            await asyncio.sleep(0)
        gated.release.set()
        a, b = await asyncio.gather(first, second)

        assert a.id == b.id, "同路径并发 create 必须幂等到同一个实体"
        assert len(index.list()) == 1
        with sqlite3.connect(tmp_path / "harness.db") as connection:
            records = connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
            order = connection.execute("SELECT COUNT(*) FROM workspace_order").fetchone()[0]
        assert (records, order) == (1, 1), "记录与顺序行必须一一对应（否则悬空 → 拒绝启动）"
        assert await gated.pending_changes() == []

        reborn = _index(tmp_path, headers)
        await reborn.initialize()  # AC13 判据：下一份索引必须能正常启动
        assert len(reborn.list()) == 1

    async def test_concurrent_attach_keeps_both_sessions(self, tmp_path: Path) -> None:
        """两个会话同时 attach 到同一项目：都必须在最终账本里。"""
        headers = _FakeHeaders()
        gated = _GateFirstLedgerStore(tmp_path / "harness.db")
        index = WorkspaceIndex(gated, headers)
        await index.initialize()
        project = _project(tmp_path, "shared")
        workspace = await index.create(project)
        headers.add("sA", _canon(project))
        headers.add("sB", _canon(project))

        gated.armed = True
        first = asyncio.create_task(index.attach_session("sA"))
        await gated.first_entered.wait()  # 第一个停在账本写库之前（缓存尚未更新）
        second = asyncio.create_task(index.attach_session("sB"))
        for _ in range(20):
            await asyncio.sleep(0)
        gated.release.set()
        await asyncio.gather(first, second)

        with sqlite3.connect(tmp_path / "harness.db") as connection:
            rows = connection.execute(
                "SELECT session_id FROM workspace_sessions WHERE workspace_id=? "
                "ORDER BY position",
                (workspace.id,),
            ).fetchall()
        persisted = [row[0] for row in rows]
        assert set(persisted) == {"sA", "sB"}, f"有会话被静默丢弃：{persisted}"
        assert set(index.get(workspace.id).session_ids) == {"sA", "sB"}  # type: ignore[union-attr]

    async def test_lock_is_shared_across_write_methods(self, tmp_path: Path) -> None:
        """各写方法共用**同一把**锁：一个写者在临界区里，另一个写方法也进不来。

        这条与上面两条不同的地方在于它否定的不是"没有锁"，而是"每个方法各自一把锁"
        ——那种实现下两个请求仍会同时改缓存与库，只是错得更隐蔽。
        """
        headers = _FakeHeaders()
        gated = _GateAfterRecordStore(tmp_path / "harness.db")
        index = WorkspaceIndex(gated, headers)
        await index.initialize()
        doomed = await index.create(_project(tmp_path, "doomed"))
        fresh = _project(tmp_path, "fresh")

        gated.armed = True
        first = asyncio.create_task(index.create(fresh))  # 停在窗口里，持有锁
        await gated.record_written.wait()
        second = asyncio.create_task(index.delete(doomed.id))  # 另一个写方法
        for _ in range(20):
            await asyncio.sleep(0)
        # 决定性证据在 store：delete 若真的闯进临界区，`begin_change` 会抛
        # AssertionError（见 _GateAfterRecordStore）；这里的 not done 只是复查。
        assert not second.done(), "另一个写者在锁被持有时进入了临界区"
        assert index.get(doomed.id) is not None

        gated.release.set()
        await asyncio.gather(first, second)
        assert index.get(doomed.id) is None, "释放后 delete 应当照常完成"


# —— 读契约：缓存 / 降级 / 初始化闸 / 元数据失败 ——


@pytest.mark.asyncio
class TestReadContract:
    async def test_unreadable_header_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        """一份读不了的日志不该让整个项目列表 500（AC6：缺 header 的候选永不返回）。"""
        headers = _FakeHeaders()
        project = _project(tmp_path, "proj")
        headers.add("good", _canon(project))
        index = _index(tmp_path, headers)
        await index.initialize()
        workspace = await index.create(project)
        await index.attach_session("good")

        # 账本里塞一条 header 读不出来的会话（模拟权限/占用问题）
        with sqlite3.connect(tmp_path / "harness.db") as connection:
            connection.execute(
                "INSERT INTO workspace_sessions (workspace_id, session_id, position) "
                "VALUES (?, 'broken', 0)",
                (workspace.id,),
            )
            connection.commit()
        headers.unreadable.add("broken")

        reborn = _index(tmp_path, headers)  # 新索引 = 空缓存，必然走读失败分支
        await reborn.initialize()
        listed = reborn.list()
        assert [w.session_ids for w in listed] == [("good",)]
        assert reborn.workspace_of_session("broken") is None

    async def test_reads_before_initialize_raise(self, tmp_path: Path) -> None:
        """未初始化时的读必须响亮失败，而不是平静地报"没有项目"。"""
        headers = _FakeHeaders()
        index = WorkspaceIndex(_store(tmp_path), headers)
        project = _project(tmp_path, "proj")
        headers.add("s1", _canon(project), agent_id="default")

        with pytest.raises(WorkspaceError):
            index.list()
        with pytest.raises(WorkspaceError):
            index.get("whatever")
        with pytest.raises(WorkspaceError):
            index.resolve_by_path(project)
        with pytest.raises(WorkspaceError):
            index.workspace_of_session("s1")
        with pytest.raises(WorkspaceError):
            await index.create(project)
        with pytest.raises(WorkspaceError):
            await index.attach_session("s1")
        with pytest.raises(WorkspaceError):
            await index.bootstrap()

        await index.initialize()
        # 初始化之后读才有效：s1 的 cwd 就是该项目 → 引导把它归组进去。
        listed = index.list()
        assert [w.title for w in listed] == ["proj"]
        assert listed[0].session_ids == ("s1",)

    async def test_touch_failure_keeps_cache_consistent_with_db(
        self, tmp_path: Path
    ) -> None:
        """账本已提交、`updated_at` 失败 → 缓存必须已经是新账本（不能停在旧值）。"""
        headers = _FakeHeaders()
        failing = _FailTouchStore(tmp_path / "harness.db")
        project = _project(tmp_path, "proj")
        headers.add("s1", _canon(project), agent_id="default")
        index = WorkspaceIndex(failing, headers)
        await index.initialize()
        workspace = await index.create(project)

        await index.attach_session("s1")  # touch 在内部失败，但不该让 attach 失败

        with sqlite3.connect(tmp_path / "harness.db") as connection:
            persisted = [
                row[0]
                for row in connection.execute(
                    "SELECT session_id FROM workspace_sessions WHERE workspace_id=?",
                    (workspace.id,),
                ).fetchall()
            ]
        assert persisted == ["s1"], "账本应当已持久写入"
        assert index.get(workspace.id).session_ids == ("s1",), (  # type: ignore[union-attr]
            "缓存与库不一致：库已更新而缓存停在旧值"
        )


# —— AC14/AC15/AC16：首次引导 ——

@pytest.mark.asyncio
class TestBootstrap:
    async def test_groups_by_canonical_cwd_newest_first(self, tmp_path: Path) -> None:
        """AC14：按目录分组、最新的排在最前；组内也是新→旧。"""
        headers = _FakeHeaders()
        old = _project(tmp_path, "old-proj")
        new = _project(tmp_path, "new-proj")
        headers.add("a1", _canon(old), "2026-01-01T00:00:00+00:00")
        headers.add("a2", _canon(old), "2026-03-01T00:00:00+00:00")
        headers.add("b1", _canon(new), "2026-06-01T00:00:00+00:00")

        index = _index(tmp_path, headers)
        await index.initialize()

        workspaces = index.list()
        assert [w.title for w in workspaces] == ["new-proj", "old-proj"]
        assert workspaces[1].session_ids == ("a2", "a1")
        assert workspaces[1].created_at == "2026-01-01T00:00:00+00:00"

    async def test_legacy_sessions_without_cwd_stay_ungrouped(
        self, tmp_path: Path
    ) -> None:
        """AC16：无 cwd 的历史遗留会话保持 Ungrouped。"""
        headers = _FakeHeaders()
        headers.add("legacy-1", None)
        headers.add("legacy-2", None)
        index = _index(tmp_path, headers)
        await index.initialize()
        assert index.list() == []

    async def test_non_canonical_or_relative_cwd_is_skipped(self, tmp_path: Path) -> None:
        """AC14"规范 cwd 有效"：非规范 / 相对路径不算有效证据。"""
        headers = _FakeHeaders()
        headers.add("relative", "some/relative/dir")
        project = _project(tmp_path, "proj")
        headers.add("dirty", f"{project}{os.sep}.")
        index = _index(tmp_path, headers)
        await index.initialize()
        assert index.list() == []

    async def test_default_per_session_directory_is_not_a_project(
        self, tmp_path: Path
    ) -> None:
        """D6：默认每会话沙箱目录（目录名 == 会话 id）不归组（AC14 的显式收窄）。"""
        headers = _FakeHeaders()
        headers.add("11111111-1111-1111-1111-111111111111", _canon(_project(tmp_path, "x")))
        headers.headers["11111111-1111-1111-1111-111111111111"] = StartedHeader(
            session_id="11111111-1111-1111-1111-111111111111",
            cwd=str(tmp_path / "workspaces" / "11111111-1111-1111-1111-111111111111"),
            created_at="2026-01-01T00:00:00+00:00",
        )
        index = _index(tmp_path, headers)
        await index.initialize()
        assert index.list() == []

    async def test_internal_subagent_child_is_not_grouped(self, tmp_path: Path) -> None:
        """内部子代理子会话不进项目账本（AC14 的第二处显式收窄，见 ADR-0025 D6）。

        运行期没有任何路径 attach 它们（只有 create_and_launch / fork 会 attach），
        所以引导若收进来，"同一类会话在不在项目里"就取决于它生于引导前后。
        """
        headers = _FakeHeaders()
        project = _project(tmp_path, "proj")
        headers.add("user-1", _canon(project), agent_id="default")
        headers.add("child-1", _canon(project), agent_id="coding")  # 内部子代理
        index = _index(tmp_path, headers)
        await index.initialize()

        listed = index.list()
        assert [w.title for w in listed] == ["proj"]
        assert listed[0].session_ids == ("user-1",), "内部子代理不该被引导收进项目"

    async def test_internal_child_in_ledger_is_not_a_member(self, tmp_path: Path) -> None:
        """账本里**已有**的内部子代理同样不算成员（账本是候选列表，成员资格现算）。

        这条堵的是"只在引导处过滤"的半套规则：那样一来，任何别处（历史数据、外部
        写入、以后新增的会话种类）把子会话放进账本，它就会作为成员冒出来。
        """
        headers = _FakeHeaders()
        project = _project(tmp_path, "proj")
        headers.add("user-1", _canon(project), agent_id="default")
        index = _index(tmp_path, headers)
        await index.initialize()
        workspace = await index.create(project)
        headers.add("child-1", _canon(project), agent_id="coding")

        # 外部手段把子会话塞进账本（绕过 attach 的成员校验）
        await _store(tmp_path).replace_session_order(workspace.id, ["child-1", "user-1"])

        reborn = _index(tmp_path, headers)
        await reborn.initialize()
        assert reborn.list()[0].session_ids == ("user-1",)
        assert reborn.workspace_of_session("child-1") is None

    async def test_only_children_directory_mints_no_project(self, tmp_path: Path) -> None:
        """只装着内部子代理的目录**不产生项目**。

        成员资格过滤（`_filter_visible`）已经保证子会话不算成员；引导这一层的过滤是
        为了不"凭空建一个永远空的项目"——父会话日志没了、只剩子会话的历史目录就是
        这种形状。两条规则各管一件事，所以各有各的用例。
        """
        headers = _FakeHeaders()
        project = _project(tmp_path, "child-only")
        headers.add("child-1", _canon(project), agent_id="coding")
        headers.add("child-2", _canon(project), agent_id="research_review")
        index = _index(tmp_path, headers)
        await index.initialize()
        assert index.list() == [], "只装着内部子代理的目录不该凭空成为一个项目"

    async def test_bootstrap_runs_only_once(self, tmp_path: Path) -> None:
        """AC16：引导只发生一次；此后新建会话只能通过 attachSession 加入。"""
        headers = _FakeHeaders()
        project = _project(tmp_path, "proj")
        headers.add("a1", _canon(project), "2026-01-01T00:00:00+00:00")
        index = _index(tmp_path, headers)
        await index.initialize()
        assert [w.title for w in index.list()] == ["proj"]

        headers.add("a2", _canon(project), "2026-06-01T00:00:00+00:00")
        reborn = _index(tmp_path, headers)
        await reborn.initialize()

        workspace = reborn.list()[0]
        assert workspace.session_ids == ("a1",), "第二次引导不该再吸收会话"

    async def test_interrupted_bootstrap_can_rerun(self, tmp_path: Path) -> None:
        """AC15：完成标记**最后写** → 中断后重跑可安全续跑（幂等、不重复）。"""
        headers = _FakeHeaders()
        first = _project(tmp_path, "p1")
        second = _project(tmp_path, "p2")
        headers.add("a1", _canon(first), "2026-01-01T00:00:00+00:00")
        headers.add("b1", _canon(second), "2026-02-01T00:00:00+00:00")

        # 第一次引导在**第二个项目写账本时**被打断：此时已完成一部分记录/账本，
        # 但完成标记还没写（标记必须最后写，AC15）。刻意不在标记写入处注入失败——
        # 那样"标记提前写"的错误实现会与正确实现表现一致，测不出真假。
        store = _store(tmp_path)
        store.replace_session_order = _fail_on_nth_call(  # type: ignore[method-assign]
            store.replace_session_order, n=2
        )
        index = WorkspaceIndex(store, headers)
        with pytest.raises(RuntimeError):
            await index.initialize()

        assert await store.get_meta("bootstrap_done") is None, "完成标记必须最后写（AC15）"

        reborn = _index(tmp_path, headers)
        await reborn.initialize()

        titles = [w.title for w in reborn.list()]
        assert titles == ["p2", "p1"], f"续跑结果不对：{titles}"
        assert reborn.list()[0].session_ids == ("b1",)
        assert reborn.list()[1].session_ids == ("a1",), "续跑重复插入了会话"

    async def test_bootstrap_with_real_session_logs(self, tmp_path: Path) -> None:
        """真 `JsonlSessionStore`：header 读取 + 归组端到端（不经替身）。"""
        store = JsonlSessionStore(tmp_path / "sessions")
        project = _project(tmp_path, "real-proj")
        Session.start(store, session_id="sess-old", cwd=project)
        Session.start(store, session_id="sess-new", cwd=project)
        Session.start(store, session_id="legacy")          # 无 cwd → Ungrouped
        Session.start(                                          # 默认每会话目录 → 不归组
            store, session_id="default-one", cwd=tmp_path / "workspaces" / "default-one"
        )

        index = WorkspaceIndex(_store(tmp_path), store)
        await index.initialize()

        workspaces = index.list()
        assert [w.title for w in workspaces] == ["real-proj"]
        assert set(workspaces[0].session_ids) == {"sess-old", "sess-new"}
        assert index.workspace_of_session("legacy") is None
        assert index.workspace_of_session("default-one") is None


def _fail_on_nth_call(method, *, n: int):
    """包装 store 方法：第 n 次调用抛错（模拟引导中途崩溃），之后放行。"""

    state = {"calls": 0}

    async def wrapper(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] == n:
            raise RuntimeError("模拟崩溃：引导中途")
        return await method(*args, **kwargs)

    return wrapper


# —— AC14 的硬证据：引导只读 header，不读正文 ——


class _BodyReadingGuard:
    """把文件包装成"读超过 N 行就报错"，用来钉死"绝不读事件正文"。"""

    def __init__(self, handle, limit: int) -> None:
        self._handle = handle
        self._limit = limit
        self.lines = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.lines += 1
        if self.lines > self._limit:
            raise AssertionError(
                f"读了第 {self.lines} 行——引导不得读事件正文（AC14）"
            )
        return next(self._handle)

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)


class TestHeaderReader:
    def test_reads_header_fields(self, tmp_path: Path) -> None:
        store = JsonlSessionStore(tmp_path / "sessions")
        project = _project(tmp_path, "proj")
        Session.start(store, session_id="h1", cwd=project, started_data={"provider": "p"})

        header = store.read_started_header("h1")
        assert header is not None
        assert header.session_id == "h1"
        assert header.cwd == _canon(project)
        assert header.created_at
        assert header.agent_id == "default"

    def test_missing_session_or_started_returns_none(self, tmp_path: Path) -> None:
        store = JsonlSessionStore(tmp_path / "sessions")
        assert store.read_started_header("nope") is None

        empty = tmp_path / "sessions" / "empty-dir"
        empty.mkdir(parents=True)
        (empty / "events.jsonl").write_text("", encoding="utf-8")
        assert store.read_started_header("empty-dir") is None

    def test_does_not_read_event_bodies(self, tmp_path: Path, monkeypatch) -> None:
        """AC14 硬证据：正文有一万条事件，读取只碰第 1 行。"""
        store = JsonlSessionStore(tmp_path / "sessions")
        project = _project(tmp_path, "proj")
        session = Session.start(store, session_id="h2", cwd=project)
        for index in range(10_000):
            session.append("user/message", {"content": f"正文 {index}"})

        real_open = Path.open

        def guarded_open(self, *args, **kwargs):
            handle = real_open(self, *args, **kwargs)
            if self.name == "events.jsonl":
                return _BodyReadingGuard(handle, limit=1)
            return handle

        monkeypatch.setattr(Path, "open", guarded_open)

        header = store.read_started_header("h2")
        assert header is not None and header.cwd == _canon(project)
