"""真实 run_stream 断连 → Session.resume 修复 dangling tool_call（spec 11 §4 回归）。

tests/test_web_api.py 的 disconnect 测试是 stub 级：只证明 SSE 层把断连信号传给了
producer。本文件补真实循环的最后一环：_drive 在 tool/call 已持久化、tool/result
尚未回填的窗口被掐断，session 落盘停在 dangling tool/call 上；此后 Session.resume
必须成功，并合成配对的 tool/result，让会话历史恢复可对账（不变量 #7 配对语义）。

实现事实（读 runtime.py / executor.py 确认，测试据此钉住真实窗口）：
- ToolExecutor 全程不写 SessionEvent；tool/call + tool/result 由 AgentRuntime 在
  execute_batch 返回【之后】背靠背 append——因此"取消在途的 execute_batch"只会
  留下带 tool_calls 的 model/completed（没有任何 tool/call，detect_dangling 无从
  修复），执行完成前掐断不会留下 dangling tool_call。
- tool/call append 与 tool/result append 之间唯一的挂起点是 run_stream 的
  `yield to_agent_event(call_event)`：此处 generator 挂起、消费者已拿到帧（不在
  __anext__ 里），task.cancel() 打不进来；唯一能到达 _drive 的终止信号是关闭
  generator 时注入的 GeneratorExit——这正是 EventSourceResponse 对断连 producer
  的真实收尾（见 test_web_api.py 顶部注释）。本测试就在这一帧上关流。
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from agent_harness.agent import AgentRuntime
from agent_harness.session import (
    DANGLING_TOOL_CONTENT,
    RUN_COMPLETED,
    RUN_FAILED,
    TOOL_CALL,
    TOOL_RESULT,
    JsonlSessionStore,
    Session,
)
from agent_harness.tooling import Tool, ToolExecutor, ToolRegistry, ToolResult
from tests.scripted_model import ScriptedModel

TOOL_CALL_ID = "call_disconnect_001"


class _NoArgs(BaseModel):
    pass


class _EchoTool(Tool):
    """快速返回的探针工具：断连发生时执行早已完成，dangling 只能来自断连窗口本身。"""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "原样返回固定文本。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _NoArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        return ToolResult.success("echoed")


@pytest.mark.asyncio
async def test_disconnected_run_stream_leaves_recoverable_dangling_tool_call(
    tmp_path: Path,
) -> None:
    """_drive 在 tool/call 与 tool/result 之间被掐断 -> Session.resume 合成 tool/result。"""
    store = JsonlSessionStore(root=tmp_path)
    session = Session.start(store)
    registry = ToolRegistry()
    registry.register(_EchoTool())
    model = ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": TOOL_CALL_ID, "name": "echo", "args": {}}],
            ),
            AIMessage(content="done"),
        ]
    )
    runtime = AgentRuntime(model, registry, ToolExecutor(registry))

    agen = runtime.run_stream(session, "hello")
    tool_call_persisted = asyncio.Event()

    async def consume() -> None:
        async for frame in agen:
            if frame.type == TOOL_CALL:
                # 帧 = 持久化 SessionEvent 的镜像：此刻 tool/call 已落盘，
                # _drive 挂在 yield to_agent_event(call_event) 上。
                tool_call_persisted.set()
                await asyncio.Event().wait()  # 挂住消费者，把断连钉在这一帧之后

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(tool_call_persisted.wait(), timeout=5.0)
    except TimeoutError:
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer
        raise AssertionError("没等到 tool/call 帧——工具回填流程未按预期推进")
    consumer.cancel()  # 消费者断连（SSE 客户端消失）
    with contextlib.suppress(asyncio.CancelledError):
        await consumer
    # SSE 层的真实收尾：关闭 producer generator，GeneratorExit 打进悬挂点。
    await agen.aclose()
    await asyncio.sleep(0)  # 让内层 _drive generator 的 GC 收尾跑一个事件循环 tick

    # 断连后落盘：dangling tool/call（无 tool/result）+ 取消臂补的 run/failed 终结。
    # Round 7 契约修订：此前断连不写任何 run 终结事件——web 层无人自动调 resume，
    # run/started 永久悬空，违反 runtime 自己的不变量（"run 绝不能永久悬挂在
    # 悬空的 run/started 上"）。现在取消臂补 run/failed(reason=cancelled)；
    # resume 的 dangling 修复是配对语义、与 run 终结状态正交，可恢复性不变。
    before_resume = store.read_events(session.session_id)
    assert [
        e.data["tool_call_id"] for e in before_resume if e.type == TOOL_CALL
    ] == [TOOL_CALL_ID]
    assert not [e for e in before_resume if e.type == TOOL_RESULT]
    terminal = [e for e in before_resume if e.type in (RUN_COMPLETED, RUN_FAILED)]
    assert [e.type for e in terminal] == [RUN_FAILED]
    assert terminal[-1].data.get("reason") == "cancelled"

    # Session.resume 必须成功，并合成配对的 tool/result（dangling 修复语义）。
    resumed = Session.resume(store, session.session_id)
    synthesized = [
        e
        for e in resumed.events
        if e.type == TOOL_RESULT and e.data.get("tool_call_id") == TOOL_CALL_ID
    ]
    assert len(synthesized) == 1
    assert synthesized[0].data.get("dangling") is True
    assert synthesized[0].data.get("content") == DANGLING_TOOL_CONTENT
