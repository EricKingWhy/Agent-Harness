"""CAPABILITIES 显式配置解析（spec 08 §6 V1：env JSON，不做 Marketplace）。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from agent_harness.capability.base import CapabilityError


class ProviderConfig(BaseModel):
    """单个 capability 的装配配置。strict 拒绝隐式强转（"yes"→True 之类）。"""

    model_config = {"strict": True}

    provider: str = "builtin"
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)


_CONFIG_ADAPTER = TypeAdapter(dict[str, ProviderConfig])


def parse_capabilities_config(raw: str | None) -> dict[str, ProviderConfig]:
    """解析 env `CAPABILITIES`（JSON 字符串）；空值 = 空 map = 零行为变化。

    形状或内容非法抛 `CapabilityError("init_failed")`——显式失败，绝不静默吞。
    """
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as error:
        raise CapabilityError(f"CAPABILITIES is not valid JSON: {error}", code="init_failed") from None
    try:
        return _CONFIG_ADAPTER.validate_python(data)
    except ValidationError as error:
        # 带上首条具体错误（字段+原因），只报 error_count() 会让用户盲猜哪个键写错。
        first = error.errors()[0]
        raise CapabilityError(
            f"CAPABILITIES config is invalid: {error.error_count()} validation error(s); "
            f"first: {'.'.join(str(loc) for loc in first.get('loc', [])) or '<root>'}: {first.get('msg')}",
            code="init_failed",
        ) from None
