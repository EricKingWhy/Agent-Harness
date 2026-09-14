"""T7（ADR-0016 §5）：多模型 catalog + 会话级模型选择（C6 / D-B②）。

语义：POST /api/sessions 可选 model 参数（不传 = 默认链，现行为不变）；
fallback 链语义不动（ADR-0014）；GET /api/models 列出可选模型（无密钥字段）。
"""

from __future__ import annotations

import json

import pytest

from agent_harness.config import Settings
from agent_harness.model.config import (
    ConfigError,
    ModelConfig,
    find_catalog_entry,
    parse_model_catalog,
)


def _settings(agent_models: str = "", **kwargs) -> Settings:
    return Settings(
        _env_file=None, workspace_dir="/tmp/x", model_api_key="sk-default",
        model_provider="deepseek", model_name="", agent_models=agent_models, **kwargs,
    )


_VALID = json.dumps([
    {"name": "qwen-max", "provider": "senseaudio", "model_name": "qwen3.8-max-0902"},
    {"name": "glm-air", "provider": "zhipu", "model_name": "glm-4.5-air",
     "api_key": "sk-glm", "temperature": 0.5},
])


class TestParseModelCatalog:
    def test_empty_settings_empty_catalog(self):
        assert parse_model_catalog(_settings()) == []

    def test_valid_catalog_parsed(self):
        entries = parse_model_catalog(_settings(_VALID))
        assert [e.name for e in entries] == ["qwen-max", "glm-air"]
        assert entries[0].model_name == "qwen3.8-max-0902"

    def test_invalid_json_loud_error(self):
        with pytest.raises(ConfigError, match="AGENT_MODELS"):
            parse_model_catalog(_settings("{not json"))

    def test_non_list_rejected(self):
        with pytest.raises(ConfigError, match="数组"):
            parse_model_catalog(_settings('{"name": "x"}'))

    def test_unknown_provider_rejected(self):
        with pytest.raises(ConfigError, match="provider"):
            parse_model_catalog(_settings(json.dumps([
                {"name": "x", "provider": "mystery", "model_name": "m"}])))

    def test_duplicate_name_rejected(self):
        with pytest.raises(ConfigError, match="重名|duplicate|name"):
            parse_model_catalog(_settings(json.dumps([
                {"name": "dup", "provider": "deepseek", "model_name": "a"},
                {"name": "dup", "provider": "deepseek", "model_name": "b"}])))


class TestResolveModelConfig:
    def test_unknown_name_raises(self):
        with pytest.raises(ConfigError, match="未知模型"):
            ModelConfig.from_catalog(_settings(_VALID), "no-such")

    def test_entry_overrides_and_fallbacks(self):
        """entry 字段优先；api_key 缺省回落 MODEL_API_KEY；base_url 缺省回落 preset。"""
        config = ModelConfig.from_catalog(_settings(_VALID), "qwen-max")
        assert config.model_name == "qwen3.8-max-0902"
        assert config.provider == "senseaudio"
        assert config.base_url == "https://api.senseaudio.cn/v1"
        assert config.get_secret_value() == "sk-default"
        assert config.temperature == 0.2  # settings 默认

        config2 = ModelConfig.from_catalog(_settings(_VALID), "glm-air")
        assert config2.get_secret_value() == "sk-glm"
        assert config2.temperature == 0.5
        assert config2.base_url == "https://open.bigmodel.cn/api/paas/v4"

    def test_default_chain_unaffected(self):
        """不选模型 = 默认链，行为与旧版逐字段一致。"""
        config = ModelConfig.from_settings(_settings(_VALID))
        assert config.model_name == "deepseek-chat"  # deepseek preset 默认
        assert config.get_secret_value() == "sk-default"


class TestFindCatalogEntry:
    """T7 #137：模型切换按 (provider, model_id) 寻址。"""

    def test_match_by_entry_name(self):
        entry = find_catalog_entry(_settings(_VALID), "senseaudio", "qwen-max")
        assert entry is not None and entry.name == "qwen-max"

    def test_match_by_upstream_model_name(self):
        entry = find_catalog_entry(_settings(_VALID), "zhipu", "glm-4.5-air")
        assert entry is not None and entry.name == "glm-air"

    def test_provider_mismatch_returns_none(self):
        assert find_catalog_entry(_settings(_VALID), "deepseek", "qwen-max") is None

    def test_unknown_returns_none(self):
        assert find_catalog_entry(_settings(_VALID), "zhipu", "nope") is None

    def test_name_match_wins_over_model_name_collision(self):
        """条目 A 的 name 撞上条目 B 的 model_name 时，精确 name 匹配优先。"""
        catalog = json.dumps([
            {"name": "alpha", "provider": "deepseek", "model_name": "beta"},
            {"name": "beta", "provider": "deepseek", "model_name": "alpha"},
        ])
        entry = find_catalog_entry(_settings(catalog), "deepseek", "beta")
        assert entry is not None and entry.name == "beta"
