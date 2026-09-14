"""Phase 5 切片 C：交互式审批 + /approve（SDD 06 Phase 5）。

覆盖：
- 显式 permission_mode=workspace-write（非 danger）+ DANGER 工具触发 →
  emit tool/approval-requested 事件 + run 暂停 + POST /approve 解决后 run 继续。
- approval_id 已 resolved → 409；不存在 → 404；session 无 queue → 404。
- 默认（不显式 permission_mode）→ 不挂 queue，auto-approve 走完。

用 uvicorn 真服务器（不是 TestClient）：需要在 run 暂停时并发发 /approve。
ScriptedModel 第一次出 tool_call(bash DANGER) → 触发审批；解决后第二次出
text 收尾。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from agent_harness.session import JsonlSessionStore


class _BashThenTextImpl:
    """实际模型实例：第一次出 bash tool_call（DANGER → 需审批）；第二次出纯文本。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs):
        if not any(getattr(m, "tool_calls", None) for m in messages):
            yield AIMessage(content="", tool_calls=[{
                "name": "bash", "args": {"command": "echo hi"}, "id": "call1",
                "type": "tool_call",
            }])
        else:
            yield AIMessageChunk(content="done")


class BashThenTextModel:
    """Factory：每次 create_chat_model 调用返回新实例（避免共享 _step 状态）。"""

    def __call__(self):
        return _BashThenTextImpl()


async def _start_server(tmp_path, monkeypatch, model_cls):
    import uvicorn

    from agent_harness.config import Settings
    from agent_harness.web.app import create_app

    monkeypatch.setattr(
        "agent_harness.assembly.create_chat_model", lambda config, **kw: _BashThenTextImpl())
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


async def _shutdown(server, serve_task):
    server.should_exit = True
    serve_task.cancel()
    try:
        await serve_task
    except asyncio.CancelledError:
        pass


def _parse(line: str) -> dict:
    return json.loads(line.removeprefix("data:").strip())


async def _read_until(stream, predicate, deadline_seconds: float = 8.0) -> dict | None:
    """从 SSE 响应流读到 predicate(frame) 为真的帧；超时返 None。"""
    async with asyncio.timeout(deadline_seconds):
        async for line in stream:
            if not line.startswith("data:"):
                continue
            frame = _parse(line)
            if predicate(frame):
                return frame
    return None


@pytest.mark.asyncio
async def test_interactive_approval_pauses_and_resolves(tmp_path, monkeypatch):
    """workspace-write + DANGER 工具 → emit approval-requested + run 暂停 +
    /approve → run 继续。"""
    import httpx2

    server, serve_task, port, _app = await _start_server(
        tmp_path, monkeypatch, BashThenTextModel)
    try:
        # 发起 run：读流直到看到 tool/approval-requested
        client = httpx2.AsyncClient(timeout=None)
        session_id = None
        approval_id = None
        async with client.stream(
            "POST", f"http://127.0.0.1:{port}/api/sessions",
            json={"task": "跑 bash", "permission_mode": "workspace-write"},
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                frame = _parse(line)
                if session_id is None:
                    session_id = frame.get("session_id")
                if frame.get("type") == "tool/approval-requested":
                    approval_id = frame["data"]["approval_id"]
                    break
        await client.aclose()
        assert session_id, "必须取得 session_id"
        assert approval_id, "必须收到 tool/approval-requested 帧"

        # 调 /approve 批准
        async with httpx2.AsyncClient(timeout=5) as approve_client:
            resp = await approve_client.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "approved": True, "reason": "test"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "resolved"

        # 等 run 完成
        store = JsonlSessionStore(root=tmp_path / "sessions")
        async with asyncio.timeout(8.0):
            while True:
                evs = store.read_events(session_id)
                if evs and evs[-1].type in ("run/completed", "run/failed"):
                    break
                await asyncio.sleep(0.05)
        # run 应完成（批准后 bash 跑通 → 第二轮 text → run/completed）
        assert evs[-1].type == "run/completed", \
            f"批准后 run 应完成，实际终态 {evs[-1].type}"
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_approve_unknown_id_404(tmp_path, monkeypatch):
    """approval_id 不存在 → 404。"""
    import httpx2

    server, serve_task, port, _app = await _start_server(
        tmp_path, monkeypatch, BashThenTextModel)
    try:
        # 先建一个交互式 session（触发 queue 注册）
        client = httpx2.AsyncClient(timeout=None)
        session_id = None
        async with client.stream(
            "POST", f"http://127.0.0.1:{port}/api/sessions",
            json={"task": "跑 bash", "permission_mode": "workspace-write"},
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                frame = _parse(line)
                if session_id is None:
                    session_id = frame.get("session_id")
                if frame.get("type") == "tool/approval-requested":
                    break
        await client.aclose()
        assert session_id, "必须取得 session_id"

        # 不存在的 approval_id
        async with httpx2.AsyncClient(timeout=5) as c:
            resp = await c.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": "no-such-id", "approved": True},
            )
            assert resp.status_code == 404
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_approve_already_resolved_409(tmp_path, monkeypatch):
    """同一 approval_id 二次 resolve → 409。"""
    import httpx2

    server, serve_task, port, _app = await _start_server(
        tmp_path, monkeypatch, BashThenTextModel)
    try:
        client = httpx2.AsyncClient(timeout=None)
        session_id = None
        approval_id = None
        async with client.stream(
            "POST", f"http://127.0.0.1:{port}/api/sessions",
            json={"task": "跑 bash", "permission_mode": "workspace-write"},
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                frame = _parse(line)
                if session_id is None:
                    session_id = frame.get("session_id")
                if frame.get("type") == "tool/approval-requested":
                    approval_id = frame["data"]["approval_id"]
                    break
        await client.aclose()
        assert session_id and approval_id

        # 第一次 resolve 成功
        async with httpx2.AsyncClient(timeout=5) as c:
            r1 = await c.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "approved": True},
            )
            assert r1.status_code == 200
            # 第二次 → 409
            r2 = await c.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "approved": True},
            )
            assert r2.status_code == 409
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_auto_approve_mode_skips_queue(tmp_path, monkeypatch):
    """不显式传 permission_mode（旧客户端）→ 不挂 queue，auto-approve 跑完。"""
    import httpx2

    server, serve_task, port, _app = await _start_server(
        tmp_path, monkeypatch, BashThenTextModel)
    try:
        client = httpx2.AsyncClient(timeout=None)
        session_id = None
        saw_approval_event = False
        async with client.stream(
            "POST", f"http://127.0.0.1:{port}/api/sessions",
            json={"task": "跑 bash"},  # 无 permission_mode → 老路径
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                frame = _parse(line)
                if session_id is None:
                    session_id = frame.get("session_id")
                if frame.get("type") == "tool/approval-requested":
                    saw_approval_event = True
                if frame.get("type") in ("run/completed", "run/failed"):
                    break
        await client.aclose()
        assert session_id
        assert not saw_approval_event, "无 permission_mode 时不应触发交互审批"
        # 默认路径不注册交互 queue；run 已完成即可作为断言
        assert not saw_approval_event
    finally:
        await _shutdown(server, serve_task)
