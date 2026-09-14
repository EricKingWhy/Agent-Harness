"""#158 MEM-3 冲突消解（retrieve-before-write）契约面。

这几组断言对应票面最容易被"看起来实现了"糊过去的地方：

1. **不丢写**：检索/决策失败必须降级成"只新增"，且**真的有一条记忆落盘**（AC5）；
2. **降级可见且脱敏**：原因只含阶段 + 异常类型名，原始异常消息（可能含用户数据/密钥）不进
   `MemoryWriteOutcome`（AC5 + BUG-012 的脱敏契约）；
3. **注入有界**：交给 provider 的既有记忆，条数与每条字符数都有上界（AC4）；
4. **决策真的落到既有记忆上**（AC1/AC2/AC7）：`consolidate` 先检索再落 #156 的机制——
   update / no-op 都在这里端到端钉住（insert/delete 见 #157 的 `test_langmem_store_actions`）。
"""

import asyncio

import pytest

from agent_harness.identity import (
    IdentityContext,
    identity_context_var,
    set_identity_context,
)
from agent_harness.memory.capability import NO_DECISION_MODEL, MemoryWriteOutcome
from agent_harness.memory.consolidation import (
    CONSOLIDATION_QUERY_LIMIT,
    INJECTED_MEMORY_CHAR_LIMIT,
    TRUNCATION_MARKER,
    BoundedSearchStore,
)
from agent_harness.memory.fake_capability import FakeMemoryCapability
from agent_harness.memory.fake_vector_store import FakeVectorStore
from agent_harness.memory.outbox_relay import OutboxRelay
from agent_harness.memory.sqlite_record_store import SqliteMemoryRecordStore
from agent_harness.memory.types import (
    MemoryEntry,
    MemoryNamespace,
    MemoryScope,
    public_metadata,
)
from tests.langmem_doubles import (
    AlwaysHitVectorStore,
    HangingChatModel,
    ScriptedChatModel,
    stable_doc_id,
)

ALICE = IdentityContext("acme", "alice", ["user"])


class _ExplodingSearchStore(FakeVectorStore):
    """检索必炸的向量后端（Milvus 不可用/超时的替身）。"""

    async def search(self, query, identity, scope, limit):  # type: ignore[override]
        raise ConnectionError("milvus is down: secret-ish detail")


class _HangingSearchStore(FakeVectorStore):
    """检索**卡住**（不抛错）的向量后端：用来让 provider 侧的时间预算真的到期。"""

    async def search(self, query, identity, scope, limit):  # type: ignore[override]
        await asyncio.sleep(30)


async def _langmem(tmp_path, vectors, *, model=None, consolidation_timeout=None, query_limit=None):
    """真 capability + 真 adapter；模型/预算走**构造参数**（不 poke 私有属性）。"""
    pytest.importorskip("langmem")
    from agent_harness.memory.langmem_capability import LangMemMemoryCapability

    records = SqliteMemoryRecordStore(tmp_path / "memory.db")
    await records.initialize()
    kwargs = {}
    if consolidation_timeout is not None:
        kwargs["consolidation_timeout"] = consolidation_timeout
    if query_limit is not None:
        kwargs["query_limit"] = query_limit
    return LangMemMemoryCapability(records, vectors, model, **kwargs), records


# ── AC5：降级不得丢写 ──


@pytest.mark.asyncio
async def test_consolidate_without_a_model_still_writes_and_reports_it(tmp_path):
    """没配决策模型：无从"检索后决策" → 如实报告，但**候选照写**。"""
    capability, _records = await _langmem(tmp_path, FakeVectorStore())
    token = set_identity_context(ALICE)
    try:
        outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {"importance": 0.5})
        assert isinstance(outcome, MemoryWriteOutcome)
        assert outcome.degraded_reason == NO_DECISION_MODEL
        assert outcome.id
        entries = await capability.list_entries(MemoryScope.USER, 10)
        assert [entry.content for entry in entries] == ["我喜欢黑咖啡"]
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_retrieval_failure_degrades_to_insert_without_losing_the_candidate(tmp_path):
    """**本票最容易做错的形状**：检索炸了 → 候选仍然落盘，且降级原因可上报。

    没有这条保证，#158 就是"让 Milvus 抖动变成静默丢记忆"。
    """
    # 给了模型才会走"检索 + 决策"这条路（AC1）；检索在这里必炸。
    capability, _ = await _langmem(tmp_path, _ExplodingSearchStore(),
                                   model=ScriptedChatModel(responses=[]))
    token = set_identity_context(ALICE)
    try:
        outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {"importance": 0.5})
        assert outcome.degraded_reason is not None
        assert outcome.degraded_reason.startswith("consolidation_failed: ")
        entries = await capability.list_entries(MemoryScope.USER, 10)
        assert [entry.content for entry in entries] == ["我喜欢黑咖啡"]
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_retrieval_timeout_degrades_to_insert_without_losing_the_candidate(tmp_path):
    """AC5 的超时形态：检索**卡住**（不是抛错）→ 预算到期 → 降级写入，候选仍在。

    这条是与"外层 writeback 预算"配套的：`consolidate` 必须自己先到期并降级，
    否则取消会越过降级边界（CancelledError 不是 Exception）。
    """
    capability, _records = await _langmem(tmp_path, _HangingSearchStore(),
                                          model=ScriptedChatModel(responses=[]),
                                          consolidation_timeout=0.05)
    token = set_identity_context(ALICE)
    try:
        outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
        # BUG-014：预算超时是内部预算耗尽语义，不重试（重试注定再超时）。
        assert outcome.degraded_reason == "consolidation_failed: TimeoutError"
        entries = await capability.list_entries(MemoryScope.USER, 10)
        assert [entry.content for entry in entries] == ["我喜欢黑咖啡"]
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_degradation_reason_carries_only_the_exception_type(tmp_path):
    """脱敏：原因里不得出现原始异常消息（它可能含用户数据/凭据）。"""
    capability, _ = await _langmem(tmp_path, _ExplodingSearchStore(),
                                   model=ScriptedChatModel(responses=[]))
    token = set_identity_context(ALICE)
    try:
        outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
        assert outcome.degraded_reason == "consolidation_failed: ConnectionError(after_1_retry)"
        assert "secret-ish" not in outcome.degraded_reason
    finally:
        identity_context_var.reset(token)


# ── AC4：注入有界（条数 + 每字符数）──


@pytest.mark.asyncio
async def test_bounded_store_caps_item_count_and_chars(tmp_path):
    """provider 面向 prompt 的检索结果：条数 ≤ query_limit、每条 ≤ 字符上界，且带截断标记。

    包的是**真 adapter**（`SqliteMilvusBaseStore`），所以这条同时证明"包一层不改变写/读路径"。
    """
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    long_content = "长" * (INJECTED_MEMORY_CHAR_LIMIT * 3)
    token = set_identity_context(ALICE)
    try:
        for index in range(CONSOLIDATION_QUERY_LIMIT + 4):
            await capability.store(MemoryScope.USER, f"{long_content}-{index}", {"tag": index})
        # 写入先落权威记录，向量索引由 outbox 异步接力（#158 之前就有的形状）。
        await OutboxRelay(records, vectors).flush()
        namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
        bounded = BoundedSearchStore(capability._store, max_chars=INJECTED_MEMORY_CHAR_LIMIT)
        # 故意要一个**大于**上界的 limit：条数上界必须是本代理执行的，
        # 而不是"上游恰好按我传的 limit 裁了"（真机 gate 实测上游会给回 6 条）。
        items = await bounded.asearch(namespace, query="长", limit=CONSOLIDATION_QUERY_LIMIT + 4)
        assert len(items) == CONSOLIDATION_QUERY_LIMIT
        for item in items:
            payload = item.value["content"]["content"]
            assert len(payload) <= INJECTED_MEMORY_CHAR_LIMIT + len(TRUNCATION_MARKER)
            assert payload.endswith(TRUNCATION_MARKER)
        # 观测面：#158 AC3 要能看见"这次检索真的发生了、检索到几条、截/丢了几条"。
        assert bounded.stats.searches == 1
        assert bounded.stats.retrieved_items == CONSOLIDATION_QUERY_LIMIT + 4
        assert bounded.stats.truncated_items == CONSOLIDATION_QUERY_LIMIT
        assert bounded.stats.dropped_items == 4
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_bounded_store_does_not_touch_short_items_or_the_write_path(tmp_path):
    """上界只影响"超长"的注入：短记忆内容逐字不变，`aput` 仍走真 adapter 落权威记录。"""
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    token = set_identity_context(ALICE)
    try:
        await capability.store(MemoryScope.USER, "短记忆", {"importance": 0.4})
        await OutboxRelay(records, vectors).flush()
        namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
        bounded = BoundedSearchStore(capability._store, max_chars=INJECTED_MEMORY_CHAR_LIMIT)
        items = await bounded.asearch(namespace, query="短", limit=5)
        assert [item.value["content"]["content"] for item in items] == ["短记忆"]
        assert bounded.stats.truncated_items == 0

        await bounded.aput(namespace, "written-through-id", {
            "kind": "MemoryPayload",
            "content": {"content": "经代理写进去的", "metadata": {"importance": 0.5}},
        })
        entries = await capability.list_entries(MemoryScope.USER, 10)
        assert "经代理写进去的" in {entry.content for entry in entries}
    finally:
        identity_context_var.reset(token)


# ── AC1/AC2/AC7：先检索、再把决策落到既有记忆上 ──


async def _seed(records, vectors, content: str, *, identity=ALICE, tag: str = "seed") -> str:
    """经权威记录层播种一条既有记忆，并用 relay 让它可被检索（真 adapter 路径）。"""
    memory_id = await records.store(MemoryEntry(
        id=f"seed-{tag}", content=content, metadata={}, scope=MemoryScope.USER,
        created_at="2026-09-01T00:00:00+00:00"), identity)
    assert await OutboxRelay(records, vectors).flush() == 1
    return memory_id


@pytest.mark.asyncio
async def test_consolidate_retrieves_the_existing_memory_then_applies_the_decision(tmp_path, caplog):
    """AC1 + AC2（update）：先检索既有记忆，再把"取代"落到同一条记录上。

    与 #157 的 `store()` 版测试的差别在**入口**：这条走 `consolidate`（#158 的契约入口），
    并额外钉住"这次写入确实先检索了"（否则"冲突被消解"可能只是碰巧没查到）。
    """
    import logging

    from langchain_core.messages import AIMessage

    vectors = AlwaysHitVectorStore()
    # 模型是"决策替身"：真正要断言的 doc id 依赖播种出来的 memory_id，所以先占位、
    # 播种后再把响应换掉（`responses` 是可替换的列表）。
    model = ScriptedChatModel(responses=[])
    capability, records = await _langmem(tmp_path, vectors, model=model)
    namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
    token = set_identity_context(ALICE)
    try:
        memory_id = await _seed(records, vectors, "我喜欢用 TypeScript 写后端")
        model.responses = [AIMessage(content="", tool_calls=[{
            "name": "PatchDoc",
            "args": {"json_doc_id": stable_doc_id(memory_id, namespace),
                     "planned_edits": "用户改用 Go 了",
                     "patches": [{"op": "replace", "path": "/content",
                                  "value": "我现在用 Go 写后端"}]},
            "id": "patch-one"}])]
        with caplog.at_level(logging.INFO, logger="agent_harness.memory"):
            outcome = await capability.consolidate(
                MemoryScope.USER, "我现在改用 Go 了，不再用 TypeScript", {"importance": 0.7})
        entries = await capability.list_entries(MemoryScope.USER, 10)
    finally:
        identity_context_var.reset(token)

    assert outcome.degraded_reason is None
    assert outcome.id == memory_id  # update 到既有那条，而不是新增
    assert [(entry.id, entry.content) for entry in entries] == [(memory_id, "我现在用 Go 写后端")]
    # AC1 的关键证据：这次写入**先检索了**（1 次检索、命中 1 条既有记忆），
    # 而不是"没查到、所以看起来只新增了"。
    events = [record for record in caplog.records if getattr(record, "event_type", None) == "memory_consolidated"]
    assert [(event.queries, event.retrieved) for event in events] == [(1, 1)]


@pytest.mark.asyncio
async def test_consolidate_no_op_decision_does_not_create_a_duplicate_row(tmp_path):
    """AC2（no-op）：provider 判定"无需改动"时不新增行，也不丢既有记忆。

    上游用"没有工具调用"表达 no-op。`consolidate` 的兜底只在**逐字相同**时复用既有 id：
    这样 no-op 不产生重复，而"内容不同却没做出决策"仍按新增保底（不丢写优先）。
    """
    from langchain_core.messages import AIMessage

    vectors = AlwaysHitVectorStore()
    capability, records = await _langmem(tmp_path, vectors,
                                         model=ScriptedChatModel(
                                             responses=[AIMessage(content="这条记忆已经存在，无需改动。")]))
    token = set_identity_context(ALICE)
    try:
        memory_id = await _seed(records, vectors, "我喜欢黑咖啡")
        outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
        entries = await capability.list_entries(MemoryScope.USER, 10)
    finally:
        identity_context_var.reset(token)

    assert outcome.degraded_reason is None
    assert outcome.id == memory_id
    assert [entry.id for entry in entries] == [memory_id]


# ── 写回编排：降级必须落到 memory/degraded（BUG-012 的契约）──


@pytest.mark.asyncio
async def test_writeback_records_degraded_consolidation(tmp_path):
    """writeback 是唯一有 session 的地方：它负责把 provider 报的降级原因落成事件。"""
    from agent_harness.memory.writeback import MemoryWriteback
    from agent_harness.session.event import MEMORY_DEGRADED
    from tests.conftest import make_session

    capability = FakeMemoryCapability(consolidation_degraded_reason="consolidation_failed: VectorStoreError")
    session = make_session(tmp_path)
    writer = MemoryWriteback(capability, _OneCandidate())
    # 身份必须在 writeback 之前就位（替身按 `get_identity_context()` 定 namespace，
    # 真机里由 Runtime 在跑 agent 之前设置）。
    token = set_identity_context(ALICE)
    try:
        writer.submit(session, session.events)
        await writer.drain()
        events = [event for event in session.events if event.type == MEMORY_DEGRADED]
        assert [(event.data["operation"], event.data["reason"]) for event in events] == [
            ("consolidation", "consolidation_failed: VectorStoreError"),
        ]
        # 降级 ≠ 丢写：候选照写。
        assert [entry.content for entry in await capability.list_entries(MemoryScope.USER, 5)] == ["候选"]
    finally:
        identity_context_var.reset(token)


class _OneCandidate:
    """抽取端口替身：一个 USER 候选。"""

    async def extract(self, events):
        from agent_harness.memory.extractor import ExtractionOutcome

        return ExtractionOutcome([(MemoryScope.USER, "候选", {"importance": 0.5})])


class _ManyCandidates:
    def __init__(self, count: int) -> None:
        self._count = count

    async def extract(self, events):
        from agent_harness.memory.extractor import ExtractionOutcome

        return ExtractionOutcome([(MemoryScope.USER, f"候选-{index}", {"importance": 0.5})
                                  for index in range(self._count)])


class _BudgetRecordingCapability:
    """记录每次调用拿到的预算，并**遵守**它（模拟 provider 的"预算内决策、超时降级"）。"""

    def __init__(self) -> None:
        self.budgets: list[float | None] = []
        self.written: list[str] = []

    async def consolidate(self, scope, content, metadata, *, budget_seconds=None):
        from agent_harness.memory.capability import MemoryWriteOutcome

        self.budgets.append(budget_seconds)
        degraded = None
        if budget_seconds is not None and budget_seconds > 0.1:
            await asyncio.sleep(min(budget_seconds, 0.05))
        elif budget_seconds is not None:
            degraded = "consolidation_failed: TimeoutError"
        self.written.append(content)
        return MemoryWriteOutcome(str(len(self.written)), degraded_reason=degraded)


# ── 预算嵌套：provider 侧必须先到期，降级写入才有机会跑 ──


def test_consolidation_budget_nests_inside_writeback():
    """常量级不变量：provider 决策预算 + 降级余量必须装得进外层预算。

    两个 `asyncio.timeout` 是嵌套的（writeback 包住整个候选循环）。若 provider 侧不先到期，
    外层取消会以 `CancelledError` 穿过 `consolidate` 的降级边界——"超时不丢写"当场失效。
    """
    from agent_harness.memory.consolidation import CONSOLIDATION_TIMEOUT_SECONDS
    from agent_harness.memory.writeback import (
        _FALLBACK_RESERVE_SECONDS,
        WRITEBACK_TIMEOUT_SECONDS,
    )

    assert CONSOLIDATION_TIMEOUT_SECONDS < WRITEBACK_TIMEOUT_SECONDS
    # 第一个候选必须能拿到**完整**的默认预算（不是被余量啃掉一截）。
    assert CONSOLIDATION_TIMEOUT_SECONDS + _FALLBACK_RESERVE_SECONDS <= WRITEBACK_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_writeback_budgets_shrink_with_the_remaining_time_and_keep_the_reserve(tmp_path):
    """每个候选的预算必须来自"外层剩余时间 − 降级余量"，且随剩余时间单调收窄。"""
    from agent_harness.memory.writeback import (
        _FALLBACK_RESERVE_SECONDS,
        MemoryWriteback,
    )
    from tests.conftest import make_session

    capability = _BudgetRecordingCapability()
    session = make_session(tmp_path)
    token = set_identity_context(ALICE)
    try:
        writer = MemoryWriteback(capability, _ManyCandidates(3), timeout_seconds=5.0)
        writer.submit(session, session.events)
        await writer.drain()
    finally:
        identity_context_var.reset(token)

    assert len(capability.budgets) == 3
    # 上界：外层预算 − 余量（第一个候选实测就在这个量级；睡眠只让后面的更小）。
    assert all(budget is not None and budget <= 5.0 - _FALLBACK_RESERVE_SECONDS
               for budget in capability.budgets)
    # 单调不增，且**真的随剩余时间收窄**：每个候选实测睡掉 50ms，所以首尾必须出现可见差值——
    # 只断言"有序"的话，一个恒定预算的变异（`return 3.0`）也能通过（code-review P2）。
    assert all(earlier >= later for earlier, later
               in zip(capability.budgets, capability.budgets[1:]))
    assert capability.budgets[0] > capability.budgets[-1]
    # 三个候选**都写了**：预算收窄不得变成丢写。
    assert capability.written == ["候选-0", "候选-1", "候选-2"]


@pytest.mark.asyncio
async def test_exhausted_budget_degrades_provider_side_instead_of_cancelling(tmp_path):
    """预算耗尽 → 立刻按"降级"处理（provider 返回降级原因），不是被外层取消。"""
    from agent_harness.memory.writeback import MemoryWriteback
    from agent_harness.session.event import MEMORY_DEGRADED
    from tests.conftest import make_session

    capability = _BudgetRecordingCapability()
    session = make_session(tmp_path)
    token = set_identity_context(ALICE)
    try:
        # 外层预算比"降级余量"还小 → 每个候选拿到的预算都是 0 → 全部立刻降级。
        writer = MemoryWriteback(capability, _ManyCandidates(2), timeout_seconds=0.5)
        writer.submit(session, session.events)
        await writer.drain()
    finally:
        identity_context_var.reset(token)

    assert capability.budgets == [0.0, 0.0]
    assert capability.written == ["候选-0", "候选-1"]  # 不丢写
    degraded = [event for event in session.events if event.type == MEMORY_DEGRADED]
    assert [(event.data["operation"], event.data["reason"]) for event in degraded] == [
        ("consolidation", "consolidation_failed: TimeoutError")]


@pytest.mark.asyncio
async def test_provider_takes_the_smaller_of_the_caller_budget_and_its_own_default(tmp_path):
    """预算是 `min(调用方给的, provider 默认)`，两个方向都要真的生效（带时限断言）。

    方向一（provider 默认更小）拦住"调用方给个大预算就能让 provider 无限等"；
    方向二（调用方给的更小）拦住"调用方预算被吞掉、外层预算白算"。用时限断言语义化：
    不生效的那一边会让耗时落到自己的预算上（1.0s / 5.0s），远大于 0.5s 的判据。
    """
    loop = asyncio.get_running_loop()
    capability, _records = await _langmem(tmp_path, _HangingSearchStore(),
                                          model=ScriptedChatModel(responses=[]))
    token = set_identity_context(ALICE)

    async def _timed(budget: float) -> tuple[float, str | None]:
        started = loop.time()
        outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {},
                                               budget_seconds=budget)
        return loop.time() - started, outcome.degraded_reason

    try:
        # 方向一：默认 0.05 必须压住调用方的 1.0。
        capability._consolidation_timeout = 0.05
        elapsed_a, reason_a = await _timed(1.0)
        # 方向二：调用方的 0.05 必须压住默认的 5.0。
        capability._consolidation_timeout = 5.0
        elapsed_b, reason_b = await _timed(0.05)
        entries = await capability.list_entries(MemoryScope.USER, 10)
    finally:
        identity_context_var.reset(token)

    # BUG-014：预算超时是内部预算耗尽语义，不重试，无标记。
    assert (reason_a, reason_b) == ("consolidation_failed: TimeoutError",
                                    "consolidation_failed: TimeoutError")
    assert elapsed_a < 0.5, f"provider 默认没生效：{elapsed_a:.2f}s"
    assert elapsed_b < 0.5, f"调用方预算没生效：{elapsed_b:.2f}s"
    # 两次都降级写入（不丢写），内容不同所以两条都在。
    assert [entry.content for entry in entries] == ["我喜欢黑咖啡", "我喜欢黑咖啡"]


@pytest.mark.asyncio
async def test_a_broken_log_handler_cannot_rewrite_the_degradation_reason(tmp_path):
    """观测面故障不得改写功能语义：第三方 handler 抛异常时，降级原因仍是真实原因。

    自定义 `Handler.emit` 抛异常会一路穿出 `logging`（CPython 不替它兜底），而我们在
    **异常处理路径**上既 `warning` 又 `log_event`——两处都不兜底的话，真实原因会被
    handler 的异常类型顶掉（真机 gate 上真踩到：gate 自己的采集 handler 写错字段名）。

    显式把 logger 调到 INFO：否则 `log_event` 的 INFO 事件会被 root 的 WARNING 级别过滤掉，
    这条用例就只能覆盖到 `warning` 那一处（变异门禁会当场证明它是空转的）。
    """
    import logging

    capability, _records = await _langmem(tmp_path, _ExplodingSearchStore(),
                                          model=ScriptedChatModel(responses=[]))

    class _BrokenHandler(logging.Handler):
        def emit(self, record):
            raise AttributeError("handler bug")

    logger = logging.getLogger("agent_harness.memory")
    broken = _BrokenHandler()
    logger.addHandler(broken)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    token = set_identity_context(ALICE)
    try:
        outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
        entries = await capability.list_entries(MemoryScope.USER, 5)
    finally:
        identity_context_var.reset(token)
        logger.removeHandler(broken)
        logger.setLevel(previous_level)

    assert outcome.degraded_reason == "consolidation_failed: ConnectionError(after_1_retry)"
    assert [entry.content for entry in entries] == ["我喜欢黑咖啡"]


@pytest.mark.asyncio
async def test_consolidation_failure_is_still_observable_with_its_retrieval_cost(tmp_path, caplog):
    """AC3：决策超时/失败时，这次多出来的检索**也要可见**（不能只有 writeback 的降级事件）。

    之前只在成功分支 log_event，超时那一刻什么都不留——而开销（一次检索 + 一次跑到一半的
    LLM 调用）恰恰已经发生了。
    """
    import logging

    # 卡在**决策**阶段（检索已完成）：这才是"检索开销已付出、决策还没回来"的真实形状。
    capability, _records = await _langmem(tmp_path, AlwaysHitVectorStore(),
                                          model=HangingChatModel(responses=[]),
                                          consolidation_timeout=0.05)
    token = set_identity_context(ALICE)
    try:
        with caplog.at_level(logging.INFO, logger="agent_harness.memory"):
            outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
        # 降级 ≠ 丢写（身份还在上下文里，读得到本 namespace）。
        entries = await capability.list_entries(MemoryScope.USER, 5)
    finally:
        identity_context_var.reset(token)

    assert outcome.degraded_reason == "consolidation_failed: TimeoutError"
    assert [entry.content for entry in entries] == ["我喜欢黑咖啡"]
    events = [record for record in caplog.records if getattr(record, "event_type", None) == "memory_consolidated"]
    assert len(events) == 1
    assert events[0].status == "failed"
    assert events[0].error_type == "TimeoutError"
    assert events[0].queries >= 1  # 检索真的发生了（开销可见）
    assert events[0].latency_ms is not None  # 耗时字段必须存在（值本身随环境浮动）


# ── 生产装配：模型必须真的接上（否则 consolidate 永远走 no_decision_model）──


def test_builtin_memory_wiring_passes_a_decision_model(tmp_path, monkeypatch):
    """AC1 的装配前提：生产形状必须给 capability 一个决策模型。

    `factories.build_memory_components` 此前**没传**模型，于是 `store()` 的 manager 分支
    从不执行 —— "写入只能新增"的真正机制在这里，而不是票面推测的 `query_model`。
    """
    import agent_harness.memory.langmem_capability as module

    captured: dict = {}

    class _Recorder:
        def __init__(self, records, vectors, model=None, **kwargs):
            captured["model"] = model
            captured["kwargs"] = kwargs

    monkeypatch.setattr(module, "LangMemMemoryCapability", _Recorder)
    # 必须打在 factories 的模块属性上：它 `from ... import create_chat_model` 已绑定。
    monkeypatch.setattr(
        "agent_harness.capability.factories.create_chat_model", lambda config, **kw: "sentinel-model"
    )
    from agent_harness.capability.factories import build_memory_components
    from agent_harness.config import Settings

    build_memory_components(
        Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            model_api_key="sk-test",
            # milvus + embedding 是装配的前置条件（缺一则 builder 直接返回 None）：
            # 本用例要证的是"装配真的走到 capability 构造并喂了模型"。
            milvus_uri="https://example.test",
            milvus_token="test-only",
            milvus_collection="col",
            embedding_model="m",
            embedding_base_url="https://x",
            embedding_api_key="k",
        )
    )
    assert captured["model"] == "sentinel-model"


# ── P0 回归：截断投影**不得**被回写进权威记录（Standards review 抓到）──


@pytest.mark.asyncio
async def test_a_metadata_only_patch_never_persists_the_truncated_projection(tmp_path):
    """上界是"给模型看的投影"，不是"该落盘的内容"：只改 metadata 的决策不得把正文截断写回。

    机制：manager 拿到的既有记忆既是 prompt，**也是** trustcall 打 patch 的基线
    （`langmem/knowledge/extraction.py`：`store_based` 来自 `store_map`，`final_puts` 在
    value 变化时 `store.aput(...)`）。如果不处理，一次只动 metadata 的 PatchDoc 会把
    "前 1000 字符 + …[已截断]" 当成新正文写回权威记录——静默吃掉长记忆的尾部。
    """
    from langchain_core.messages import AIMessage

    vectors = AlwaysHitVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
    full_text = "用户的长期偏好记录。" * (INJECTED_MEMORY_CHAR_LIMIT // 4)
    assert len(full_text) > INJECTED_MEMORY_CHAR_LIMIT * 2
    token = set_identity_context(ALICE)
    try:
        memory_id = await _seed(records, vectors, full_text)
        capability._model = ScriptedChatModel(responses=[AIMessage(content="", tool_calls=[{
            "name": "PatchDoc",
            "args": {"json_doc_id": stable_doc_id(memory_id, namespace),
                     "planned_edits": "只补一个 metadata 字段",
                     "patches": [{"op": "add", "path": "/metadata/seen", "value": True}]},
            "id": "patch-metadata"}])])  # 私有替身：doc id 需要播种后的 id，只能晚绑定
        outcome = await capability.consolidate(
            MemoryScope.USER, "顺手记一下：我们聊过这个偏好", {"importance": 0.5})
        stored = await records.get(memory_id, ALICE)
    finally:
        identity_context_var.reset(token)

    assert outcome.degraded_reason is None
    assert stored.content == full_text, "截断投影被写进了权威记录"
    assert TRUNCATION_MARKER not in stored.content
    assert stored.metadata.get("seen") is True  # 决策本身仍然落盘


# ── code-review 修复面：截断投影修复 / 成本记账 / 观测兜底 ──


@pytest.mark.asyncio
async def test_write_back_repair_only_touches_our_truncated_projection(tmp_path):
    """`aput` 只修"确实是本代理截断出来的那一份投影"，其余写入原样透传。

    三种不该动的形状：①短内容（没有标记）；②内容自带标记但**那一行**的正文并不以它为前缀
    （别的文本）；③行根本不存在（新建）。猜错等于静默改坏 provider 的写。
    """
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
    bounded = BoundedSearchStore(capability._store, max_chars=INJECTED_MEMORY_CHAR_LIMIT)
    token = set_identity_context(ALICE)
    try:
        payload = {"kind": "MemoryPayload", "content": {"content": "短内容", "metadata": {}}}
        await bounded.aput(namespace, "no-marker", payload)
        assert (await records.get("no-marker", ALICE)).content == "短内容"

        # ② 既有行的正文与"投影前缀"对不上：必须原样写入（不能被既有正文顶掉）
        await records.store(MemoryEntry(id="unrelated-row", content="原有正文", metadata={},
                                        scope=MemoryScope.USER,
                                        created_at="2026-09-01T00:00:00+00:00"), ALICE)
        marked_but_unrelated = f"完全不同的正文{TRUNCATION_MARKER}"
        await bounded.aput(namespace, "unrelated-row",
                           {"kind": "MemoryPayload",
                            "content": {"content": marked_but_unrelated, "metadata": {}}})
        assert (await records.get("unrelated-row", ALICE)).content == marked_but_unrelated

        # ③ 行不存在（新建）：带标记也不猜
        await bounded.aput(namespace, "brand-new",
                           {"kind": "MemoryPayload",
                            "content": {"content": f"新记忆{TRUNCATION_MARKER}", "metadata": {}}})
        assert (await records.get("brand-new", ALICE)).content == f"新记忆{TRUNCATION_MARKER}"

        assert bounded.stats.repaired_items == 0  # 没有一条被"修"过
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_the_proxy_still_forwards_delete_and_get_to_the_real_store(tmp_path):
    """代理不得改变 provider 的写/读路径：`adelete`/`aget` 原样透传（#157 的删除链路）。

    manager 判"这条过时了"时走的就是 `store.adelete`——代理吞掉它，删除就静默失效。
    """
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
    bounded = BoundedSearchStore(capability._store)
    token = set_identity_context(ALICE)
    try:
        await records.store(MemoryEntry(id="doomed", content="等着被删", metadata={},
                                        scope=MemoryScope.USER,
                                        created_at="2026-09-01T00:00:00+00:00"), ALICE)
        assert (await bounded.aget(namespace, "doomed")) is not None
        await bounded.adelete(namespace, "doomed")
        with pytest.raises(KeyError):
            await records.get("doomed", ALICE)
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_write_back_repair_restores_the_full_body_and_is_counted(tmp_path):
    """正例：投影 + metadata 变化 → 正文恢复全文，metadata 更新，并且**被计数**（AC3）。"""
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
    full_text = "长" * (INJECTED_MEMORY_CHAR_LIMIT * 2)
    bounded = BoundedSearchStore(capability._store, max_chars=INJECTED_MEMORY_CHAR_LIMIT)
    token = set_identity_context(ALICE)
    try:
        await records.store(MemoryEntry(id="long-one", content=full_text, metadata={"seen": False},
                                        scope=MemoryScope.USER,
                                        created_at="2026-09-01T00:00:00+00:00"), ALICE)
        projection = full_text[:INJECTED_MEMORY_CHAR_LIMIT] + TRUNCATION_MARKER
        await bounded.aput(namespace, "long-one",
                           {"kind": "MemoryPayload",
                            "content": {"content": projection, "metadata": {"seen": True}}})
        restored = await records.get("long-one", ALICE)
        assert restored.content == full_text
        # 行里除了用户 metadata 还挂着 provider 的内部载荷（`_langmem_value`）：
        # 这里读的是"用户可见"的那一层。
        assert public_metadata(restored.metadata) == {"seen": True}
        assert bounded.stats.repaired_items == 1
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_retrieval_failure_is_counted_as_a_search(tmp_path, caplog):
    """AC3：检索**抛错**也要记成一次检索（计数在 await 之前），否则不可用路径永远 queries=0。"""
    import logging

    capability, _records = await _langmem(tmp_path, _ExplodingSearchStore(),
                                          model=ScriptedChatModel(responses=[]))
    token = set_identity_context(ALICE)
    try:
        with caplog.at_level(logging.INFO, logger="agent_harness.memory"):
            await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
    finally:
        identity_context_var.reset(token)

    events = [record for record in caplog.records if getattr(record, "event_type", None) == "memory_consolidated"]
    # BUG-014：ConnectionError 瞬时错误重试 1 次 → 两次 attempt 各发一条事件。
    assert [(event.status, event.queries) for event in events] == [("failed", 1), ("failed", 1)]


@pytest.mark.asyncio
async def test_no_op_fallback_search_is_counted_in_the_same_event(tmp_path, caplog):
    """AC3：no-op 之后那次兜底检索也要记进同一事件（`fallback_searches`）。"""
    import logging

    from langchain_core.messages import AIMessage

    vectors = AlwaysHitVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    token = set_identity_context(ALICE)
    try:
        await _seed(records, vectors, "我喜欢黑咖啡")
        capability._model = ScriptedChatModel(responses=[AIMessage(content="无需改动。")])
        with caplog.at_level(logging.INFO, logger="agent_harness.memory"):
            await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
    finally:
        identity_context_var.reset(token)

    events = [record for record in caplog.records if getattr(record, "event_type", None) == "memory_consolidated"]
    assert len(events) == 1
    assert events[0].queries == 1          # manager 的检索
    assert events[0].fallback_searches == 1  # no-op 之后的兜底检索
    assert events[0].decisions == 0


@pytest.mark.asyncio
async def test_degradation_event_persistence_failure_does_not_rewrite_the_reason(tmp_path):
    """降级事件的 append 失败不得把 `consolidation_failed` 顶成 `writeback / unavailable`。

    （code-review P2：消解降级分支的 append 此前没有同款保护，与紧邻的抽取分支不一致。）
    """
    from agent_harness.memory.writeback import MemoryWriteback
    from agent_harness.session.event import MEMORY_DEGRADED
    from tests.conftest import make_session

    capability = FakeMemoryCapability(consolidation_degraded_reason="consolidation_failed: VectorStoreError")
    session = make_session(tmp_path)
    original_append = session.append
    failed_once = False

    def flaky_append(event_type, data, **kwargs):
        nonlocal failed_once
        # **只炸第一次**：这样"没兜底"的版本会走到外层处理器再 append 一次（成功），
        # 事件流里就会多出一条 `writeback / unavailable: RuntimeError`——本用例正是判这个。
        if event_type == MEMORY_DEGRADED and not failed_once:
            failed_once = True
            raise RuntimeError("ledger-unavailable")
        return original_append(event_type, data, **kwargs)

    session.append = flaky_append  # type: ignore[method-assign]
    writer = MemoryWriteback(capability, _OneCandidate())
    token = set_identity_context(ALICE)
    try:
        writer.submit(session, session.events)
        await writer.drain()
        entries = await capability.list_entries(MemoryScope.USER, 5)
    finally:
        identity_context_var.reset(token)

    # 观测写失败 → 该条事件丢掉（不重试），但**不得**被改写成别的降级语义；候选照写。
    assert failed_once
    assert [event for event in session.events if event.type == MEMORY_DEGRADED] == []
    assert [entry.content for entry in entries] == ["候选"]


# ── 三轮 review 修复面：读不到就不许猜 / 计数只在落盘后 / 兜底检索失败也要记账 ──


class _BrokenStoreMethod:
    """把真 store 的**单个**方法弄坏，其余原样透传（测代理自身的防御，不动真适配器）。"""

    def __init__(self, inner, *, aget_raises=None, aput_raises=None):
        self._inner = inner
        self._aget_raises = aget_raises
        self._aput_raises = aput_raises

    async def aget(self, *args, **kwargs):
        if self._aget_raises is not None:
            raise self._aget_raises
        return await self._inner.aget(*args, **kwargs)

    async def aput(self, *args, **kwargs):
        if self._aput_raises is not None:
            raise self._aput_raises
        return await self._inner.aput(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _FallbackSearchExplodes(FakeVectorStore):
    """manager 的检索正常，no-op 之后那次**兜底检索**炸（测 AC3 的"失败路径也记"）。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def search(self, query, identity, scope, limit):  # type: ignore[override]
        self.calls += 1
        if self.calls >= 2:
            raise ConnectionError("fallback search is down: secret-ish detail")
        return await super().search(query, identity, scope, limit)


@pytest.mark.asyncio
async def test_repair_refuses_to_guess_the_body_when_the_row_cannot_be_read(tmp_path):
    """读不到权威正文时**不许**原样写入投影，必须把错误抛出去交给降级边界（code-review P0）。

    原样写入 = 把"前 1000 字符 + 标记"当事实落盘，正是本次修复要消灭的静默截尾；读失败时
    "猜投影就是正文"没有任何依据。抛出去 → `consolidate` 降级成整条新增，既有行原封不动
    ——宁可多一条，不可少一截。
    """
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
    full_text = "长" * (INJECTED_MEMORY_CHAR_LIMIT * 2)
    projection = full_text[:INJECTED_MEMORY_CHAR_LIMIT] + TRUNCATION_MARKER
    bounded = BoundedSearchStore(
        _BrokenStoreMethod(capability._store, aget_raises=ConnectionError("row read is down")))
    token = set_identity_context(ALICE)
    try:
        await records.store(MemoryEntry(id="long-one", content=full_text, metadata={},
                                        scope=MemoryScope.USER,
                                        created_at="2026-09-01T00:00:00+00:00"), ALICE)
        with pytest.raises(ConnectionError):
            await bounded.aput(namespace, "long-one",
                               {"kind": "MemoryPayload",
                                "content": {"content": projection, "metadata": {}}})
        stored = await records.get("long-one", ALICE)
    finally:
        identity_context_var.reset(token)

    assert stored.content == full_text, "读不到行时把截断投影写进了权威记录"
    assert TRUNCATION_MARKER not in stored.content
    assert bounded.stats.repaired_items == 0


@pytest.mark.asyncio
async def test_a_bare_marker_write_is_never_repaired_into_the_existing_row(tmp_path):
    """正文**恰好只有标记**时空字符串恒为前缀，会把任何既有行顶掉——不许猜（code-review P2）。"""
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
    bounded = BoundedSearchStore(capability._store, max_chars=INJECTED_MEMORY_CHAR_LIMIT)
    token = set_identity_context(ALICE)
    try:
        await records.store(MemoryEntry(id="existing", content="原有正文", metadata={},
                                        scope=MemoryScope.USER,
                                        created_at="2026-09-01T00:00:00+00:00"), ALICE)
        await bounded.aput(namespace, "existing",
                           {"kind": "MemoryPayload",
                            "content": {"content": TRUNCATION_MARKER, "metadata": {}}})
        stored = await records.get("existing", ALICE)
    finally:
        identity_context_var.reset(token)

    assert stored.content == TRUNCATION_MARKER
    assert bounded.stats.repaired_items == 0


@pytest.mark.asyncio
async def test_a_repaired_projection_is_counted_only_after_the_write_lands(tmp_path):
    """"修过一次"只有在真的写下去之后才算数：写失败时不能报 repaired（code-review P2）。"""
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    namespace = MemoryNamespace.of(MemoryScope.USER, ALICE).as_tuple()
    full_text = "长" * (INJECTED_MEMORY_CHAR_LIMIT * 2)
    projection = full_text[:INJECTED_MEMORY_CHAR_LIMIT] + TRUNCATION_MARKER
    bounded = BoundedSearchStore(
        _BrokenStoreMethod(capability._store, aput_raises=RuntimeError("write is down")))
    token = set_identity_context(ALICE)
    try:
        await records.store(MemoryEntry(id="long-one", content=full_text, metadata={},
                                        scope=MemoryScope.USER,
                                        created_at="2026-09-01T00:00:00+00:00"), ALICE)
        with pytest.raises(RuntimeError):
            await bounded.aput(namespace, "long-one",
                               {"kind": "MemoryPayload",
                                "content": {"content": projection, "metadata": {}}})
        stored = await records.get("long-one", ALICE)
    finally:
        identity_context_var.reset(token)

    assert stored.content == full_text      # 写入没发生 → 行没变
    assert bounded.stats.repaired_items == 0  # 也就不许报"修过"


@pytest.mark.asyncio
async def test_a_failing_no_op_fallback_search_still_reports_its_cost(tmp_path, caplog):
    """兜底检索抛错时：候选照写（不丢写），且这次检索**仍要可见**（AC3：失败路径也记）。

    计数必须在 await **之前**（与 `asearch` 同一口径），并且失败要发事件——否则这条路
    既丢了那次真实检索的开销，也丢了"决策已跑过"的事实。
    """
    import logging

    from langchain_core.messages import AIMessage

    vectors = _FallbackSearchExplodes()
    capability, records = await _langmem(tmp_path, vectors)
    token = set_identity_context(ALICE)
    try:
        await _seed(records, vectors, "我喜欢黑咖啡")
        capability._model = ScriptedChatModel(responses=[AIMessage(content="无需改动。")])
        with caplog.at_level(logging.INFO, logger="agent_harness.memory"):
            outcome = await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
        entries = await capability.list_entries(MemoryScope.USER, 5)
    finally:
        identity_context_var.reset(token)

    assert outcome.degraded_reason == "consolidation_failed: ConnectionError(after_1_retry)"
    # 兜底检索炸了 → 没有可比对的既有行 → 候选**无条件新增**（不丢写优先）。既有行还在，
    # 于是出现两条同内容：这是本票显式选的代价（宁可多一条，不可少一条），断言它而不是否认它。
    assert sorted(entry.content for entry in entries) == ["我喜欢黑咖啡", "我喜欢黑咖啡"]
    events = [record for record in caplog.records if getattr(record, "event_type", None) == "memory_consolidated"]
    # BUG-014：ConnectionError 是瞬时错误 → 重试 1 次后降级（原因带标记），
    # 两次 attempt 各发一条事件（开销如实计 2 次检索 + 兜底 1 次）。
    assert [(event.status, event.error_type.replace("(after_1_retry)", ""),
             event.fallback_searches) for event in events] == [
        ("failed", "ConnectionError", 1), ("failed", "ConnectionError", 0)]


@pytest.mark.asyncio
async def test_remaining_budget_is_arithmetic_on_the_deadline_and_clamps_at_zero():
    """直接钉 `_remaining_budget` 的算术与下界：常量返回值这种变异必须被杀死。"""
    from agent_harness.memory.writeback import (
        _FALLBACK_RESERVE_SECONDS,
        MemoryWriteback,
    )

    now = asyncio.get_running_loop().time()
    remaining = MemoryWriteback._remaining_budget(now + 5.0)
    assert _FALLBACK_RESERVE_SECONDS < remaining < 5.0  # 既扣了余量，也不是常量
    assert abs(remaining - (5.0 - _FALLBACK_RESERVE_SECONDS)) < 0.01
    assert MemoryWriteback._remaining_budget(now - 1.0) == 0.0  # 过期的 deadline 不能变负数


@pytest.mark.asyncio
async def test_the_manager_is_wired_with_a_query_model_and_the_limits(tmp_path, monkeypatch):
    """**AC1/AC7-1 的载荷点**：manager 必须同时拿到 `query_model` 与 `query_limit`。

    只传 `model` 时上游走 `get_dialated_windows`（拿最近消息本身当 query），语义对立的旧记忆
    真机召回不到（`retrieved=0`）；传了 `query_model` 才改成"先生成假想记忆再检索"，这是 AC7-1
    "新旧立场收敛"能成立的前提。这条接线只靠真机 gate 兜底是不够的（gate 依赖外部服务），
    所以在这里用**构造缝**（`_manager` 是注入的工厂）把它钉住：删掉 `query_model=` 本用例即红。
    """
    from langchain_core.messages import AIMessage

    vectors = AlwaysHitVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    model = ScriptedChatModel(responses=[AIMessage(content="无需改动。")])
    capability._model = model
    captured: dict = {}
    original = capability._manager

    def recording_manager(bound_model, **kwargs):
        captured["model"] = bound_model
        captured.update(kwargs)
        return original(bound_model, **kwargs)

    monkeypatch.setattr(capability, "_manager", recording_manager)
    token = set_identity_context(ALICE)
    try:
        await _seed(records, vectors, "我喜欢黑咖啡")
        await capability.consolidate(MemoryScope.USER, "我喜欢黑咖啡", {})
    finally:
        identity_context_var.reset(token)

    assert captured["model"] is model
    assert captured["query_model"] is model          # 少了它 → 召回不到旧立场（AC7-1 塌）
    assert captured["query_limit"] == CONSOLIDATION_QUERY_LIMIT
    assert captured["store"] is not None and captured["enable_deletes"] is True


@pytest.mark.asyncio
async def test_repair_read_failure_degrades_end_to_end_without_losing_either_row(tmp_path):
    """P0 修复的**另一半**：读不到权威正文 → 抛出去 → `consolidate` 降级整条新增。

    代理边界那半条已由 `test_repair_refuses_to_guess_the_body_when_the_row_cannot_be_read`
    钉住；这里补端到端：既有行**原封不动**（全文、无标记），候选**另起一行落盘**（不丢写）。
    """
    vectors = FakeVectorStore()
    capability, records = await _langmem(tmp_path, vectors)
    full_text = "长" * (INJECTED_MEMORY_CHAR_LIMIT * 2)
    capability._store = _BrokenStoreMethod(capability._store, aget_raises=ConnectionError("read down"))
    token = set_identity_context(ALICE)
    try:
        await records.store(MemoryEntry(id="long-one", content=full_text, metadata={},
                                        scope=MemoryScope.USER,
                                        created_at="2026-09-01T00:00:00+00:00"), ALICE)
        outcome = await capability.consolidate(MemoryScope.USER, "新候选", {"importance": 0.5})
        existing = await records.get("long-one", ALICE)
        entries = await capability.list_entries(MemoryScope.USER, 10)
    finally:
        identity_context_var.reset(token)

    assert outcome.degraded_reason is not None and outcome.id
    assert existing.content == full_text and TRUNCATION_MARKER not in existing.content
    assert sorted(entry.content for entry in entries) == ["新候选", full_text]


def test_the_fake_model_never_mistakes_a_decision_call_for_query_generation():
    """替身的相位判别必须结构可靠：候选正文里恰好含 query 生成的标志词时也不能认错。

    （`QueryGenerationMixin` 按 prompt 文本判别；若只做正向匹配，一条内容里带那句话的记忆
    会让**决策**调用被当成 query 生成 → 测试测到的是别的相位，而且是静默的。）
    """
    from langchain_core.messages import HumanMessage

    from tests.langmem_doubles import _is_query_generation

    query_prompt = HumanMessage(content=(
        "Use parallel tool calling to search for distinct memories relevant to this conversation:"
        "\n\n<convo>\n用户说了一句\n</convo>."))
    decision_prompt = HumanMessage(content=(
        "You are a memory subroutine for an AI.\n\nGenerate JSONPatches to update the existing "
        'memories.\n{"content": "Use parallel tool calling 这句话出现在候选正文里", '
        '"metadata": {}}'))

    assert _is_query_generation([query_prompt]) is True
    assert _is_query_generation([decision_prompt]) is False
