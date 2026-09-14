"""HTTP 层 SSE 断连 → detached-run 语义的端到端契约（ADR-0016 §2.1，D-A）。

Phase 9 语义（已修订）：断连取消 run（run/failed(reason=cancelled)）。
ADR-0016 D-A 反转为 **detached-run**：断连只 unsubscribe，run 继续跑到
自然终态——前端 Esc/停止改走显式 `POST /cancel`（见 test_web_cancel.py）。
本文件钉住 HTTP 层反转后的契约，防止装配/中间件层演进时回归。
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import BaseModel

from agent_harness.session import JsonlSessionStore
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint


class SlowStreamModel:
    """20 chunk × 0.1s ≈ 2s 慢流：断连发生时 run 必然在途。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        for i in range(20):
            await asyncio.sleep(0.1)
            yield AIMessageChunk(content=f"chunk{i} ")


class _SlowArgs(BaseModel):
    command: str


class SlowBashTool(Tool):
    """1.5s 慢工具：复现"工具执行中断连"的精确场景（断连期间工具在途）。"""

    def __init__(self, sandbox) -> None:
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "slow bash"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _SlowArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.MUTATING

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.WORKSPACE_WRITE

    @property
    def timeout_seconds(self) -> float:
        return 30.0

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(verifiable=False)

    async def execute(self, args: BaseModel) -> ToolResult:
        await asyncio.sleep(1.5)
        return ToolResult.success("done")


async def _start_server(tmp_path, monkeypatch, model):
    import uvicorn

    from agent_harness.config import Settings
    from agent_harness.web.app import create_app

    monkeypatch.setattr(
        "agent_harness.assembly.create_chat_model", lambda config, **kw: model())
    app = create_app(Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
    ))
    uv_config = uvicorn.Config(app, host="127.0.0.1", port=0,
                               log_level="error", lifespan="on")
    server = uvicorn.Server(uv_config)
    serve_task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "uvicorn 未能在预期时间内启动"
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, serve_task, port


async def _read_until(line_marker: str, port: int) -> None:
    """读 SSE 流直到出现标记帧，然后立刻断开连接——不排空流。"""
    import httpx2

    client = httpx2.AsyncClient(timeout=None)
    try:
        async with client.stream(
            "POST", f"http://127.0.0.1:{port}/api/sessions",
            json={"task": "慢任务"},
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line_marker in line:
                    break
    finally:
        await client.aclose()


async def _wait_for_run_completed(store: JsonlSessionStore,
                                  deadline_seconds: float = 12.0) -> None:
    """断连后 run 必须继续跑到自然终态（run/completed 落盘）。"""
    async with asyncio.timeout(deadline_seconds):
        while True:
            ids = store.list_session_ids()
            if ids:
                events = store.read_events(ids[0])
                if events and events[-1].type == "run/completed":
                    return
            await asyncio.sleep(0.1)


async def _shutdown(server, serve_task) -> None:
    server.should_exit = True
    serve_task.cancel()
    try:
        await serve_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_client_disconnect_mid_run_does_not_cancel(tmp_path, monkeypatch):
    """run 在途（text/delta 已流式）时客户端断连 → run 继续跑到 run/completed。"""
    server, serve_task, port = await _start_server(
        tmp_path, monkeypatch, SlowStreamModel)
    try:
        await _read_until("text/delta", port)
        await _wait_for_run_completed(JsonlSessionStore(root=tmp_path / "sessions"))
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_client_disconnect_during_tool_execution_does_not_cancel(tmp_path, monkeypatch):
    """工具执行中断连 → run 不被取消，跑到自然终态。

    ScriptedModel 先发 tool_call（进入 1.5s 慢工具），断连落在 execute_batch
    在途窗口；detached 语义下 run 继续走完第二个响应（run/completed）。
    """
    scripted = ScriptedToolThenDone()
    server, serve_task, port = await _start_server(
        tmp_path, monkeypatch, lambda: scripted)
    try:
        monkeypatch.setattr("agent_harness.assembly.BashTool", SlowBashTool)
        await _read_until("tool/call", port)
        await _wait_for_run_completed(JsonlSessionStore(root=tmp_path / "sessions"))
    finally:
        await _shutdown(server, serve_task)


class ScriptedToolThenDone:
    """第一轮发 tool_call，第二轮给最终回答。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        if not any(getattr(m, "tool_calls", None) for m in messages):
            yield AIMessage(content="", tool_calls=[{
                "name": "bash", "args": {"command": "slow"}, "id": "call1",
                "type": "tool_call",
            }])
        else:
            yield AIMessageChunk(content="done")
