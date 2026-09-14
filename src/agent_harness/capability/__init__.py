"""Capability / Plugin 基础（spec 08）：可插拔业务能力，Agent Core 零特判。"""

from agent_harness.capability.base import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityRegistry,
    Degradation,
)

__all__ = [
    "CapabilityDescriptor",
    "CapabilityError",
    "CapabilityRegistry",
    "Degradation",
]
