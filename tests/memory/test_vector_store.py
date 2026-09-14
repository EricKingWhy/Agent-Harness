"""向量索引契约的离线替身与隔离。"""

import pytest

from agent_harness.identity import IdentityContext
from agent_harness.memory.fake_vector_store import FakeVectorStore
from agent_harness.memory.types import MemoryScope, memory_session_var


@pytest.mark.asyncio
async def test_fake_vector_search_isolated_and_idempotent():
    vector = FakeVectorStore()
    alice = IdentityContext("acme", "alice", ["user", "session"])
    await vector.upsert("m1", "TypeScript preference", {"scope": "user"}, alice)
    await vector.upsert("m1", "TypeScript preference", {"scope": "user"}, alice)
    assert await vector.search("TypeScript", alice, MemoryScope.USER, 1) == [("m1", 1.0)]
    assert await vector.search("", alice, MemoryScope.USER, 5) == []
    for other in (IdentityContext("acme", "bob", ["user"]), IdentityContext("other", "alice", ["user"])):
        assert await vector.search("TypeScript", other, MemoryScope.USER, 5) == []
    token = memory_session_var.set("one")
    try:
        await vector.upsert("m2", "TypeScript local", {"scope": "session"}, alice)
        assert await vector.search("TypeScript", alice, MemoryScope.SESSION, 5) == [("m2", 1.0)]
        memory_session_var.set("two")
        assert await vector.search("TypeScript", alice, MemoryScope.SESSION, 5) == []
    finally:
        memory_session_var.reset(token)
