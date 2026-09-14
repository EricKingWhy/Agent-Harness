"""MCP server 配置解析（T1）：schema 响亮失败 + ${VAR} 秘密间接引用。"""

import pytest

from agent_harness.mcp import ConfigError, parse_mcp_servers
from agent_harness.tooling.contract import ToolPermission


def _stdio(**overrides):
    base = {"name": "local", "transport": "stdio", "command": "npx", "args": ["-y", "fake"]}
    base.update(overrides)
    return base


def _http(**overrides):
    base = {"name": "remote", "transport": "http", "url": "https://example.com/mcp"}
    base.update(overrides)
    return base


class TestParseServers:
    def test_valid_stdio_and_http_with_defaults(self):
        servers = parse_mcp_servers({"servers": [_stdio(), _http()]})
        assert [s.name for s in servers] == ["local", "remote"]
        assert all(s.timeout_seconds == 30.0 for s in servers)
        assert all(s.enabled for s in servers)
        assert servers[0].args == ["-y", "fake"]

    def test_empty_servers_list_is_valid(self):
        assert parse_mcp_servers({}) == []

    def test_servers_must_be_list_not_dict(self):
        with pytest.raises(ConfigError, match="必须是列表"):
            parse_mcp_servers({"servers": {"github": {}}})

    def test_dict_shape_error_names_claude_code_format(self):
        """dict 形状的专属报错必须可达：用户带着 Claude Code 配置来时，
        要告诉他为什么不能直接粘，而不是收到一句泛泛的"必须是列表"。"""
        with pytest.raises(ConfigError, match="Claude Code"):
            parse_mcp_servers({"servers": {"github": {}}})

    def test_non_dict_entry_is_reported(self):
        with pytest.raises(ConfigError, match=r"servers\[0\]"):
            parse_mcp_servers({"servers": ["nope"]})

    def test_stdio_requires_command(self):
        with pytest.raises(ConfigError, match="local"):
            parse_mcp_servers({"servers": [{"name": "local", "transport": "stdio"}]})

    def test_http_requires_url(self):
        with pytest.raises(ConfigError, match="remote"):
            parse_mcp_servers({"servers": [{"name": "remote", "transport": "http"}]})

    def test_unknown_transport_rejected(self):
        with pytest.raises(ConfigError, match="remote"):
            parse_mcp_servers({"servers": [_http(transport="sse")]})

    def test_unknown_keys_fail_loud_not_silent(self):
        """ZCode 反模式防线：未知字段必须响亮报错，不静默丢弃。"""
        with pytest.raises(ConfigError, match="local"):
            parse_mcp_servers({"servers": [_stdio(typoe="typo-key")]})

    def test_invalid_name_rejected(self):
        with pytest.raises(ConfigError, match="name"):
            parse_mcp_servers({"servers": [_stdio(name="a/b")]})

    def test_all_errors_reported_in_one_pass(self):
        with pytest.raises(ConfigError) as excinfo:
            parse_mcp_servers({"servers": [_stdio(name="ok cmd missing: no"), _stdio()]})
        # 每个坏 server 都在错误信息里（一次性报全，不来回改配置）
        assert "ok cmd missing: no" in str(excinfo.value)


class TestSecretRefs:
    def test_env_and_headers_expand_from_process_env(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "tok-123")
        servers = parse_mcp_servers({"servers": [
            _http(headers={"Authorization": "Bearer ${MY_TOKEN}"}),
            _stdio(env={"API_KEY": "${MY_TOKEN}"}),
        ]})
        assert servers[0].headers["Authorization"] == "Bearer tok-123"
        assert servers[1].env["API_KEY"] == "tok-123"

    def test_default_value_form(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        servers = parse_mcp_servers({"servers": [
            _stdio(env={"X": "${MISSING_VAR:-fallback}"})],
        })
        assert servers[0].env["X"] == "fallback"

    def test_missing_var_without_default_fails_loud(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(ConfigError, match="MISSING_VAR"):
            parse_mcp_servers({"servers": [
                _stdio(env={"API_KEY": "${MISSING_VAR}"})],
            })

    def test_plain_values_pass_through(self):
        servers = parse_mcp_servers({"servers": [_stdio(env={"PLAIN": "value-$not-a-ref"})]})
        assert servers[0].env["PLAIN"] == "value-$not-a-ref"

    def test_malformed_refs_fail_loud_not_silent(self):
        """空引用/嵌套引用等畸形 ${...}：响亮报错而不是把字面残渣发给
        远端（typo 的 token 会静默变成 'Bearer ${}'，坏配置推迟到首次调用）。"""
        for bad in ("${}", "${A${B}}", "${1ABC}"):
            with pytest.raises(ConfigError, match=r"\$\{"):
                parse_mcp_servers({"servers": [_stdio(env={"X": bad})]})


class TestPermissionOverrides:
    def test_tool_permissions_parsed_as_enum(self):
        servers = parse_mcp_servers({"servers": [
            _stdio(tool_permissions={"write_file": "workspace-write"}),
        ]})
        assert servers[0].tool_permissions == {
            "write_file": ToolPermission.WORKSPACE_WRITE,
        }

    def test_invalid_permission_value_rejected(self):
        with pytest.raises(ConfigError, match="local"):
            parse_mcp_servers({"servers": [
                _stdio(tool_permissions={"write_file": "admin"}),
            ]})


def test_disabled_servers_still_parsed():
    """enabled 过滤是 wiring 的职责，解析层保留（声明与生效分离）。"""
    servers = parse_mcp_servers({"servers": [_stdio(enabled=False)]})
    assert servers[0].enabled is False


def test_duplicate_server_names_rejected():
    """重复 server 名响亮拒绝：命名空间与 lifecycle 追踪都会歧义。"""
    with pytest.raises(ConfigError, match="重复"):
        parse_mcp_servers({"servers": [_stdio(), _stdio()]})
