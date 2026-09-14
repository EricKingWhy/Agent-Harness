"""向量索引只返回权威记录 ID 与查询分数。"""

from typing import Protocol

from agent_harness.identity import IdentityContext
from agent_harness.memory.types import MemoryScope


class VectorIndexStore(Protocol):
    async def upsert(self, memory_id: str, content: str, metadata: dict, identity: IdentityContext) -> None: ...
    async def search(self, query: str, identity: IdentityContext, scope: MemoryScope, limit: int) -> list[tuple[str, float]]: ...
    async def delete(self, memory_id: str, identity: IdentityContext, scope: MemoryScope) -> None:
        """按 namespace 删除一条向量（硬删的传播路径，幂等）。

        relay 用它执行 `MemoryOperation.DELETE`；此刻权威记录行已经不存在，所以
        identity/scope 只能由 outbox 自己携带（见 `record_store.PendingMemory`）。
        """
        ...

    async def get(self, memory_id: str, identity: IdentityContext, scope: MemoryScope) -> dict | None:
        """按 namespace 读回一条向量（对账/验收用，不是模型侧入口）。

        "无残留"必须可验证：`search` 只能证明"检索不到"，证明不了"索引里真的没有"
        （limit、语义漂移、阈值都可能让它看起来为空）。硬删的验收靠它按 id 断言。
        """
        ...


class VectorStoreError(RuntimeError):
    """不携带 SDK 原始异常文本或凭证的分类错误。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Memory vector store: {code}")
