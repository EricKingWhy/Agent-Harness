"""#149 ARCH-6 / ADR-0024：memory provider seam —— 装配期真分派 + 白名单同源。

本票要防的形状（背景节原文）：名字被白名单接受、`CapabilityDescriptor.provider_name`
如实写配置值，但 `build_memory_components` **不分派** → 描述符对外声称一个并未生效的
provider（一旦有人往白名单加名字却忘了写实现，就变成"静默用 LangMem 而自称 mem0"）。

因此本文件的断言分两类：
1. **结构不变量**：白名单不是第二份清单，它**派生自**分派表（`_known_providers()`）。
   若有人把 `_known_providers` 的 memory 分支回退成硬编码集合（即恢复成两份清单），
   `test_new_provider_needs_no_whitelist_edit` 会红。
2. **端到端真分派**：一个 Fake provider 从 `CAPABILITIES` 配置一路走到注册表，
   描述符声称什么、`registry.get()` 里就必须真的是什么（身份相等，不是名字相等）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from agent_harness.capability.base import (
    CapabilityError,
    CapabilityRegistry,
    Degradation,
)
from agent_harness.capability.config import parse_capabilities_config
from agent_harness.capability.factories import (
    _MEMORY_PROVIDER_FACTORIES,
    MemoryComponents,
    build_builtin_memory_components,
    build_memory_components,
    memory_provider_names,
)
from agent_harness.capability.wiring import _known_providers, wire_capabilities
from agent_harness.config import Settings
from agent_harness.memory.types import MemoryEntry, MemoryScope

READY_SETTINGS = {
    "milvus_uri": "https://example.test",
    "milvus_token": "test-only",
    "milvus_collection": "col",
    "embedding_model": "m",
    "embedding_base_url": "https://x",
    "embedding_api_key": "k",
}


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, workspace_dir=str(tmp_path), **READY_SETTINGS)


class _InMemoryCapability:
    """最小但**真的能用**的 MemoryCapability（AC5：产出可用，不是占位对象）。"""

    def __init__(self) -> None:
        self.entries: dict[str, MemoryEntry] = {}
        self._next = 0

    async def store(self, scope: MemoryScope, content: str, metadata: dict, *,
                    budget_seconds: float | None = None) -> str:
        self._next += 1
        memory_id = f"fake-{self._next}"
        self.entries[memory_id] = MemoryEntry(
            id=memory_id, content=content, metadata=metadata,
            created_at=datetime.now(UTC).isoformat(), scope=scope,
        )
        return memory_id

    async def consolidate(self, scope: MemoryScope, content: str, metadata: dict, *,
                          budget_seconds: float | None = None):
        """#158 的写入入口：替身不做冲突消解（无降级），但仍要满足协议形状。"""
        from agent_harness.memory.capability import MemoryWriteOutcome

        return MemoryWriteOutcome(await self.store(scope, content, metadata))

    async def update(self, memory_id: str, scope: MemoryScope, content: str,
                     metadata: dict) -> str:
        """upsert by id（契约：id 不存在即新建，id 由调用方给定）。"""
        existing = self.entries.get(memory_id)
        self.entries[memory_id] = MemoryEntry(
            id=memory_id, content=content, metadata=metadata,
            created_at=existing.created_at if existing else datetime.now(UTC).isoformat(),
            scope=scope,
        )
        return memory_id

    async def forget(self, memory_id: str) -> bool:
        return self.entries.pop(memory_id, None) is not None

    async def list_entries(self, scope: MemoryScope, limit: int, offset: int = 0) -> list[MemoryEntry]:
        """契约方法（#159）：按 namespace 分页列出——与真实现同款"先取后切"。"""
        scoped = [e for e in self.entries.values() if e.scope is scope]
        return scoped[max(0, offset):max(0, offset) + max(0, limit)]

    async def recall(self, scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]:
        return [e for e in self.entries.values() if e.scope is scope][:limit]

    async def search(self, scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]:
        return [e for e in self.entries.values() if query in e.content][:limit]


class _FakeMemoryComponents:
    """Fake provider 的产物：**只有 capability / writeback / 生命周期，没有内部组件**。

    `records` / `vectors` 恒为 None 不是偷懒——它正是 AC6 的断言载体：装配方只允许调用
    `initialize()` / `close()`，不得自己伸手去 `records.initialize()` /
    `vectors.initialize()`，也不得去 `relay.start()`（那是 provider 内部的初始化顺序）。
    谁把 record / vector / relay 的启动搬回 `_wire_memory`，这里就 AttributeError →
    OPTIONAL 降级 → 注册表里没有 memory。
    """

    def __init__(self) -> None:
        self.capability = _InMemoryCapability()
        self.records = None
        self.vectors = None
        self.writeback = object()
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


def _build_fake(settings: Settings) -> _FakeMemoryComponents:
    return _FakeMemoryComponents()


class TestDispatchTableIsSingleSourceOfTruth:
    def test_every_accepted_provider_has_a_factory(self):
        """AC1/AC3：白名单与分派表是同一个集合——不存在"接受了却没有实现"的名字。"""
        names = memory_provider_names()
        # 冻结的期望（非重言）：命名收口后恰好这两个名字。多一个名字就得配一条
        # builder，少一个名字就是别名回归。
        assert names == {"builtin", "langmem"}
        # 白名单是**派生**的，不是第二份要手工同步的清单。
        assert _known_providers("memory") == names
        for name in names:
            assert callable(_MEMORY_PROVIDER_FACTORIES[name]), name

    def test_langmem_is_an_alias_of_builtin_not_a_second_implementation(self):
        """AC3 命名收口：两个名字指向**同一个** builder（`is`，不是"另一个等价实现"）。"""
        assert _MEMORY_PROVIDER_FACTORIES["langmem"] is _MEMORY_PROVIDER_FACTORIES["builtin"]
        assert _MEMORY_PROVIDER_FACTORIES["builtin"] is build_builtin_memory_components

    def test_new_provider_needs_no_whitelist_edit(self, monkeypatch):
        """D3 反漂移关键断言：往分派表加一行，白名单**自动**接受（无需第二处同步）。

        mutation：把 `_known_providers` 改回真正的 `_STATIC_KNOWN_PROVIDERS["memory"]`
        硬编码查找 → 本用例红。
        """
        monkeypatch.setitem(_MEMORY_PROVIDER_FACTORIES, "not-yet-real", _build_fake)
        assert "not-yet-real" in _known_providers("memory")

    def test_deprecated_alias_is_still_accepted(self):
        """AC3 明确"不硬失败"：既有 `.env` 写着 langmem 的部署不能因改名而启动失败。"""
        assert "langmem" in _known_providers("memory")


class TestDispatchBehavior:
    def test_default_provider_is_builtin(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setitem(
            _MEMORY_PROVIDER_FACTORIES, "builtin",
            lambda settings: calls.append("builtin") or None,
        )
        build_memory_components(_settings_for_default())
        assert calls == ["builtin"]

    def test_langmem_alias_dispatches_to_builtin_and_warns(self, monkeypatch, caplog):
        calls: list[str] = []
        monkeypatch.setitem(
            _MEMORY_PROVIDER_FACTORIES, "langmem",
            lambda settings: calls.append("langmem") or None,
        )
        with caplog.at_level(logging.WARNING):
            build_memory_components(_settings_for_default(), provider="langmem")
        assert calls == ["langmem"]
        assert any(
            "已弃用" in record.getMessage() and "builtin" in record.getMessage()
            for record in caplog.records
        ), "弃用别名必须留下可检索的 warning（否则又回到'无人知道'的旧状态）"

    def test_unknown_provider_fails_loudly_at_factory(self):
        """AC1：未知 provider 在 factory 层是硬失败，且**报出已知集合**便于修配置。

        码固定为 `init_failed`——ADR-0010 Q3 冻结的四个码之一（"factory 构造失败 /
        config 非法"），不新增第五个码。
        """
        with pytest.raises(CapabilityError) as err:
            build_memory_components(_settings_for_default(), provider="mem0")
        assert err.value.code == "init_failed"
        assert "mem0" in str(err.value)
        assert "builtin" in str(err.value)

    @pytest.mark.asyncio
    async def test_unknown_provider_fails_loudly_at_assembly(self, tmp_path):
        """AC1/AC5：同一错误在装配期同样是硬失败（不走 OPTIONAL_RUNTIME 降级）。

        factory 层与装配层各有一道检查是**刻意的**：装配层先按白名单拦截用户配置
        （与既有 provider 校验同形），factory 层是防御性兜底——万一将来有别的装配
        路径直接调 factory，也不允许静默换成默认实现。
        """
        with pytest.raises(CapabilityError) as err:
            await wire_capabilities(
                CapabilityRegistry(),
                parse_capabilities_config('{"memory": {"provider": "mem0"}}'),
                settings=_settings(tmp_path),
            )
        assert err.value.code == "init_failed"
        assert "mem0" in str(err.value)


class TestFakeProviderFullDispatch:
    """AC5：Fake provider 走**完整分派**（配置 → 装配 → 注册表 → 可用 capability）。"""

    @pytest.mark.asyncio
    async def test_descriptor_cannot_lie_about_the_provider(self, tmp_path, monkeypatch):
        components = _FakeMemoryComponents()
        monkeypatch.setitem(_MEMORY_PROVIDER_FACTORIES, "fake", lambda settings: components)

        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry,
            parse_capabilities_config('{"memory": {"provider": "fake"}}'),
            settings=_settings(tmp_path),
        )

        descriptor = registry.descriptor("memory")
        assert descriptor.provider_name == "fake"
        assert descriptor.degradation is Degradation.OPTIONAL_RUNTIME
        # 身份相等：描述符声称的 provider 就是真正被构造出来的那一个（不是"同名"）。
        assert registry.get("memory") is components.capability
        assert wiring.memory is components
        assert wiring.memory_writer is components.writeback
        assert [p.name for p in wiring.context_providers] == ["memory"]

    @pytest.mark.asyncio
    async def test_dispatched_capability_is_actually_usable(self, tmp_path, monkeypatch):
        monkeypatch.setitem(_MEMORY_PROVIDER_FACTORIES, "fake", _build_fake)
        registry = CapabilityRegistry()
        await wire_capabilities(
            registry,
            parse_capabilities_config('{"memory": {"provider": "fake"}}'),
            settings=_settings(tmp_path),
        )
        capability = registry.get("memory")
        memory_id = await capability.store(MemoryScope.USER, "我喜欢黑咖啡", {"importance": 0.8})
        assert memory_id
        hits = await capability.search(MemoryScope.USER, "黑咖啡", limit=5)
        assert [entry.content for entry in hits] == ["我喜欢黑咖啡"]
        assert await capability.recall(MemoryScope.USER, "", limit=5)

    @pytest.mark.asyncio
    async def test_lifecycle_is_owned_by_provider(self, tmp_path, monkeypatch):
        """AC6：装配方只调 initialize()/close()，不碰 provider 内部组件。

        `_FakeMemoryComponents` 只有 capability / writeback / 生命周期，`records` /
        `vectors` 都是 None，也**没有** `relay`。装配能跑通并成功注册，就证明装配方
        没替 provider 做内部初始化——谁把 `records.initialize()` / `relay.start()`
        之类的调用搬回 `_wire_memory`，这里就会 AttributeError → OPTIONAL 降级 →
        注册表里没有 memory（下面那条 registry 断言因此是必需的，不只是装饰）。
        """
        components = _FakeMemoryComponents()
        monkeypatch.setitem(_MEMORY_PROVIDER_FACTORIES, "fake", lambda settings: components)
        registry = CapabilityRegistry()
        await wire_capabilities(
            registry,
            parse_capabilities_config('{"memory": {"provider": "fake"}}'),
            settings=_settings(tmp_path),
        )
        assert registry.optional("memory") is components.capability
        assert components.initialized and not components.closed

    @pytest.mark.asyncio
    async def test_half_initialized_provider_is_closed_by_its_own_contract(self, tmp_path, monkeypatch):
        """AC6 失败路径：initialize() 抛错 → 装配方按 provider 的 close() 收尾。

        契约归 provider 的含义是**连清理也只走 provider 的入口**——装配方不知道
        内部有哪些东西要关，只负责在失败时调用同一个 close()。
        """

        class _HalfBroken(_FakeMemoryComponents):
            async def initialize(self) -> None:
                raise RuntimeError("simulated provider outage")

        components = _HalfBroken()
        monkeypatch.setitem(_MEMORY_PROVIDER_FACTORIES, "fake", lambda settings: components)
        registry = CapabilityRegistry()
        wiring = await wire_capabilities(
            registry,
            parse_capabilities_config('{"memory": {"provider": "fake"}}'),
            settings=_settings(tmp_path),
        )
        assert components.closed is True
        assert registry.available() == []  # OPTIONAL_RUNTIME 降级
        assert wiring.memory is None
        assert wiring.memory_writer is None


def _settings_for_default() -> Settings:
    """只调 factory 分派、不真正构造组件时的 settings（内容无关紧要，用不到 Milvus）。"""
    return Settings(_env_file=None, workspace_dir=".")


class TestBuiltinProviderOwnLifecycle:
    """AC6/D6：`builtin` **自己**实现 initialize/close 的顺序（装配方不再代劳）。

    直接给真 `MemoryComponents` 注入三个记录顺序的替身，不需要 Milvus / LangMem——
    这样"relay 由 initialize 启动"这条契约才是可证伪的：改造前它在装配方手里，
    把它从 `initialize()` 挪回 `_wire_memory` 或直接删掉，本类都会红。
    """

    class _Writeback:
        def __init__(self, log: list[str]) -> None:
            self._log = log

        async def close(self) -> None:
            self._log.append("writeback.close")

    def _components(self, log: list[str]) -> MemoryComponents:
        class _Records:
            async def initialize(self) -> None:
                log.append("records.initialize")

        class _Vectors:
            async def initialize(self) -> None:
                log.append("vectors.initialize")

            async def close(self) -> None:
                log.append("vectors.close")

        class _Relay:
            def start(self) -> None:
                log.append("relay.start")

            async def stop(self) -> None:
                log.append("relay.stop")

        return MemoryComponents(
            capability=object(), records=_Records(), vectors=_Vectors(),
            relay=_Relay(), writeback=self._Writeback(log),
        )

    @pytest.mark.asyncio
    async def test_initialize_builds_stores_then_starts_relay(self):
        log: list[str] = []
        await self._components(log).initialize()
        # relay 必须在两个存储就绪**之后**启动（它要读 outbox / collection）。
        assert log == ["records.initialize", "vectors.initialize", "relay.start"]

    @pytest.mark.asyncio
    async def test_close_stops_relay_then_writeback_then_vectors(self):
        log: list[str] = []
        components = self._components(log)
        await components.initialize()
        log.clear()
        await components.close()
        assert log == ["relay.stop", "writeback.close", "vectors.close"]

    @pytest.mark.asyncio
    async def test_close_is_safe_after_failed_initialize(self):
        """半初始化失败时装配方会调 close()——即使 relay 从未启动，close 也必须收敛。"""
        log: list[str] = []
        components = self._components(log)

        class _BrokenVectors:
            async def initialize(self) -> None:
                raise RuntimeError("simulated milvus outage")

            async def close(self) -> None:
                log.append("vectors.close")

        components.vectors = _BrokenVectors()
        with pytest.raises(RuntimeError):
            await components.initialize()
        # 失败前只有 records 装好；relay **没有**启动。close() 仍须按顺序收敛且不抛。
        assert log == ["records.initialize"]
        await components.close()  # 不得抛出：失败路径的收尾由 provider 自己兜住
        assert log == ["records.initialize", "relay.stop", "writeback.close", "vectors.close"]
