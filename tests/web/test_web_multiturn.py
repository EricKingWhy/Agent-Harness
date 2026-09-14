"""续聊端点 + WebSocket 测试（T2 / #132）。

测试 POST /api/sessions/{id}/messages 续聊端点和 WebSocket /api/ws 基础设施。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent_harness.config import Settings
from agent_harness.web.app import create_app


@pytest.fixture
def app_and_client(tmp_path):
    """创建隔离的 FastAPI app + TestClient。"""
    settings = Settings(
        workspace_dir=str(tmp_path),
        model_api_key="test-key",
        model_name="test-model",
        model_provider="openai",
        enable_cors=True,
    )
    app = create_app(settings)
    client = TestClient(app)
    yield app, client


class TestSendMessageEndpoint:
    """POST /api/sessions/{id}/messages 续聊端点。"""

    def test_messages_endpoint_not_found(self, app_and_client):
        """不存在的 session → 404。"""
        _, client = app_and_client
        response = client.post(
            "/api/sessions/nonexistent-uuid/messages",
            json={"content": "hello", "mode": "queue"},
        )
        assert response.status_code == 404

    def test_messages_endpoint_invalid_mode(self, app_and_client):
        """mode 不合法 → 422。"""
        _, client = app_and_client
        response = client.post(
            "/api/sessions/some-id/messages",
            json={"content": "hello", "mode": "invalid"},
        )
        assert response.status_code == 422

    def test_messages_endpoint_empty_content(self, app_and_client):
        """content 为空 → 422。"""
        _, client = app_and_client
        response = client.post(
            "/api/sessions/some-id/messages",
            json={"content": "", "mode": "queue"},
        )
        assert response.status_code == 422

    def test_messages_endpoint_unsafe_session_id(self, app_and_client):
        """session_id 含反斜杠 → 422（路径逃逸防护）。

        正斜杠在 URL 路径里会被 FastAPI 拆段，测不到校验；
        反斜杠作为单个段传入 → service 层 InvalidSessionId → 422。
        """
        _, client = app_and_client
        response = client.post(
            "/api/sessions/a\\b/messages",
            json={"content": "hello", "mode": "queue"},
        )
        assert response.status_code == 422


class TestQueueCancelEndpoint:
    """POST /api/sessions/{id}/queue/{queue_id}/cancel。"""

    def test_cancel_queue_not_found(self, app_and_client):
        """不存在的 session → 404。"""
        _, client = app_and_client
        response = client.post(
            "/api/sessions/nonexistent/queue/fake-queue-id/cancel",
        )
        assert response.status_code == 404


class TestWebSocketBasics:
    """WebSocket /api/ws 基础设施。"""

    def test_ws_connect_and_ping_pong(self, app_and_client):
        """WS 建连 + ping/pong 心跳。"""
        _, client = app_and_client
        with client.websocket_connect("/api/ws") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "pong"

    def test_ws_subscribe_nonexistent_session(self, app_and_client):
        """subscribe 不存在的 session → error。"""
        _, client = app_and_client
        with client.websocket_connect("/api/ws") as ws:
            ws.send_text(json.dumps({"type": "subscribe", "session_id": "nonexistent"}))
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "error"

    def test_ws_invalid_json(self, app_and_client):
        """非 JSON 消息 → error。"""
        _, client = app_and_client
        with client.websocket_connect("/api/ws") as ws:
            ws.send_text("not json at all")
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "error"
            assert "invalid JSON" in payload["message"]

    def test_ws_unknown_message_type_ignored(self, app_and_client):
        """未知 type → 无响应（不报错，连接保持）。"""
        _, client = app_and_client
        with client.websocket_connect("/api/ws") as ws:
            ws.send_text(json.dumps({"type": "unknown_command"}))
            ws.send_text(json.dumps({"type": "ping"}))
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "pong"


class TestWebSocketMultisession:
    """多会话订阅：单 WS 连接订阅多个 session。"""

    def test_ws_subscribe_multiple_sessions(self, app_and_client):
        """subscribe 两个不存在 session → 两个 error 帧。"""
        _, client = app_and_client
        with client.websocket_connect("/api/ws") as ws:
            ws.send_text(json.dumps({"type": "subscribe", "session_id": "sess-a"}))
            msg1 = ws.receive_text()
            payload1 = json.loads(msg1)
            assert payload1["type"] == "error"

            ws.send_text(json.dumps({"type": "subscribe", "session_id": "sess-b"}))
            msg2 = ws.receive_text()
            payload2 = json.loads(msg2)
            assert payload2["type"] == "error"

    def test_ws_subscribe_then_ping(self, app_and_client):
        """subscribe 后仍可 ping → 连接保持。"""
        _, client = app_and_client
        with client.websocket_connect("/api/ws") as ws:
            ws.send_text(json.dumps({"type": "subscribe", "session_id": "nope"}))
            ws.receive_text()  # error frame

            ws.send_text(json.dumps({"type": "ping"}))
            msg = ws.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "pong"


class TestWebSocketDisconnectCleanup:
    """断开连接后服务端仍可服务新连接（不崩溃）。

    真正的「订阅者归零」断言在 tests/web/test_web_ws_relay.py::
    test_ws_disconnect_cleans_subscriber（需要真实在途 run + RunManager 内部状态）；
    这里只做轻量的连接级 smoke：断开后服务端可继续接受新连接。
    """

    def test_ws_disconnect_does_not_crash(self, app_and_client):
        """WS 断开后服务端不崩溃，可继续接受新连接。"""
        _, client = app_and_client
        with client.websocket_connect("/api/ws") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            ws.receive_text()
        # 断开后再次建连验证服务端仍然正常
        with client.websocket_connect("/api/ws") as ws2:
            ws2.send_text(json.dumps({"type": "ping"}))
            msg = ws2.receive_text()
            payload = json.loads(msg)
            assert payload["type"] == "pong"


class TestCrashReconcileGuard:
    """T8 #138：崩溃遗留（UNKNOWN tool_call）续聊必须 409，不伪造「结果未知」。

    不变量 #13/#14：Ledger reconcile 是唯一恢复入口；UNKNOWN 高风险副作用
    无 ReconcileCallback 时安全拒绝，绝不能落到 Session.resume 的 dangling
    兜底去替模型猜结论。
    """

    def _seed_crashed_unknown(self, app, session_id: str) -> None:
        import asyncio

        from agent_harness.session import Session
        from agent_harness.session.event import TOOL_CALL, USER_MESSAGE
        from agent_harness.storage import Operation, OperationState

        state = app.state.agent
        session = Session.start(state.store, session_id=session_id)
        run_id, _ = session.begin_run()
        session.append(USER_MESSAGE, {"content": "删库"}, run_id=run_id)
        session.append(
            TOOL_CALL,
            {
                "tool_call_id": "call-1",
                "tool_name": "bash",
                "args": {"command": "rm -rf /prod"},
            },
            run_id=run_id,
        )

        async def _seed() -> None:
            await state.ensure_stores()
            await state.operation_ledger.create(Operation(
                tool_call_id="call-1",
                session_id=session_id,
                run_id=run_id,
                agent_id="default",
                tool_name="bash",
                args_identity='{"command": "rm -rf /prod"}',
                state=OperationState.PENDING,
                started_at="2026-09-09T00:00:00+00:00",
            ))
            await state.operation_ledger.update_state(
                session_id, "call-1", OperationState.RUNNING
            )
            await state.operation_ledger.update_state(
                session_id, "call-1", OperationState.UNKNOWN
            )

        asyncio.run(_seed())

    def test_unknown_operation_blocks_continue_with_409(self, app_and_client):
        app, client = app_and_client
        session_id = "crashed-unknown"
        self._seed_crashed_unknown(app, session_id)

        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"content": "继续", "mode": "queue"},
        )

        assert response.status_code == 409
        assert "UNKNOWN" in response.json()["detail"]
        # 拒绝即零伪造：没有合成 tool/result，也没有假的恢复完成标记
        events = app.state.agent.store.read_events(session_id)
        assert not any(e.type == "tool/result" for e in events)
        assert not any(e.type == "session/resumed" for e in events)

    def test_terminal_operation_is_reconciled_then_continue_succeeds(
        self, tmp_path, monkeypatch
    ):
        """Ledger 有终态 → 精确回填后照常续跑（守卫不误伤正常路径）。"""
        import asyncio

        from fastapi.testclient import TestClient
        from langchain_core.messages import AIMessage

        from agent_harness.config import Settings
        from agent_harness.session import Session
        from agent_harness.session.event import TOOL_CALL, USER_MESSAGE
        from agent_harness.storage import Operation, OperationState
        from agent_harness.web.app import create_app
        from tests.scripted_model import ScriptedModel

        monkeypatch.setattr(
            "agent_harness.assembly.create_chat_model",
            lambda config, **kw: ScriptedModel([AIMessage(content="done")]),
        )
        app = create_app(Settings(
            _env_file=None, workspace_dir=str(tmp_path),
            model_api_key="sk-test", model_provider="deepseek",
            model_name="deepseek-chat", enable_cors=False,
        ))
        client = TestClient(app)
        state = app.state.agent
        session_id = "crashed-succeeded"
        session = Session.start(
            state.store,
            session_id=session_id,
            workspace_registry=state.workspace_registry,
        )
        run_id, _ = session.begin_run()
        session.append(USER_MESSAGE, {"content": "跑测试"}, run_id=run_id)
        session.append(
            TOOL_CALL,
            {"tool_call_id": "call-1", "tool_name": "bash", "args": {"command": "pytest"}},
            run_id=run_id,
        )

        async def _seed() -> None:
            await state.ensure_stores()
            await state.operation_ledger.create(Operation(
                tool_call_id="call-1",
                session_id=session_id,
                run_id=run_id,
                agent_id="default",
                tool_name="bash",
                args_identity='{"command": "pytest"}',
                state=OperationState.PENDING,
                started_at="2026-09-09T00:00:00+00:00",
            ))
            await state.operation_ledger.update_state(
                session_id, "call-1", OperationState.RUNNING
            )
            await state.operation_ledger.update_state(
                session_id, "call-1", OperationState.SUCCEEDED
            )

        asyncio.run(_seed())

        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"content": "继续", "mode": "queue"},
        )

        assert response.status_code == 200
        events = app.state.agent.store.read_events(session_id)
        assert any(
            e.type == "tool/result" and e.data["tool_call_id"] == "call-1"
            for e in events
        )


class TestTypedEvents:
    """新 typed SessionEvent 词汇表注册。"""

    def test_new_event_types_in_vocabulary(self):
        """4 个新事件类型都在 EVENT_TYPES 里（durable 词汇表）。"""
        from agent_harness.session.event import EVENT_TYPES

        assert "message/queued" in EVENT_TYPES
        assert "queue/cancelled" in EVENT_TYPES
        assert "steer/requested" in EVENT_TYPES
        assert "steer/applied" in EVENT_TYPES

    def test_new_event_constants_exist(self):
        """常量导出可用。"""
        from agent_harness.session.event import (
            MESSAGE_QUEUED,
            QUEUE_CANCELLED,
            STEER_APPLIED,
            STEER_REQUESTED,
        )

        assert MESSAGE_QUEUED == "message/queued"
        assert QUEUE_CANCELLED == "queue/cancelled"
        assert STEER_REQUESTED == "steer/requested"
        assert STEER_APPLIED == "steer/applied"
