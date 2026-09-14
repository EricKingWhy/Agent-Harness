"""宿主只读目录列举端点（WS-7 / #170，ADR-0028）。

Web UI 的「目录选择器」绕不开一个平台事实：浏览器拿不到真实绝对路径
（`<input webkitdirectory>` 只回报 `C:\\fakepath\\<名字>`；File System Access API 的
`showDirectoryPicker()` 句柄不暴露完整路径）。所以唯一可行路径是**后端列举 + 前端自绘**
——这正是 #155 AC3 当初写下的"若要做目录浏览器，需新的宿主侧端点"。

三条刻意的边界：

- **只读**：只列目录名与绝对路径，`depth` 恒为 1；不读文件内容、不做搜索/通配、无写语义。
- **诚实降级**：条目超过 `MAX_ENTRIES` → 截断并标记 `truncated: true`，不静默丢数据。
- **不展开符号链接**：symlink 目录照实列**一个**条目；点击进入时后端按真实目标解析，仍是
  一层列举——不递归就不会循环，也不会"逃逸"成另一棵树的全量展开。

来源闸复用 `web.projects.require_trusted_origin`（ADR-0028 D2）：**刻意不复制**——安全规则
有两份副本就是两个漂移面。
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from typing import TYPE_CHECKING

import anyio
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent_harness.sandbox.paths import canonical_workspace_path, is_absolute_path
from agent_harness.web.domain_errors import workspace_http_error
from agent_harness.web.projects import require_trusted_origin

if TYPE_CHECKING:
    from fastapi import FastAPI

#: 单次列举的条目上限。超限截断 + `truncated: true`（AC4）。500 足够任何真实目录的
#: 分页浏览需求，又给"列整个 C:\\"这类请求一个上界（响应体 + 前端渲染成本）。
MAX_ENTRIES = 500


class DirEntry(BaseModel):
    """一个子目录（或一个盘符根）。"""

    #: 目录名（不含路径）；根条目是根路径本身（如 `C:\\`、`/`）。
    name: str
    #: 绝对路径。子目录条目按**父目录 + 名字**拼出（不 realpath 展开——symlink 照列）；
    #: 根条目即根路径。
    path: str


class DirListing(BaseModel):
    """`GET /api/host/dirs` 的响应。"""

    #: 规范化后的当前目录；**根模式**（未传 `path`）为 `None`。
    path: str | None
    #: 上一级（供"向上"）；根 / 根模式为 `None`。
    parent: str | None
    #: 条目是否被 `MAX_ENTRIES` 截断（截断后 `entries` 是**排序后**的前缀）。
    truncated: bool
    entries: list[DirEntry] = Field(default_factory=list)


RootLister = Callable[[], list[DirEntry]]


def _list_os_roots() -> list[DirEntry]:
    """生产实现：Windows = 存在的盘符根；POSIX = `["/"]`。

    Python ≥3.12 用 `os.listdrives()`（内核返回，**零 I/O**——避免一个断连的映射网络盘
    把请求挂住几十秒）；更老的解释器退回"逐个盘符 `exists`"，那条路可能有这个代价，
    所以只在没有 `listdrives` 时才走。盘符拼写与系统一致（`C:\\` 带尾分隔符）。
    """
    if os.name != "nt":
        return [DirEntry(name="/", path="/")]
    listdrives = getattr(os, "listdrives", None)
    if listdrives is not None:
        return [DirEntry(name=drive, path=drive) for drive in listdrives()]
    return [
        DirEntry(name=f"{letter}:\\", path=f"{letter}:\\")
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if os.path.exists(f"{letter}:\\")
    ]


#: 根枚举 provider（**可注入**）：生产是 `_list_os_roots`，测试替换成假根。
#: 让测试不真扫盘符——真扫盘既慢又依赖机器（PRD §5 的测试决策）。
ROOTS_PROVIDER: RootLister = _list_os_roots


def _sorted(entries: list[DirEntry]) -> list[DirEntry]:
    """按 name 排序（大小写不敏感 + 原名兜底：跨平台确定，Windows 上是系统惯例）。

    同一个口径服务根模式与子目录列举——前端只依赖"按 name 有序"这一条，不关心来源。
    """
    return sorted(entries, key=lambda entry: (entry.name.casefold(), entry.name))


def _roots_listing() -> DirListing:
    return DirListing(path=None, parent=None, truncated=False,
                      entries=_sorted(ROOTS_PROVIDER()))


def _os_error(canonical: str, error: OSError) -> HTTPException:
    """文件系统 errno → HTTP（**每个 errno 走自己的分支**，绝不冒 500）。

    状态码与文案都收在 `web/domain_errors.workspace_http_error`（同一张表 + 同一份
    中文文案）：`POST /api/projects` 也用它，所以同一个路径在"目录浏览"和"注册项目"
    两处给出**逐字相同**的一句话（API-01，2026-09-13）。
    `canonical` 传进去是为了让 detail 里的路径是规范化后的形态。
    """
    return workspace_http_error(error, path=canonical)


def _directory_listing(path: str) -> DirListing:
    """给定目录的一层列举（同步 I/O；由 handler 卸载到 worker 线程）。"""
    if not is_absolute_path(path):
        # 与 `POST /api/projects` 的 `_require_absolute_path` 同款：必须在 realpath
        # **之前**挡住形态——`realpath(".")` 会解析成进程当前工作目录，把一次笔误
        # 变成"列举服务器碰巧启动的目录"。平台分支见 `sandbox.paths.is_absolute_path`。
        raise HTTPException(status_code=422, detail="path 必须是绝对路径")
    if "\x00" in path:
        # POSIX 的 realpath 遇 NUL 抛 ValueError（不是 OSError）→ 会穿透成 500。
        raise HTTPException(status_code=422, detail="path 含非法字符（NUL）")
    canonical = canonical_workspace_path(path)
    try:
        # `os.stat` 而不是 `os.path.exists`/`isdir`：后两者把 PermissionError 吞成
        # False，会把"存在但读不到"报成"目录不存在"（也与 ADR-0028"不降级"冲突）。
        mode = os.stat(canonical).st_mode
    except OSError as error:
        raise _os_error(canonical, error) from error
    if not stat.S_ISDIR(mode):
        raise HTTPException(status_code=422, detail=f"不是目录：{canonical}")

    try:
        names = os.listdir(canonical)
    except OSError as error:
        # 检查与列举之间有 TOCTOU 窗口（目录被删/被换成文件/断连网络盘）。这些 errno
        # 各有自己的状态码，不能只抓 PermissionError 让其余的冒成 500。
        raise _os_error(canonical, error) from error

    entries: list[DirEntry] = []
    for name in names:
        full = os.path.join(canonical, name)
        # `isdir` 跟随符号链接 → 指向目录的链接照列一个条目（AC6）；指向文件/断链的
        # 链接不是目录，不列（`isdir` 自身不抛，stat 失败一律按"不是目录"处理）。
        if not os.path.isdir(full):
            continue
        entries.append(DirEntry(name=name, path=full))

    ordered = _sorted(entries)
    parent = os.path.dirname(canonical)
    return DirListing(
        path=canonical,
        # 盘根（`D:\\`、`/`）的 dirname 是自己 → 没有"上一级"，报 null 而不是原地打转。
        parent=None if parent in ("", canonical) else parent,
        truncated=len(ordered) > MAX_ENTRIES,
        entries=ordered[:MAX_ENTRIES],
    )


def register_host_dir_routes(app: FastAPI) -> None:
    """把宿主目录列举路由挂到既有 app（`create_app` 里一行调用的接入面）。"""

    @app.get("/api/host/dirs")
    async def list_host_dirs(
        path: str | None = Query(default=None),
        _: None = Depends(require_trusted_origin),
    ) -> DirListing:
        """列盘符根（`path` 缺省）或某个目录的**直接子目录**（只读，一层）。

        错误矩阵（不冒 500）：非绝对 → 422 `path 必须是绝对路径` / 不存在 → 404
        `目录不存在：<规范路径>` / 是文件 → 422 `不是目录：<规范路径>` / 无权限 → 403
        `无权限访问：<规范路径>`。

        `path` **不设** `max_length`：超长是 OS 层问题（ENAMETOOLONG → 422 的中文 detail），
        交给 FastAPI 参数校验会在矩阵外多出一种 **list 形状**的 `detail`（前端要原样显示
        detail，形状不一致等于没契约）。
        """
        if path is None:
            # 根枚举也是系统调用（3.11 无 `os.listdrives` 时是 26 次 `exists`）：同样
            # 卸载到 worker——一个断连的映射网络盘不该挂住整个事件循环。
            return await anyio.to_thread.run_sync(_roots_listing)
        # 目录可能很大，`listdir` 是阻塞系统调用：卸载到 worker 线程（与 #153 的列表
        # 路径同款）。`HTTPException` 从线程里抛出后照常由 FastAPI 处理。
        return await anyio.to_thread.run_sync(_directory_listing, path)


#: 供 `web/__init__.py` 之类的聚合导入保持稳定（本模块的公开面）。
__all__ = [
    "MAX_ENTRIES",
    "ROOTS_PROVIDER",
    "DirEntry",
    "DirListing",
    "RootLister",
    "register_host_dir_routes",
]
