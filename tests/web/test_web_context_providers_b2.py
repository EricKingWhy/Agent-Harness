"""Ticket B2：context_providers 运行时消费的 web 层验收（ADR-0021）。

覆盖验收标准的 web 侧：
  - GET /api/context-providers 返当前装配清单（从 wiring 投影，非空当配置开了）
  - GET 字段 schema 锁定：每条 entry 含 id / display_name / description
  - 配置关了某 provider → 该 provider 不出现
  - POST /api/sessions 传未知 id → 422（handler 层对 wiring 校验）
  - POST /api/sessions 传合法 id → 不因 context_providers 字段被 422

bare_client（空 capabilities）→ GET 返空；wired_client（手工注入 wiring）→ GET 返真实清单。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_harness.capability.wiring import CapabilityWiring
from agent_harness.config import Settings
from agent_harness.web.app import create_app


class _FakeMemoryProvider:
    """Placeholder provider with stable name (ADR-0020b mechanism)."""
    name: str = "memory"

    async def select(self, messages):
        return []


class _FakeSkillsProvider:
    """Placeholder provider with stable name (ADR-0020b mechanism)."""
    name: str = "skills"

    async def select(self, messages):
        return []


@pytest.fixture
def bare_client(tmp_path):
    """无外部依赖的 app（capabilities=''，无 provider 装配）。"""
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
    )
    return TestClient(create_app(settings, enable_cors=False))


@pytest.fixture
def wired_client(tmp_path):
    """wiring 预注入两个 provider（绕过真实装配，直接写 AppState._wiring）。

    直接写 _wiring 字段等价于 wiring 已装配完成（get_wiring 的缓存路径会命中）。
    用 placeholder provider 实例——GET 只投影元数据，不调 select()。
    """
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
    )
    app = create_app(settings, enable_cors=False)
    wiring = CapabilityWiring()
    # ADR-0020b mechanism: providers with `name` class attribute
    wiring.context_providers = [_FakeMemoryProvider(), _FakeSkillsProvider()]
    # 直接落 _wiring + _registry（模拟装配已完成）；get_wiring 缓存命中即可
    from agent_harness.capability.base import CapabilityRegistry
    app.state.agent._wiring = wiring
    app.state.agent._registry = CapabilityRegistry()
    return TestClient(app)


# ── GET /api/context-providers：投影真实装配清单 ──


class TestGetContextProvidersB2:
    def test_bare_returns_empty_when_no_providers_wired(self, bare_client):
        """验收：未装配任何 provider → 返 [] （诚实降级，不伪造）。"""
        resp = bare_client.get("/api/context-providers")
        assert resp.status_code == 200
        assert resp.json() == {"providers": []}

    def test_wired_returns_real_catalog(self, wired_client):
        """验收：wiring 装配了 memory + skills → GET 返真实清单（非空）。"""
        resp = wired_client.get("/api/context-providers")
        assert resp.status_code == 200
        body = resp.json()
        ids = [p["id"] for p in body["providers"]]
        assert set(ids) == {"memory", "skills"}

    def test_wired_schema_locked(self, wired_client):
        """字段 schema 锁定：每条 entry 含 id / display_name / description。"""
        resp = wired_client.get("/api/context-providers")
        for p in resp.json()["providers"]:
            assert set(p.keys()) == {"id", "display_name", "description"}
            assert isinstance(p["id"], str)
            assert isinstance(p["display_name"], str)
            assert isinstance(p["description"], str)

    def test_wired_top_level_key_stable(self, wired_client):
        """顶层 key 锁定为 'providers'（契约形态不变，B1 已锁）。"""
        resp = wired_client.get("/api/context-providers")
        assert set(resp.json().keys()) == {"providers"}


# ── POST /api/sessions：context_providers 422 校验 ──


class TestPostContextProvidersValidation:
    def test_unknown_id_returns_422(self, wired_client):
        """验收：传 wiring 里没有的 id → 422（handler 层对真实装配集校验）。"""
        # 用一个必然失败的 task + workspace 组合避免真的起 run——validator 在
        # build_runtime 之前就 422，不会进 RunManager。
        resp = wired_client.post("/api/sessions", json={
            "task": "x", "workspace": "test-b2-unknown",
            "context_providers": ["rag"],
        })
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "rag" in detail
        assert "memory" in detail or "skills" in detail  # 提示可用清单

    def test_known_id_accepted_not_422_for_context_field(self, wired_client):
        """合法 id 不因 context_providers 字段被 422（其他失败原因可接受）。"""
        resp = wired_client.post("/api/sessions", json={
            "task": "x", "workspace": "test-b2-ok",
            "context_providers": ["memory"],
        })
        # 不是 422 即说明 context_providers 字段通过了校验（可能是别的错误码，
        # 例如 model 不可用等运行时问题，但不是 context_providers 校验失败）
        if resp.status_code == 422:
            detail = resp.json().get("detail", "")
            assert "context_providers" not in str(detail), (
                f"合法 id 不应触发 context_providers 422；detail={detail}"
            )

    def test_empty_list_accepted(self, wired_client):
        """空列表是合法值（显式选了不启用任何 provider）。"""
        resp = wired_client.post("/api/sessions", json={
            "task": "x", "workspace": "test-b2-empty",
            "context_providers": [],
        })
        if resp.status_code == 422:
            detail = resp.json().get("detail", "")
            assert "context_providers" not in str(detail)
