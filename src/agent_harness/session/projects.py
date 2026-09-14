"""项目（Workspace）应用服务——WS-4 / #154 的 HTTP 面到领域索引之间的一层。

**为什么单独成模块**：`session/service.py` 是会话生命周期的门面（create/resume/fork/
cancel/...），项目 CRUD 是另一件事。这里只做三件 `WorkspaceIndex` 不做的事：

1. **装配前置**：`ensure_stores()` + 索引存在性（与 `list_sessions` 同款：未初始化就读
   会得到"全是未分组"的假事实，见 #153 的 review 结论）；
2. **AC7 的前置校验**：attach 之前会话必须**已存在且已带 cwd**，且其 cwd 指向的项目就是
   请求里的项目——否则拒绝，不留"账本有 id 但会话无 cwd"的中间态；
3. **把 workspace 包的异常翻译成会话层词汇**（`UnknownWorkspace` → `WorkspaceNotFound`），
   让 HTTP 层只需要认 `SessionServiceError` 一套映射（ARCH-5 单一映射源）。

**不做**：不做权限（ADR-0025 D1 的来源闸在 `web/projects.py`），不做 DTO（HTTP 层自己
映射），不写任何 `SessionEvent`（项目对模型不可见）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import anyio

from agent_harness.session.errors import (
    SessionNotFound,
    WorkspaceMoveInvalid,
    WorkspaceNotFound,
)
from agent_harness.session.service import validate_session_id
from agent_harness.workspace import Workspace

if TYPE_CHECKING:
    from agent_harness.web.app import AppState
    from agent_harness.workspace import WorkspaceIndex

logger = logging.getLogger(__name__)


class ProjectService:
    """项目 CRUD（供 Web handler 调用；`state` 与 `SessionService` 同款）。"""

    def __init__(self, state: AppState) -> None:
        self._state = state

    # —— 装配 ——

    async def _index(self) -> WorkspaceIndex:
        """`ensure_stores()` 之后的索引（Web 装配恒存在）。"""
        await self._state.ensure_stores()
        index = self._state.workspace_index
        if index is None:
            # 装配错误，不是用户错误：Web 装配恒带索引（`assembly.py`），走到这里说明
            # 有人用 CLI 形状的 AppState 调了项目 API。500 比伪造"项目不存在"诚实。
            raise RuntimeError("当前装配没有 workspace 索引，无法提供项目 API")
        return index

    async def _read(self, workspace_id: str) -> Workspace:
        """按 id 取项目（未注册 → `WorkspaceNotFound`）。

        `index.get()` 会真读账本成员的 `events.jsonl` 头部（`_view → _filter_visible`），
        所以与 #153 的列表路径同款卸载到 worker 线程。它**返回 None 而不是抛
        `UnknownWorkspace`**（索引的读方法都这样），所以这里不需要翻译。
        """
        index = await self._index()
        project = await anyio.to_thread.run_sync(index.get, workspace_id)
        if project is None:
            raise WorkspaceNotFound(f"项目 '{workspace_id}' 不存在")
        return project

    # —— 端点背后的事实 ——

    async def create(self, path: str, title: str | None = None) -> tuple[Workspace, int]:
        """注册**已存在**的目录为项目（同一规范路径幂等），并补齐归入匹配的既有会话。

        返回（项目, 本次新归入的会话数）。AC5（#169）：注册后（**含幂等命中既有项目**）
        把所有 header cwd 等于该目录、却不在账本里的会话 attach 进来——软删除 →
        重注册的闭环由此补齐；幂等重放时计数为 0。判定在后端做（只有它知道每个会话
        的 cwd），前端不猜。

        `WorkspaceIndex.create` 原样传出 `FileNotFoundError` / `NotADirectoryError`——
        由 HTTP 层翻译（404 / 422），本层不吞。
        """
        index = await self._index()
        project = await index.create(path, title)
        attached = await index.attach_matching_sessions(project.id)
        # attach 之后重新读：`index.create` 返回的视图是 attach **之前**的成员表，
        # 直接用它会让响应里的 session_ids 少掉刚补进来的会话。
        return await self._read(project.id), attached

    async def list(self) -> list[Workspace]:
        """全部项目，**注册表顺序**（新建前插）。"""
        index = await self._index()
        # 每条账本要读成员 header：同步磁盘 I/O 走 worker（同 #153）。
        return await anyio.to_thread.run_sync(index.list)

    async def get(self, workspace_id: str) -> Workspace:
        return await self._read(workspace_id)

    async def resolve(self, path: str) -> Workspace:
        """按路径解析（不注册）：未注册 → `WorkspaceNotFound`。"""
        index = await self._index()
        project = await anyio.to_thread.run_sync(index.resolve_by_path, path)
        if project is None:
            raise WorkspaceNotFound(f"路径 '{path}' 未注册为项目")
        return project

    async def rename(self, workspace_id: str, title: str) -> Workspace:
        index = await self._index()
        await self._read(workspace_id)  # 未知 id → 404（而不是 set_title 里 KeyError）
        return await index.set_title(workspace_id, title)

    async def delete(self, workspace_id: str) -> tuple[Workspace, int]:
        """软删除；返回（删除前的项目, 被解除分组的会话数）。

        AC11：只摘注册记录 + 顺序行 + 会话账本——目录、用户文件、实时会话、已落盘日志
        一概不动。返回删除前的项目是为了让响应能说清"有多少会话回到未分组"（AC4）。
        """
        index = await self._index()
        project = await self._read(workspace_id)
        removed = await index.delete(workspace_id)
        if not removed:
            # 只有"先读出、再被别人删掉"的竞态能到这儿（进程内写锁不含读）。
            raise WorkspaceNotFound(f"项目 '{workspace_id}' 不存在")
        return project, len(project.session_ids)

    async def attach(self, workspace_id: str, session_id: str) -> Workspace:
        """把会话加入项目（AC7：会话必须已存在、已带 cwd，且 cwd 指向本项目）。

        真幂等：**已经是本项目成员的会话直接返回**，不重写账本——否则重复 attach 会把用户
        手工拖过的位置重置到队首（`WorkspaceIndex.attach_session` 的"新会话前插"是**创建
        期**语义，不该被一次幂等重试触发）。
        """
        index = await self._index()
        project = await self._read(workspace_id)
        validate_session_id(session_id)  # 422（名字字段，不是路径）
        if session_id in project.session_ids:
            return project
        header = await self._read_header(session_id)
        if header is None:
            raise SessionNotFound(f"session '{session_id}' not found")
        if not header.cwd:
            raise WorkspaceMoveInvalid(
                f"会话 '{session_id}' 没有 cwd 锚（历史遗留），无法判定它属于哪个项目"
            )
        owner = await anyio.to_thread.run_sync(index.resolve_by_path, header.cwd)
        if owner is None or owner.id != project.id:
            raise WorkspaceMoveInvalid(
                f"会话 '{session_id}' 的目录不属于项目 '{project.title}'"
                + ("" if owner is None else f"（属于 '{owner.title}'）")
            )
        await index.attach_session(session_id)
        return await self._read(workspace_id)

    async def _read_header(self, session_id: str):
        """读会话 header，**OSError 一律降级为"没有 header"**（与索引同款，见
        `WorkspaceIndex._read_header`）：一份被占用/被删的日志不该把请求打成 500，
        更不该把服务端绝对路径原样放进错误详情里（Windows 文件占用在本仓真实出现过）。
        """
        try:
            return await anyio.to_thread.run_sync(
                self._state.store.read_started_header, session_id
            )
        except OSError:
            logger.warning("读取会话 %s 的 header 失败，按不可 attach 处理", session_id,
                           exc_info=True)
            return None

    async def detach(self, workspace_id: str, session_id: str) -> Workspace:
        """把会话移出项目（幂等：不在本项目里 → 无写操作）。

        只调 `detach_session` 当会话**确实**在本项目的可见成员里：`index.detach_session`
        的语义是"从任何账本移出"，不先校验会把 URL 指向 A、实际改掉 B 的账本。
        """
        index = await self._index()
        project = await self._read(workspace_id)
        validate_session_id(session_id)
        if session_id in project.session_ids:
            await index.detach_session(session_id)
        return await self._read(workspace_id)

    async def reorder(
        self, workspace_id: str, session_id: str, before: str | None
    ) -> Workspace:
        """账本内重排（DOM `insertBefore`：`before=None` → 追加尾部）。

        成员先校验：`index.insert_session_before` 是全局扫描（会找到别的项目里的会话），
        不先挡住就可能在 A 项目的 URL 下改掉 B 项目的顺序。

        `before == session_id`（把自己插到自己前面）按 DOM 语义是**无操作**，直接返回：
        交给索引会先 `remove` 再从锚点里找自己 → 找不到 → 409，那是实现细节漏进了契约。
        """
        index = await self._index()
        project = await self._read(workspace_id)
        validate_session_id(session_id)
        members = set(project.session_ids)
        if session_id not in members:
            raise WorkspaceMoveInvalid(
                f"会话 '{session_id}' 不在项目 '{project.title}' 的账本里"
            )
        if before is not None:
            validate_session_id(before)
            if before not in members:
                raise WorkspaceMoveInvalid(
                    f"锚点会话 '{before}' 不在项目 '{project.title}' 的账本里"
                )
            if before == session_id:
                return project
        await index.insert_session_before(session_id, before)
        return await self._read(workspace_id)
