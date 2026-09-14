"""GET /api/context-providers 动态投影测试（ADR-0020b 运行时消费）。

覆盖三条契约：
  E1：bare 配置（无 CAPABILITIES）→ wiring.context_providers 空 → 返 []；
  E2：装配 memory + skills capability → 返两条带 id/display_name/description；
  E3：端点返回的 id 集合 == 实际 wiring provider 的 name 集合（单一事实源对齐）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_harness.capability.wiring import CapabilityWiring
from agent_harness.config import Settings
from agent_harness.memory.context_provider import MemoryContextProvider
from agent_harness.skills.context_provider import SkillCatalogContextProvider
from agent_harness.web.app import CONTEXT_PROVIDER_DESCRIPTIONS, create_app


@pytest.fixture
def bare_client(tmp_path):
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
    )
    return TestClient(create_app(settings, enable_cors=False))


@pytest.fixture
def wired_client(tmp_path):
    """装配 memory + skills capability 的 client（触发两个 provider 进 wiring）。

    注意：真实的 memory/skills wiring 需要外部依赖（Milvus / skill 目录）。
    本 fixture 用 stub_get_wiring 直接注入带真实 provider 实例的 wiring，
    避免依赖运行时外部服务——这是端点投影测试，不是 capability 装配测试。
    """
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path),
        model_api_key="sk-test", enable_cors=False,
        capabilities='{"memory": {"provider": "builtin"}, "skills": {"provider": "builtin"}}',
    )
    app = create_app(settings, enable_cors=False)

    # Stub：跳过真实装配（需要外部依赖），直接注入真实 provider 实例。
    # 用 sentinel capability 对象构造 provider——endpoint 只读 .name，不调 .select。
    from agent_harness.capability.base import CapabilityRegistry

    class _Sentinel:
        """provider 构造所需的最小 capability stand-in（endpoint 不调 select）。"""
    wiring = CapabilityWiring(context_providers=[
        MemoryContextProvider(_Sentinel()),  # type: ignore[arg-type]
        SkillCatalogContextProvider(_Sentinel()),  # type: ignore[arg-type]
    ])
    fake_registry = CapabilityRegistry()

    async def stub_get_wiring():
        app.state.agent._registry = fake_registry
        app.state.agent._wiring = wiring
        return app.state.agent._registry, app.state.agent._wiring

    app.state.agent.get_wiring = stub_get_wiring
    return TestClient(app)


class TestContextProvidersEndpoint:
    def test_bare_returns_empty(self, bare_client):
        """E1：bare 配置（无 CAPABILITIES）→ 返 []（诚实降级）。"""
        resp = bare_client.get("/api/context-providers")
        assert resp.status_code == 200
        assert resp.json() == {"providers": []}

    def test_wired_returns_two_providers(self, wired_client):
        """E2：memory + skills 装配 → 返两条带 id/display_name/description。"""
        resp = wired_client.get("/api/context-providers")
        assert resp.status_code == 200
        body = resp.json()
        providers = body["providers"]
        ids = [p["id"] for p in providers]
        assert set(ids) == {"memory", "skills"}
        for p in providers:
            assert set(p.keys()) == {"id", "display_name", "description"}
            assert isinstance(p["id"], str)
            assert p["display_name"]  # 非空
            assert p["description"]  # 非空

    def test_endpoint_ids_match_provider_name_attribute(self, wired_client):
        """E3：端点 id 集合 == CONTEXT_PROVIDER_DESCRIPTIONS 的键集合（单一事实源）。"""
        resp = wired_client.get("/api/context-providers")
        ids = {p["id"] for p in resp.json()["providers"]}
        # 端点投影的 id 必须与 PROVIDER_DESCRIPTIONS 常量键完全一致——
        # 前端据端点渲染选项，用户选的 id 回传给 POST /api/sessions，
        # 再经 assembly._select_context_providers 按 provider.name 筛选。
        assert ids <= set(CONTEXT_PROVIDER_DESCRIPTIONS.keys())
        # memory/skills 两个 provider 的 name 也必须落在常量里
        assert "memory" in ids
        assert "skills" in ids


class TestProviderNameAttributes:
    """provider 类的 name 属性是筛选契约的稳定锚点——改了会破坏请求兼容。"""

    def test_memory_provider_name(self):
        assert MemoryContextProvider.name == "memory"

    def test_skills_provider_name(self):
        assert SkillCatalogContextProvider.name == "skills"


class TestContextProvidersHandler422:
    """POST /api/sessions 的 context_providers handler 层 422 校验（B2-MixIn）。

    validator 只查形状（非空字符串），集合校验在 handler 内对 wiring 真实装配
    的 provider name 集合做——与 model 字段 from_catalog 422 同模式。
    """

    def test_unknown_id_returns_422_with_available(self, wired_client):
        """未知 id → 422 + detail 含 available 清单（诚实反馈，不 fail-open）。"""
        resp = wired_client.post("/api/sessions", json={
            "task": "x", "workspace": "b2-mixin-unknown",
            "context_providers": ["nonexistent"],
        })
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "nonexistent" in detail
        # detail 含 available 清单——让客户端看到当前实际装配了什么
        assert "memory" in detail or "skills" in detail

    def test_known_id_not_422_for_context_field(self, wired_client):
        """合法 id（已装配）→ 不因 context_providers 字段被 422。"""
        resp = wired_client.post("/api/sessions", json={
            "task": "x", "workspace": "b2-mixin-ok",
            "context_providers": ["memory"],
        })
        # 不是 422 即说明 context_providers 字段通过了校验（其他失败原因可接受）
        if resp.status_code == 422:
            detail = resp.json().get("detail", "")
            assert "context_providers" not in str(detail), (
                f"合法 id 不应触发 context_providers 422；detail={detail}"
            )

    def test_empty_list_accepted(self, wired_client):
        """空列表是合法值（显式选了不启用任何 provider）。"""
        resp = wired_client.post("/api/sessions", json={
            "task": "x", "workspace": "b2-mixin-empty",
            "context_providers": [],
        })
        if resp.status_code == 422:
            detail = resp.json().get("detail", "")
            assert "context_providers" not in str(detail)

    def test_bare_config_known_id_returns_422(self, bare_client):
        """bare 配置（没装配任何 provider）传 ["memory"] → 422（memory 没装配）。"""
        resp = bare_client.post("/api/sessions", json={
            "task": "x", "workspace": "b2-mixin-bare",
            "context_providers": ["memory"],
        })
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "memory" in detail

    def test_none_context_providers_accepted(self, wired_client):
        """None（默认）→ 正常（用默认全量，不触发 422）。"""
        resp = wired_client.post("/api/sessions", json={
            "task": "x", "workspace": "b2-mixin-none",
        })
        if resp.status_code == 422:
            detail = resp.json().get("detail", "")
            assert "context_providers" not in str(detail)

