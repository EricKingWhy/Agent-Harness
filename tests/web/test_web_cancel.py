"""T5（ADR-0016 §2.2）：显式取消端点 POST /api/sessions/{id}/cancel。

验收映射（规格 01 §22 场景 E）：取消只发生在显式 POST /cancel——detached-run
下断连不再借道取消臂。语义：在途 → 200 cancelling；无在途 run → 200
no_active_run（幂等成功，前端 Esc 竞态是常态）；session 不存在 → 404。
"""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessageChunk

from agent_harness.session import JsonlSessionStore


class SlowStreamModel:
    """30 chunk × 0.1s = 3s 慢流：取消请求发出时 run 必然在途。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        for i in range(30):
            await asyncio.sleep(0.1)
            yield AIMessageChunk(content=f"chunk{i} ")


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
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, serve_task, port, app


async def _shutdown(server, serve_task) -> None:
    server.should_exit = True
    serve_task.cancel()
    try:
        await serve_task
    except asyncio.CancelledError:
        pass


async def _start_run_and_read_first_delta(port: int) -> str:
    """发起 run，读到一个 text/delta 帧后断开（detached：run 继续在途），
    返回 session_id。"""
    import httpx2

    session_id = None
    client = httpx2.AsyncClient(timeout=None)
    try:
        async with client.stream(
            "POST", f"http://127.0.0.1:{port}/api/sessions",
            json={"task": "慢任务"},
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if '"session_id"' not in line:
                    continue
                frame = json.loads(line.removeprefix("data:").strip())
                session_id = frame.get("session_id")
                if frame.get("type") == "text/delta":
                    break
    finally:
        await client.aclose()
    assert session_id, "未从流中取得 session_id"
    return session_id


async def _wait_for(store: JsonlSessionStore, session_id: str,
                    predicate, deadline_seconds: float = 8.0) -> None:
    async with asyncio.timeout(deadline_seconds):
        while True:
            events = store.read_events(session_id)
            if events and predicate(events):
                return
            await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_cancel_stops_active_run(tmp_path, monkeypatch):
    """在途 run 显式取消 → 200 cancelling + run/failed(reason=cancelled) 落盘。"""
    server, serve_task, port, _app = await _start_server(
        tmp_path, monkeypatch, SlowStreamModel)
    import httpx2

    store = JsonlSessionStore(root=tmp_path / "sessions")
    try:
        session_id = await _start_run_and_read_first_delta(port)
        async with httpx2.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelling"
        await _wait_for(
            store, session_id,
            lambda events: events[-1].type == "run/failed"
            and events[-1].data.get("reason") == "cancelled",
        )
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_cancel_without_active_run_is_idempotent_success(tmp_path, monkeypatch):
    """无在途 run 的取消是幂等成功（200 no_active_run），不是错误。"""
    server, serve_task, port, _app = await _start_server(
        tmp_path, monkeypatch, SlowStreamModel)
    import httpx2

    session_id = await _start_run_and_read_first_delta(port)
    try:
        # 等自然终态后取消 → no_active_run
        completed_store = JsonlSessionStore(root=tmp_path / "sessions")
        await _wait_for(completed_store, session_id,
                        lambda events: events[-1].type == "run/completed")
        async with httpx2.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_active_run"
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_cancel_unknown_session_404(tmp_path, monkeypatch):
    server, serve_task, port, _app = await _start_server(
        tmp_path, monkeypatch, SlowStreamModel)
    import httpx2

    try:
        async with httpx2.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/api/sessions/no-such-session/cancel")
        assert resp.status_code == 404
    finally:
        await _shutdown(server, serve_task)
