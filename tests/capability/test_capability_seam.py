"""T1：CapabilityDescriptor / CapabilityError / CapabilityRegistry（spec 08 §2/§3/§5/§7）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_harness.capability.base import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityRegistry,
    Degradation,
)


def _descriptor(**overrides) -> CapabilityDescriptor:
    fields = {
        "name": "memory", "version": "1.0.0", "provider_name": "langmem",
        "capabilities": ["store", "search"], "risk": "low",
        "degradation": Degradation.OPTIONAL_RUNTIME,
    }
    fields.update(overrides)
    return CapabilityDescriptor(**fields)


class TestDescriptor:
    def test_spec08_field_list_roundtrip(self):
        d = _descriptor(supports_streaming=True, supports_recovery=False,
                        supports_concurrency=True, config_schema={"a": "int"})
        assert d.name == "memory" and d.provider_name == "langmem"
        assert d.capabilities == ["store", "search"]
        assert d.supports_streaming is True and d.supports_recovery is False
        assert d.supports_concurrency is True
        assert d.config_schema == {"a": "int"}
        assert d.degradation is Degradation.OPTIONAL_RUNTIME
        assert d.enabled is True  # 默认启用

    def test_missing_spec_fields_rejected(self):
        with pytest.raises(ValidationError):
            CapabilityDescriptor(name="x")  # type: ignore[call-arg]

    def test_supports_checks_subcapability(self):
        d = _descriptor()
        assert d.supports("store") is True
        assert d.supports("ingest") is False


class TestDegradation:
    def test_three_classes_from_spec08(self):
        assert {d.value for d in Degradation} == {
            "REQUIRED_CORE", "OPTIONAL_RUNTIME", "OPTIONAL_OBSERVABILITY",
        }


class TestRegistry:
    def test_register_and_get(self):
        registry = CapabilityRegistry()
        provider = object()
        registry.register(_descriptor(), provider)
        assert registry.get("memory") is provider
        assert registry.descriptor("memory").provider_name == "langmem"
        assert [d.name for d in registry.available()] == ["memory"]

    def test_duplicate_registration_rejected(self):
        registry = CapabilityRegistry()
        registry.register(_descriptor(), object())
        with pytest.raises(CapabilityError) as err:
            registry.register(_descriptor(), object())
        # 重复注册是装配冲突：用 init_failed（not_found 专指"注册表无此能力"，ADR-0010 Q2）。
        assert err.value.code == "init_failed"
        # 原.provider 不被静默覆盖：
        first = registry.get("memory")
        with pytest.raises(CapabilityError):
            registry.register(_descriptor(provider_name="other"), object())
        assert registry.get("memory") is first

    def test_get_missing_raises_not_found(self):
        with pytest.raises(CapabilityError) as err:
            CapabilityRegistry().get("web")
        assert err.value.code == "not_found"

    def test_optional_missing_returns_none(self):
        assert CapabilityRegistry().optional("web") is None

    def test_optional_present_returns_provider(self):
        registry = CapabilityRegistry()
        provider = object()
        registry.register(_descriptor(), provider)
        assert registry.optional("memory") is provider

    def test_disabled_provider_get_raises_disabled_and_optional_none(self):
        registry = CapabilityRegistry()
        registry.register(_descriptor(enabled=False), object())
        with pytest.raises(CapabilityError) as err:
            registry.get("memory")
        assert err.value.code == "disabled"
        assert registry.optional("memory") is None
        # available() 列出 disabled 条目，带 enabled 标记由消费方判断：
        assert registry.descriptor("memory").enabled is False

    def test_error_vocabulary_is_explicit(self):
        for code in ("not_found", "unsupported", "disabled", "init_failed"):
            err = CapabilityError(f"boom: {code}", code=code)
            assert err.code == code
            assert code in str(err)
