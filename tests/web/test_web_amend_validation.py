"""P1 回归：``/resume`` 与 ``/messages`` 的 amend 校验对齐 create 路径（未知值 → 422）。

背景（docs/HANDOFF_FRONTEND_TECH_DEBT.md §5 P1）：Q2 让这两个端点开始透传
amend 字段，但没有 create 路径的三道校验——未知 ``model`` / ``agent_profile``
会在 ``build_runtime`` 抛未捕获异常 → **500**，未知 ``context_providers``
被静默跳过。本文件锁定 422 语义（与 ``POST /api/sessions`` 一致），
并锁定合法值不被过度拒绝。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent_harness.capability.wiring import CapabilityWiring
from agent_harness.config import Settings
from agent_harness.session.service import (
    AmendOptions,
    SendMessageResult,
    SessionService,
)
from agent_harness.web.app import create_app

#: 合法 model 需要真实 catalog 条目（provider 必须是内置 preset）。
_CATALOG_JSON = '[{"name": "gpt-4o", "provider": "deepseek", "model_name": "gpt-4o-mini"}]'


class _FakeMemoryProvider:
    """带稳定 name 的占位 provider（ADR-0020b 机制）。"""

    name: str = "memory"

    async def select(self, messages):
        return []


@pytest.fixture
def bare_client(tmp_path):
    """无 provider 装配的 app（任何 context_providers id 都是未知）。"""
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", agent_models=_CATALOG_JSON,
        enable_cors=False,
    )
    return TestClient(create_app(settings, enable_cors=False))


@pytest.fixture
def wired_client(tmp_path):
    """预注入一个 provider（memory）的 app——用于合法 id 的正向用例。"""
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
    )
    app = create_app(settings, enable_cors=False)
    wiring = CapabilityWiring()
    wiring.context_providers = [_FakeMemoryProvider()]
    from agent_harness.capability.base import CapabilityRegistry

    app.state.agent._wiring = wiring
    app.state.agent._registry = CapabilityRegistry()
    return TestClient(app)


# ── POST /api/sessions/{id}/messages ──────────────────────────────────


class TestSendMessageAmendValidation:
    """``/messages`` 的 amend 未知值 → 422（不是 500 / 静默忽略）。"""

    def test_unknown_reasoning_effort_422(self, bare_client):
        resp = bare_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "reasoning_effort": "nope"},
        )
        assert resp.status_code == 422

    def test_unknown_agent_profile_422(self, bare_client):
        resp = bare_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "agent_profile": "nope"},
        )
        assert resp.status_code == 422

    def test_unknown_context_provider_422(self, bare_client):
        resp = bare_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "context_providers": ["rag"]},
        )
        assert resp.status_code == 422
        assert "rag" in str(resp.json()["detail"])

    def test_unknown_model_422_not_500(self, bare_client):
        """回归：曾经 build_runtime 抛 ConfigError → 500。"""
        resp = bare_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "model": "definitely-not-a-model"},
        )
        assert resp.status_code == 422

    def test_valid_agent_profile_not_rejected(self, bare_client):
        """合法档位通过校验 → 走到 service（session 不存在 → 404，不是 422）。"""
        resp = bare_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "agent_profile": "coding"},
        )
        assert resp.status_code == 404

    def test_valid_context_provider_not_rejected(self, wired_client):
        """wiring 里存在的 id 通过校验 → 走到 service（404，不是 422）。"""
        resp = wired_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "context_providers": ["memory"]},
        )
        assert resp.status_code == 404

    def test_valid_model_not_rejected(self, bare_client):
        """catalog 里存在的 model 通过校验 → 走到 service（404，不是 422）。"""
        resp = bare_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "model": "gpt-4o"},
        )
        assert resp.status_code == 404

    def test_steer_ignores_amend_not_validated(self, bare_client):
        """契约 §3.1/P3：steer 不消费 amend → 未知 model 不触发 422。

        走到 service 后因 session 不存在返回 404——足以证明 amend 未被校验。
        """
        resp = bare_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "mode": "steer", "model": "definitely-not-a-model"},
        )
        assert resp.status_code == 404

    def test_queued_with_active_run_ignores_amend(self, bare_client, monkeypatch):
        """在途 run 的 queued 消息：amend 未被消费 → 按契约丢弃为全 None。"""
        captured: dict = {}

        async def fake_send(self, **kwargs):
            captured.update(kwargs)
            return SendMessageResult(
                status="queued", queued_message=SimpleNamespace(queue_id="q-1")
            )

        monkeypatch.setattr(SessionService, "send_message", fake_send)
        monkeypatch.setattr(
            bare_client.app.state.agent.run_manager,
            "get_active",
            lambda sid: object(),  # 在途 run 存在
        )
        resp = bare_client.post(
            "/api/sessions/sid-1/messages",
            json={"content": "hi", "model": "definitely-not-a-model"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "queued", "queue_id": "q-1"}
        assert captured["amend"] == AmendOptions()


# ── POST /api/sessions/{id}/resume ────────────────────────────────────


class TestResumeAmendValidation:
    """``/resume`` 的 amend 未知值 → 422（与 /messages 同语义）。"""

    def test_unknown_reasoning_effort_422(self, bare_client):
        resp = bare_client.post(
            "/api/sessions/sid-1/resume",
            json={"task": "go", "reasoning_effort": "nope"},
        )
        assert resp.status_code == 422

    def test_unknown_agent_profile_422(self, bare_client):
        resp = bare_client.post(
            "/api/sessions/sid-1/resume",
            json={"task": "go", "agent_profile": "nope"},
        )
        assert resp.status_code == 422

    def test_unknown_context_provider_422(self, bare_client):
        resp = bare_client.post(
            "/api/sessions/sid-1/resume",
            json={"task": "go", "context_providers": ["rag"]},
        )
        assert resp.status_code == 422
        assert "rag" in str(resp.json()["detail"])

    def test_unknown_model_422_not_500(self, bare_client):
        resp = bare_client.post(
            "/api/sessions/sid-1/resume",
            json={"task": "go", "model": "definitely-not-a-model"},
        )
        assert resp.status_code == 422

    def test_valid_agent_profile_not_rejected(self, bare_client):
        resp = bare_client.post(
            "/api/sessions/sid-1/resume",
            json={"task": "go", "agent_profile": "coding"},
        )
        assert resp.status_code == 404

    def test_valid_model_not_rejected(self, bare_client):
        """catalog 里存在的 model 通过校验 → 走到 service（404，不是 422）。"""
        resp = bare_client.post(
            "/api/sessions/sid-1/resume",
            json={"task": "go", "model": "gpt-4o"},
        )
        assert resp.status_code == 404
