"""抽取降级的可观测性（BUG-012）：回退必须落 ``memory/degraded``，成功不得有噪音。

真机现场：中文模型把 JSON 分隔符写成全角引号 → 严格校验失败 → 抽取**静默**退回
正则启发式（生产 prompt 连测 5/5），事件流里零痕迹、用户侧完全不可见。本文件钉住
「回退必留痕、成功零噪音、降级不丢候选」三条。
"""

import pytest

from agent_harness.memory.extractor import ExtractionOutcome
from agent_harness.memory.types import MemoryScope
from agent_harness.memory.writeback import MemoryWriteback
from tests.conftest import make_session


class RecordingCapability:
    """契约合规的替身：#158 之后写入入口是 `consolidate`（未降级时 reason=None）。"""

    def __init__(self) -> None:
        self.stored: list[tuple[MemoryScope, str, dict]] = []

    async def store(self, scope: MemoryScope, content: str, metadata: dict, *,
                    budget_seconds: float | None = None) -> str:
        self.stored.append((scope, content, metadata))
        return f"mem-{len(self.stored)}"

    async def consolidate(self, scope, content, metadata, *, budget_seconds=None):
        from agent_harness.memory.capability import MemoryWriteOutcome

        return MemoryWriteOutcome(await self.store(scope, content, metadata))

    async def search(self, scope, query, limit):  # pragma: no cover — 本文件不用
        return []

    async def recall(self, scope, query, limit):  # pragma: no cover — 本文件不用
        return []


@pytest.mark.asyncio
async def test_extraction_fallback_is_recorded_as_degraded_event(tmp_path):
    class FallbackExtractor:
        async def extract(self, events):
            return ExtractionOutcome(
                [(MemoryScope.USER, "Prefers Rust", {"importance": 0.7})],
                degraded_reason="heuristic_fallback: ValidationError",
            )

    session = make_session(tmp_path)
    writer = MemoryWriteback(RecordingCapability(), FallbackExtractor())
    writer.submit(session, session.events)
    await writer.drain()

    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert len(degraded) == 1
    assert degraded[0].data["operation"] == "extraction"
    assert degraded[0].data["reason"] == "heuristic_fallback: ValidationError"


@pytest.mark.asyncio
async def test_successful_extraction_produces_no_degraded_event(tmp_path):
    """对照组：LLM 路径成功时不得产生噪音——否则「降级」信号会贬值到无人看。"""
    class CleanExtractor:
        async def extract(self, events):
            return ExtractionOutcome([(MemoryScope.USER, "Prefers Rust", {"importance": 0.9})])

    session = make_session(tmp_path)
    writer = MemoryWriteback(RecordingCapability(), CleanExtractor())
    writer.submit(session, session.events)
    await writer.drain()

    assert not [e for e in session.events if e.type == "memory/degraded"]


@pytest.mark.asyncio
async def test_fallback_candidates_are_still_stored(tmp_path):
    """降级只在**质量**，不在可用性：正则抽到的候选照常落库。"""
    class FallbackExtractor:
        async def extract(self, events):
            return ExtractionOutcome(
                [(MemoryScope.SESSION, "decision-x", {"importance": 0.5})],
                degraded_reason="heuristic_fallback: TimeoutError",
            )

    capability = RecordingCapability()
    session = make_session(tmp_path)
    writer = MemoryWriteback(capability, FallbackExtractor())
    writer.submit(session, session.events)
    await writer.drain()

    assert [content for _, content, _ in capability.stored] == ["decision-x"]


@pytest.mark.asyncio
async def test_degraded_event_carries_run_id_for_attribution(tmp_path):
    """MEMORY_DEGRADED 必须能归因到那个 run（R3-7）——抽取路径此前无覆盖。"""
    from agent_harness.session import SessionEvent

    class FallbackExtractor:
        async def extract(self, events):
            return ExtractionOutcome([], degraded_reason="heuristic_fallback: TimeoutError")

    session = make_session(tmp_path)
    run_event = SessionEvent(seq=1, type="run/started", session_id=session.session_id,
                             run_id="run-attr-1", data={"turn_index": 1})
    writer = MemoryWriteback(RecordingCapability(), FallbackExtractor())
    writer.submit(session, [run_event])
    await writer.drain()

    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert len(degraded) == 1
    assert degraded[0].run_id == "run-attr-1"


@pytest.mark.asyncio
async def test_observability_write_failure_does_not_drop_candidates(tmp_path):
    """降级只在**质量**不在可用性：观测事件写不下去时，候选照样要落库。

    （code-review P2：append 与存储循环同在一个 try 内，append 抛异常会整段跳过。）
    """
    class FallbackExtractor:
        async def extract(self, events):
            return ExtractionOutcome([(MemoryScope.USER, "keep-me", {"importance": 0.7})],
                                     degraded_reason="heuristic_fallback: ValidationError")

    capability = RecordingCapability()
    session = make_session(tmp_path)
    original_append = session.append

    def flaky_append(event_type, data, **kwargs):
        if event_type == "memory/degraded":
            raise RuntimeError("ledger-unavailable")
        return original_append(event_type, data, **kwargs)

    session.append = flaky_append  # type: ignore[method-assign]
    writer = MemoryWriteback(capability, FallbackExtractor())
    writer.submit(session, session.events)
    await writer.drain()

    assert [content for _, content, _ in capability.stored] == ["keep-me"]
    assert not [e for e in session.events if e.type == "memory/degraded"]


@pytest.mark.asyncio
async def test_failing_candidate_write_is_recorded_as_degraded_not_silent(tmp_path):
    """#157 AC5：provider 侧（含它发起的删除/更新）失败**不得静默**。

    `_write` 逐候选隔离并把失败计数落成 `memory/degraded`/`writeback` 的 `partial: N/M`——
    这条路径一直存在，却从未被测试钉过；#157 解禁 provider 删除后，"模型让删、删除却失败"
    会真的走到这里，所以现在必须证明它不静默：候选失败 → 事件流里有一条带数量的降级记录。
    事件 reason 只带类型名/数量（脱敏不变量），根因只进日志。
    """

    class ExplodingCapability:
        """写入入口（契约的 `consolidate`）整体不可用：连降级写入都失败。"""

        async def store(self, scope, content, metadata):
            raise ConnectionError("milvus down")

        async def consolidate(self, scope, content, metadata, *, budget_seconds=None):
            raise ConnectionError("milvus down")

    class OneCandidate:
        async def extract(self, events):
            return ExtractionOutcome([(MemoryScope.USER, "会失败的一条", {"importance": 0.5})])

    session = make_session(tmp_path)
    writer = MemoryWriteback(ExplodingCapability(), OneCandidate())
    writer.submit(session, session.events)
    await writer.drain()

    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert len(degraded) == 1
    assert degraded[0].data["operation"] == "writeback"
    assert degraded[0].data["reason"] == "partial: 1/1 candidates failed"


@pytest.mark.asyncio
async def test_real_langmem_delete_failure_degrades_but_never_drops_the_candidate(tmp_path):
    """AC5 的真身：**真** LangMem 链路上的删除失败必须落 `memory/degraded`，且候选不丢。

    与上一条（合成 capability）的区别是走了完整链路：脚本化模型发 RemoveDoc → 真
    manager/trustcall → 真 adapter → 记录层 `delete` 抛错（存储不可用）。

    #158 把写入入口换成 `consolidate` 之后，这条路径的语义**变强**了：消解失败不再让候选
    一起失败（旧的 `partial: 1/1`），而是降级成"只新增"——所以这里同时断言两件事：
    ``consolidation`` 降级可见（不静默）+ 候选真的落盘（不丢写）。reason 只带类型名。
    """
    pytest.importorskip("langmem")
    from langchain_core.messages import AIMessage

    from agent_harness.identity import (
        IdentityContext,
        identity_context_var,
        set_identity_context,
    )
    from agent_harness.memory.langmem_capability import LangMemMemoryCapability
    from agent_harness.memory.outbox_relay import OutboxRelay
    from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
    from agent_harness.memory.types import MemoryEntry, MemoryNamespace
    from tests.langmem_doubles import (
        AlwaysHitVectorStore,
        ScriptedChatModel,
        stable_doc_id,
    )

    alice = IdentityContext("acme", "alice", ["user"])

    class FailingDelete(SqliteMemoryRecordStore):
        """底层存储不可用：删除一律失败（真路径上的失败，而不是被调用的假对象）。"""

        async def delete(self, memory_id, identity):
            raise ConnectionError("storage unavailable")

    class OneCandidate:
        async def extract(self, events):
            return ExtractionOutcome([(MemoryScope.USER, "alice 现在用 Rust", {"importance": 0.5})])

    records = FailingDelete(tmp_path / "memory.db")
    await records.initialize()
    vectors = AlwaysHitVectorStore()
    model = ScriptedChatModel(responses=[AIMessage(content="", tool_calls=[{
        "name": "RemoveDoc",
        "args": {"json_doc_id": stable_doc_id(
            "m1", MemoryNamespace.of(MemoryScope.USER, alice).as_tuple())},
        "id": "remove-one"}])])
    capability = LangMemMemoryCapability(records, vectors, model)
    session = make_session(tmp_path)

    token = set_identity_context(alice)
    try:
        await records.store(MemoryEntry(id="m1", content="alice 喜欢 Python", metadata={},
                                       scope=MemoryScope.USER,
                                       created_at="2026-09-04T00:00:00+00:00"), alice)
        assert await OutboxRelay(records, vectors).flush() == 1
        writer = MemoryWriteback(capability, OneCandidate())
        writer.submit(session, session.events)
        await writer.drain()
        written = [entry.content for entry in await records.list_by_scope(MemoryScope.USER, alice, 10)]
    finally:
        identity_context_var.reset(token)

    degraded = [e for e in session.events if e.type == "memory/degraded"]
    assert len(degraded) == 1
    assert degraded[0].data["operation"] == "consolidation"
    assert degraded[0].data["reason"].startswith("consolidation_failed: ")
    assert "storage unavailable" not in degraded[0].data["reason"]
    assert "alice 现在用 Rust" in written
