"""测试用权威记录；复制值以模拟持久化的对象隔离。"""

from agent_harness.identity import IdentityContext
from agent_harness.memory.types import (
    MemoryEntry,
    MemoryScope,
    row_namespace_matches,
    scope_to_namespace,
)


class FakeMemoryRecordStore:
    def __init__(self) -> None:
        self._records: dict[str, tuple[tuple[str, ...], MemoryEntry]] = {}

    async def initialize(self) -> None:
        pass

    async def store(self, entry: MemoryEntry, identity: IdentityContext) -> str:
        namespace = scope_to_namespace(entry.scope, identity)
        existing = self._records.get(entry.id)
        if existing and existing[0] != namespace:
            raise PermissionError("Memory belongs to a different namespace")
        self._records[entry.id] = (namespace, entry.model_copy(deep=True, update={
            "indexed": False, "score": None,
            "created_at": existing[1].created_at if existing else entry.created_at,
        }))
        return entry.id

    async def get(self, memory_id: str, identity: IdentityContext) -> MemoryEntry:
        row = self._records.get(memory_id)
        if row is None or row[0][1:3] != (identity.tenant_id, identity.user_id):
            raise KeyError(memory_id)
        if not row_namespace_matches(row[0], row[1].scope, identity):
            raise KeyError(memory_id)
        return row[1].model_copy(deep=True)

    async def list_by_scope(
        self, scope: MemoryScope, identity: IdentityContext, limit: int,
    ) -> list[MemoryEntry]:
        namespace = scope_to_namespace(scope, identity)
        entries = [entry for ns, entry in self._records.values() if ns == namespace]
        return [entry.model_copy(deep=True) for entry in
                sorted(entries, key=lambda entry: (entry.created_at, entry.id), reverse=True)[:max(0, limit)]]

    async def delete(self, memory_id: str, identity: IdentityContext) -> bool:
        """硬删的**记录行半边**（与 `SqliteMemoryRecordStore.delete` 同一组验收，
        见 test_record_store.py 的参数化用例）。

        `row_namespace_matches(row 的 scope, identity)` 同时覆盖 tenant/user 与 SESSION
        绑定两层校验：不匹配（含"当前上下文解析不出这一行的 namespace"）即"不是你的记忆"
        → `PermissionError`（不是 `False`——静默 False 会让调用方以为删掉了）。

        本 fake 不实现 outbox（`pending`/`acknowledge`）：跨"记录行 + 索引意图"的原子性
        与 ack/revision 语义由 sqlite 实现的测试覆盖，fake 只保证内存记录的删除语义与
        它一致。
        """
        row = self._records.get(memory_id)
        if row is None:
            return False
        if not row_namespace_matches(row[0], row[1].scope, identity):
            raise PermissionError("Memory belongs to a different namespace")
        del self._records[memory_id]
        return True
