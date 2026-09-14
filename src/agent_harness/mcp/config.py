"""MCP server 配置解析（T1）：schema 校验、${VAR} 秘密间接引用、响亮失败。

设计决策（ADR-0012）：
- server 配置 schema 对齐 Claude Code 形状；**未知字段响亮失败**（ZCode 的
  未知键静默丢弃是最疼的反模式——配置写错是人的错误，必须让人立刻看见）。
- `env`/`headers` 值支持 `${VAR}` / `${VAR:-default}` 进程环境变量展开——
  秘密间接引用（明文 token 不入库，oh-my-pi 同款）；缺失变量显式报错。
- stdio server 启动环境 = OS 必需项白名单 + 配置的 env 项，不继承全量进程
  env（第三方 server 是不可信代码，C2 同款泄漏防线——在 client.py 落地）。
"""

from __future__ import annotations

import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_harness.tooling.contract import ToolPermission

#: MCP 工具输出的字符预算（ADR-0012 决策 8；与 read 工具同一预算哲学）。
MAX_OUTPUT_CHARS = 50_000

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_SECRET_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(ValueError):
    """MCP 配置错误（schema 非法 / ${VAR} 缺失）——wiring 响亮失败 init_failed。"""


class MCPServerConfig(BaseModel):
    """单个 MCP server 的连接与权限配置（ADR-0012 决策 9/5）。"""

    model_config = ConfigDict(extra="forbid")  # 未知字段响亮失败，不静默丢弃

    name: str = Field(..., description="server 名（工具命名空间段）")
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0)
    enabled: bool = True
    # 个别工具的权限覆写（bare tool name → ToolPermission 值）；ADR-0012 决策 5
    tool_permissions: dict[str, ToolPermission] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        # name 会成为工具命名空间段（mcp__{server}__{tool}），禁止分隔符注入
        if not _NAME_PATTERN.fullmatch(value):
            raise ValueError(
                f"server name 只接受字母/数字/_/-（避免与命名分段冲突）：{value!r}"
            )
        return value

    @model_validator(mode="after")
    def _validate_transport_requirements(self) -> MCPServerConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"stdio server '{self.name}' 缺少 command")
        if self.transport == "http" and not self.url:
            raise ValueError(f"http server '{self.name}' 缺少 url")
        return self


def expand_secret_ref(value: str, *, context: str) -> str:
    """展开值内所有 `${VAR}` / `${VAR:-default}` 进程环境变量引用（支持嵌入）。

    秘密间接引用：配置里只写变量名，明文 token 留在进程环境（oh-my-pi 同款）。
    引用缺失且无默认值 → ConfigError 显式报错（缺变量是部署错误，静默替换
    成空串会把坏配置推迟到首次调用才爆）。展开后仍残留 ${...} 形状（空引用 /
    非法变量名 / 嵌套）→ 同样显式报错：typo 的引用静默变成字面量发给远端，
    等于把坏配置伪装成"合法"凭证。
    """

    def _replace(match: re.Match[str]) -> str:
        var, default = match.group(1), match.group(2)
        resolved = os.environ.get(var)
        if resolved is None:
            if default is not None:
                return default
            raise ConfigError(
                f"{context}: 引用的环境变量 {var!r} 未设置（${{{var}}}）"
            )
        return resolved

    expanded = _SECRET_REF.sub(_replace, value)
    residue = re.search(r"\$\{[^}]*\}", expanded)
    if residue:
        raise ConfigError(
            f"{context}: 存在无法展开的引用 {residue.group(0)!r}"
            "（空引用/非法变量名/嵌套引用）；请检查写法或改用 ${VAR:-default}"
        )
    return expanded


def _expand_config_secrets(config: MCPServerConfig) -> MCPServerConfig:
    """对 env/headers 的值做 ${VAR} 展开（ADR-0012：env/headers 是秘密通道）。"""
    expanded_env = {
        key: expand_secret_ref(value, context=f"server '{config.name}' env.{key}")
        for key, value in config.env.items()
    }
    expanded_headers = {
        key: expand_secret_ref(value, context=f"server '{config.name}' headers.{key}")
        for key, value in config.headers.items()
    }
    return config.model_copy(update={"env": expanded_env, "headers": expanded_headers})


def parse_mcp_servers(options: dict[str, Any]) -> list[MCPServerConfig]:
    """解析 capabilities options 里的 servers 列表；所有问题一次性报全。

    schema 非法 → ConfigError（wiring 映射为 init_failed 响亮失败，Q10）；
    disabled 的 server 保留在列表里（enabled 过滤是 wiring 的职责）。
    """
    raw_servers = options.get("servers", [])
    # dict 形状（Claude Code 的配置格式）先于泛型检查单独点名——用户带着别家
    # 配置粘进来时，要告诉他为什么不能直接用，而不是一句泛泛的"必须是列表"。
    if isinstance(raw_servers, dict):
        raise ConfigError(
            "mcp options.servers 必须是列表（dict 形状是 Claude Code 的格式，"
            "本仓用显式列表并以 name 字段为键）"
        )
    if not isinstance(raw_servers, list):
        raise ConfigError(
            f"mcp options.servers 必须是列表，得到 {type(raw_servers).__name__}"
        )

    errors: list[str] = []
    parsed: list[MCPServerConfig] = []
    for index, raw in enumerate(raw_servers):
        if not isinstance(raw, dict):
            errors.append(f"servers[{index}]: 必须是对象，得到 {type(raw).__name__}")
            continue
        try:
            parsed.append(_expand_config_secrets(MCPServerConfig.model_validate(raw)))
        except (ValueError, TypeError) as error:
            # pydantic ValidationError 的 str() 已含全部子错误明细
            name_hint = raw.get("name", f"index-{index}")
            errors.append(f"server '{name_hint}': {error}")
    # 重复 server 名会让命名空间（mcp__{server}__{tool}）与 lifecycle 追踪歧义
    names = [server.name for server in parsed]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"server 名重复: {duplicates}（同名先到先得会静默吞掉后者）")
    if errors:
        raise ConfigError("MCP server 配置错误：\n" + "\n".join(f"- {e}" for e in errors))
    return parsed
