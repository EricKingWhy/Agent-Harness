"""Builtin Capability factories（ADR-0010 Q5）：按 settings 构造 Provider 实例。

所有具体 SDK import 都在 factory 函数内部惰性执行——Core / 其他 capability
不因本模块的存在而依赖可选 extra（不变量 #21）。

Memory 的 provider 分派见 ADR-0024：**provider 的边界是整个 `MemoryComponents`
包**（capability + records + vectors + relay + writeback 一体替换），而不是单个
`MemoryCapability` 实现——因为想做"记忆产品"的上游（Mem0 / Zep / Letta）几乎都
自带存储层。`MemoryComponents.initialize()` / `close()` 的生命周期同样归 provider
自己（不变量 #17：LangMem 只是默认 provider）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_harness.capability.base import CapabilityError
from agent_harness.config import Settings
from agent_harness.model.config import ModelConfig
from agent_harness.model.provider import create_chat_model

logger = logging.getLogger(__name__)


class MemoryComponents:
    """聚合 Memory 子系统内各组件（ADR-0024：这就是一个 provider 的**完整边界**）。

    生命周期契约（ticket #149 AC6）：`initialize()` / `close()` 由 **provider 自己**
    拥有与实现——装配方只负责在启动期调用 `initialize()`、在关停期调用 `close()`，
    **不假设内部有哪些组件**（`builtin` 的顺序——记录库 → 向量库 → relay——见下）。
    provider 换实现时生命周期语义随之改变，装配方零改动。
    """

    def __init__(self, capability: Any, records: Any, vectors: Any, relay: Any, writeback: Any) -> None:
        self.capability = capability
        self.records = records
        self.vectors = vectors
        self.relay = relay
        self.writeback = writeback

    async def initialize(self) -> None:
        # 顺序（provider 自己的实现细节，装配方不关心）：SQLite 记录库先建表 →
        # 向量库惰性建立 collection → 最后启动 relay（此时 outbox 表与 collection 都就绪）。
        # relay 归这里启动而不是装配方（ADR-0024 D6）：否则换一个不带 `.relay` 属性的
        # provider 时，装配方会 AttributeError，把"能用的 provider"降级成"没有记忆"。
        if hasattr(self.records, "initialize"):
            await self.records.initialize()
        if hasattr(self.vectors, "initialize"):
            await self.vectors.initialize()
        self.relay.start()

    async def close(self) -> None:
        # 关闭顺序：先停 relay（停止派生任务），再关写回任务池，最后断向量库连接。
        await self.relay.stop()
        await self.writeback.close()
        if hasattr(self.vectors, "close"):
            await self.vectors.close()


def build_builtin_memory_components(settings: Settings) -> MemoryComponents | None:
    """`builtin` provider：现有 sqlite + milvus + outbox + langmem 组合。

    配置不全返回 None（OPTIONAL_RUNTIME 降级），与 .env 的两个最小集合对齐：
      - 向量检索：milvus_uri + milvus_token + milvus_collection（无则不做语义记忆）
      - 嵌入模型：embedding_model + embedding_base_url + embedding_api_key（无则无法嵌入）
    两者都齐才装配；任一缺失返回 None，Runtime 继续工作但没有记忆能力。
    """
    milvus_ready = bool(
        settings.milvus_uri
        and settings.milvus_token.get_secret_value()
        and settings.milvus_collection
    )
    embedding_ready = bool(
        settings.embedding_model
        and settings.embedding_base_url
        and settings.embedding_api_key.get_secret_value()
    )
    if not (milvus_ready and embedding_ready):
        return None

    from agent_harness.memory.embeddings import create_embeddings
    from agent_harness.memory.extractor import MemoryExtractor
    from agent_harness.memory.langmem_capability import LangMemMemoryCapability
    from agent_harness.memory.milvus_vector_store import MilvusVectorStore
    from agent_harness.memory.outbox_relay import OutboxRelay
    from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
    from agent_harness.memory.writeback import MemoryWriteback

    records = SqliteMemoryRecordStore(Path(settings.workspace_dir) / "memory.db")
    vectors = MilvusVectorStore(settings, create_embeddings(settings))
    # #158：**必须**把决策模型喂给 capability——此前这里不传模型，于是"检索既有记忆后
    # 决定 insert/update/delete"这条路径在生产里根本没执行过（写入只能新增的真正机制）。
    # 一个模型实例喂两处（抽取 + 消解），避免建两个客户端。
    model = create_chat_model(ModelConfig.from_settings(settings))
    capability = LangMemMemoryCapability(records, vectors, model)
    relay = OutboxRelay(records, vectors)
    writeback = MemoryWriteback(capability, MemoryExtractor(model))
    return MemoryComponents(
        capability=capability,
        records=records,
        vectors=vectors,
        relay=relay,
        writeback=writeback,
    )


#: Memory 的 per-provider 分派表（ADR-0024，形状照抄 wiring 的 `_BUILTIN_WIRING`）。
#: 新增一个记忆产品 = **在这里加一行 + 写一个 builder**，装配侧零改动。
#: 这张表同时是装配期 provider 白名单的唯一事实源（见 `memory_provider_names()`）——
#: "白名单收下了名字、却没有任何实现" 的漂移在结构上不可能再发生（08 §5）。
_MEMORY_PROVIDER_FACTORIES: dict[str, Callable[[Settings], MemoryComponents | None]] = {
    "builtin": build_builtin_memory_components,  # sqlite + milvus + outbox + langmem
    "langmem": build_builtin_memory_components,  # 历史别名：同一实现（见下）
}

#: 「名字与 `builtin` 指向同一实现」的旧配置值：接受但明确告知已弃用。
#: 之所以不直接删掉 `langmem`：既有 `.env` 与测试配置里写着它，删掉会让升级变成
#: 装配期硬失败（unknown provider），代价大于收益。这与"名字不同、实现相同、
#: 无人知道"的旧状态的区别在于——**这里写明了**，且启用时每次装配都会 warning
#: （`enabled: false` 不构造 provider，自然不 warning）。
_DEPRECATED_MEMORY_PROVIDERS: frozenset[str] = frozenset({"langmem"})


def memory_provider_names() -> set[str]:
    """本模块真正能构造的 memory provider 名（装配期白名单的唯一事实源）。"""
    return set(_MEMORY_PROVIDER_FACTORIES)


def build_memory_components(settings: Settings, *, provider: str = "builtin") -> MemoryComponents | None:
    """按 provider 分派到对应的 MemoryComponents builder（ADR-0024）。

    未知 provider 在此显式失败（`CapabilityError(code="init_failed")`——用
    ADR-0010 Q3 冻结的四个码之一，不新增码）——装配期硬失败，不降级：配置写错是
    用户必须修的错误，静默接受名字而用别的实现会让
    `CapabilityDescriptor.provider_name` 对外撒谎（08 §5）。
    """
    factory = _MEMORY_PROVIDER_FACTORIES.get(provider)
    if factory is None:
        raise CapabilityError(
            f"unknown memory provider '{provider}' "
            f"(known: {sorted(_MEMORY_PROVIDER_FACTORIES)})",
            code="init_failed",
        )
    if provider in _DEPRECATED_MEMORY_PROVIDERS:
        logger.warning(
            "memory provider '%s' 是已弃用别名，与 'builtin' 同一实现；"
            "请把 CAPABILITIES.memory.provider 改为 'builtin'",
            provider,
        )
    return factory(settings)
