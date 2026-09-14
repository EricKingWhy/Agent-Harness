"""Q2 spec tests: amend 字段经 HTTP 端点透传到 ``SessionService``。

spec 要求（docs/TECH_DEBT_FIX_SPEC.md §Q2）：
  - 验证 ``POST /api/sessions/{id}/resume`` 带 amend 字段时正确透传

接缝：patch ``SessionService.resume_and_launch`` 捕获调用参数，再抛
``ActiveRunConflict`` 让请求以 409 收束——避免在单元测试里拉起真实 run /
消费 SSE 流。断言点是「端点确实把请求体的 amend 字段组装成 AmendOptions
并原样传入 service」，这正是 Q2 要防的回归（新增字段只加在 Pydantic 模型上
却忘了接线）。P1 之后端点会先校验 amend（未知值 → 422），故 fixture 备好
真实 catalog 条目与 memory provider，让合法值能走到接缝。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_harness.capability.wiring import CapabilityWiring
from agent_harness.config import Settings
from agent_harness.session.service import (
    ActiveRunConflict,
    AmendOptions,
    SessionService,
)
from agent_harness.web.app import create_app

#: 合法 amend 取值需要真实 catalog 条目 + 已装配 provider（P1 校验之后，
#: 端点不再放行未知值——透传测试必须用合法值才能走到 service 接缝）。
_CATALOG_JSON = '[{"name": "gpt-4o", "provider": "deepseek", "model_name": "gpt-4o-mini"}]'


class _FakeMemoryProvider:
    name: str = "memory"

    async def select(self, messages):
        return []


@pytest.fixture
def app_and_client(tmp_path):
    """创建隔离的 FastAPI app + TestClient（catalog + memory provider 就位）。"""
    settings = Settings(
        workspace_dir=str(tmp_path),
        model_api_key="test-key",
        model_name="test-model",
        model_provider="openai",
        agent_models=_CATALOG_JSON,
        enable_cors=True,
    )
    app = create_app(settings)
    wiring = CapabilityWiring()
    wiring.context_providers = [_FakeMemoryProvider()]
    from agent_harness.capability.base import CapabilityRegistry

    app.state.agent._wiring = wiring
    app.state.agent._registry = CapabilityRegistry()
    client = TestClient(app)
    yield app, client


class TestResumeEndpointAmendPassthrough:
    """POST /api/sessions/{id}/resume 透传 amend 字段。"""

    def test_resume_endpoint_forwards_amend(self, app_and_client, monkeypatch):
        """请求体四个 amend 字段 → AmendOptions 原样传给 resume_and_launch。"""
        captured: dict = {}

        async def fake_resume(self, **kwargs):
            captured.update(kwargs)
            raise ActiveRunConflict("already active")

        monkeypatch.setattr(SessionService, "resume_and_launch", fake_resume)
        _, client = app_and_client

        response = client.post(
            "/api/sessions/test-sid/resume",
            json={
                "task": "继续",
                "reasoning_effort": "deep",
                "agent_profile": "coding",
                "context_providers": ["memory"],
                "model": "gpt-4o",
            },
        )

        assert response.status_code == 409
        assert captured["session_id"] == "test-sid"
        assert captured["task"] == "继续"
        assert captured["amend"] == AmendOptions(
            reasoning_effort="deep",
            agent_profile="coding",
            context_providers=["memory"],
            model="gpt-4o",
        )

    def test_resume_endpoint_without_amend_sends_all_none(
        self, app_and_client, monkeypatch
    ):
        """不传 amend 字段 → AmendOptions 全 None（当前行为不变）。"""
        captured: dict = {}

        async def fake_resume(self, **kwargs):
            captured.update(kwargs)
            raise ActiveRunConflict("already active")

        monkeypatch.setattr(SessionService, "resume_and_launch", fake_resume)
        _, client = app_and_client

        response = client.post(
            "/api/sessions/test-sid/resume",
            json={"task": "继续"},
        )

        assert response.status_code == 409
        assert captured["amend"] == AmendOptions()
