"""会话侧 cwd 锚（WS-1 / issue #151）：`session/started` 的 `cwd` 字段读写。

为什么要有这个锚：会话↔工作区的绑定原本只写在 sandbox 映射文件
（`<workspaces_root>/<session_id>.json` 的 `workspace_root`）里，那张表本质是
**sandbox 映射表**，被寄生成"成员资格真源"。会话自己没有任何不可变 cwd，
"这个会话属于哪个项目"就无从在会话侧校验——只能单向信任映射表。

本模块提供两件事：
- ``cwd_event_data`` —— 构造并入 ``session/started`` 的 ``{"cwd": ...}``（写入侧）；
- ``session_cwd`` —— 从事件流派生该值（读取侧，含历史遗留的 ``None`` 语义）。

三条语义（#151 AC1–AC3）：
1. **规范化**：值经 `canonical_workspace_path` 唯一一套规范化（与映射表同源）；
2. **不可变**：只有建会话时写一次——resume / replay / fork / model-change / 续聊
   都不追加、不改写第二条 ``session/started``（`JsonlSessionStore` 是 append-only，
   结构上决定了已落盘的事件不可改）；
3. **加法式**：旧会话没有该字段 → 读出 ``None``（= 历史遗留，未分组），
   **不回填猜测**、不让旧日志读取失败。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from agent_harness.sandbox.paths import canonical_workspace_path
from agent_harness.session.event import SESSION_STARTED, SessionEvent


def cwd_event_data(cwd: str | Path | None) -> dict[str, str]:
    """→ 可并入 ``session/started`` 的 ``{"cwd": 规范化绝对路径}``。

    ``None``（以及空串）→ ``{}``（不写字段）：缺省值就是"历史遗留 = 未分组"，
    不写一个 ``"cwd": None`` 进日志——那会让"老日志没有该键"与"新日志写了个空值"
    变成两种形状，读取侧要多一套判空。

    空串必须在这里挡掉，不能交给 ``realpath``：``os.path.realpath("")``
    返回的是**进程当前工作目录**，会把会话静默锚到服务器碰巧启动的那个目录——
    比"未分组"糟得多，而且与读取侧（空串按"无 cwd"）自相矛盾。
    """
    if not cwd:
        return {}
    return {"cwd": canonical_workspace_path(cwd)}


def session_cwd(events: Iterable[SessionEvent]) -> str | None:
    """从事件流派生会话 cwd；无（历史遗留）或形状非法 → ``None``。

    取**第一条** ``session/started``：该字段写后不可变，第一条即权威值（用最后
    一条会让"将来某处多追加一条 started"静默改写归属）。非字符串或空串一律按
    "无 cwd"处理——旧日志/手写日志不能因为一个坏字段让读取方炸掉（AC3）。
    """
    for event in events:
        if event.type != SESSION_STARTED:
            continue
        value = event.data.get("cwd")
        return value if isinstance(value, str) and value else None
    return None
