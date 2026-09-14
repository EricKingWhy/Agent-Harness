"""Stable-boundary Checkpoint domain contracts.

Checkpoint 是"已经持久化成功、可以恢复的稳定状态事实"（07 §2），不是代码执行到某一行，
也不是对话事实。它与 SessionEvent 分层：checkpoint/saved 永远不进 SessionEvent（ADR-0004 Round 5）。

本模块只定义 ABC 和值对象，不绑定具体存储后端；SQLite 实现见 storage.sqlite。
PostgreSQL 实现本 Phase 只留 ABC 替换边界，不实装。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from agent_harness.session import Session


def _default_created_at() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class CheckpointBoundary(str, Enum):
    """07 §3 冻结的四个稳定边界——AgentRuntime 只在这四个点请求 Checkpoint。

    USER_ACCEPTED         用户消息已写入，模型即将被调用；
    MODEL_COMPLETED       一轮模型回复已持久化（含或不含 tool_calls）；
    TOOL_BATCH_COMPLETED  一整批 tool_call/result 已回填；
    FINAL_COMPLETED       Run 正常结束。
    """

    USER_ACCEPTED = "USER_ACCEPTED"
    MODEL_COMPLETED = "MODEL_COMPLETED"
    TOOL_BATCH_COMPLETED = "TOOL_BATCH_COMPLETED"
    FINAL_COMPLETED = "FINAL_COMPLETED"


class Checkpoint(BaseModel):
    """一条稳定边界快照——存储层的可恢复事实辅助。"""

    session_id: str
    boundary_type: CheckpointBoundary
    event_seq: int
    payload_json: str | None = None
    created_at: str = _default_created_at()


class CheckpointStore(ABC):
    """稳定边界快照的异步持久化边界。

    PostgreSQL 实现只在本 ABC 上形成替换边界，Phase 4 不实装。
    """

    @abstractmethod
    async def initialize(self) -> None:
        """创建 schema（幂等）。"""

    @abstractmethod
    async def save(self, checkpoint: Checkpoint) -> None:
        """写入一条 Checkpoint；同一 (session_id, boundary_type, event_seq) 主键唯一。"""

    @abstractmethod
    async def list_for_session(self, session_id: str) -> list[Checkpoint]:
        """按 event_seq 升序列出某 session 的全部 Checkpoint。"""

    @abstractmethod
    async def latest(self, session_id: str) -> Checkpoint | None:
        """返回某 session 最近一条 Checkpoint（最高 event_seq），无则 None。"""

    @abstractmethod
    async def delete_for_session(self, session_id: str) -> int:
        """删除某 session 的全部 Checkpoint，返回删除条数。

        会话硬删的一部分（ADR-0029）：Checkpoint 是**恢复辅助**，它描述的那份事件日志
        被删掉后就没有恢复对象了。幂等：未知 / 已清空 → 0，不抛错。
        """


class CheckpointPolicy(ABC):
    """薄 seam：AgentRuntime 在每个稳定边界调 maybe_save 决定是否落盘。

    ADR-0004 Round 2 §CheckpointPolicy：默认实现 OnStableBoundary（生产）；
    测试可用 NoCheckpoint / EveryStep。
    """

    @abstractmethod
    async def maybe_save(
        self,
        session: Session,
        boundary_type: CheckpointBoundary,
        *,
        event_seq: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Checkpoint | None:
        """在稳定边界被调用；返回落盘的 Checkpoint，或 None 表示不保存。"""


class OnStableBoundary(CheckpointPolicy):
    """生产默认策略：在四个稳定边界一律落盘。

    需要 checkpoint_store；没有 store 时退化为 no-op（保持 AgentRuntime 可选接线，
    不强制 Core 依赖存储）。
    """

    def __init__(self, checkpoint_store: CheckpointStore | None) -> None:
        self._store = checkpoint_store

    async def maybe_save(
        self,
        session: Session,
        boundary_type: CheckpointBoundary,
        *,
        event_seq: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Checkpoint | None:
        if self._store is None:
            return None
        seq = session.next_seq - 1 if event_seq is None else event_seq
        checkpoint = Checkpoint(
            session_id=session.session_id,
            boundary_type=boundary_type,
            event_seq=seq,
            payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
        )
        await self._store.save(checkpoint)
        return checkpoint


class NoCheckpoint(CheckpointPolicy):
    """测试用：任何边界都不落盘。"""

    async def maybe_save(
        self,
        session: Session,
        boundary_type: CheckpointBoundary,
        *,
        event_seq: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Checkpoint | None:
        return None


class EveryStep(CheckpointPolicy):
    """测试用：每个边界都落盘（同一 ABC 接口，证明策略可替换）。

    行为与 OnStableBoundary 在四个稳定边界一致——区别在于语义保证：它明确表示
    "无差别保存"，用于验证 AgentRuntime 真的在每个边界都调了 policy。
    """

    def __init__(self, checkpoint_store: CheckpointStore | None) -> None:
        self._store = checkpoint_store

    async def maybe_save(
        self,
        session: Session,
        boundary_type: CheckpointBoundary,
        *,
        event_seq: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Checkpoint | None:
        if self._store is None:
            return None
        seq = session.next_seq - 1 if event_seq is None else event_seq
        checkpoint = Checkpoint(
            session_id=session.session_id,
            boundary_type=boundary_type,
            event_seq=seq,
            payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
        )
        await self._store.save(checkpoint)
        return checkpoint
