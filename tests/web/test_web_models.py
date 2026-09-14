"""T7 web 契约（ADR-0016 §5）：GET /api/models + POST /api/sessions 的 model 参数。"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent_harness.config import Settings
from agent_harness.web.app import create_app
from tests.scripted_model import ScriptedModel

_AGENT_MODELS = (
    '[{"name": "qwen-max", "provider": "senseaudio", "model_name": "qwen3.8-max-0902"}]'
)


@pytest.fixture
def catalog_app(tmp_path):
    # _env_file=None：钉死测试配置，不吃机器 .env（MODEL_NAME/FALLBACK_* 会漂移）
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
        model_provider="deepseek", model_name="deepseek-chat",
        fallback_model_provider="zhipu", fallback_model_name="glm-4.5-air",
        fallback_model_api_key="sk-fallback",
        agent_models=_AGENT_MODELS,
    )
    return create_app(settings, enable_cors=False)


@pytest.fixture
def catalog_client(catalog_app):
    return TestClient(catalog_app)


class TestModelsEndpoint:
    def test_lists_default_and_catalog_without_secrets(self, catalog_client):
        resp = catalog_client.get("/api/models")
        assert resp.status_code == 200
        body = resp.json()
        models = body["models"]
        # 旧字段 alias（向后兼容）
        assert [m["name"] for m in models] == ["deepseek-chat", "qwen-max"]
        assert models[0]["default"] is True and models[1]["default"] is False
        assert models[1]["model"] == "qwen3.8-max-0902"
        assert models[1]["provider"] == "senseaudio"
        # Phase 2 新字段（SDD 03 §16 ModelOption）
        assert [m["id"] for m in models] == ["deepseek-chat", "qwen-max"]
        assert models[0]["is_default"] is True and models[1]["is_default"] is False
        assert all(m["is_available"] is True for m in models)
        assert models[0]["metadata_source"] == "provider_preset"
        assert models[0]["display_name"] == "deepseek-chat"
        serialized = json.dumps(body)
        assert "api_key" not in serialized and "sk-" not in serialized, \
            "模型列表绝不携带密钥字段"

    def test_models_carry_provider_preset_capabilities(self, catalog_client):
        """deepseek preset 已知能力位下发，未知能力位省略（契约：not guessed）。"""
        body = catalog_client.get("/api/models").json()
        deepseek = next(m for m in body["models"] if m["id"] == "deepseek-chat")
        # 已验证的能力位（来自 PROVIDER_PRESETS）
        assert deepseek.get("supports_tools") is True
        assert deepseek.get("context_window") == 64000
        assert deepseek.get("speed_tier") == "fast"
        # 未在 preset 声明的能力位必须不出现在响应里
        assert "supports_vision" not in deepseek, \
            "supports_vision 未在 deepseek preset 声明，不该被猜出来"
        assert "supports_reasoning_summary" not in deepseek

    def test_models_catalog_entry_without_capabilities_falls_back_to_preset(self, catalog_client):
        """catalog 条目不声明能力位 → 回落 preset，metadata_source=provider_preset。"""
        body = catalog_client.get("/api/models").json()
        # qwen-max 的 provider 是 senseaudio（见 _AGENT_MODELS），preset 无能力位声明
        qwen = next(m for m in body["models"] if m["id"] == "qwen-max")
        assert qwen["metadata_source"] == "provider_preset"
        # senseaudio preset 没有任何能力位 → 全部省略
        assert "supports_tools" not in qwen
        assert "context_window" not in qwen

    def test_models_catalog_entry_overrides_preset(self, tmp_path):
        """catalog 条目显式声明能力位 → 覆盖 preset，metadata_source=agent_models。"""
        from agent_harness.config import Settings
        from agent_harness.web.app import create_app

        agent_models = (
            '[{"name": "deepseek-pro", "provider": "deepseek", '
            '"model_name": "deepseek-chat", '
            '"context_window": 128000, "supports_tools": false}]'
        )
        settings = Settings(
            _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test",
            model_provider="deepseek", model_name="deepseek-chat",
            agent_models=agent_models,
        )
        client = TestClient(create_app(settings, enable_cors=False))
        body = client.get("/api/models").json()
        pro = next(m for m in body["models"] if m["id"] == "deepseek-pro")
        assert pro["metadata_source"] == "agent_models"
        assert pro["context_window"] == 128000, "catalog 覆盖 preset"
        assert pro["supports_tools"] is False, "catalog 覆盖 preset"
        # 未在 catalog 条目声明的能力位（speed_tier）回落 preset
        assert pro.get("speed_tier") == "fast"

    def test_models_no_secret_leak_with_capabilities(self, catalog_client):
        """加能力位后序列化仍无密钥泄露（跨字段序列化）。"""
        body = catalog_client.get("/api/models").json()
        serialized = json.dumps(body)
        assert "sk-test" not in serialized
        assert "api_key" not in serialized


class TestSessionModelParam:
    def test_model_selection_reaches_chat_model(self, catalog_client):
        """model 参数命中 catalog → 装配层拿到该 model_name 的配置。"""
        seen: dict = {}

        def fake_factory(config, *, reasoning_effort=None, **kw):
            # build_runtime 对 primary/fallback 各调一次——收集全量，主链取首个
            seen.setdefault("names", []).append(config.model_name)
            return ScriptedModel(responses=[AIMessage(content="ok")])

        with patch("agent_harness.assembly.create_chat_model", side_effect=fake_factory):
            resp = catalog_client.post(
                "/api/sessions", json={"task": "hi", "model": "qwen-max"})
        assert resp.status_code == 200
        assert seen["names"][0] == "qwen3.8-max-0902"
        assert "glm-4.5-air" in seen["names"], "fallback 链不受 model 选择影响（ADR-0014）"

    def test_no_model_param_keeps_default_chain(self, catalog_client):
        """不传 model = 默认链（现行为不变）。"""
        seen: dict = {}

        def fake_factory(config, *, reasoning_effort=None, **kw):
            seen.setdefault("names", []).append(config.model_name)
            return ScriptedModel(responses=[AIMessage(content="ok")])

        with patch("agent_harness.assembly.create_chat_model", side_effect=fake_factory):
            resp = catalog_client.post("/api/sessions", json={"task": "hi"})
        assert resp.status_code == 200
        assert seen["names"][0] == "deepseek-chat"

    def test_unknown_model_422(self, catalog_client):
        with patch("agent_harness.assembly.create_chat_model",
                   return_value=ScriptedModel(responses=[AIMessage(content="ok")])):
            resp = catalog_client.post(
                "/api/sessions", json={"task": "hi", "model": "no-such"})
        assert resp.status_code == 422
        assert "no-such" in resp.text
