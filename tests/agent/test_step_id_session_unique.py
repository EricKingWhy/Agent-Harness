"""step_id session 级唯一性回归（TICKET_STEP_ID_COLLISION_MULTI_TURN）。

前端 projection 用 step_id 定位 turn（`resolveStep` → `withTurnAt`），其设计
不变量是「step_id 在 session 级唯一」。旧实现里 runtime 的 step_id 是 per-run
局部计数器，第二轮续聊又从 1 编号 → 与首轮撞号，前端把第二轮模型输出折叠进
首轮 turn（首轮回答被清空、次轮回答错位）。

本文件锁定四条不变量：
1. 续聊 run 的 model 事件 step_id 严格大于前序 run（不再撞号）；
2. step_id 连续接续（第二轮从首轮最大 step 继续），与前端给 user 消息分配
   的 `turns.length + 1` 对齐；
3. 前一轮在首个 model 事件前就终结（失败/取消）时，基数仍要推进——这类
   「空轮」不产出正 step_id，只看最大 step_id 会再次撞号；
4. `steps`（run 内轮次计数）不被全局步号污染——max_steps 保险丝与
   AgentRunResult.steps 仍是本轮轮数。
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from agent_harness.agent import AgentRuntime
from agent_harness.agent.types import STATUS_COMPLETED, STATUS_FAILED
from agent_harness.session import (
    MODEL_COMPLETED,
    MODEL_STARTED,
    RUN_FAILED,
    RUN_STARTED,
    USER_MESSAGE,
)
from agent_harness.tooling import Tool, ToolExecutor, ToolRegistry, ToolResult
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel


class _EchoArgs(BaseModel):
    text: Annotated[str, Field(..., description="要回显的文本")]


class EchoTool(Tool):
    """最小工具：给「一轮多步」场景制造 tool_call 往返。"""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "回显文本。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EchoArgs

    async def execute(self, args: _EchoArgs) -> ToolResult:
        return ToolResult.success(message=args.text, data={"echo": args.text})


def _runtime(model: ScriptedModel, *, with_tool: bool = False,
             max_steps: int = 20) -> AgentRuntime:
    registry = ToolRegistry()
    if with_tool:
        registry.register(EchoTool())
    return AgentRuntime(model=model, registry=registry,
                        executor=ToolExecutor(registry), max_steps=max_steps)


async def _run_turn(runtime: AgentRuntime, session, text: str):
    """驱动一轮 run_stream，返回 (本轮持久化 SessionEvent, 本轮流式 AgentEvent)。

    每轮单独构造 Runtime（与 web/CLI 每轮 build_runtime 一致）——本测试关心的是
    跨 run 的 session 级编号，不是 Runtime 实例复用。
    """
    start = len(session.events)
    streamed = [event async for event in runtime.run_stream(session, text)]
    return session.events[start:], streamed


def _steps_of(events) -> list[int]:
    return [e.step_id for e in events if e.type == MODEL_COMPLETED]


class TestStepIdSessionUnique:
    @pytest.mark.asyncio
    async def test_second_turn_continues_after_first(self, tmp_path):
        """两轮纯对话：第二轮 model 事件接续，而不是又从 1 开始。"""
        session = make_session(tmp_path)
        model = ScriptedModel([AIMessage(content="你好啊"), AIMessage(content="你是王浩宇")])

        first_events, _ = await _run_turn(_runtime(model), session, "你好")
        second_events, second_streamed = await _run_turn(
            _runtime(model), session, "我是谁",
        )

        assert _steps_of(first_events) == [1], "首轮仍是 1（首轮行为不变）"
        assert _steps_of(second_events) == [2], "旧行为是 1 → 前端折叠覆盖首轮 turn"
        # model/started 的 data.step 是前端 resolveStep 的首选键，同样必须接续
        started = [e.data["step"] for e in second_streamed if e.type == MODEL_STARTED]
        assert started == [2]

    @pytest.mark.asyncio
    async def test_multi_step_turn_advances_base_to_max_step(self, tmp_path):
        """首轮跑满 3 步（两次工具往返）：第二轮从 4 接续。

        4 正是前端给第二轮 user 消息分配的 `turns.length + 1`（首轮 3 个 step
        各占一个 turn）——两侧对齐才不会再出现「回答错位到上一轮」。
        """
        session = make_session(tmp_path)
        model = ScriptedModel([
            AIMessage(content="", tool_calls=[
                {"id": "echo-1", "name": "echo", "args": {"text": "a"}}]),
            AIMessage(content="", tool_calls=[
                {"id": "echo-2", "name": "echo", "args": {"text": "b"}}]),
            AIMessage(content="首轮完成"),
            AIMessage(content="第二轮完成"),
        ])
        runtime = _runtime(model, with_tool=True)

        first_events, _ = await _run_turn(runtime, session, "生产三轮")
        second_events, _ = await _run_turn(runtime, session, "续聊")

        assert _steps_of(first_events) == [1, 2, 3]
        assert _steps_of(second_events) == [4]
        # user 消息不带 step_id（前端按 turn 数分配）——本轮契约未变
        assert [e.step_id for e in session.events if e.type == USER_MESSAGE] == [None, None]

    @pytest.mark.asyncio
    async def test_turn_dying_before_model_call_still_advances_base(self, tmp_path):
        """首轮在首个 model 事件前就失败：该轮只留下 user 消息（无 step_id），
        max_step_id 仍是 0。基数若只看最大 step_id，第二轮会再次从 1 编号，
        与首轮 user 占用的 turn 1 撞号——正是原 bug 的另一条触发路径。
        """
        session = make_session(tmp_path)
        # 空剧本：首次模型调用即 RuntimeError（剧本耗尽）→ run/failed，无 model/completed
        failed = await _runtime(ScriptedModel([])).run(session, "第一条")

        assert failed.status == STATUS_FAILED
        assert session.events[-1].type == RUN_FAILED, "失败兜底必须写出终态事件"
        assert _steps_of(session.events) == [], "该轮没有 model/completed"

        second_events, _ = await _run_turn(
            _runtime(ScriptedModel([AIMessage(content="第二条回答")])), session, "第二条",
        )
        assert _steps_of(second_events) == [2], "第二轮必须避开首轮 user 的 turn 1"

    @pytest.mark.asyncio
    async def test_run_local_steps_not_contaminated_by_base(self, tmp_path):
        """`steps` 仍是 run 内轮次计数：第二轮 max_steps 预算与
        AgentRunResult.steps 都不被全局步号吃掉。"""
        session = make_session(tmp_path)
        model = ScriptedModel([
            AIMessage(content="", tool_calls=[
                {"id": "echo-1", "name": "echo", "args": {"text": "a"}}]),
            AIMessage(content="首轮完成"),
            AIMessage(content="第二轮完成"),
        ])
        runtime = _runtime(model, with_tool=True, max_steps=3)

        first = await runtime.run(session, "第一轮")
        second = await runtime.run(session, "第二轮")

        assert first.status == STATUS_COMPLETED and first.steps == 2
        # 若把全局基数写进 steps，第二轮会从 3 起算并立刻撞 max_steps
        assert second.status == STATUS_COMPLETED and second.steps == 1

    @pytest.mark.asyncio
    async def test_cancelled_turn_then_follow_up_keeps_increasing(self, tmp_path):
        """取消轮（生成器关闭 → 取消臂补 run/failed）之后续聊仍继续编号。

        取消发生在首个 model/completed 之前时，该轮没有持久化 step_id——
        与上一条「空轮」同构，同样靠用户轮数把基数推走。
        """
        session = make_session(tmp_path)
        # 第一轮：跑到 run/started（run 已开）即断连（等价 SSE 客户端消失）
        agen = _runtime(ScriptedModel([AIMessage(content="不会被写完")])).run_stream(
            session, "第一轮",
        )
        async for frame in agen:
            if frame.type == RUN_STARTED:
                break
        await agen.aclose()
        # 收尾由内层 _drive 生成器被回收时同步执行（取消臂不 yield）；给它几个
        # 事件循环 tick 落地，避免依赖单次 sleep(0) 的时序假设。
        for _ in range(20):
            if session.events[-1].type == RUN_FAILED:
                break
            await asyncio.sleep(0)

        assert session.events[-1].type == RUN_FAILED
        assert session.events[-1].data.get("reason") == "cancelled"
        assert _steps_of(session.events) == []

        second_events, _ = await _run_turn(
            _runtime(ScriptedModel([AIMessage(content="第二轮回答")])), session, "第二轮",
        )
        assert _steps_of(second_events) == [2]
