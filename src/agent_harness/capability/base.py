"""Capability seam 核心（spec 08）：Descriptor / Error / 命名 Registry。

Service Definition → Service Provider → Consumer（08 §1）的 Python 化表达。
V1 显式注册（08 §6），不做 entry-point 扫描、不做 Marketplace。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Degradation(str, Enum):
    """Capability 三档降级分类（08 §7 原文）。"""

    REQUIRED_CORE = "REQUIRED_CORE"  # 缺失则 Agent Core 无法启动
    OPTIONAL_RUNTIME = "OPTIONAL_RUNTIME"  # 缺失则功能不可用但基础 Agent 可运行
    OPTIONAL_OBSERVABILITY = "OPTIONAL_OBSERVABILITY"  # 缺失不得影响业务执行


class CapabilityError(RuntimeError):
    """Capability 域显式错误词汇表（08 §2）。降级只能走 optional() 的 None 路径。"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


class CapabilityDescriptor(BaseModel):
    """能力自描述元数据——字段清单为 spec 08 §5 原文 + 本项目两个必需位。

    Phase 2 加法（SDD 03 §17 CapabilityManifest）：display_name / surfaces / actions
    全 Optional，用于 GET /api/capabilities 端点投影 manifest。

    **插件仍可以不填**（未声明 surfaces → 端点按保守默认投影：chat/timeline=true、余 false；
    未声明 actions → 全 false），因为"没说"与"说了没有"该被区分开。
    但**面的可见性不只由插件决定**：`changes`（文件/改动）与 `terminal`（输出）由
    **内置工具**产出，它们不由任何插件产出，所以由恒在的 core 条目声明——
    见 `capability/manifest.py`（#193）。条目形状也只在那边定义一次。
    """

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    risk: str = "low"
    supports_streaming: bool = False
    supports_recovery: bool = False
    supports_concurrency: bool = False
    config_schema: dict[str, Any] = Field(default_factory=dict)
    degradation: Degradation
    enabled: bool = True
    # Phase 2 加法（SDD 03 §17）：UI manifest 投影用。默认 None = 该 capability
    # 不声明 surface/action 覆盖；端点投影时用保守默认（chat/timeline=true，余=false）。
    display_name: str | None = None
    surfaces: dict[str, bool] | None = None
    actions: dict[str, bool] | None = None

    def supports(self, capability: str) -> bool:
        """Consumer 使用前 MUST 检查；不支持必须显式报错（08 §5：不允许静默忽略）。"""
        return capability in self.capabilities


class CapabilityRegistry:
    """命名 Provider Registry（08 §3）。重复注册同名抛错，绝不静默覆盖。"""

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._descriptors: dict[str, CapabilityDescriptor] = {}

    def register(self, descriptor: CapabilityDescriptor, provider: Any) -> None:
        name = descriptor.name
        if name in self._providers:
            raise CapabilityError(
                f"capability '{name}' is already registered "
                f"(provider={self._descriptors[name].provider_name}); "
                "duplicate registration is rejected, not silently overridden",
                code="init_failed",
            )
        self._descriptors[name] = descriptor
        self._providers[name] = provider

    def get(self, name: str) -> Any:
        """按名取 Provider；缺失/停用都显式报错（Consumer 依赖它是硬依赖）。"""
        descriptor = self._descriptors.get(name)
        if descriptor is None:
            raise CapabilityError(f"capability '{name}' is not registered", code="not_found")
        if not descriptor.enabled:
            raise CapabilityError(f"capability '{name}' is disabled by config", code="disabled")
        return self._providers[name]

    def optional(self, name: str) -> Any | None:
        """OPTIONAL 语义（08 §7）：缺失/停用返回 None，由 Consumer 降级。"""
        try:
            return self.get(name)
        except CapabilityError:
            return None

    def descriptor(self, name: str) -> CapabilityDescriptor:
        descriptor = self._descriptors.get(name)
        if descriptor is None:
            raise CapabilityError(f"capability '{name}' is not registered", code="not_found")
        return descriptor

    def available(self) -> list[CapabilityDescriptor]:
        """已注册（含 disabled）的 descriptor 列表，注册顺序稳定。"""
        return list(self._descriptors.values())
