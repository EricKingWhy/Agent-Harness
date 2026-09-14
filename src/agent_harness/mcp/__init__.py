"""MCP Client 能力（Phase 8，ADR-0012）。

MCP = 一种 Capability Provider：server 配置进 CAPABILITIES env JSON，
discovery 在 wiring 时执行，tool 贡献进 ToolRegistry（统一 Executor 路径，
零旁路——不变量 #7）；server 不可达按 OPTIONAL_RUNTIME 降级（不变量 #21）。
角色只有 Client（spec 09 冻结）；V1 只做 tools 原语。
"""

from agent_harness.mcp.config import (
    MAX_OUTPUT_CHARS,
    ConfigError,
    MCPServerConfig,
    expand_secret_ref,
    parse_mcp_servers,
)

__all__ = [
    "MAX_OUTPUT_CHARS",
    "ConfigError",
    "MCPServerConfig",
    "expand_secret_ref",
    "parse_mcp_servers",
]
