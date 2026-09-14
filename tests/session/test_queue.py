"""MessageQueueManager 测试（T2 / #132）。

测试续聊排队与 steer 注册的内存状态管理。
"""

from __future__ import annotations

import pytest

from agent_harness.session.queue import MessageQueueManager, SteerRequest


@pytest.fixture
def manager() -> MessageQueueManager:
    return MessageQueueManager()


class TestEnqueueAndDrain:
    @pytest.mark.asyncio
    async def test_enqueue_and_drain_fifo(self, manager):
        """消息按 FIFO 顺序消费。"""
        msg1 = await manager.enqueue(
            session_id="s1", content="hello", created_at="2026-01-01T00:00:00",
        )
        msg2 = await manager.enqueue(
            session_id="s1", content="world", created_at="2026-01-01T00:00:01",
        )
        assert msg1.queue_id != msg2.queue_id

        drained1 = await manager.drain_next("s1")
        assert drained1 is not None
        assert drained1.content == "hello"

        drained2 = await manager.drain_next("s1")
        assert drained2 is not None
        assert drained2.content == "world"

        # 队列空了
        drained3 = await manager.drain_next("s1")
        assert drained3 is None

    @pytest.mark.asyncio
    async def test_drain_empty_returns_none(self, manager):
        """空队列 drain 返回 None。"""
        assert await manager.drain_next("nonexistent") is None

    @pytest.mark.asyncio
    async def test_pending_count(self, manager):
        """pending_count 返回未取消的数量。"""
        assert await manager.pending_count("s1") == 0
        await manager.enqueue(session_id="s1", content="a", created_at="t")
        await manager.enqueue(session_id="s1", content="b", created_at="t")
        assert await manager.pending_count("s1") == 2


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_marks_message(self, manager):
        """cancel 标记消息为已取消，drain_next 跳过。"""
        msg1 = await manager.enqueue(session_id="s1", content="first", created_at="t")
        await manager.enqueue(session_id="s1", content="second", created_at="t")

        cancelled = await manager.cancel(session_id="s1", queue_id=msg1.queue_id)
        assert cancelled is True

        # drain 跳过已取消的 msg1，直接返回 msg2
        drained = await manager.drain_next("s1")
        assert drained is not None
        assert drained.content == "second"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, manager):
        """取消不存在的 queue_id → False。"""
        assert await manager.cancel(session_id="s1", queue_id="fake-id") is False

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_returns_false(self, manager):
        """重复取消 → 第二次返回 False。"""
        msg = await manager.enqueue(session_id="s1", content="x", created_at="t")
        assert await manager.cancel(session_id="s1", queue_id=msg.queue_id) is True
        assert await manager.cancel(session_id="s1", queue_id=msg.queue_id) is False


class TestListPending:
    @pytest.mark.asyncio
    async def test_list_pending_excludes_cancelled(self, manager):
        """list_pending 不包含已取消的。"""
        msg1 = await manager.enqueue(session_id="s1", content="a", created_at="t")
        await manager.enqueue(session_id="s1", content="b", created_at="t")
        await manager.cancel(session_id="s1", queue_id=msg1.queue_id)

        pending = await manager.list_pending("s1")
        assert len(pending) == 1
        assert pending[0].content == "b"


class TestSteer:
    @pytest.mark.asyncio
    async def test_register_and_drain_steer(self, manager):
        """steer 注册后 drain 取出并清除。"""
        req = await manager.register_steer(
            session_id="s1", content="steer this", run_id="run-1", created_at="t",
        )
        assert isinstance(req, SteerRequest)
        assert req.content == "steer this"

        steers = await manager.drain_steers("s1")
        assert len(steers) == 1
        assert steers[0].steer_id == req.steer_id

        # drain 后清空
        assert await manager.drain_steers("s1") == []

    @pytest.mark.asyncio
    async def test_drain_steers_empty(self, manager):
        """无 steer 请求时 drain 返回空列表。"""
        assert await manager.drain_steers("s1") == []


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_removes_all(self, manager):
        """cleanup 清除 session 的所有队列和 steer 状态。"""
        await manager.enqueue(session_id="s1", content="a", created_at="t")
        await manager.register_steer(session_id="s1", content="s", run_id="r", created_at="t")
        await manager.cleanup("s1")

        assert await manager.pending_count("s1") == 0
        assert await manager.drain_steers("s1") == []
        assert await manager.drain_next("s1") is None
