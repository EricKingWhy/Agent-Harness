"""Workspace 实体与会话 header 的值对象（ADR-0025 D2/D6）。

`StartedHeader` 是 bootstrap 能看到的**全部**东西：`session/started` 事件信封里的
`time` + `data` 里的 `cwd` / `agent_id`，加上会话目录名（= id）。它刻意**不含**
任何事件正文——AC14 要求引导"绝不读事件正文"。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_harness.session.header import StartedHeader

__all__ = ["StartedHeader", "Workspace", "WorkspaceStatus"]

#: AC8：目录缺失永不改写记录，只改这里报告出来的状态。
WorkspaceStatus = Literal["ok", "missing-dir"]


@dataclass(frozen=True)
class Workspace:
    """一个项目（Workspace 实体）。

    `session_ids` 是**已过成员资格过滤**的有序会话列表（新→旧，AC5/AC6）：
    账本里有、且该会话 header 的规范 cwd 逐字符等于 `path` 的才在里面。
    """

    id: str
    path: str
    title: str
    created_at: str
    updated_at: str
    session_ids: tuple[str, ...] = ()

    def status(self) -> WorkspaceStatus:
        """AC8：目录当前是否存在；**不做任何记录改写**。"""
        return "ok" if Path(self.path).is_dir() else "missing-dir"

    @staticmethod
    def default_title(path: str) -> str:
        """AC3：缺省标题 = 末段路径；无末段（根路径）用根路径拼写。

        `Path(r"D:\\").name == ""` / `Path("/").name == ""` → 退回 `str(Path(path))`
        （POSIX 上 `str(Path("/")) == "/"`，Windows 上盘根是 `"D:\\"`）。
        """
        name = Path(path).name
        return name or str(Path(path))
