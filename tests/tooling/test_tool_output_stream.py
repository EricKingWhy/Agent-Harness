"""T3（ADR-0016 §4）：工具输出真流式 + tool/call 预持久化。

验收映射（规格 01 §22 场景 C）：stdout/stderr 增量发射、channel 保真、
大输出不撑爆（帧上限 + channel 总量上限）；02 §8.3 状态机时序
（call → running/output_delta* → deferred → result）。
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from pydantic import BaseModel, Field

from agent_harness.agent import AgentRuntime
from agent_harness.session import (
    TOOL_CALL,
    TOOL_OUTPUT_DELTA,
    TOOL_RESULT,
    JsonlSessionStore,
    Session,
)
from agent_harness.tooling import (
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    ToolSideEffect,
)
from agent_harness.tooling.contract import PermissionPolicy, ToolPermission
from agent_harness.tooling.output_stream import ToolOutputStream


class _NoArgs(BaseModel):
    text: str = Field(default="x")


class _StreamingTool(Tool):
    """从工作线程逐段推 sink（模拟 sandbox reader 线程回调）。"""

    def __init__(self, segments: list[tuple[str, str]], *, delay: float = 0.0) -> None:
        self._segments = segments
        self._delay = delay

    @property
    def name(self) -> str:
        return "streamy"

    @property
    def description(self) -> str:
        return "streaming probe"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _NoArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    async def execute(self, args: _NoArgs) -> ToolResult:
        from agent_harness.tooling.output_stream import tool_output_sink_var

        sink = tool_output_sink_var.get()
        assert sink is not None, "执行期必须能从 contextvar 取到 sink"

        def produce():
            for channel, text in self._segments:
                if self._delay:
                    time.sleep(self._delay)
                sink.push(channel, text)
            sink.close()

        threading.Thread(target=produce, daemon=True).start()
        await asyncio.sleep(0.05)
        return ToolResult.success("done")


class _QuietTool(Tool):
    @property
    def name(self) -> str:
        return "quiet"

    @property
    def description(self) -> str:
        return "no output"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _NoArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    async def execute(self, args: _NoArgs) -> ToolResult:
        return ToolResult.success("quiet done")


def _executor(*tools: Tool) -> ToolExecutor:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolExecutor(registry, policy=PermissionPolicy.DANGER_FULL_ACCESS)


def _make_session(tmp_path) -> Session:
    return Session.start(JsonlSessionStore(root=tmp_path / "sessions"))


class TestToolOutputStreamUnit:
    @pytest.mark.asyncio
    async def test_push_caps_channel_total(self, tmp_path):
        """channel 总量上限（64KB）：超出部分丢弃，tool/result 仍是完整真相。"""
        from agent_harness.tooling.output_stream import TOOL_OUTPUT_MAX_CHANNEL_CHARS

        session = _make_session(tmp_path)
        sink = ToolOutputStream(
            session, tool_call_id="c1", run_id="r1", step_id=1,
            window=0.0, max_frame_chars=8192,
        )
        sink.push("stdout", "a" * TOOL_OUTPUT_MAX_CHANNEL_CHARS)
        sink.push("stdout", "overflow-should-be-dropped")
        sink.close()
        events = await sink.drain()
        total = sum(len(e.data["delta"]) for e in events if e.data["channel"] == "stdout")
        assert total == TOOL_OUTPUT_MAX_CHANNEL_CHARS

    @pytest.mark.asyncio
    async def test_close_flushes_remaining(self, tmp_path):
        session = _make_session(tmp_path)
        sink = ToolOutputStream(
            session, tool_call_id="c1", run_id="r1", step_id=1,
            window=30.0,  # 窗口极大：只有 close 能触发 flush
        )
        sink.push("stderr", "boom")
        sink.close()
        events = await sink.drain()
        assert len(events) == 1
        assert events[0].data["channel"] == "stderr"
        assert events[0].data["delta"] == "boom"
        assert events[0].data["tool_call_id"] == "c1"


class TestExecutorOutputStreaming:
    @pytest.mark.asyncio
    async def test_streams_deltas_with_channel_fidelity(self, tmp_path):
        """执行期增量落盘：channel 保真、相邻同 channel 合帧、result 终态。"""
        session = _make_session(tmp_path)
        executor = _executor(_StreamingTool([
            ("stdout", "line1\n"), ("stdout", "line2\n"),
            ("stderr", "warn\n"), ("stdout", "line3\n"),
        ]))
        from agent_harness.storage import OperationContext

        executions = await executor.execute_batch(
            [{"id": "c1", "name": "streamy", "args": {}}],
            session=session,
            operation_context=OperationContext(
                session_id=session.session_id, run_id="r1",
            ),
            step_id=1,
        )
        assert executions[0].result.ok

        deltas = [e for e in session.events if e.type == TOOL_OUTPUT_DELTA]
        assert deltas, "输出增量必须落盘"
        channels = [(e.data["channel"], e.data["delta"]) for e in deltas]
        joined_stdout = "".join(t for c, t in channels if c == "stdout")
        joined_stderr = "".join(t for c, t in channels if c == "stderr")
        assert joined_stdout == "line1\nline2\nline3\n"
        assert joined_stderr == "warn\n"
        for e in deltas:
            assert e.data["tool_call_id"] == "c1"
            assert e.run_id == "r1" and e.step_id == 1

    @pytest.mark.asyncio
    async def test_quiet_tool_emits_no_deltas(self, tmp_path):
        """非流式工具零 delta（02 §7.5：不要求每个工具都流）。"""
        session = _make_session(tmp_path)
        executor = _executor(_QuietTool())
        from agent_harness.storage import OperationContext

        await executor.execute_batch(
            [{"id": "c1", "name": "quiet", "args": {}}],
            session=session,
            operation_context=OperationContext(
                session_id=session.session_id, run_id="r1",
            ),
            step_id=1,
        )
        assert not [e for e in session.events if e.type == TOOL_OUTPUT_DELTA]


class TestRuntimeToolSequence:
    @pytest.mark.asyncio
    async def test_call_precedes_deltas_and_result(self, tmp_path):
        """完整时序：tool/call（预持久化）→ output_delta* → tool/result。"""
        from langchain_core.messages import AIMessage

        from tests.scripted_model import ScriptedModel

        session = _make_session(tmp_path)
        registry = ToolRegistry()
        registry.register(_StreamingTool([("stdout", "chunk-a\n"), ("stdout", "chunk-b\n")]))
        executor = ToolExecutor(registry, policy=PermissionPolicy.DANGER_FULL_ACCESS)
        model = ScriptedModel([
            AIMessage(content="", tool_calls=[{
                "name": "streamy", "args": {}, "id": "c1", "type": "tool_call",
            }]),
            AIMessage(content="finished"),
        ])
        runtime = AgentRuntime(
            model=model, registry=registry, executor=executor, max_steps=5,
        )

        frames = [e async for e in runtime.run_stream(session, "run tool")]

        seq_types = [(e.seq, e.type) for e in frames if e.seq is not None]
        call_idx = next(i for i, (_, t) in enumerate(seq_types) if t == TOOL_CALL)
        delta_idx = [i for i, (_, t) in enumerate(seq_types) if t == TOOL_OUTPUT_DELTA]
        result_idx = next(i for i, (_, t) in enumerate(seq_types) if t == TOOL_RESULT)
        assert delta_idx, "必须有输出增量"
        assert call_idx < min(delta_idx) < result_idx, \
            "时序必须是 call → delta* → result（02 §8.3）"
        deltas = [e for e in frames if e.type == TOOL_OUTPUT_DELTA]
        assert "".join(e.data["delta"] for e in deltas) == "chunk-a\nchunk-b\n"
