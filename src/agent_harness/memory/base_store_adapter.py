"""LangGraph BaseStore adapter；仅由可选 LangMem Provider 导入。

`PutOp` 的三种形状对应三个动作（LangGraph 的删除就是 `value=None`）：
`value` 为 dict → 写入/覆盖（同 id 即更新），`value is None` → **硬删**（#157 解禁，
落到 `MemoryRecordStore.delete`），`ttl` 非空 → 仍拒绝（另一套语义，见下文）。
"""

import asyncio
import logging
from datetime import UTC, datetime

from langgraph.store.base import BaseStore, GetOp, Item, PutOp, SearchItem, SearchOp

from agent_harness.identity import get_identity_context
from agent_harness.memory.record_store import MemoryRecordStore
from agent_harness.memory.types import (
    LANGMEM_INTERNAL_METADATA_KEY,
    MemoryEntry,
    MemoryNamespace,
    MemoryScope,
)
from agent_harness.memory.vector_store import VectorIndexStore

logger = logging.getLogger(__name__)


class SqliteMilvusBaseStore(BaseStore):
    def __init__(self, records: MemoryRecordStore, vectors: VectorIndexStore) -> None:
        self.records = records
        self.vectors = vectors

    @staticmethod
    def _scope(namespace: tuple[str, ...]) -> MemoryScope:
        # 形状/根段/归属校验收进 MemoryNamespace.authorize 一处（A3）。
        return MemoryNamespace.authorize(namespace, get_identity_context()).scope

    def batch(self, ops):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.abatch(ops))
        raise RuntimeError("Use async BaseStore methods inside an event loop")

    async def abatch(self, ops):
        results = []
        for op in ops:
            if not isinstance(op, (GetOp, PutOp, SearchOp)):
                raise NotImplementedError("Namespace enumeration is not exposed")
            namespace = op.namespace_prefix if isinstance(op, SearchOp) else op.namespace
            scope = self._scope(namespace)
            identity = get_identity_context()
            if isinstance(op, PutOp):
                # TTL 一律先拒（含 `value=None, ttl=...` 这种既删又过期的畸形组合）：
                # TTL（到点自动过期）是另一套语义，本票不实现，静默忽略它会承诺一个永远不会
                # 兑现的过期。今天它在公开 API 层就被 LangGraph 拒掉（`supports_ttl=False`），
                # 所以这里是防御性边界而非热路径——正因为它离热路径远，才要求分支顺序与
                # 文档写的一致，而不是"恰好也不会有人这么传"。
                if op.ttl is not None:
                    raise NotImplementedError("Memory TTL is not enabled")
                if op.value is None:
                    # LangGraph 的删除形状：`store.adelete(ns, key)` 等价于
                    # `PutOp(namespace, key, None)`。硬删（#156 的机制），namespace 授权与归属
                    # 校验都在 records.delete 内——provider 的删除动作碰不到别人的记忆。
                    if not await self.records.delete(op.key, identity):
                        # 幂等，但**不得静默**：一次什么都没删掉的删除意图要留痕，否则
                        # "模型说删了、其实什么都没发生"无法被发现。级别是 warning 日志而不是
                        # `memory/degraded` 事件——后者表示"降级/失败"，幂等空操作不是失败，
                        # 且 ADR-0026 明令记忆审计不进会话事件流。
                        logger.warning("LangMem delete for %s matched no record row", op.key)
                    results.append(None)
                    continue
                payload = op.value.get("content")
                if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
                    raise TypeError("Expected structured Memory content")
                metadata = {**payload.get("metadata", {}), LANGMEM_INTERNAL_METADATA_KEY: {
                    "kind": op.value.get("kind", "MemoryPayload"), "content": payload,
                }}
                await self.records.store(MemoryEntry(id=op.key, content=payload["content"], metadata=metadata,
                                                      scope=scope, created_at=datetime.now(UTC).isoformat()), identity)
                results.append(None)
            elif isinstance(op, GetOp):
                try:
                    entry = await self.records.get(op.key, identity)
                except KeyError:
                    results.append(None)
                    continue
                if entry.scope != scope:
                    results.append(None)
                    continue
                results.append(self._item(entry, namespace))
            else:
                if op.limit <= 0 or op.offset < 0:
                    results.append([])
                    continue
                if op.query:
                    hits = await self.vectors.search(op.query, identity, scope, op.limit + op.offset)
                    entries = []
                    for key, score in hits:
                        try:
                            entry = await self.records.get(key, identity)
                        except KeyError:
                            continue
                        if entry.scope == scope:
                            entries.append(entry.model_copy(update={"score": score}))
                else:
                    entries = await self.records.list_by_scope(scope, identity, op.limit + op.offset)
                items = [self._item(entry, namespace, search=True) for entry in entries]
                if op.filter:
                    items = [item for item in items if all(item.value.get(k) == v for k, v in op.filter.items())]
                results.append(items[op.offset:op.offset + op.limit])
        return results

    @staticmethod
    def _item(entry: MemoryEntry, namespace, search=False):
        value = entry.metadata.get(LANGMEM_INTERNAL_METADATA_KEY, {"kind": "MemoryPayload", "content": {
            "content": entry.content, "metadata": entry.metadata,
        }})
        timestamp = datetime.fromisoformat(entry.created_at)
        kwargs = {"value": value, "key": entry.id, "namespace": namespace,
                  "created_at": timestamp, "updated_at": timestamp}
        return SearchItem(**kwargs, score=entry.score) if search else Item(**kwargs)
