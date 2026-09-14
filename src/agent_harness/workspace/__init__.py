"""Workspace 实体（DSH 同构）：项目 ↔ 多会话的显式建模。

**与 `agent_harness.sandbox.WorkspaceRegistry` 无关**——那个是"会话 → 沙箱目录"的映射表
（`<root>/workspaces/<session_id>.json`，只有 create/get/exists/stop/delete，无枚举）。
本包是 ADR-0025 的 Workspace **实体 + 有序会话账本**：`id`（uuid）稳定引用、`path`
（规范绝对路径）做唯一性、`sessionIds` 有序手工拥有。

本包是**索引**而不是第二真相源（不变量 #22）：会话 header 的 `cwd` 才是成员资格的真相，
账本可被重建（见 `WorkspaceIndex.bootstrap`）。

模型不可见：没有工具、没有提示词、没有会话事件（ticket #152 参考节）。
"""

from agent_harness.workspace.index import (
    SessionHeaders,
    UnknownLedgerEntry,
    UnknownWorkspace,
    WorkspaceError,
    WorkspaceIndex,
)
from agent_harness.workspace.models import StartedHeader, Workspace
from agent_harness.workspace.store import SqliteWorkspaceStore, WorkspaceRegistryCorrupt

__all__ = [
    "SessionHeaders",
    "SqliteWorkspaceStore",
    "StartedHeader",
    "UnknownLedgerEntry",
    "UnknownWorkspace",
    "Workspace",
    "WorkspaceError",
    "WorkspaceIndex",
    "WorkspaceRegistryCorrupt",
]
