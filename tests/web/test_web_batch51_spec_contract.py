"""Batch 5.1：关闭 Phase 5 spec 缺口——审批契约补全（G1/G2/G3 + S2 GC）。

覆盖：
- G2：tool/approval-requested payload 含 spec 必须字段
       （action_type / title / allowed_decisions / tool_call_id）。
- G3：/approve 校验 decision ∈ allowed_decisions；非法 decision → 422；
       decision 不在允许集 → 422。
- G1：/approve resolve 后 JSONL 含 permission/resolved durable 事件
       （审计 trail），可据 approval_id 配对 requested ↔ resolved。
- S2：interactive session 的 approval_queue 在 run 终结后被 GC。
- 兼容：仅传 approved 不传 decision 的旧路径仍然通过（推导）。

与 test_web_phase5_approval.py 共享 uvicorn 真服务器模式（run 需在审批点
暂停，必须并发发 /approve）。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from agent_harness.session import JsonlSessionStore


class _BashThenTextImpl:
    """第一次出 bash tool_call（DANGER → 需审批）；第二次出纯文本收尾。"""

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


async def _await_run_terminated(store, session_id, deadline=8.0):
    """轮询 JSONL 直到看到 run/completed 或 run/failed。"""
    async with asyncio.timeout(deadline):
        while True:
            evs = store.read_events(session_id)
            if evs and evs[-1].type in ("run/completed", "run/failed"):
                return evs
            await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_approval_requested_payload_has_spec_fields(tmp_path, monkeypatch):
    """G2：tool/approval-requested payload 必须含 spec §9 PermissionRequestedData
    的必须字段：action_type / title / allowed_decisions / tool_call_id。
    """
    import httpx2

    server, serve_task, port, _app = await _start_server(
        tmp_path, monkeypatch, BashThenTextModel)
    try:
        client = httpx2.AsyncClient(timeout=None)
        session_id = None
        requested_frame = None
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
                    requested_frame = frame["data"]
                    break
        await client.aclose()

        assert requested_frame is not None, "必须收到 tool/approval-requested"
        # spec 必须字段（03 §9 PermissionRequestedData）
        assert "action_type" in requested_frame, "payload 缺 action_type"
        assert "title" in requested_frame, "payload 缺 title"
        assert "allowed_decisions" in requested_frame, "payload 缺 allowed_decisions"
        assert "tool_call_id" in requested_frame, "payload 缺 tool_call_id"
        # allowed_decisions 必须是列表且含 deny + approve_once（当前支持的子集）
        allowed = requested_frame["allowed_decisions"]
        assert isinstance(allowed, list) and "deny" in allowed and "approve_once" in allowed
        # 批准后清场（让 run 干净结束，避免 serve_task 悬挂）
        store = JsonlSessionStore(root=tmp_path / "sessions")
        async with httpx2.AsyncClient(timeout=5) as ac:
            await ac.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": requested_frame["approval_id"], "approved": True},
            )
        await _await_run_terminated(store, session_id)
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_approve_with_decision_field(tmp_path, monkeypatch):
    """G3：/approve 接受 decision=approve_once 并 resolve；返回体含 decision。"""
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
        assert approval_id

        store = JsonlSessionStore(root=tmp_path / "sessions")
        async with httpx2.AsyncClient(timeout=5) as ac:
            resp = await ac.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "decision": "approve_once"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "resolved"
            assert body["decision"] == "approve_once"

        await _await_run_terminated(store, session_id)
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_approve_rejects_disallowed_decision(tmp_path, monkeypatch):
    """G3：decision 不在 requested 事件的 allowed_decisions 内 → 422。
    当前 allowed = [deny, approve_once]，传 approve_session → 422。
    """
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
        assert approval_id

        async with httpx2.AsyncClient(timeout=5) as ac:
            resp = await ac.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "decision": "approve_session"},
            )
            assert resp.status_code == 422

        # 清场：合法批准让 run 收尾
        store = JsonlSessionStore(root=tmp_path / "sessions")
        async with httpx2.AsyncClient(timeout=5) as ac:
            await ac.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "approved": True},
            )
        await _await_run_terminated(store, session_id)
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_approve_invalid_decision_string_422(tmp_path, monkeypatch):
    """G3：decision 不是合法 PermissionDecision 字符串 → 422。"""
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
        assert approval_id

        async with httpx2.AsyncClient(timeout=5) as ac:
            resp = await ac.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "decision": "bogus"},
            )
            assert resp.status_code == 422

        store = JsonlSessionStore(root=tmp_path / "sessions")
        async with httpx2.AsyncClient(timeout=5) as ac:
            await ac.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "approved": True},
            )
        await _await_run_terminated(store, session_id)
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_permission_resolved_event_in_jsonl(tmp_path, monkeypatch):
    """G1：/approve resolve 后 JSONL 含 permission/resolved durable 事件；
    可据 approval_id 把 requested ↔ resolved 配对（审计 trail）。
    """
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

        store = JsonlSessionStore(root=tmp_path / "sessions")
        async with httpx2.AsyncClient(timeout=5) as ac:
            await ac.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "decision": "deny",
                      "reason": "test deny"},
            )
        evs = await _await_run_terminated(store, session_id)

        # 审计 trail：找到 requested 与 resolved，approval_id 一致
        requested = [e for e in evs if e.type == "tool/approval-requested"]
        resolved = [e for e in evs if e.type == "permission/resolved"]
        assert len(requested) >= 1, "JSONL 必须含 tool/approval-requested"
        assert len(resolved) >= 1, "JSONL 必须含 permission/resolved（审计 trail）"
        assert resolved[0].data["approval_id"] == approval_id
        assert resolved[0].data["decision"] == "deny"
        assert resolved[0].data["reason"] == "test deny"
        # run 被拒后应失败（bash 被拒 → 无 tool_call 配对 → run 收尾）
        assert evs[-1].type == "run/completed"
    finally:
        await _shutdown(server, serve_task)


@pytest.mark.asyncio
async def test_approval_queue_gc_after_run_completes(tmp_path, monkeypatch):
    """S2：interactive session 的 approval_queue 在 run 终结后被 GC。
    run/completed 之后 AppState.approval_queues 不应再持有该 session 的 queue。
    """
    import httpx2

    server, serve_task, port, app = await _start_server(
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

        # run 暂停时 queue 必然存在
        state = app.state.agent
        assert session_id in state.approval_queues, "run 暂停时 queue 必须存在"

        store = JsonlSessionStore(root=tmp_path / "sessions")
        async with httpx2.AsyncClient(timeout=5) as ac:
            await ac.post(
                f"http://127.0.0.1:{port}/api/sessions/{session_id}/approve",
                json={"approval_id": approval_id, "approved": True},
            )
        await _await_run_terminated(store, session_id)

        # done_callback 在 task 终结后被事件循环调度，可能在 JSONL 落盘之后
        # 才执行——给事件循环一小段宽限让它跑完。
        await asyncio.sleep(0.1)

        # run 终结后 queue 应被 GC（不泄漏）
        assert session_id not in state.approval_queues, \
            "run 终结后 approval_queue 必须被 GC（防泄漏）"
    finally:
        await _shutdown(server, serve_task)
