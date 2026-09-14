"""项目（Workspace）HTTP 面——WS-4 / #154。

独立 router 文件（与 `lineage.py` 同款）：`app.py` 已被流式改造重刀过，注册只经
`create_app` 里的一行调用接入，把冲突面压到最小。

## 契约形状（前端消费）

```
Project = {id, path, title, status, session_ids, created_at, updated_at}
```

`session_ids` 是**账本手工序**（已过成员资格过滤），前端按它渲染项目内顺序；
`status` 只有 `ok` / `missing-dir`（目录被移走时**不改任何记录**，只如实上报）。

## 两条语义（票面硬约束）

1. **软删除**：`DELETE /api/projects/{id}` 只摘注册记录与账本——目录、用户文件、
   实时会话、已落盘日志一概不动，那些会话回到未分组。响应里的 `detail` 必须说清这一点
   （AC4：避免调用方误以为连坐删除）。
2. **对模型不可见**：项目是宿主侧能力，本模块**不写任何 `SessionEvent`**。

## 来源闸（ADR-0025 D1 的 (b)）

`create(path)` 接受**任意已存在目录**，这是本票新增的能力面；ADR-0025 D1 要求它在
"未配置 `jwt_secret` 的本地信任模式 + CORS `*`"下也必须有一条防线。做法是在**所有
项目端点（读 + 写）**上校验 `Origin`：浏览器一定会为跨源请求带上它，非本机 hostname
→ 403。读端点也挂闸的理由是**答案本身是本地信息**——项目列表里全是用户的绝对路径，
不能让任意网页枚举（CORS `*` 会把响应交给对方读）。

无 `Origin` 的请求（CLI / curl / 服务端）不是浏览器发起，无法被第三方网页利用，放行；
配置了 `jwt_secret` 时整体跳过——那时请求已过认证层，跨源网页拿不到签名 token。
放行 no-Origin 意味着**部署前提仍是"服务只绑 loopback"**（见 ADR-0025 D1 残留段）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from agent_harness.sandbox.paths import is_absolute_path
from agent_harness.session.errors import SessionServiceError
from agent_harness.session.projects import ProjectService
from agent_harness.web.domain_errors import http_error, workspace_http_error
from agent_harness.workspace import Workspace, WorkspaceError

if TYPE_CHECKING:
    from fastapi import FastAPI

#: 视为"本机来源"的 hostname（Vite dev server 5173 / 直连 8000 / IPv6 回环）。
_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def require_trusted_origin(request: Request) -> None:
    """宿主侧端点的来源闸（ADR-0025 D1 的 (b)；ADR-0028 D2 起 `GET /api/host/dirs` 复用同一份）。

    只在未配置 `jwt_secret`（本地信任模式）时生效；无 `Origin` 或本机 `Origin` 放行。
    `Origin: null`（sandboxed iframe / `file://`）没有 hostname → 拒绝。
    """
    state = request.app.state.agent
    if state.settings.jwt_secret:
        return  # 认证层才是边界（fail-closed，见 AuthSeamMiddleware）
    origin = request.headers.get("origin")
    if origin is None:
        return  # 非浏览器发起：第三方网页无法构造不带 Origin 的浏览器请求
    hostname = urlparse(origin).hostname
    if hostname is None or hostname.lower() not in _LOCAL_HOSTNAMES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"拒绝跨源访问：Origin={origin!r}。宿主侧 API（项目 / 目录列举）"
                "只接受本机来源（配置 JWT_SECRET 后由认证层接管）。"
            ),
        )


def _require_absolute_path(value: str) -> str:
    """项目路径必须是**绝对路径**（ADR-0025 D1：前端让用户输入绝对路径）。

    为什么不能只靠 `canonical_workspace_path` 兜：`realpath` 会把 `""` / `"   "` / `"."`
    解析成**进程当前工作目录**、把 `".."` 解析成**盘根**——于是"注册我的项目"变成"把服务器
    碰巧启动的目录、甚至整个盘当成项目"。这是 WS-1 已就 `realpath("")` 记录过的同一类
    **静默锚定**错误，必须在规范化**之前**挡住形态。

    文案（API-02，2026-09-13 真机验收）：三句都走**中文**，与同层的
    `host_dirs._directory_listing`（`path 必须是绝对路径` / `path 含非法字符（NUL）`）和
    `SessionService._resolve_cwd`（`cwd 必须是绝对路径：…`）同一口径。此前这里是英文
    （`path must be an absolute path`），而前端 `readErrorDetail()` 只剥掉 Pydantic 的
    `Value error, ` 前缀、把 msg 原样渲染——中文界面里直接蹦出一句英文。
    改的是**我们自己写**的 msg（不是 Pydantic 内建文案），所以不引入全局 localizer。
    """
    if not value.strip():
        raise ValueError("path 不能为空")
    if "\x00" in value:
        raise ValueError("path 含非法字符（NUL）")
    # 平台分支的绝对形态判定收在 `sandbox.paths.is_absolute_path`（#170 批次抽出）：
    # 此处原先写 `PureWindowsPath(value).is_absolute()`，在 POSIX 上会把合法绝对路径
    # （`/home/x`，无 drive → False）一律拒掉；Windows 口径逐字不变（仍要求盘符 + 根）。
    if not is_absolute_path(value):
        raise ValueError("path 必须是绝对路径")
    return value


class Project(BaseModel):
    """单个项目（`GET /api/projects` 一行）。"""

    id: str
    path: str
    title: str
    #: 目录当前是否存在；`missing-dir` 只上报事实，不改注册记录（AC8 的同类立场）。
    status: Literal["ok", "missing-dir"]
    #: 账本**手工序**（已过成员资格过滤）——前端按它渲染项目内顺序。
    session_ids: list[str]
    created_at: str
    updated_at: str


class CreateProjectRequest(BaseModel):
    """`POST /api/projects`：注册一个**已存在**的目录（不存在的路径 → 404，不 mkdir）。"""

    path: str = Field(min_length=1, max_length=4096)
    title: str | None = Field(default=None, max_length=200)

    @field_validator("path")
    @classmethod
    def _absolute(cls, value: str) -> str:
        return _require_absolute_path(value)

    @field_validator("title")
    @classmethod
    def _reject_blank_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            # 同 API-02 口径：我们自己写的 msg 一律中文（前端原样渲染 msg）。
            raise ValueError("title 不能为空")
        return value


class ResolveProjectRequest(BaseModel):
    """`POST /api/projects/resolve`：按路径解析，**不注册**。"""

    path: str = Field(min_length=1, max_length=4096)

    @field_validator("path")
    @classmethod
    def _absolute(cls, value: str) -> str:
        return _require_absolute_path(value)


class RenameProjectRequest(BaseModel):
    """`PATCH /api/projects/{id}`（`setTitle`）。"""

    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title 不能为空")
        return value


class AttachSessionRequest(BaseModel):
    """`POST /api/projects/{id}/sessions`：把会话加入项目（幂等）。"""

    session_id: str = Field(min_length=1)


class ReorderSessionRequest(BaseModel):
    """`POST /api/projects/{id}/sessions/{sid}/order`：账本内重排。

    `before=None` → 追加尾部（DOM `insertBefore` 语义）。
    """

    before: str | None = None


class ProjectCreated(Project):
    """`POST /api/projects` 的响应 = 项目 + 本次新归入的会话数（AC5 / #169）。

    为什么要多这个字段：注册是"确保这个目录下的会话都归这儿"的动作，调用方需要知道
    它**实际**改动了什么（软删除 → 重注册后补回 N 个；幂等重放为 0），而不是自己去
    比对注册前后的账本——那正是"前端猜后端语义"。
    """

    #: 本次调用新 attach 进来的会话数（幂等重放 → 0）。
    sessions_attached: int


class ProjectDeleted(BaseModel):
    """`DELETE /api/projects/{id}` 的响应：**软删除**结果。

    `detail` 必须让调用方一眼看到"会话没被删除"（AC4）——前端可直接显示它。
    """

    id: str
    deleted: bool
    #: 有多少会话因此回到未分组。
    sessions_detached: int
    detail: str


@asynccontextmanager
async def _translated() -> AsyncIterator[None]:
    """把领域异常翻成 HTTP（两套词汇 → 两张 single-source 表）。

    这里用上下文管理器而不是每端点两臂 `except`：本模块有 9 个端点，
    逐个重述就是 ARCH-5 刚消灭掉的 18 个 except 臂（#144 的结论）。

    元组里的 `OSError` 是**父类**——`FileNotFoundError` / `NotADirectoryError` /
    `PermissionError` / 裸 `OSError`（EINVAL、ENAMETOOLONG）都由 `_WORKSPACE_ERROR_STATUS`
    按**精确类型**分别给出 404 / 422 / 403 / 422。本模块的 OSError 来源只有路径校验
    （`os.stat` / `realpath`）；SQLite 走 aiosqlite 抛 `sqlite3.Error`（不是 OSError），
    所以不会把内部 I/O 故障伪装成 4xx。
    """
    try:
        yield
    except SessionServiceError as error:  # 会话层词汇（含 WS-4 的 WorkspaceMoveInvalid）
        raise http_error(error) from error
    except (WorkspaceError, OSError) as error:
        raise workspace_http_error(error) from error


def _project(workspace: Workspace) -> Project:
    return Project(
        id=workspace.id,
        path=workspace.path,
        title=workspace.title,
        status=workspace.status(),
        session_ids=list(workspace.session_ids),
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def register_project_routes(app: FastAPI) -> None:
    """把项目路由挂到既有 app（`create_app` 里一行调用的接入面）。"""

    def _service() -> ProjectService:
        return ProjectService(app.state.agent)

    @app.post("/api/projects")
    async def create_project(
        req: CreateProjectRequest, _: None = Depends(require_trusted_origin)
    ) -> ProjectCreated:
        """注册**已存在**的目录为项目，并归入 cwd 匹配的既有会话（AC5 / #169）。

        同一规范路径 → 返回既有实体（不重建、不重复入序，AC5）；路径不存在 → 404、
        存在但不是目录 → 422（AC2/AC3）；两种情况都**不**在磁盘上留下痕迹。
        响应里的 `sessions_attached` = 本次**新**归入的会话数（幂等重放 → 0）。
        """
        async with _translated():
            project, attached = await _service().create(req.path, req.title)
        return ProjectCreated(
            **_project(project).model_dump(), sessions_attached=attached
        )

    @app.get("/api/projects")
    async def list_projects(_: None = Depends(require_trusted_origin)) -> list[Project]:
        """全部项目，**注册表顺序**（新建项目前插，不是按标题/路径排序）。

        读端点也过来源闸：响应里是用户的绝对路径（见模块 docstring）。
        """
        async with _translated():
            return [_project(w) for w in await _service().list()]

    @app.post("/api/projects/resolve")
    async def resolve_project(
        req: ResolveProjectRequest, _: None = Depends(require_trusted_origin)
    ) -> Project:
        """按路径解析项目（幂等查询，**不注册**）；未注册 → 404。

        前端"这个目录是不是已有项目"的入口：拿到 404 才去调 create。
        """
        async with _translated():
            return _project(await _service().resolve(req.path))

    @app.get("/api/projects/{project_id}")
    async def get_project(
        project_id: str, _: None = Depends(require_trusted_origin)
    ) -> Project:
        async with _translated():
            return _project(await _service().get(project_id))

    @app.patch("/api/projects/{project_id}")
    async def rename_project(
        project_id: str,
        req: RenameProjectRequest,
        _: None = Depends(require_trusted_origin),
    ) -> Project:
        """重命名（`setTitle`）——标题是项目唯一的可变元数据。"""
        async with _translated():
            return _project(await _service().rename(project_id, req.title))

    @app.delete("/api/projects/{project_id}")
    async def delete_project(
        project_id: str, _: None = Depends(require_trusted_origin)
    ) -> ProjectDeleted:
        """**软删除**：只摘注册记录与账本，会话与目录一概不动（AC4/AC11）。"""
        async with _translated():
            project, detached = await _service().delete(project_id)
        return ProjectDeleted(
            id=project.id,
            deleted=True,
            sessions_detached=detached,
            detail=(
                f"项目「{project.title}」已从注册表移除，{detached} 个会话回到未分组。"
                "目录、用户文件与会话日志均未删除（软删除，可重新注册同一目录）。"
            ),
        )

    @app.post("/api/projects/{project_id}/sessions")
    async def attach_session(
        project_id: str,
        req: AttachSessionRequest,
        _: None = Depends(require_trusted_origin),
    ) -> Project:
        """把会话加入项目（AC7：会话必须已存在、已带 cwd，且 cwd 指向本项目）。"""
        async with _translated():
            return _project(await _service().attach(project_id, req.session_id))

    @app.delete("/api/projects/{project_id}/sessions/{session_id}")
    async def detach_session(
        project_id: str,
        session_id: str,
        _: None = Depends(require_trusted_origin),
    ) -> Project:
        """把会话移出项目（幂等：不在本项目 → 无写操作）；会话日志逐字节不动。"""
        async with _translated():
            return _project(await _service().detach(project_id, session_id))

    @app.post("/api/projects/{project_id}/sessions/{session_id}/order")
    async def reorder_session(
        project_id: str,
        session_id: str,
        req: ReorderSessionRequest,
        _: None = Depends(require_trusted_origin),
    ) -> Project:
        """账本内重排（`before=None` → 追加尾部）；跨项目重排 → 409。"""
        async with _translated():
            return _project(
                await _service().reorder(project_id, session_id, req.before)
            )
