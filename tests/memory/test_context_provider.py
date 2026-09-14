"""Memory retrieval budgets, failure isolation, and background run writeback."""

import asyncio
import logging

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from agent_harness.agent import AgentRuntime
from agent_harness.context.builder import ContextBuilder
from agent_harness.context.tokens import estimate_message_tokens
from agent_harness.identity import (
    IdentityContext,
    identity_context_var,
    set_identity_context,
)
from agent_harness.memory.context_provider import MemoryContextProvider
from agent_harness.memory.extractor import ExtractionOutcome
from agent_harness.memory.fake_capability import FakeMemoryCapability
from agent_harness.memory.types import MemoryEntry, MemoryScope, memory_session_var
from agent_harness.memory.writeback import MemoryWriteback
from agent_harness.session import USER_MESSAGE, SessionEvent
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel


@pytest.mark.asyncio
async def test_select_budget_ranking_and_builder_insertion(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "TypeScript"})

    class Candidates:
        async def search(self, scope, query, limit):
            assert (scope, query, limit) == (MemoryScope.USER, "TypeScript", 20)
            return [MemoryEntry(id=str(i), content=text, metadata={"importance": 0.5},
                                score=score, created_at="2026-09-04T00:00:00+00:00", scope=scope)
                    for i, (text, score) in enumerate([("low " * 200, 0.1), ("TypeScript preferred", 1)])]

    provider = MemoryContextProvider(Candidates())
    selected = await provider.select(session, 90)
    assert len(selected) == 1 and isinstance(selected[0], SystemMessage)
    assert "TypeScript preferred" in selected[0].content and "low " not in selected[0].content
    assert estimate_message_tokens(selected) <= 90
    assert await provider.select(session, 1) == []
    builder = ContextBuilder(ScriptedModel([]), max_context_tokens=250, context_providers=[provider])
    history = session.derive_messages()
    messages = await builder.build(session)
    assert isinstance(messages[0], SystemMessage)
    assert messages[-1] == history[-1]
    assert session.derive_messages() == history
    assert estimate_message_tokens(messages) <= 250 * 0.85


@pytest.mark.asyncio
async def test_builder_clips_provider_that_ignores_budget(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "hello"})

    class Oversized:
        async def select(self, session, token_budget):
            return [SystemMessage(content="memory " * 1000)]

    builder = ContextBuilder(ScriptedModel([]), max_context_tokens=200, context_providers=[Oversized()])
    assert await builder.build(session) == session.derive_messages()


@pytest.mark.asyncio
async def test_replacement_context_provider_cannot_fail_runtime(tmp_path):
    class Broken:
        async def select(self, session, token_budget):
            raise ConnectionError("private-provider-error")

    registry = ToolRegistry()
    runtime = AgentRuntime(ScriptedModel([AIMessage(content="done")]), registry, ToolExecutor(registry),
                           context_providers=[Broken()])
    assert (await runtime.run(make_session(tmp_path), "hello")).final_text == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "timeout", "cancel"])
async def test_retrieval_failure_and_cancellation(tmp_path, failure):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "hello"})

    class Broken:
        async def search(self, *args, **kwargs):
            if failure == "timeout":
                await asyncio.Event().wait()
            if failure == "cancel":
                raise asyncio.CancelledError
            raise RuntimeError("credential-must-not-appear")

    provider = MemoryContextProvider(Broken(), timeout_seconds=0.01)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await provider.select(session, 100)
        assert not any(e.type == "memory/degraded" for e in session.events)
        return
    registry = ToolRegistry()
    runtime = AgentRuntime(ScriptedModel([AIMessage(content="done")]), registry, ToolExecutor(registry),
                           context_providers=[provider])
    assert (await runtime.run(session, "hello")).final_text == "done"
    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert len(degraded) == 1
    assert "credential" not in str(degraded)


@pytest.mark.asyncio
async def test_empty_memory(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "hello"})
    assert await MemoryContextProvider(FakeMemoryCapability()).select(session, 1000) == []


@pytest.mark.asyncio
async def test_background_writeback_is_nonblocking_and_captures_identity(tmp_path):
    release = asyncio.Event()
    captured = []

    class Extractor:
        async def extract(self, events):
            await release.wait()
            captured.append([e.data["content"] for e in events if e.type == USER_MESSAGE])
            return ExtractionOutcome([(MemoryScope.USER, "TypeScript", {}),
                                      (MemoryScope.SESSION, "decision", {})])

    capability = FakeMemoryCapability()
    writer = MemoryWriteback(capability, Extractor())
    registry = ToolRegistry()
    runtime = AgentRuntime(ScriptedModel([AIMessage(content="done"), AIMessage(content="again")]),
                           registry, ToolExecutor(registry), memory_writer=writer)
    session = make_session(tmp_path)
    token = set_identity_context(IdentityContext("acme", "alice", ["user", "session"]))
    try:
        result = await asyncio.wait_for(runtime.run(session, "I prefer TypeScript"), 1)
        assert result.final_text == "done" and captured == []
        await runtime.run(session, "next turn")
    finally:
        identity_context_var.reset(token)
    release.set()
    await writer.drain()
    assert captured == [["I prefer TypeScript"], ["next turn"]]
    assert await capability.search(MemoryScope.USER, "TypeScript", 20) == []
    token = set_identity_context(IdentityContext("acme", "alice", ["user", "session"]))
    session_token = memory_session_var.set(session.session_id)
    try:
        assert len(await capability.search(MemoryScope.USER, "TypeScript", 20)) == 2
        assert len(await capability.search(MemoryScope.SESSION, "decision", 20)) == 2
    finally:
        memory_session_var.reset(session_token)
        identity_context_var.reset(token)
    assert memory_session_var.get() is None


@pytest.mark.asyncio
async def test_background_failure_is_durable_and_redacted(tmp_path):
    class Broken:
        async def extract(self, events):
            raise RuntimeError("credential-must-not-appear")

    session = make_session(tmp_path)
    writer = MemoryWriteback(FakeMemoryCapability(), Broken())
    writer.submit(session, session.events)
    await writer.drain()
    assert session.events[-1].type == "memory/degraded"
    assert "credential" not in str(session.events[-1].data)


@pytest.mark.asyncio
async def test_writeback_failure_logs_root_cause_and_types_reason(tmp_path, caplog):
    """写回失败必须把根因（含堆栈）写进日志，并在降级事件 reason 里带上异常
    类型名，让代码 Bug 与存储故障可区分；原始异常消息不进事件流（防泄露）。"""
    class Broken:
        async def extract(self, events):
            raise RuntimeError("storage-outage-details")

    session = make_session(tmp_path)
    writer = MemoryWriteback(FakeMemoryCapability(), Broken())
    with caplog.at_level(logging.ERROR, logger="agent_harness.memory"):
        writer.submit(session, session.events)
        await writer.drain()
    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert len(degraded) == 1
    assert degraded[0].data["reason"] == "unavailable: RuntimeError"
    assert "RuntimeError" in caplog.text  # 根因日志（含堆栈）可观测
    assert "storage-outage-details" not in str(degraded[0].data)  # 原始消息不进事件


@pytest.mark.asyncio
async def test_degraded_event_fires_exactly_once_per_failure(tmp_path):
    """每次失败恰好产生一条 memory/degraded，不丢失也不重复。"""
    class Broken:
        async def extract(self, events):
            raise RuntimeError("boom")

    session = make_session(tmp_path)
    writer = MemoryWriteback(FakeMemoryCapability(), Broken())
    writer.submit(session, session.events)
    writer.submit(session, session.events)
    await writer.drain()
    assert len([e for e in session.events if e.type == "memory/degraded"]) == 2


@pytest.mark.asyncio
async def test_stream_mirrors_retrieval_degradation_and_writer_can_close(tmp_path):
    class Broken:
        async def search(self, *args, **kwargs):
            raise RuntimeError("unavailable")

    cancelled = asyncio.Event()
    started = asyncio.Event()

    class SlowExtractor:
        async def extract(self, events):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    session = make_session(tmp_path)
    writer = MemoryWriteback(FakeMemoryCapability(), SlowExtractor())
    registry = ToolRegistry()
    runtime = AgentRuntime(ScriptedModel([AIMessage(content="done")]), registry, ToolExecutor(registry),
                           context_providers=[MemoryContextProvider(Broken())], memory_writer=writer)
    events = [event async for event in runtime.run_stream(session, "hello")]
    degraded = next(e for e in events if e.type == "memory/degraded")
    assert degraded.seq == next(e.seq for e in session.events if e.type == "memory/degraded")
    assert events[-1].type == "run/completed"
    await asyncio.wait_for(started.wait(), 1)
    await writer.close()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_search_failure_logs_root_cause_and_types_reason(tmp_path, caplog):
    """检索失败的降级事件 reason 带异常类型名（与 writeback 同一模式）：
    日志含根因堆栈，原始异常消息不进事件流（防泄露）。"""
    class Broken:
        async def search(self, *args, **kwargs):
            raise RuntimeError("milvus-down-detail")

    session = make_session(tmp_path)
    session.append("user/message", {"content": "找一下我的偏好"})
    provider = MemoryContextProvider(Broken())
    with caplog.at_level(logging.ERROR, logger="agent_harness.memory"):
        accepted = await provider.select(session, token_budget=500)
    assert accepted == []
    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert len(degraded) == 1
    assert degraded[0].data["reason"] == "unavailable: RuntimeError"
    assert "RuntimeError" in caplog.text
    assert "milvus-down-detail" not in str(degraded[0].data)


@pytest.mark.asyncio
async def test_degraded_event_carries_run_id(tmp_path):
    """MEMORY_DEGRADED 必须带 run_id（R3-7 跨层对账）：事件要能定位到
    具体哪一轮 run 的上下文构建发生了降级。run 上下文经 session 层的
    contextvar 传递（runtime 设置、provider 读取），不改变 Provider 协议。"""
    from agent_harness.session import RUN_STARTED

    session = make_session(tmp_path)

    class Broken:
        async def search(self, *args, **kwargs):
            raise RuntimeError("boom")

    provider = MemoryContextProvider(Broken())
    registry = ToolRegistry()
    runtime = AgentRuntime(ScriptedModel([AIMessage(content="done")]), registry,
                           ToolExecutor(registry), context_providers=[provider])
    await runtime.run(session, "hello")

    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert len(degraded) == 1
    run_started = next(e for e in session.events if e.type == RUN_STARTED)
    assert degraded[0].run_id == run_started.run_id


# ── C3（用户拍板）：writeback 逐候选隔离 + close 先 drain ──


@pytest.mark.asyncio
async def test_writeback_isolates_per_candidate_failures(tmp_path):
    """单个候选 store 失败不得吞掉其余候选（此前顺序写、第 N 个失败全丢）。"""
    from agent_harness.memory.fake_capability import FakeMemoryCapability

    class FlakyStore(FakeMemoryCapability):
        def __init__(self):
            super().__init__()
            self.stored: list[str] = []

        async def store(self, scope, content, metadata):
            if "boom" in content:
                raise ConnectionError("store offline")
            self.stored.append(content)
            return f"mem-{len(self.stored)}"

    from agent_harness.memory.types import MemoryScope

    class StaticExtractor:
        async def extract(self, events):
            return ExtractionOutcome([
                (MemoryScope.SESSION, "good-1", {"importance": 0.5}),
                (MemoryScope.SESSION, "boom-candidate", {"importance": 0.5}),
                (MemoryScope.SESSION, "good-2", {"importance": 0.5}),
            ])

    session = make_session(tmp_path)
    writer = MemoryWriteback(FlakyStore(), StaticExtractor())
    writer.submit(session, [SessionEvent(seq=1, type=USER_MESSAGE,
                                         session_id=session.session_id,
                                         data={"content": "hi"})])
    await writer.drain()
    cap = writer._capability
    assert cap.stored == ["good-1", "good-2"], "部分失败必须隔离，不吞掉其余候选"
    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert any("partial" in e.data["reason"] for e in degraded)


@pytest.mark.asyncio
async def test_close_drains_pending_writeback(tmp_path):
    """close() 必须先 drain（等在途写完成），超时才取消——此前直接 cancel，
    已抽取未存储的候选静默丢失。"""
    import asyncio as _asyncio

    from agent_harness.memory.fake_capability import FakeMemoryCapability
    from agent_harness.memory.types import MemoryScope

    class SlowStore(FakeMemoryCapability):
        def __init__(self):
            super().__init__()
            self.stored: list[str] = []

        async def store(self, scope, content, metadata):
            await _asyncio.sleep(0.2)
            self.stored.append(content)
            return "mem-1"

    class StaticExtractor:
        async def extract(self, events):
            return ExtractionOutcome([(MemoryScope.SESSION, "drained-candidate", {"importance": 0.5})])

    session = make_session(tmp_path)
    writer = MemoryWriteback(SlowStore(), StaticExtractor())
    writer.submit(session, [SessionEvent(seq=1, type=USER_MESSAGE,
                                         session_id=session.session_id,
                                         data={"content": "hi"})])
    await _asyncio.sleep(0.05)  # 任务已启动、还在 store 的 sleep 中
    await writer.close()
    assert writer._capability.stored == ["drained-candidate"], "close 丢弃了在途候选"
