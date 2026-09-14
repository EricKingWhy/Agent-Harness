"""会话 header 投影（WS-2 / #152）：`session/started` 一条事件的只读视图。

`StartedHeader` 是 workspace 首次引导能看到**全部**东西：会话 id（= 目录名）、`cwd`、
`createdAt`（事件信封的 `time`）、`agent_id`。它刻意**不含**任何事件正文——AC14 要求
引导"绝不读事件正文"。

放在 session 层而不是 workspace 层：header 是会话的属性，`JsonlSessionStore` 直接
返回它；workspace 索引是消费方（依赖方向 session ← workspace）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StartedHeader:
    """会话不可变 header 的投影（第一条 `session/started` + 会话 id）。"""

    session_id: str
    cwd: str | None
    created_at: str | None
    agent_id: str | None = None
