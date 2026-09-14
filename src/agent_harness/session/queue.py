"""MessageQueueManager — 续聊排队与 steer 的内存状态管理（T2 / #132）。

PRD §5.3 / §6：活跃 run 时新消息默认进队列（MESSAGE_QUEUED），
run 结束后自动消费队列开下一轮；用户可选 steer 模式注入当前 run
（STEER_REQUESTED → STEER_APPLIED）。

设计要点：
- 队列状态在内存（本管理器），事实持久化在 SessionEvent（单一事实源 #22）。
- 每 session 一个 asyncio.Queue + 一个消费 task（run 结束时拉起）。
- cancel_queue 取消队列项 → QUEUE_CANCELLED 事件。
- steer 请求先写 STEER_REQUESTED 事件，runtime 注入后写 STEER_APPLIED
  （注入本身需要 runtime 侧 hook，本管理器只负责排队与事件触发）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import uuid4

logger = logging.getLogger("agent_harness.session.queue")


@dataclass
class QueuedMessage:
    """一个排队中的续聊消息。"""

    queue_id: str
    content: str
    session_id: str
    created_at: str
    cancelled: bool = False


@dataclass
class SteerRequest:
    """一个 steer 请求（立即注入当前 run）。"""

    steer_id: str
    content: str
    session_id: str
    run_id: str
    created_at: str


class MessageQueueManager:
    """每 session 的消息队列 + steer 请求注册表。

    生命周期由 SessionService 管理：
    - send_message(mode="queue") 在活跃 run 时把消息放入队列。
    - run 结束时 SessionService 调 drain_next() 取出下一条并开新 run。
    - cancel_queue() 取消队列项。
    - steer() 注册 steer 请求（runtime 侧注入由 runtime hook 处理）。
    """

    def __init__(self) -> None:
        # session_id → 有界队列（按 FIFO 消费）
        self._queues: dict[str, list[QueuedMessage]] = {}
        # session_id → steer 请求列表（runtime 在下一步前检查）
        self._steers: dict[str, list[SteerRequest]] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self, *, session_id: str, content: str, created_at: str
    ) -> QueuedMessage:
        """把消息放入 session 的队列，返回 QueuedMessage。"""
        queue_id = str(uuid4())
        msg = QueuedMessage(
            queue_id=queue_id,
            content=content,
            session_id=session_id,
            created_at=created_at,
        )
        async with self._lock:
            self._queues.setdefault(session_id, []).append(msg)
        return msg

    async def drain_next(self, session_id: str) -> QueuedMessage | None:
        """取出下一条未取消的排队消息（FIFO），移除已取消的前置项。"""
        async with self._lock:
            queue = self._queues.get(session_id)
            if not queue:
                return None
            while queue:
                msg = queue.pop(0)
                if not msg.cancelled:
                    if not queue:
                        self._queues.pop(session_id, None)
                    return msg
            self._queues.pop(session_id, None)
            return None

    async def cancel(self, *, session_id: str, queue_id: str) -> bool:
        """标记队列项为已取消。返回 True 表示找到并取消。"""
        async with self._lock:
            queue = self._queues.get(session_id)
            if not queue:
                return False
            for msg in queue:
                if msg.queue_id == queue_id and not msg.cancelled:
                    msg.cancelled = True
                    return True
            return False

    async def pending_count(self, session_id: str) -> int:
        """未取消的排队项数量。"""
        async with self._lock:
            queue = self._queues.get(session_id, [])
            return sum(1 for m in queue if not m.cancelled)

    async def list_pending(self, session_id: str) -> list[QueuedMessage]:
        """列出未取消的排队项（只读）。"""
        async with self._lock:
            queue = self._queues.get(session_id, [])
            return [m for m in queue if not m.cancelled]

    async def register_steer(
        self, *, session_id: str, content: str, run_id: str, created_at: str
    ) -> SteerRequest:
        """注册一个 steer 请求。runtime 在下一步前检查并注入。"""
        steer_id = str(uuid4())
        req = SteerRequest(
            steer_id=steer_id,
            content=content,
            session_id=session_id,
            run_id=run_id,
            created_at=created_at,
        )
        async with self._lock:
            self._steers.setdefault(session_id, []).append(req)
        return req

    async def drain_steers(self, session_id: str) -> list[SteerRequest]:
        """取出并清除 session 的所有待处理 steer 请求。"""
        async with self._lock:
            return self._steers.pop(session_id, [])

    async def cleanup(self, session_id: str) -> None:
        """session 结束 / GC 时清理队列和 steer 状态。"""
        async with self._lock:
            self._queues.pop(session_id, None)
            self._steers.pop(session_id, None)
