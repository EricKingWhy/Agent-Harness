"""WorkspaceIndex：Workspace 实体 + 有序会话账本的语义层（ADR-0025）。

分工：`store.py` 只管持久化，本模块管**语义**——内存缓存（AC10 同步读）、成员资格
双向校验与修剪（AC6）、有序账本的手工重排（AC5）、软删除（AC11）、首次引导（AC14–16）、
以及两次写入之间的意图日志解决（AC12/AC13）。

**命名**：`sandbox.WorkspaceRegistry` 是"会话 → 沙箱目录映射"，本类是"项目实体 +
会话索引"，两者无关（D7）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import anyio

from agent_harness.sandbox.paths import canonical_workspace_path
from agent_harness.workspace.models import StartedHeader, Workspace
from agent_harness.workspace.store import (
    CHANGE_CREATE,
    CHANGE_DELETE,
    SqliteWorkspaceStore,
    WorkspaceRegistryCorrupt,
    require_existing_directory,
)

logger = logging.getLogger("agent_harness.workspace")

_BOOTSTRAP_DONE = "bootstrap_done"


class SessionHeaders(Protocol):
    """会话 header 的只读来源（由 `JsonlSessionStore` 结构化满足）。

    只需要两件事：枚举会话 id、读**一条** `session/started`。实现必须**不读事件正文**
    （AC14），且对"没有 header / 形状非法"返回 `None` 而不是抛错。
    """

    def list_session_ids(self) -> list[str]: ...

    def read_started_header(self, session_id: str) -> StartedHeader | None: ...


class WorkspaceError(Exception):
    """本模块的错误基类。"""


class UnknownWorkspace(WorkspaceError):
    """未知 workspace_id。"""


class UnknownLedgerEntry(WorkspaceError):
    """重排/剪枝时引用了不在该账本里的会话。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


# 用户视角会话的 `session/started.agent_id`。`Session.start` 的默认值就是这个
# （`session/session.py`），三个创建入口——Web（`service.create_and_launch`）、
# fork（`fork.fork_session`）、CLI（`cli.py`）——都不覆盖它。
_USER_FACING_AGENT_ID = "default"


def _is_internal_child(header: StartedHeader) -> bool:
    """这条 header 是不是"内部子代理子会话"（不是用户视野里的一轮对话）？

    判据只看信封上的 `agent_id`：内部子代理用 profile 名起会话
    （`multiagent/provider.py`: `agent_id=spec.name`，如 `coding`），而所有用户视角
    的会话都是 `"default"`。`None` 视为用户视角（历史上没有该字段的会话不该被误伤）。
    只读 header，不碰事件正文（AC14）。
    """
    return header.agent_id is not None and header.agent_id != _USER_FACING_AGENT_ID


class WorkspaceIndex:
    """Workspace 实体 + 有序会话账本（内存缓存 + SQLite 持久）。

    **写串行化**：所有写入方法都在同一个 `asyncio.Lock` 下执行。这不是保险起见，
    而是正确性前提——`create`/`attach_session` 等都是"读缓存 → 判断 → 写库 → 更新
    缓存"的复合操作，中间有 `await`。HTTP 端点会在同一进程里并发进入（双击提交、
    两个标签页同一个 workspace 名），交错时两个请求都会看到"路径还没被拥有"：
    轻则 `INSERT OR REPLACE` 把先写的那条记录换成新的 id 却留着它的顺序行（留下
    悬空顺序行 → 下次启动按 AC13 大声失败而拒绝启动），重则两个 attach 各自基于
    同一份旧账本写库，其中一个会话从索引里**静默消失**。`InstanceLock` 只保证
    跨进程互斥，不覆盖同进程内的请求并发，所以锁必须在这一层。

    读方法（`get`/`list`/`resolve_by_path`/`workspace_of_session`）刻意**不加锁**：
    它们都是同步的（只读内存缓存，不 `await`），而写方法一律"先提交数据库、再改
    内存缓存"，所以读永远不会看到半个状态——要么看到旧值要么看到新值。
    """

    def __init__(
        self,
        store: SqliteWorkspaceStore,
        headers: SessionHeaders,
    ) -> None:
        self._store = store
        self._headers = headers
        self._records: dict[str, Workspace] = {}
        self._order: list[str] = []
        self._ledger: dict[str, list[str]] = {}
        # 可重入性：`initialize` 内部要调 `resolve_pending_change`/`bootstrap`，
        # 所以公开方法拿锁、内部实现（`*_locked`）不拿，避免自己锁死自己。
        self._write_lock = asyncio.Lock()
        self._initialized = False

    # —— 生命周期 ——

    async def initialize(self) -> None:
        """幂等启动：建表 → 解决待定变更 → 判损坏 → 载入缓存 → 首次引导。"""
        async with self._write_lock:
            await self._store.initialize()
            await self._resolve_pending_change_locked()
            await self._reject_corruption()
            await self._load()
            await self._bootstrap_locked()
            self._initialized = True

    async def resolve_pending_change(self) -> str | None:
        """AC12：启动时**恰好**解决一个被标记的变更；0 个 → 无操作；≥2 个 → 大声失败。

        - `delete` 被中断 → **补完**（确保记录/顺序/会话账本都不存在）；
        - `create` 被中断 → **回滚**（注册可重建，回滚是安全方向）。

        两种解决的实现都是"确保两者皆无"（幂等），所以重复调用安全。
        """
        async with self._write_lock:
            return await self._resolve_pending_change_locked()

    async def _resolve_pending_change_locked(self) -> str | None:
        pending = await self._store.pending_changes()
        if not pending:
            return None
        if len(pending) > 1:
            raise WorkspaceRegistryCorrupt(
                "workspace 待定变更标记多于一个（单写者模型下不可能），无法推断意图顺序："
                f"{pending!r}；请人工检查 workspace_changes 表"
            )
        change_id, kind, workspace_id = pending[0]
        if kind not in (CHANGE_CREATE, CHANGE_DELETE):
            raise WorkspaceRegistryCorrupt(
                f"未知的待定变更类型 {kind!r}（change_id={change_id}）"
            )
        await self._store.drop_sessions(workspace_id)
        await self._store.drop_record(workspace_id)
        await self._store.drop_order(workspace_id, change_id)
        direction = "补完被中断的 delete" if kind == CHANGE_DELETE else "回滚被中断的 create"
        logger.warning(
            "workspace 启动了 %s（kind=%s, workspace_id=%s）", direction, kind, workspace_id
        )
        return kind

    async def _reject_corruption(self) -> None:
        """AC13：**没有**标记的顺序/表不一致 → 大声失败，不静默修补。"""
        missing = await self._store.missing_order_ids()
        dangling = await self._store.dangling_order_ids()
        orphan_ledgers = await self._store.orphan_session_workspaces()
        if missing or dangling or orphan_ledgers:
            raise WorkspaceRegistryCorrupt(
                "workspace 注册表顺序与记录表不一致，且没有待定变更标记："
                f"有记录无顺序={missing}，有顺序无记录={dangling}，"
                f"有会话账本无记录={orphan_ledgers}；"
                "拒绝静默修补（AC13），请人工检查 harness.db"
            )


    async def _load(self) -> None:
        records = await self._store.load_workspaces()
        self._records = {workspace.id: workspace for workspace in records}
        self._order = [workspace.id for workspace in records]
        raw_ledger = await self._store.load_session_ledger()
        self._ledger = {
            workspace_id: ids
            for workspace_id, ids in raw_ledger.items()
            if workspace_id in self._records
        }

    def _require_initialized(self) -> None:
        """读/写都要求先 `initialize()`。

        没有这道闸，未初始化时 `list()` 会**平静地**返回 `[]`——对"项目还没建"与
        "忘了初始化"给出同一个答案。这是留给 #153 `GET /api/projects` 的陷阱，
        所以宁可响亮失败。
        """
        if not self._initialized:
            raise WorkspaceError(
                "WorkspaceIndex 未初始化：请先 await initialize()（Web 侧走 ensure_stores）"
            )

    # —— 读（AC10：同步缓存读）——

    def get(self, workspace_id: str) -> Workspace | None:
        self._require_initialized()
        record = self._records.get(workspace_id)
        return self._view(record) if record is not None else None

    def list(self) -> list[Workspace]:
        """按注册表顺序（新→旧）返回全部项目。"""
        self._require_initialized()
        return [self._view(self._records[wid]) for wid in self._order]

    def resolve_by_path(self, path: str | Path) -> Workspace | None:
        """按规范路径查（与 `create` 同一套 realpath；**不创建**、不要求存在）。"""
        self._require_initialized()
        canonical = canonical_workspace_path(path)
        for workspace_id in self._order:
            if self._records[workspace_id].path == canonical:
                return self._view(self._records[workspace_id])
        return None

    def workspace_of_session(self, session_id: str) -> Workspace | None:
        """会话当前属于哪个项目（按**可见**账本判定）。"""
        self._require_initialized()
        for workspace_id in self._order:
            if session_id in self._visible_ids(workspace_id):
                return self._view(self._records[workspace_id])
        return None

    # —— 实体写入 ——

    async def create(self, path: str | Path, title: str | None = None) -> Workspace:
        """AC9：把**已存在**的目录注册为项目；规范路径已被拥有 → 幂等返回既有实体。

        目录不存在/不是目录 → 原样传出 `FileNotFoundError` / `NotADirectoryError`。
        """
        async with self._write_lock:
            self._require_initialized()
            canonical = canonical_workspace_path(path)
            require_existing_directory(canonical)
            existing = self._record_by_path(canonical)
            if existing is not None:
                return self._view(existing)
            record = await self._persist_new_workspace(
                canonical, title or Workspace.default_title(canonical), _now(), at_front=True
            )
            return self._view(record)

    async def set_title(self, workspace_id: str, title: str) -> Workspace:
        async with self._write_lock:
            self._require_initialized()
            record = self._require(workspace_id)
            now = _now()
            await self._store.set_title(workspace_id, title, now)
            updated = replace(record, title=title, updated_at=now)
            self._records[workspace_id] = updated
            return self._view(updated)

    async def delete(self, workspace_id: str) -> bool:
        """AC11 软删除：只摘注册记录 + 顺序条目 + 会话账本。

        **目录、用户文件、实时会话、已落盘日志一概不动**——那些会话变为 Ungrouped。
        未知 id → `False`（不抛）。
        """
        async with self._write_lock:
            self._require_initialized()
            if workspace_id not in self._records:
                return False
            change_id = await self._store.begin_change(CHANGE_DELETE, workspace_id, _now())
            await self._store.drop_sessions(workspace_id)
            await self._store.drop_record(workspace_id)
            await self._store.drop_order(workspace_id, change_id)
            self._records.pop(workspace_id, None)
            self._order = [wid for wid in self._order if wid != workspace_id]
            self._ledger.pop(workspace_id, None)
            return True

    # —— 会话账本（AC5/AC6/AC7）——

    async def attach_session(self, session_id: str) -> Workspace | None:
        """把会话加入**它 header cwd 所属**的项目（新会话前插，AC5）。

        只加入**已注册**的项目：没有 cwd / cwd 不匹配任何项目 → `None`（不隐式创建）。
        "未指定项目的默认会话"因此天然保持 Ungrouped（其目录不注册）。

        #154 起本方法是 HTTP 写路径：内部的 header 读（`_read_header` / `_filter_visible`
        / `_view`）都是**同步磁盘 I/O**，一律卸载到 worker 线程——与
        `SessionService.list_sessions` 同款（#153 review 的 P2-1）。
        """
        async with self._write_lock:
            self._require_initialized()
            header = await anyio.to_thread.run_sync(self._read_header, session_id)
            if header is None or not header.cwd:
                return None
            record = self._record_by_path(header.cwd)
            if record is None:
                return None
            current = [sid for sid in self._ledger.get(record.id, ()) if sid != session_id]
            kept = await anyio.to_thread.run_sync(self._filter_visible, record, current)
            await self._persist_ledger(record.id, [session_id, *kept])
            # `self.get`（而不是用上面那份 `record`）：`_persist_ledger` 刚替换了
            # `_records[id]`（新 `updated_at`），只有重新取缓存才拿到**提交后**的值。
            return await anyio.to_thread.run_sync(self.get, record.id)

    async def attach_matching_sessions(self, workspace_id: str) -> int:
        """AC5（#169）：把 header cwd 等于本项目 path 的既有会话全部归入；返回**新归入**数。

        与 `bootstrap` 的分工：bootstrap 只在首次启动跑一次、会**新建**项目；本方法只
        服务**已注册**项目（不建项目），可在每次注册时重复调用（软删除 → 重注册的
        闭环由此补齐）。未知 id → `UnknownWorkspace`（`_require`）——编程错误，不是
        用户输入错误。

        幂等：已在账本里的会话不重复计入。

        **剪枝只剪"读到且明确不属于"的候选**：本方法会扫全库读 header，而 header 可能
        暂时读不到（Windows 文件占用在本仓真实出现过，`_read_header` 有意降级为
        `None`）。`_visible_ids` 的过滤视图无法区分"cwd 不匹配"与"这次读不到"——直接拿
        它重写账本会把后者**永久**删掉（`_visible_ids` 只看账本，位置丢了就再也回不来，
        会话静默变成 Ungrouped）；而 AC6 只要求"缺 header 的候选本次不算成员"。所以这
        里自己分类：读不到 → 原样保留；读到且不匹配/内部子代理 → 剪掉（D3 的持久修剪）。
        """
        async with self._write_lock:
            self._require_initialized()
            record = self._require(workspace_id)

            # 第一遍：账本现有候选分类（剪"明确不属于"、留"这次读不到"）
            kept: list[str] = []
            visible: set[str] = set()
            for session_id in self._ledger.get(record.id, []):
                header = await anyio.to_thread.run_sync(self._read_header, session_id)
                if header is None:
                    kept.append(session_id)
                    continue
                if not header.cwd or header.cwd != record.path:
                    continue
                if _is_internal_child(header):
                    continue
                kept.append(session_id)
                visible.add(session_id)

            # 第二遍：全库找 cwd 匹配、当前不是成员的会话
            candidates = await anyio.to_thread.run_sync(self._headers.list_session_ids)
            adopted: list[tuple[str, str]] = []
            for session_id in candidates:
                if session_id in visible:
                    continue
                header = await anyio.to_thread.run_sync(self._read_header, session_id)
                if header is None or not header.cwd or header.cwd != record.path:
                    continue
                if _is_internal_child(header):
                    continue
                adopted.append((header.created_at or "", session_id))
            if not adopted:
                return 0
            # 最新的排前面（与 bootstrap AC14 同一口径）：重注册后补进来的历史会话，
            # 顺序不该由文件系统枚举顺序决定。
            adopted.sort(key=lambda item: item[0], reverse=True)
            fresh = {session_id for _, session_id in adopted}
            await self._persist_ledger(
                record.id,
                [
                    *(session_id for _, session_id in adopted),
                    *(session_id for session_id in kept if session_id not in fresh),
                ],
            )
            return len(adopted)

    async def detach_session(self, session_id: str) -> int:
        """AC7：把会话移出账本（幂等）。不在账本上 → 无写操作（除修剪外）。

        **永不触碰会话自身的日志**——只改账本。

        :returns: 本次**真的摘掉了它**的账本数（#172 硬删的回执要用："从几个项目里
            解除"必须是实际发生的动作，不能是调用方另算一遍的近似值——`list()` 给的是
            **可见成员**视图，而本方法修剪的是**原始账本**，两者在"记录了但不可见"的
            行上会不一致）。遍历的是全部账本，所以同一 id 被重复收录时会 >1。
        """
        detached = 0
        async with self._write_lock:
            self._require_initialized()
            for workspace_id, ids in list(self._ledger.items()):
                if session_id not in ids:
                    continue
                record = self._records[workspace_id]
                kept = await anyio.to_thread.run_sync(
                    self._filter_visible, record, ids
                )
                await self._persist_ledger(
                    workspace_id, [sid for sid in kept if sid != session_id]
                )
                detached += 1
        return detached

    async def insert_session_before(
        self, session_id: str, before: str | None = None
    ) -> Workspace:
        """AC5：显式重排（DOM `insertBefore` 语义：无 anchor → 追加尾部）。"""
        async with self._write_lock:
            self._require_initialized()
            workspace_id = None
            for candidate, ids in self._ledger.items():
                if session_id in ids:
                    workspace_id = candidate
                    break
            if workspace_id is None:
                raise UnknownLedgerEntry(
                    f"会话 '{session_id}' 不在任何项目账本里，无法重排"
                )
            record = self._records[workspace_id]
            ordered = await anyio.to_thread.run_sync(
                self._filter_visible, record, self._ledger[workspace_id]
            )
            if session_id not in ordered:
                raise UnknownLedgerEntry(
                    f"会话 '{session_id}' 的 header cwd 与项目 '{record.title}' 不符（已被剪枝）"
                )
            ordered.remove(session_id)
            if before is None:
                ordered.append(session_id)
            else:
                if before not in ordered:
                    raise UnknownLedgerEntry(
                        f"锚点会话 '{before}' 不在项目 '{record.title}' 的账本里"
                    )
                ordered.insert(ordered.index(before), session_id)
            await self._persist_ledger(workspace_id, ordered)
            view = await anyio.to_thread.run_sync(self.get, workspace_id)
            assert view is not None  # 刚写过账本，记录必然在
            return view

    # —— 首次引导（AC14/15/16）——

    async def bootstrap(self) -> int:
        """首次成功启动时按 header cwd 归组历史会话；返回新建的 workspace 数。

        幂等：完成标记**最后写**（AC15），被中断可安全续跑。只发生一次（AC16）：
        此后新建的会话只能通过 `attach_session` 加入。
        """
        async with self._write_lock:
            self._require_initialized()
            return await self._bootstrap_locked()

    async def _bootstrap_locked(self) -> int:
        if await self._store.get_meta(_BOOTSTRAP_DONE):
            return 0
        groups = self._collect_header_groups()
        created = 0
        # 最新的排在最前（AC14）：按组内**最新**会话时间倒序。
        ordered_ids: list[str] = []
        for path, headers in sorted(
            groups.items(),
            key=lambda item: max(h.created_at or "" for h in item[1]),
            reverse=True,
        ):
            record = self._record_by_path(path)
            if record is None:
                born = min(
                    (h.created_at for h in headers if h.created_at), default=_now()
                )
                record = await self._persist_new_workspace(
                    path, Workspace.default_title(path), born, at_front=False
                )
                created += 1
            ordered_ids.append(record.id)
            incoming = [
                h.session_id
                for h in sorted(headers, key=lambda h: h.created_at or "", reverse=True)
            ]
            existing = [sid for sid in self._ledger.get(record.id, ()) if sid not in incoming]
            await self._persist_ledger(record.id, [*incoming, *existing])
        # 收尾：把注册表顺序重写成本次算出的完整顺序。中断后重跑时，上一次已经把
        # 一部分记录进了顺序表，"只追加"会把旧项目排到新项目前面——重写才使
        # "中断后重跑"与"一次跑完"等价（AC15）；不在本次分组里的既有项目排在后面。
        covered = set(ordered_ids)
        final_order = [*ordered_ids, *(wid for wid in self._order if wid not in covered)]
        if final_order:
            await self._store.replace_workspace_order(final_order)
            self._order = final_order
        await self._store.set_meta(_BOOTSTRAP_DONE, _now())
        if created:
            logger.info("workspace bootstrap 归组了 %d 个项目", created)
        return created

    def _collect_header_groups(self) -> dict[str, list[StartedHeader]]:
        groups: dict[str, list[StartedHeader]] = {}
        for session_id in self._headers.list_session_ids():
            header = self._read_header(session_id)
            if header is None or not header.cwd:
                continue
            if _is_internal_child(header):
                # 内部子代理**不进项目账本**（成员资格也在 `_filter_visible` 里挡，
                # 这里挡是为了不给"只装着子会话的目录"凭空建一个空项目）。
                # 运行期没有任何路径 attach 它们（`multiagent/provider.py` 直接
                # `Session(...)` + append，只有 `SessionService.create_and_launch`/
                # `fork` 会 attach），所以若引导把它们收进账本，"同一类会话是否出现
                # 在项目里"就取决于它生于引导标记之前还是之后——同一份数据两种答案。
                continue
            cwd = header.cwd
            if not os.path.isabs(cwd) or canonical_workspace_path(cwd) != cwd:
                logger.warning(
                    "bootstrap 跳过会话 %s：header cwd 不是规范绝对路径（%r）",
                    session_id, cwd,
                )
                continue
            if Path(cwd).name == session_id:
                # D6 收窄：未指定项目时目录建成 workspaces_root/<session_id>，
                # "目录名 == 会话 id"正是它的结构特征。按字面分组会给每个未命名会话
                # 凭空造一个项目（标题还是 uuid）。要反过来只需删掉这个判断。
                continue
            groups.setdefault(cwd, []).append(header)
        return groups

    # —— 内部 ——

    def _require(self, workspace_id: str) -> Workspace:
        record = self._records.get(workspace_id)
        if record is None:
            raise UnknownWorkspace(workspace_id)
        return record

    def _record_by_path(self, canonical_path: str) -> Workspace | None:
        for workspace_id in self._order:
            if self._records[workspace_id].path == canonical_path:
                return self._records[workspace_id]
        return None

    def _visible_ids(self, workspace_id: str) -> list[str]:
        """AC6：账本里有 + header cwd 逐字符等于 `path` 的候选（同步过滤）。

        比较**照字面**（不重新 realpath）：已存 header 的 cwd 是写时规范化的产物，
        成员资格必须在目录被移动/链接被重指之后保持不变（WS-1 交接约束）。
        """
        return self._filter_visible(
            self._records[workspace_id], self._ledger.get(workspace_id, [])
        )

    def _read_header(self, session_id: str) -> StartedHeader | None:
        """读一条 header；I/O 失败降级为"无 header"，不让一份坏日志拖垮整个列表。

        **刻意不缓存**：header 的 cwd 写后不可变（WS-1 AC2），所以缓存"看起来"安全；
        但 AC6 把"**缺** header 的候选"也列为永不返回——会话目录被移走/日志被删之后，
        永久缓存会继续把它当成员返回，与 AC6 直接冲突。读成本是一次带缓冲的首行读，
        #153 的列表路径按"一次请求构建一份 map"消化即可，不值得用永久陈旧换这点 I/O。

        降级理由：`read_started_header` 会因权限/占用/磁盘错误抛 `OSError`。一份读不了
        的日志不该让整个项目列表 500——按 AC6"缺 header 的候选永不返回"处理（该会话
        本次不算成员），并记 warning。
        """
        try:
            return self._headers.read_started_header(session_id)
        except OSError:
            logger.warning(
                "读取会话 %s 的 header 失败，本次按无 header 处理", session_id,
                exc_info=True,
            )
            return None

    def _filter_visible(self, record: Workspace, ids: list[str]) -> list[str]:
        """成员资格过滤（AC6）：候选只有在"属于这个项目"时才返回。

        三道闸，缺一不可：有 header、header cwd 逐字符等于项目 path、**不是内部子代理
        子会话**。账本因此是**候选列表**而不是成员列表——这是 D3"账本=索引"的落地：
        索引可以多存（历史遗留、外部写入、以后新增的会话种类），成员资格永远在这里
        现算。
        """
        kept: list[str] = []
        for session_id in ids:
            header = self._read_header(session_id)
            if header is None or not header.cwd:
                continue
            if header.cwd != record.path:
                continue
            if _is_internal_child(header):
                continue
            kept.append(session_id)
        return kept

    def _view(self, record: Workspace) -> Workspace:
        return replace(record, session_ids=tuple(self._visible_ids(record.id)))

    async def _persist_ledger(self, workspace_id: str, session_ids: list[str]) -> None:
        """写账本（AC6：这里同时就是"下一次被接受的变更持久修剪候选"）。

        顺序要紧：**账本一提交就更新缓存**，再去做 `updated_at` 这种元数据写入。
        反过来的话，`touch` 失败（busy timeout / 磁盘错误）会让库里的账本已经变了、
        缓存却还是旧的——"先提交数据库、再改缓存"的不变量当场破掉，`get().session_ids`
        会与实际持久内容不一致直到重启。`updated_at` 是纯元数据（AC4 只要求它是合法
        时间戳），丢了不影响成员资格与顺序，所以它 best-effort。
        """
        now = _now()
        await self._store.replace_session_order(workspace_id, session_ids)
        self._ledger[workspace_id] = list(session_ids)
        try:
            await self._store.touch(workspace_id, now)
        except Exception:
            logger.warning(
                "账本已写入，但更新 workspace %s 的 updated_at 失败", workspace_id,
                exc_info=True,
            )
            return
        self._records[workspace_id] = replace(self._records[workspace_id], updated_at=now)

    async def _persist_new_workspace(
        self, path: str, title: str, created_at: str, *, at_front: bool
    ) -> Workspace:
        """D5 的两写入序列：标记 → 记录 → 顺序（+同事务清标记）。"""
        now = _now()
        record = Workspace(
            id=str(uuid4()),
            path=path,
            title=title,
            created_at=created_at,
            updated_at=now,
        )
        change_id = await self._store.begin_change(CHANGE_CREATE, record.id, now)
        await self._store.write_record(record)
        if at_front:
            await self._store.prepend_record(record.id, change_id)
            self._order.insert(0, record.id)
        else:
            await self._store.append_record(record.id, change_id)
            self._order.append(record.id)
        self._records[record.id] = record
        self._ledger.setdefault(record.id, [])
        return record
