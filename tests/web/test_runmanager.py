"""T4（ADR-0016 §2.1）：Session listener + RunManager detached-run 契约。

验收映射（规格 01 §22 场景 E）：断连不杀 run、订阅者实时收到 durable 事实
（含工具输出 delta）、孤儿宽限期回收、幂等合并（listener 与镜像 yield 不重复）。
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agent_harness.agent import AgentRuntime
from agent_harness.session import RUN_COMPLETED, RUN_STARTED, Session
from agent_harness.session.store import JsonlSessionStore
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.scripted_model import ScriptedModel


def _make_session(tmp_path: Path) -> Session:
    return Session.start(JsonlSessionStore(root=tmp_path / "sessions"))


def _runtime(model) -> AgentRuntime:
    return AgentRuntime(
        model=model, registry=ToolRegistry(),
        executor=ToolExecutor(ToolRegistry()), max_steps=5,
    )


class TestSessionListener:
    @pytest.mark.asyncio
    async def test_listener_receives_appended_events(self, tmp_path):
        session = _make_session(tmp_path)
        seen: list = []
        session.add_listener(seen.append)
        session.append(RUN_STARTED, {}, run_id="r1")
        assert [e.type for e in seen] == [RUN_STARTED]
        session.remove_listener(seen.append)
        session.append(RUN_COMPLETED, {}, run_id="r1")
        assert len(seen) == 1, "移除后不再收到"

    @pytest.mark.asyncio
    async def test_listener_error_does_not_break_append(self, tmp_path):
        session = _make_session(tmp_path)

        def boom(_event):
            raise RuntimeError("listener fault")

        session.add_listener(boom)
        event = session.append(RUN_STARTED, {}, run_id="r1")
        assert event.seq >= 0, "listener 异常不得破坏 append 契约"
        assert session.events[-1].type == RUN_STARTED


class TestRunManager:
    @pytest.mark.asyncio
    async def test_disconnect_does_not_kill_run(self, tmp_path):
        """核心语义反转（D-A）：订阅者离开后 run 继续跑到终态。"""
        from agent_harness.web.runmanager import RunManager

        store = JsonlSessionStore(root=tmp_path / "sessions")
        session = _make_session(tmp_path)
        runtime = _runtime(ScriptedModel([AIMessage(content="done")]))
        manager = RunManager(disconnect_grace_seconds=60.0)
        try:
            run, subscriber = manager.launch(session, runtime, "hi")

            # 订阅者收首批事件后立即离开（模拟断连）
            first = await asyncio.wait_for(subscriber.queue.get(), timeout=5)
            assert first is not None
            run.unsubscribe(subscriber)

            # run 继续执行到终态（不因断连取消）
            await asyncio.wait_for(run.task, timeout=10)
            types = [e.type for e in store.read_events(session.session_id)]
            assert types[-1] == RUN_COMPLETED
        finally:
            await manager.aclose()

    @pytest.mark.asyncio
    async def test_subscriber_receives_events_without_duplicates(self, tmp_path):
        """durable 事实幂等合并：listener 捕获 + 镜像 yield 双通道不产生重复。"""
        from agent_harness.web.runmanager import RunManager

        session = _make_session(tmp_path)
        runtime = _runtime(ScriptedModel([AIMessage(content="hello")]))
        manager = RunManager(disconnect_grace_seconds=60.0)
        try:
            _run, subscriber = manager.launch(session, runtime, "hi")
            frames = []
            while True:
                item = await asyncio.wait_for(subscriber.queue.get(), timeout=5)
                if item is manager.DONE:
                    break
                frames.append(item)

            seqs = [f.seq for f in frames if f.seq is not None]
            assert len(seqs) == len(set(seqs)), "durable 事件不得重复入队"
            types = [f.type for f in frames]
            assert "user/message" in types and RUN_COMPLETED in types
            assert types[-1] == RUN_COMPLETED
        finally:
            await manager.aclose()

    @pytest.mark.asyncio
    async def test_orphan_run_reclaimed_after_grace(self, tmp_path, monkeypatch):
        """零订阅者超过宽限期 → run 被回收（取消臂收尾 run/failed）。"""
        from agent_harness.web.runmanager import RunManager

        class SlowModel:
            def bind_tools(self, tools, **kwargs):
                return self

            async def astream(self, messages, **kwargs):
                await asyncio.sleep(60)
                yield AIMessageChunk(content="never")

        from langchain_core.messages import AIMessageChunk

        store = JsonlSessionStore(root=tmp_path / "sessions")
        session = _make_session(tmp_path)
        runtime = _runtime(SlowModel())
        manager = RunManager(disconnect_grace_seconds=0.2)
        try:
            run, subscriber = manager.launch(session, runtime, "hi")
            await asyncio.sleep(0.05)
            run.unsubscribe(subscriber)  # 孤儿化

            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(run.task, timeout=5)
            types = [e.type for e in store.read_events(session.session_id)]
            assert types[-1] == "run/failed"
            assert any(e.type == "run/failed" and e.data.get("reason") == "orphaned"
                       for e in store.read_events(session.session_id))
        finally:
            await manager.aclose()

    @pytest.mark.asyncio
    async def test_cancel_marks_task(self, tmp_path):
        from agent_harness.web.runmanager import RunManager

        session = _make_session(tmp_path)
        runtime = _runtime(ScriptedModel([AIMessage(content="done")]))
        manager = RunManager(disconnect_grace_seconds=60.0)
        try:
            run, _subscriber = manager.launch(session, runtime, "hi")
            assert manager.cancel(session.session_id) is True
            assert manager.cancel("no-such-session") is False
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(run.task, timeout=5)
        finally:
            await manager.aclose()
