"""Ticket B1：Context / Agent / Reasoning 三档只读清单端点（SDD 03 §10/§16 对齐）。

背景：Phase 5（df03990）已把 reasoning_effort / agent_profile / context_providers
四个字段作为 **staged 契约**接收（API 边界验证通过、运行时记一条 INFO 日志后忽略）。
前端 Phase 2b Composer control row 需要这三个字段的**清单端点**才能做选档 UI。

本测试覆盖三个新端点 × 三条 case：
  ① 正常返回已知值；
  ② 空目录降级（context-providers 当前可能返 []）；
  ③ 字段 schema 锁定（契约形态稳定，前端可放心消费）。

契约形态对齐既有 /api/permission-modes（封闭枚举：{id, display_name, description}）
与 /api/capabilities（动态列表，未装配就是空，不伪造）。Reuse First（§6）。
Scope Lock（§8）：本测试只锁清单端点契约，不验运行时消费（那是独立批次）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_harness.config import Settings
from agent_harness.web.app import create_app


@pytest.fixture
def bare_client(tmp_path):
    """无外部依赖的 app + client（对齐 test_web_phase2_endpoints 的 bare_client）。"""
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        enable_cors=False,
    )
    return TestClient(create_app(settings, enable_cors=False))


# ── GET /api/reasoning-efforts ──


class TestReasoningEfforts:
    def test_returns_three_known_efforts(self, bare_client):
        """返回 Phase 5 validator 已锁定的三个档位：minimal / standard / deep。"""
        resp = bare_client.get("/api/reasoning-efforts")
        assert resp.status_code == 200
        body = resp.json()
        efforts = body["efforts"]
        ids = [e["id"] for e in efforts]
        # 已知值必须完整（与 CreateSessionRequest._validate_reasoning_effort 同集合）
        assert ids == ["minimal", "standard", "deep"]
        for e in efforts:
            assert e["display_name"], "每个 effort 必须有 display_name"
            assert e["description"], "每个 effort 必须有 description"

    def test_schema_locked(self, bare_client):
        """字段 schema 锁定：每条 entry 必须含 id / display_name / description。"""
        resp = bare_client.get("/api/reasoning-efforts")
        body = resp.json()
        for e in body["efforts"]:
            assert set(e.keys()) == {"id", "display_name", "description"}
            assert isinstance(e["id"], str)
            assert isinstance(e["display_name"], str)
            assert isinstance(e["description"], str)

    def test_id_set_matches_validator(self, bare_client):
        """端点返回的 id 集合必须与 POST /api/sessions validator 接受的集合完全一致。
        不多不少——多了会让前端提交一个后端会 422 的值，少了会让前端少一个合法选项。
        """
        resp = bare_client.get("/api/reasoning-efforts")
        ids = {e["id"] for e in resp.json()["efforts"]}
        assert ids == {"minimal", "standard", "deep"}


# ── GET /api/agent-profiles ──


class TestAgentProfiles:
    def test_returns_three_known_profiles(self, bare_client):
        """返回 Phase 5 validator 已锁定的三个 profile：main / coding / research_review。"""
        resp = bare_client.get("/api/agent-profiles")
        assert resp.status_code == 200
        body = resp.json()
        profiles = body["profiles"]
        ids = [p["id"] for p in profiles]
        # 已知值必须完整（与 CreateSessionRequest._validate_agent_profile 同集合）
        assert ids == ["main", "coding", "research_review"]
        for p in profiles:
            assert p["display_name"], "每个 profile 必须有 display_name"
            assert p["description"], "每个 profile 必须有 description"

    def test_schema_locked(self, bare_client):
        """字段 schema 锁定：每条 entry 必须含 id / display_name / description。"""
        resp = bare_client.get("/api/agent-profiles")
        body = resp.json()
        for p in body["profiles"]:
            assert set(p.keys()) == {"id", "display_name", "description"}
            assert isinstance(p["id"], str)
            assert isinstance(p["display_name"], str)
            assert isinstance(p["description"], str)

    def test_id_set_matches_validator(self, bare_client):
        """端点返回的 id 集合必须与 POST /api/sessions validator 接受的集合完全一致。"""
        resp = bare_client.get("/api/agent-profiles")
        ids = {p["id"] for p in resp.json()["profiles"]}
        assert ids == {"main", "coding", "research_review"}


# ── GET /api/context-providers ──


class TestContextProviders:
    def test_empty_by_default_is_honest(self, bare_client):
        """默认未装配任何 context provider → 返回 [] （诚实降级，不伪造）。

        与 /api/capabilities 同原则：没有装配就不编条目，前端据空列表自行 fallback。
        （注意 `/api/capabilities` 现在**不是**空的——它有恒在的 core 条目，见 #193；
        空列表那条路径留给了"真的什么都没装配"的清单端点。）
        """
        resp = bare_client.get("/api/context-providers")
        assert resp.status_code == 200
        body = resp.json()
        # 当前 runtime 尚未装配任何 provider → 诚实返空数组
        assert body == {"providers": []}

    def test_schema_locked(self, bare_client):
        """顶层 key 锁定为 'providers'，值为 list（即便为空）。"""
        resp = bare_client.get("/api/context-providers")
        body = resp.json()
        assert "providers" in body
        assert isinstance(body["providers"], list)

    def test_top_level_key_stable(self, bare_client):
        """顶层 key 契约稳定：'providers'（复数，与 capabilities/modes 同模式）。

        不用 'context_providers' 长名——保持既有端点的短 key 风格（models/modes/
        capabilities/efforts/profiles/providers）。
        """
        resp = bare_client.get("/api/context-providers")
        body = resp.json()
        assert set(body.keys()) == {"providers"}
