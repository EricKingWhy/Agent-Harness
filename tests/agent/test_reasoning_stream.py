"""T2（ADR-0016 §3）：delta 合帧 + reasoning 事件族 + 中断保内容。

验收映射（规格 01 §22）：场景 A（reasoning 流式）、D（中断部分内容保留）、
S18/S19（历史恢复 + 禁逐 token 落盘）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from agent_harness.agent import AgentRuntime
from agent_harness.session import (
    MODEL_COMPLETED,
    REASONING_COMPLETED,
    REASONING_DELTA,
    REASONING_INTERRUPTED,
    REASONING_STARTED,
    RUN_FAILED,
    TEXT_DELTA,
    JsonlSessionStore,
    Session,
)
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.scripted_model import ScriptedModel


class ReasoningStreamModel:
    """按剧本逐个 yield 预构造 chunk（含 additional_kwargs.reasoning_content）。"""

    def __init__(self, chunks: list[AIMessageChunk]) -> None:
        self._chunks = chunks

    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        for chunk in self._chunks:
            yield chunk

    async def ainvoke(self, messages, **kwargs):
        return AIMessage(content="unused")


def _reasoning(text: str) -> AIMessageChunk:
    return AIMessageChunk(content="", additional_kwargs={"reasoning_content": text})


def _build_runtime(model, tmp_path: Path) -> AgentRuntime:
    return AgentRuntime(
        model=model,
        registry=ToolRegistry(),
        executor=ToolExecutor(ToolRegistry()),
        max_steps=5,
    )


def _make_session(tmp_path: Path) -> Session:
    return Session.start(JsonlSessionStore(root=tmp_path / "sessions"))


class TestReasoningEventFamily:
    @pytest.mark.asyncio
    async def test_reasoning_lifecycle_durable_events(self, tmp_path, monkeypatch):
        """思考 chunk → started/delta/completed 全族 durable（有 seq、落盘）。"""
        monkeypatch.setattr("agent_harness.agent.streaming.FLUSH_WINDOW_SECONDS", 0)
        model = ReasoningStreamModel([
            _reasoning("先想第一步。"),
            _reasoning("再想第二步。"),
            AIMessageChunk(content="最终答案"),
        ])
        runtime = _build_runtime(model, tmp_path)
        session = _make_session(tmp_path)

        frames = [e async for e in runtime.run_stream(session, "hi")]

        types = [e.type for e in frames]
        assert REASONING_STARTED in types
        assert REASONING_COMPLETED in types
        started = next(e for e in frames if e.type == REASONING_STARTED)
        assert started.data["source"] == "model"
        assert started.seq is not None and started.block_id

        deltas = [e for e in frames if e.type == REASONING_DELTA]
        assembled = "".join(e.data["delta"] for e in deltas)
        assert assembled == "先想第一步。再想第二步。"
        for d in deltas:
            assert d.data["source"] == "model"
            assert d.seq is not None
            assert d.block_id == started.block_id

        # 全部落盘：JSONL 里能读回同型事件（S18 历史恢复的前提）
        persisted_types = {e.type for e in session.events}
        assert {REASONING_STARTED, REASONING_DELTA, REASONING_COMPLETED} <= persisted_types

    @pytest.mark.asyncio
    async def test_no_reasoning_chunks_no_reasoning_events(self, tmp_path):
        """模型不吐思考 → reasoning 事件整族不出现（零伪造，D-B③）。"""
        model = ScriptedModel([AIMessage(content="直接回答")])
        runtime = _build_runtime(model, tmp_path)
        session = _make_session(tmp_path)

        frames = [e async for e in runtime.run_stream(session, "hi")]
        assert not [e for e in frames if e.type.startswith("reasoning/")]
        assert not [e for e in session.events if e.type.startswith("reasoning/")]

    @pytest.mark.asyncio
    async def test_coalesced_single_flush_before_boundary(self, tmp_path):
        """窗口内快速 chunk 合帧：不到 30ms 的逐 token 流只在块边界落一行（S19）。"""
        model = ReasoningStreamModel([
            _reasoning("甲"), _reasoning("乙"), _reasoning("丙"),
            AIMessageChunk(content="答"), AIMessageChunk(content="案"),
        ])
        runtime = _build_runtime(model, tmp_path)
        session = _make_session(tmp_path)

        frames = [e async for e in runtime.run_stream(session, "hi")]
        reasoning_deltas = [e for e in frames if e.type == REASONING_DELTA]
        text_deltas = [e for e in frames if e.type == TEXT_DELTA]
        assert len(reasoning_deltas) == 1
        assert reasoning_deltas[0].data["delta"] == "甲乙丙"
        assert len(text_deltas) == 1
        assert text_deltas[0].data["delta"] == "答案"

    @pytest.mark.asyncio
    async def test_text_closes_reasoning_new_reasoning_gets_new_block(self, tmp_path, monkeypatch):
        """文本到达关闭思考块；思考再开 = 新 block_id（02 §8.1 块不变量）。"""
        monkeypatch.setattr("agent_harness.agent.streaming.FLUSH_WINDOW_SECONDS", 0)
        model = ReasoningStreamModel([
            _reasoning("思考A"),
            AIMessageChunk(content="文本1"),
            _reasoning("思考B"),
            AIMessageChunk(content="文本2"),
        ])
        runtime = _build_runtime(model, tmp_path)
        session = _make_session(tmp_path)

        frames = [e async for e in runtime.run_stream(session, "hi")]
        started = [e for e in frames if e.type == REASONING_STARTED]
        completed = [e for e in frames if e.type == REASONING_COMPLETED]
        assert len(started) == 2 and len(completed) == 2
        assert started[0].block_id != started[1].block_id
        # 第一个块的 completed 先于第二个块的 started（叙事顺序 = seq 顺序）
        assert completed[0].seq < started[1].seq

    @pytest.mark.asyncio
    async def test_text_deltas_are_durable_and_assemble_to_content(self, tmp_path):
        """text/delta 合帧落盘：拼接 == model/completed.content（S19）。"""
        model = ScriptedModel([AIMessage(content="Hello, world!")])
        runtime = _build_runtime(model, tmp_path)
        session = _make_session(tmp_path)

        frames = [e async for e in runtime.run_stream(session, "hi")]
        deltas = [e for e in frames if e.type == TEXT_DELTA]
        completed = next(e for e in frames if e.type == MODEL_COMPLETED)
        assert deltas, "合帧后的文本 delta 必须存在"
        assert "".join(d.data["delta"] for d in deltas) == completed.data["content"]
        assert all(d.seq is not None for d in deltas)


class TestReasoningInterruption:
    @pytest.mark.asyncio
    async def test_model_failure_mid_reasoning_marks_interrupted(self, tmp_path):
        """模型流中途失败：部分思考已落盘 + reasoning/interrupted + run/failed。"""
        model = ReasoningStreamModel([
            _reasoning("想到一半"),
            AIMessageChunk(content=""),
        ])
        # 剧本吐完思考 chunk 后流挂死失败

        async def failing_astream(messages, **kwargs):
            yield _reasoning("想到一半")
            raise ConnectionError("provider down")

        model.astream = failing_astream  # type: ignore[method-assign]
        runtime = _build_runtime(model, tmp_path)
        session = _make_session(tmp_path)

        frames = [e async for e in runtime.run_stream(session, "hi")]
        types = [e.type for e in frames]
        assert REASONING_INTERRUPTED in types
        assert "model/failed" in types
        failed = [e for e in session.events if e.type == RUN_FAILED]
        assert failed and failed[-1].data.get("reason") is None
        # 部分内容保留（S18/16.4）：中断前思考已在 durable 流里
        persisted = [e for e in session.events if e.type == REASONING_DELTA]
        assert persisted and persisted[0].data["delta"] == "想到一半"
        interrupted = next(e for e in session.events if e.type == REASONING_INTERRUPTED)
        assert interrupted.block_id == persisted[0].block_id

    @pytest.mark.asyncio
    async def test_consumer_close_mid_reasoning_persists_partial(self, tmp_path, monkeypatch):
        """消费者中途关流（断连/取消路径）：残余缓冲 flush + interrupted 落盘。"""
        monkeypatch.setattr("agent_harness.agent.streaming.FLUSH_WINDOW_SECONDS", 0)
        model = ReasoningStreamModel([
            _reasoning("部分思考"),
            AIMessageChunk(content="稍后的文本"),
        ])

        async def slow_astream(messages, **kwargs):
            yield _reasoning("部分思考")
            await asyncio.sleep(0.5)  # 消费者在此窗口关流
            yield AIMessageChunk(content="不应到达")

        model.astream = slow_astream  # type: ignore[method-assign]
        runtime = _build_runtime(model, tmp_path)
        session = _make_session(tmp_path)

        drive = runtime.run_stream(session, "hi")
        async for event in drive:
            if event.type == REASONING_DELTA:
                break
        await drive.aclose()
        await asyncio.sleep(0.6)  # 让悬挂的内层生成器自然走完，避免 loop 关闭警告

        persisted_types = [e.type for e in session.events]
        assert REASONING_DELTA in persisted_types
        assert REASONING_INTERRUPTED in persisted_types
        assert any(e.type == RUN_FAILED and e.data.get("reason") == "cancelled"
                   for e in session.events)


class TestReasoningProviderExtraction:
    def test_reasoning_chat_openai_lifts_reasoning_content(self):
        """langchain-openai 基类丢弃第三方 reasoning_content；子类抬进 additional_kwargs。"""
        from langchain_openai.chat_models.base import AIMessageChunk as _AIMessageChunk

        from agent_harness.model.provider import ReasoningChatOpenAI

        model = ReasoningChatOpenAI(
            model="test-model", api_key="sk-test", base_url="http://127.0.0.1:1",
        )
        chunk = {
            "id": "c1",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "", "reasoning_content": "想一下"},
            }],
        }
        generation = model._convert_chunk_to_generation_chunk(chunk, _AIMessageChunk, None)
        assert generation is not None
        assert generation.message.additional_kwargs["reasoning_content"] == "想一下"

    def test_runtime_extracts_reasoning_per_chunk(self):
        from agent_harness.agent.runtime import _extract_reasoning

        assert _extract_reasoning(_reasoning("abc")) == "abc"
        assert _extract_reasoning(AIMessageChunk(content="x")) == ""
        assert _extract_reasoning(AIMessageChunk(content="x", additional_kwargs={})) == ""


class TestCoalescingWindowRegression:
    @pytest.mark.asyncio
    async def test_long_block_keeps_coalescing_after_first_window(self, tmp_path):
        """回归（review 发现）：首个窗口过期后合帧不得退化为逐 chunk 落盘。

        旧实现 `_rsn_since` 只在开块时设置、flush 后不重置——30ms 后每个
        chunk 都触发"窗口已过期"即时 flush，长思考块 = 数千 fsync 行（S19）。
        """
        monkeypatch_window = pytest.MonkeyPatch()
        monkeypatch_window.setattr(
            "agent_harness.agent.streaming.FLUSH_WINDOW_SECONDS", 0.05)
        try:
            chunks = [_reasoning(f"第{i}句。") for i in range(20)]
            model = ReasoningStreamModel(chunks)

            async def paced_astream(messages, **kwargs):
                for chunk in chunks:
                    yield chunk
                    await asyncio.sleep(0.015)  # 15ms/chunk：窗口内 3-4 个

            model.astream = paced_astream  # type: ignore[method-assign]
            runtime = _build_runtime(model, tmp_path)
            session = _make_session(tmp_path)

            frames = [e async for e in runtime.run_stream(session, "hi")]
            reasoning_deltas = [e for e in frames if e.type == REASONING_DELTA]
            # 20 chunk × 15ms ≈ 300ms / 50ms 窗口 ≈ 6-8 次合帧（远小于 20）
            assert len(reasoning_deltas) <= 10, (
                f"窗口过期后合帧退化为逐 chunk（{len(reasoning_deltas)} 行）——S19 违背"
            )
            assert "".join(e.data["delta"] for e in reasoning_deltas) == \
                "".join(f"第{i}句。" for i in range(20))
        finally:
            monkeypatch_window.undo()


class TestMemoryWritebackPrivacy:
    @pytest.mark.asyncio
    async def test_writeback_excludes_streaming_facts(self, tmp_path, monkeypatch):
        """review 发现：reasoning/*（provider 思考）与 delta 事件不得进记忆抽取
        （02 §15 隐私硬边界 + 50 条窗口不被 chunk 挤占）。"""
        submitted: list = []

        class FakeWriter:
            def submit(self, session, events):
                submitted.append(events)

        model = ReasoningStreamModel([
            _reasoning("私密思考内容"),
            AIMessageChunk(content="回答"),
        ])
        monkeypatch.setattr("agent_harness.agent.streaming.FLUSH_WINDOW_SECONDS", 0)
        runtime = _build_runtime(model, tmp_path)
        runtime._memory_writer = FakeWriter()
        session = _make_session(tmp_path)

        async for _ in runtime.run_stream(session, "hi"):
            pass

        assert submitted, "writeback 应被调用"
        types = [e.type for e in submitted[0]]
        assert not any(t.startswith("reasoning/") for t in types), (
            "reasoning 事件（provider 思考）不得进记忆抽取"
        )
        assert "text/delta" not in types and "tool/output_delta" not in types, (
            "流式增量与 model/completed、tool/result 重复，不得进抽取窗口"
        )
        assert "user/message" in types and "model/completed" in types
