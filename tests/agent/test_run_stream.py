"""AgentRuntime.run_stream() 流式契约测试（Phase 9）。

验证：
1. run_stream 合帧 yield text/delta（ADR-0016：durable，带 seq）。
2. 每个持久化事件都有镜像 AgentEvent（带 seq）。
3. 流式 delta 拼接后等于 model/completed 的 content。
4. run() 向后兼容（用 ainvoke，不依赖 astream）。
5. run_stream 跑完后 session 事件事实源跟 run() 一致。

不用真实模型——ScriptedModel.astream 确定性按 chunk_size 切 content。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from agent_harness.agent import AgentRuntime
from agent_harness.session import (
    MODEL_COMPLETED,
    MODEL_STARTED,
    RUN_COMPLETED,
    RUN_STARTED,
    TEXT_DELTA,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    Session,
)
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel


def _build_runtime(model, tmp_path) -> AgentRuntime:
    """最小 runtime：只有模型，没有工具（流式契约测试不需要真实工具）。"""
    registry = ToolRegistry()
    return AgentRuntime(
        model=model,
        registry=registry,
        executor=ToolExecutor(registry),
        max_steps=5,
    )


@pytest.mark.asyncio
async def test_run_stream_yields_model_delta_chunks(tmp_path):
    """text/delta 合帧流式输出，拼接等于 model/completed 的 content。"""
    # ScriptedModel 默认 chunk_size=8，把 "Hello, world!" 切成 2 个 chunk
    model = ScriptedModel([AIMessage(content="Hello, world!")])
    runtime = _build_runtime(model, tmp_path)
    session = make_session(tmp_path)

    events = [e async for e in runtime.run_stream(session, "hi")]

    deltas = [e for e in events if e.type == TEXT_DELTA]
    completed = [e for e in events if e.type == MODEL_COMPLETED]

    # 合帧（30ms 窗口内快速 chunk）：ScriptedModel 的两个 chunk 在窗口内
    # 到达 → 一条 text/delta（S19 禁逐 token 行）；拼接仍 = content。
    assert len(deltas) >= 1
    assert len(completed) == 1
    assembled = "".join(d.data["delta"] for d in deltas)
    assert assembled == completed[0].data["content"] == "Hello, world!"
    # delta 是 durable 事实：合帧事件带 seq（ADR-0016 §3.1）
    for d in deltas:
        assert d.seq is not None, "text/delta 合帧后必须持久化（带 seq）"


@pytest.mark.asyncio
async def test_run_stream_yields_model_started_before_delta(tmp_path):
    """model/started 在 model/delta 之前出现，标记一轮模型调用开始。"""
    model = ScriptedModel([AIMessage(content="done")])
    runtime = _build_runtime(model, tmp_path)
    session = make_session(tmp_path)

    events = [e async for e in runtime.run_stream(session, "hi")]
    types = [e.type for e in events]

    assert MODEL_STARTED in types
    started_idx = types.index(MODEL_STARTED)
    first_delta_idx = next((i for i, t in enumerate(types) if t == TEXT_DELTA), len(types))
    assert started_idx < first_delta_idx, "model/started 必须在第一个 text/delta 之前"


@pytest.mark.asyncio
async def test_run_stream_durable_events_have_seq(tmp_path):
    """持久化事件（user/message, run/started, model/completed, run/completed）都有 seq。"""
    model = ScriptedModel([AIMessage(content="answer")])
    runtime = _build_runtime(model, tmp_path)
    session = make_session(tmp_path)

    events = [e async for e in runtime.run_stream(session, "hi")]
    durable_types = {USER_MESSAGE, RUN_STARTED, MODEL_COMPLETED, RUN_COMPLETED}

    for e in events:
        if e.type in durable_types:
            assert e.seq is not None, f"{e.type} 是持久化事件，必须有 seq"
            assert e.is_durable


@pytest.mark.asyncio
async def test_run_stream_emits_tool_events(tmp_path):
    """带 tool_calls 的轮次：tool/call + tool/result 事件也被 yield（带 seq）。

    这里只验证事件流形状，不真实执行工具（registry 空 → 工具调用失败 →
    ToolResult ok=False，但事件流契约不变）。
    """
    model = ScriptedModel([
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "bash", "args": {"command": "ls"}}]),
        AIMessage(content="done"),
    ])
    runtime = _build_runtime(model, tmp_path)
    session = make_session(tmp_path)

    events = [e async for e in runtime.run_stream(session, "run ls")]
    types = [e.type for e in events]

    assert TOOL_CALL in types, "tool/call 事件应该出现在流里"
    assert TOOL_RESULT in types, "tool/result 事件应该出现在流里"
    # 这两个都有 seq（持久化）
    assert next(e for e in events if e.type == TOOL_CALL).seq is not None
    assert next(e for e in events if e.type == TOOL_RESULT).seq is not None


@pytest.mark.asyncio
async def test_run_backward_compatible_with_ainvoke(tmp_path):
    """run() 仍用 ainvoke（非流式），返回 AgentRunResult，不依赖 astream。"""
    model = ScriptedModel([AIMessage(content="legacy answer")])
    runtime = _build_runtime(model, tmp_path)
    session = make_session(tmp_path)

    result = await runtime.run(session, "hi")

    assert result.status == "completed"
    assert result.final_text == "legacy answer"
    assert result.steps == 1


@pytest.mark.asyncio
async def test_run_stream_and_run_produce_same_session_events(tmp_path):
    """run_stream 和 run 对同一个剧本产生同样的 SessionEvent 事实源。"""
    # 两个独立 session + 两个独立 model（同样的剧本）
    script = [AIMessage(content="same answer")]

    model_stream = ScriptedModel(script)
    model_invoke = ScriptedModel(script)

    runtime_stream = _build_runtime(model_stream, tmp_path)
    runtime_invoke = _build_runtime(model_invoke, tmp_path)

    session_stream = make_session(tmp_path / "stream")
    session_invoke = make_session(tmp_path / "invoke")

    async for _ in runtime_stream.run_stream(session_stream, "hi"):
        pass
    await runtime_invoke.run(session_invoke, "hi")

    # 比较 SessionEvent 的 type + data（seq 因为独立 session 会不同，不比 seq）
    # ADR-0016 §3.1：run_stream 现在额外产生合帧流式事实（text/delta）——
    # run() 走 ainvoke 无流式 chunk。两者的【非流式事实】（user/run/model/tool
    # 生命周期）仍必须逐条一致；流式增量是 stream 专属的 durable 补充。
    stream_fact_types = {TEXT_DELTA, "reasoning/started", "reasoning/delta",
                         "reasoning/completed", "reasoning/interrupted"}

    def shape(session: Session):
        return [(e.type, e.data) for e in session.events
                if e.type not in stream_fact_types]

    assert shape(session_stream) == shape(session_invoke), \
        "run_stream 和 run 的非流式 SessionEvent 事实源应该一致"
