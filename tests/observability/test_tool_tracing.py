"""T3 #119：tool span（逐 attempt 链）+ SubAgent agent 型观测 + 嵌套绑定。

ADR-0018 D5/D7：工具调用 = ``tool`` 型观测；delegate 工具 = ``agent`` 型 +
具体目标命名（绝不用 tool/span 隐藏 SubAgent 结构），其存活期间设置嵌套
绑定——child run 的 RunTracer 认领 agent 观测为根，child 的 generation
全部挂在其下（官方结构：无 dispatch/execution 双节点）。
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from agent_harness.observability import LangfuseSink, RunTracer
from agent_harness.observability.tracer import current_trace_binding
from agent_harness.tooling import Tool, ToolExecutor, ToolRegistry, ToolResult
from agent_harness.tooling.result import ErrorCode
from tests.observability.test_tracer import FakeRecorder


class _Args(BaseModel):
    value: Annotated[int, Field(...)]


class _FlakyTool(Tool):
    """第一次执行返回可重试失败（驱动唯一 Retry Layer），第二次成功。"""

    def __init__(self):
        self.calls = 0

    @property
    def name(self) -> str:
        return "flaky"

    @property
    def description(self) -> str:
        return "重试链观测用。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _Args

    async def execute(self, args: _Args) -> ToolResult:
        self.calls += 1
        if self.calls == 1:
            return ToolResult.failure(
                message="transient boom",
                error_code=ErrorCode.TIMEOUT,
                retryable=True,
            )
        return ToolResult.success(message="ok")


class _DelegateLikeTool(Tool):
    """is_subagent_dispatch 工具：执行期间模拟 child runtime 建自己的 tracer。"""

    is_subagent_dispatch = True

    @property
    def name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        return "委派给 SubAgent。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _Args

    async def execute(self, args: _Args) -> ToolResult:
        binding = current_trace_binding.get()
        assert binding is not None, "delegate 执行期间必须有嵌套绑定"
        child = RunTracer(
            self._sink, session_id="child-sess", run_id="child-run",
            agent_id="researcher", user_input="子任务",
        )
        child.run_started()
        gen = child.model_call_started(step=1, messages=[{"role": "user", "content": "m"}])
        child.model_call_completed(gen, output_text="子回答", usage=None, duration_ms=1)
        child.run_completed("子回答")
        type(self).captured_child = child
        return ToolResult.success(message="委派完成", data={"child_session_id": "child-sess"})

    captured_child: RunTracer | None = None
    _sink: LangfuseSink


def _sink(recorder: FakeRecorder) -> LangfuseSink:
    return LangfuseSink(
        public_key="pk", secret_key="sk", base_url="https://example.invalid",
        client_factory=lambda **kwargs: recorder.client(),
    )


def _tracer(recorder: FakeRecorder) -> RunTracer:
    tracer = RunTracer(
        _sink(recorder), session_id="sess", run_id="run", agent_id="default",
        user_input="任务",
    )
    tracer.run_started()
    return tracer


@pytest.mark.asyncio
async def test_tool_span_records_attempt_chain_and_completion():
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    root = recorder.spans[0]

    registry = ToolRegistry()
    tool = _FlakyTool()
    registry.register(tool)
    executor = ToolExecutor(registry)
    execution = await executor.execute(
        {"id": "call_1", "name": "flaky", "args": {"value": 1}}, tracer=tracer,
    )

    assert execution.result.ok
    tool_spans = [c for c in root.children if c.kind == "tool"]
    assert len(tool_spans) == 1
    span = tool_spans[0]
    assert span.name == "flaky"
    assert span.kwargs["input"] == {"value": 1}
    assert span.kwargs["metadata"]["tool_call_id"] == "call_1"
    final = span.updates[-1]
    assert final["metadata"]["outcome"] == "success"
    assert len(final["metadata"]["attempts"]) == 2
    assert final["metadata"]["attempts"][0]["ok"] is False
    assert final["metadata"]["attempts"][0]["error_code"] == "TIMEOUT"
    assert final["metadata"]["attempts"][1]["ok"] is True
    assert span.ended


@pytest.mark.asyncio
async def test_delegate_tool_uses_agent_observation_and_nests_child():
    recorder = FakeRecorder()
    tracer = _tracer(recorder)
    root = recorder.spans[0]

    registry = ToolRegistry()
    tool = _DelegateLikeTool()
    tool._sink = tracer._sink
    registry.register(tool)
    executor = ToolExecutor(registry)
    execution = await executor.execute(
        {"id": "call_d", "name": "delegate", "args": {"value": 1}}, tracer=tracer,
    )

    assert execution.result.ok
    agent_spans = [c for c in root.children if c.kind == "agent"]
    assert len(agent_spans) == 1, "delegate 必须是 agent 型观测（不是 tool/span）"
    agent_span = agent_spans[0]
    assert agent_span.name == "delegate"
    # child tracer 认领 agent 观测为根：generation 挂在其下、同一 trace。
    child = type(tool).captured_child
    assert child is not None
    assert child.trace_id == tracer.trace_id
    generations = [c for c in agent_span.children if c.kind == "generation"]
    assert len(generations) == 1
    assert generations[0].kwargs["input"] == [{"role": "user", "content": "m"}]
    # 根的生命周期归父侧 executor：agent 观测由 tool_span_completed 收口。
    assert agent_span.ended
    # 绑定已还原：执行结束后 contextvar 回到 None。
    assert current_trace_binding.get() is None
