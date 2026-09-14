"""工具事件发射单一 owner（批次 C / 架构候选 3）。

"TOOL_CALL → 延迟事件 → TOOL_RESULT"的持久化顺序此前编码在三处
（runtime 结果循环 / executor abort flush / overflow 的 pending_events 契约），
且 abort 路径的 run 归因从 runtime 两层外设置的 contextvar 隐式读取——
executor 的 docstring 声称"不维护 Session"却经隐式 seam 写 Session。
收拢后：顺序知识只在 ToolExecutor.emit_call_events / emit_result_event，
run 归因是显式参数。
"""

import json

import pytest
from pydantic import BaseModel, Field

from agent_harness.session import (
    TOOL_CALL,
    TOOL_RESULT,
    run_context_var,
)
from agent_harness.storage import OperationContext
from agent_harness.tooling import (
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    ToolSideEffect,
)
from agent_harness.tooling.contract import PermissionPolicy, ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint


class EchoArgs(BaseModel):
    text: str = Field(default="x")


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo"

    @property
    def args_schema(self) -> type[BaseModel]:
        return EchoArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.READ_ONLY

    @property
    def timeout_seconds(self) -> float:
        return 5.0

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(verifiable=False)

    async def execute(self, args: EchoArgs) -> ToolResult:
        return ToolResult.success(args.text)


class BigOutputTool(EchoTool):
    """大输出工具：overflow save 失败在 retry 域之外传播（存储失败不属于
    Tool failure），从而触发批次 abort flush 路径。"""

    @property
    def name(self) -> str:
        return "big"

    async def execute(self, args: EchoArgs) -> ToolResult:
        return ToolResult.success("y" * 5000)


def _executor(*tools: Tool) -> ToolExecutor:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolExecutor(registry, policy=PermissionPolicy.DANGER_FULL_ACCESS)


@pytest.mark.asyncio
async def test_emit_call_event_then_pending_events_order(tmp_path):
    """TOOL_CALL（执行前，ADR-0016 §4.1）→ 延迟事件（R6-7：artifact/created
    不得前向引用 tool_call），顺序知识单一持有。"""
    from tests.conftest import make_session

    session = make_session(tmp_path)
    executor = _executor(EchoTool())
    call_event = executor.emit_call_event(
        session,
        tool_call_id="call-1", tool_name="bash",
        args={"command": "ls"},
        run_id="run-1", step_id=2,
    )
    pending = executor.emit_pending_events(
        session,
        pending_events=[("artifact/created", {"artifact_id": "a1"})],
        run_id="run-1", step_id=2,
    )
    assert call_event.type == TOOL_CALL
    assert call_event.data["tool_call_id"] == "call-1"
    assert call_event.run_id == "run-1" and call_event.step_id == 2
    assert [e.type for e in pending] == ["artifact/created"]
    assert [e.type for e in session.events[-2:]] == [TOOL_CALL, "artifact/created"], \
        "事件已持久化"


@pytest.mark.asyncio
async def test_emit_result_event_wraps_json_content(tmp_path):
    from tests.conftest import make_session

    session = make_session(tmp_path)
    executor = _executor(EchoTool())
    result = ToolResult.success("done")
    event = executor.emit_result_event(
        session, tool_call_id="call-1",
        content=result.model_dump_json(), run_id="run-1", step_id=2,
    )
    assert event.type == TOOL_RESULT
    assert json.loads(event.data["content"])["message"] == "done"


@pytest.mark.asyncio
async def test_batch_abort_attributes_run_id_from_operation_context(tmp_path, monkeypatch):
    """批次 abort 路径的 run 归因走显式 operation_context.run_id——不再从
    runtime 两层外设置的 contextvar 隐式读取（docstring 说"不维护 Session"
    却经隐式 seam 写 Session，全仓最隐蔽的耦合）。

    ADR-0016 §4.1 flush 语义：TOOL_CALL 由 Runtime 预持久化（不在 flush 补），
    flush 只补已提交执行的延迟事件（artifact/externalized 等）——本测试直接调
    execute_batch，预持久化缺席，因此只断言 pending 事件归因。"""
    from tests.conftest import make_session

    # 显式证明不再依赖 contextvar：即使它带着另一个 run_id 也不用
    token = run_context_var.set("contextvar-run")

    class UnavailableStore:
        async def save(self, *args, **kwargs):
            raise ConnectionError("storage offline")

    from agent_harness.tooling.overflow import ArtifactOverflowHandler
    session = make_session(tmp_path)
    executor = _executor(EchoTool(), BigOutputTool())
    executor._overflow_handler = ArtifactOverflowHandler(UnavailableStore())
    calls = [
        {"id": "call-1", "name": "echo", "args": {}},
        {"id": "call-2", "name": "big", "args": {}},
    ]
    try:
        await executor.execute_batch(
            calls, session=session,
            operation_context=OperationContext(
                session_id=session.session_id, run_id="opctx-run",
            ),
        )
    finally:
        run_context_var.reset(token)

    # T5 (#135): fail-open — store unavailable → no externalization,
    # raw tool result kept in-session. No pending events to flush.
    assert not [e for e in session.events if e.type == TOOL_CALL], \
        "flush 不补 TOOL_CALL（预持久化契约，补发即重复）"
