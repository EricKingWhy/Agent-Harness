"""按字面匹配的测试 adapter，不声称提供语义 embedding。"""

from agent_harness.identity import IdentityContext
from agent_harness.memory.types import MemoryScope, scope_to_namespace


class FakeVectorStore:
    """镜像 `MilvusVectorStore` 的 upsert/search/delete/get 四个动词。

    `delete` 按 namespace 过滤（跨 namespace 删不掉，与真实 adapter 的 filter 同款）；
    `get` 是"无残留"的验收入口（`search` 只能证明检索不到）。
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[tuple[str, ...], str], tuple[str, dict]] = {}

    async def upsert(self, memory_id: str, content: str, metadata: dict, identity: IdentityContext) -> None:
        namespace = scope_to_namespace(MemoryScope(metadata["scope"]), identity)
        self._rows[namespace, memory_id] = (content, dict(metadata))

    async def search(self, query: str, identity: IdentityContext, scope: MemoryScope, limit: int) -> list[tuple[str, float]]:
        namespace = scope_to_namespace(scope, identity)
        if not query:
            return []
        return [(key, 1.0) for (ns, key), (content, _) in self._rows.items()
                if ns == namespace and query.casefold() in content.casefold()][:max(0, limit)]

    async def delete(self, memory_id: str, identity: IdentityContext, scope: MemoryScope) -> None:
        self._rows.pop((scope_to_namespace(scope, identity), memory_id), None)

    async def get(self, memory_id: str, identity: IdentityContext, scope: MemoryScope) -> dict | None:
        row = self._rows.get((scope_to_namespace(scope, identity), memory_id))
        if row is None:
            return None
        content, metadata = row
        return {"memory_id": memory_id, "content": content, "metadata": metadata}
