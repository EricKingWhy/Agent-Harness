"""P0-001 回归：POST /api/sessions/{id}/messages 的 launched SSE 流序列化。

缺陷：send_message 的事件生成器对 AgentEvent 调用了 ``ev.to_dict()``，
而 AgentEvent 没有 ``to_dict()``（只有 SessionEvent 有）。一旦续聊走
launched 直驱新 run，SSE 生成器发射首包时就 AttributeError → 流崩溃。

本测试把会话驱动到可续聊（完成）态，再对 /messages 发续聊，消费完整
launched SSE 流并断言每帧都能被正确解析（即序列化成功、无崩溃）。
修复前该测试红灯（流抛 AttributeError / 空 / 500）；修复后绿灯。

接缝（与 test_web_stream.py 同）：真实 ASGI 服务器 + httpx2 流式客户端
+ ScriptedModel 测试桩（astream 提供确定性 AIMessage 流）。
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from tests.scripted_model import ScriptedModel


class _OneTurnModel(ScriptedModel):
    """每次新 run 都吐一条最终 AIMessage（ScriptedModel 语义：剧本耗尽即报错）。

    create_chat_model 每轮 build_runtime 都会被调用、新建实例，因此首轮与
    续聊轮各自从第一条剧本开始，单条剧本足够。
    """

    def __init__(self) -> None:
        super().__init__([AIMessage(content="task done")])


async def _start_server(tmp_path, monkeypatch):
    import uvicorn

    from agent_harness.config import Settings
    from agent_harness.web.app import create_app

    monkeypatch.setattr(
        "agent_harness.assembly.create_chat_model",
        lambda config, **kw: _OneTurnModel(),
    )
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
    return server, serve_task, port


async def _shutdown(server, serve_task) -> None:
    server.should_exit = True
    serve_task.cancel()
    try:
        await serve_task
    except asyncio.CancelledError:
        pass


def _parse_frame(line: str) -> dict:
    import json
    return json.loads(line.removeprefix("data:").strip())


async def _collect_stream(port: int, method: str, path: str, body: dict | None,
                          stop_types: set[str] | None = None) -> list[dict]:
    """消费 SSE 流到终态；捕获序列化异常以便清晰报出。"""
    import httpx2

    frames: list[dict] = []
    client = httpx2.AsyncClient(timeout=None)
    try:
        if body is not None:
            context = client.stream(method, f"http://127.0.0.1:{port}{path}", json=body)
        else:
            context = client.stream(method, f"http://127.0.0.1:{port}{path}")
        async with context as response:
            assert response.status_code == 200, f"期望 200，实际 {response.status_code}"
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                frame = _parse_frame(line)  # 序列化失败/畸形帧在此抛错 → 红灯
                frames.append(frame)
                if stop_types and frame.get("type") in stop_types:
                    break
    finally:
        await client.aclose()
    return frames


@pytest.mark.asyncio
async def test_send_message_launched_sse_serializes_without_crash(tmp_path, monkeypatch):
    """会话完成后再续聊：launched SSE 流必须被正确序列化，不得 AttributeError。"""
    server, serve_task, port = await _start_server(tmp_path, monkeypatch)
    try:
        # 第一轮：创建会话 → run/completed（流式收集到终态即保证会话空闲）
        first = await _collect_stream(
            port, "POST", "/api/sessions", {"task": "首轮任务"},
            stop_types={"run/completed"})
        assert first, "首轮必须收到 SSE 帧"
        session_id = first[0].get("session_id")
        assert session_id, "首帧应带 session_id"

        # 第二轮：续聊 → launched → SSE 直驱新 run → 必须能消费完整流
        follow = await _collect_stream(
            port, "POST", f"/api/sessions/{session_id}/messages",
            {"content": "继续", "mode": "queue", "max_steps": 10},
            stop_types={"run/completed", "run/failed"})
        assert follow, "续聊 launched 必须收到 SSE 帧（修复前空流/崩溃=红灯）"
        # 每帧都必须能解析为 {type, data, session_id} 形状 → 序列化成功
        for frame in follow:
            assert "type" in frame, f"帧缺少 type: {frame}"
            assert "data" in frame, f"帧缺少 data: {frame}"
        assert follow[-1]["type"] in ("run/completed", "run/failed"), \
            "续聊流必须以终态收尾"

        # different-session 一致性：续聊帧带同一 session_id
        assert all(f.get("session_id") == session_id for f in follow), \
            "续聊帧必须带对应用户会话 id"
    finally:
        await _shutdown(server, serve_task)
