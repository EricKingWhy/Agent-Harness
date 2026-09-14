"""Operation Ledger domain contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel, computed_field


class OperationState(str, Enum):
    """Durable lifecycle of one Tool invocation."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    NEED_RECONCILE = "NEED_RECONCILE"


class Operation(BaseModel):
    """Persisted identity and current state of one Tool invocation."""

    tool_call_id: str
    session_id: str
    run_id: str | None = None
    agent_id: str | None = None
    tool_name: str
    args_identity: str
    state: OperationState
    result_json: str | None = None
    artifact_ref: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    reconcile_meta: str | None = None

    @computed_field
    @property
    def operation_id(self) -> str:
        """会话内标识（= tool_call_id）；Ledger 主键是 (session_id, tool_call_id) 复合键（C5）。

        tool_call_id 由模型生成、只在会话内唯一——单列主键会让跨会话复用
        同一 id 的两个 Operation 互相覆盖。
        """
        return self.tool_call_id


class OperationContext(BaseModel):
    """Session identity attached to each Operation by the Runtime."""

    session_id: str
    run_id: str | None = None
    agent_id: str | None = None


class OperationLedger(ABC):
    """Async persistence boundary for Operation state."""

    @abstractmethod
    async def initialize(self) -> None:
        """Create the Ledger schema if it does not exist."""

    @abstractmethod
    async def create(self, operation: Operation) -> None:
        """Persist a new PENDING Operation."""

    @abstractmethod
    async def get(self, session_id: str, tool_call_id: str) -> Operation | None:
        """Load one Operation by its (session_id, tool_call_id) composite key."""

    @abstractmethod
    async def update_state(
        self,
        session_id: str,
        tool_call_id: str,
        state: OperationState,
        *,
        result_json: str | None = None,
        artifact_ref: str | None = None,
        reconcile_meta: str | None = None,
    ) -> Operation:
        """Move one Operation to an allowed next state and return it."""

    @abstractmethod
    async def list_for_session(self, session_id: str) -> list[Operation]:
        """List a Session's Operations in creation order."""

    @abstractmethod
    async def delete_for_session(self, session_id: str) -> int:
        """Remove every Operation of a Session; return how many rows went away.

        会话硬删的一部分（ADR-0029）：append-only 事件日志（唯一真相源）被删除后，
        台账行描述的对象已不存在，也没有任何东西可供 reconcile——留着它只剩
        "会话不存在却有台账"这一种解释。

        幂等：未知 / 已清理干净的 session 返回 0、不抛错（重跑即自愈，ADR-0029 D3）。
        """
