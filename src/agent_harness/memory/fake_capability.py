"""零 SDK 的测试 MemoryCapability。"""

from datetime import UTC, datetime
from uuid import uuid4

from agent_harness.identity import get_identity_context
from agent_harness.memory.capability import MemoryWriteOutcome
from agent_harness.memory.fake_record_store import FakeMemoryRecordStore
from agent_harness.memory.types import MemoryEntry, MemoryScope


class FakeMemoryCapability:
    def __init__(self, consolidation_degraded_reason: str | None = None) -> None:
        self._records = FakeMemoryRecordStore()
        #: #158：替身**不做**真实冲突消解（那需要真模型），所以"消解降级"由构造参数驱动——
        #: 默认 `None`（未降级），需要验 AC5 时显式传入原因。真实降级语义由 langmem 实现 +
        #: 集成测试覆盖；替身只保证契约形状（返回即已写入）。
        self._consolidation_degraded_reason = consolidation_degraded_reason

    async def store(self, scope: MemoryScope, content: str, metadata: dict, *,
                    budget_seconds: float | None = None) -> str:
        entry = MemoryEntry(id=str(uuid4()), content=content, metadata=metadata, scope=scope,
                            created_at=datetime.now(UTC).isoformat())
        return await self._records.store(entry, get_identity_context())

    async def consolidate(self, scope: MemoryScope, content: str, metadata: dict, *,
                          budget_seconds: float | None = None) -> MemoryWriteOutcome:
        """#158 的写入入口（契约见 `capability.py`）：先写入，再如实报告是否降级。"""
        return MemoryWriteOutcome(await self.store(scope, content, metadata),
                                  degraded_reason=self._consolidation_degraded_reason)

    async def update(self, memory_id: str, scope: MemoryScope, content: str, metadata: dict) -> str:
        """按 id 覆盖写（生命周期契约见 `capability.py`）。"""
        entry = MemoryEntry(id=memory_id, content=content, metadata=metadata, scope=scope,
                            created_at=datetime.now(UTC).isoformat())
        return await self._records.store(entry, get_identity_context())

    async def forget(self, memory_id: str) -> bool:
        return await self._records.delete(memory_id, get_identity_context())

    async def list_entries(self, scope: MemoryScope, limit: int, offset: int = 0) -> list[MemoryEntry]:
        """按 namespace 分页列出（契约见 `capability.py`）——与真实现同款先取后切。"""
        entries = await self._records.list_by_scope(scope, get_identity_context(), max(0, limit) + max(0, offset))
        return entries[max(0, offset):max(0, offset) + max(0, limit)]

    async def search(self, scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]:
        entries = await self._records.list_by_scope(scope, get_identity_context(), 10000)
        return [entry.model_copy(update={"score": 1.0}) for entry in entries
                if query and query.casefold() in entry.content.casefold()][:max(0, limit)]

    async def recall(self, scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]:
        return await self.search(scope, query, limit)
