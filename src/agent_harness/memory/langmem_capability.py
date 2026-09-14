"""LangMem Formation/Consolidation 与工具读写，存储权威留在项目内。"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from agent_harness.identity import get_identity_context
from agent_harness.logging import log_event
from agent_harness.memory.capability import NO_DECISION_MODEL, MemoryWriteOutcome
from agent_harness.memory.consolidation import (
    CONSOLIDATION_DEGRADED_PREFIX,
    CONSOLIDATION_QUERY_LIMIT,
    CONSOLIDATION_RETRY_BACKOFF_SECONDS,
    CONSOLIDATION_TIMEOUT_SECONDS,
    BoundedSearchStore,
    _is_retryable,
)
from agent_harness.memory.record_store import MemoryRecordStore
from agent_harness.memory.types import (
    MemoryEntry,
    MemoryNamespace,
    MemoryScope,
    public_metadata,
)
from agent_harness.memory.vector_store import VectorIndexStore

logger = logging.getLogger("agent_harness.memory")


def _warn_safely(message: str, *args: Any) -> None:
    """降级路径上的日志：观测面故障**不得吞掉恢复动作**。

    自定义 `Handler.emit` 抛异常会穿出 `logging`（CPython 不替它兜底），`extra` 里撞上
    LogRecord 保留字段还会让 `makeRecord` 抛 `KeyError`。这些调用都在 except 块里——
    不兜底就意味着"降级写入"这个不丢写的恢复动作被一条日志打断。
    """
    with contextlib.suppress(Exception):
        logger.warning(message, *args)


class MemoryPayload(BaseModel):
    content: str
    metadata: dict = Field(default_factory=dict)


class LangMemMemoryCapability:
    def __init__(self, records: MemoryRecordStore, vectors: VectorIndexStore, model: Any = None,
                 *, query_limit: int = CONSOLIDATION_QUERY_LIMIT,
                 consolidation_timeout: float = CONSOLIDATION_TIMEOUT_SECONDS) -> None:
        from langmem import (
            create_manage_memory_tool,
            create_memory_store_manager,
            create_search_memory_tool,
        )

        from agent_harness.memory.base_store_adapter import SqliteMilvusBaseStore

        self._records = records
        self._store = SqliteMilvusBaseStore(records, vectors)
        self._manage = create_manage_memory_tool
        self._search = create_search_memory_tool
        self._manager = create_memory_store_manager
        self._model = model
        # #158：注入 prompt 的条数上界（字符上界由 `BoundedSearchStore` 管）与单次决策预算。
        self._query_limit = query_limit
        self._consolidation_timeout = consolidation_timeout

    async def store(self, scope: MemoryScope, content: str, metadata: dict,
                    *, budget_seconds: float | None = None) -> str:
        """写入一条记忆：有决策模型时由 provider 的 manager 决定 insert/update/delete，
        否则无条件插入（`_insert`）。"检索后决策"的策略入口见 `consolidate`。

        `budget_seconds` 是本次决策的时间预算（调用方按自己的外层预算给），None 用默认值。
        """
        namespace = MemoryNamespace.of(scope, get_identity_context()).as_tuple()
        if self._model is not None:
            # #157：解禁上游本来就有的删除能力——models 判"这条过时了"时会发 RemoveDoc，
            # manager 转成 `store.adelete(ns, key)`，落进 adapter 的 `PutOp(value=None)` 分支。
            # 只作用于本 namespace：manager 只能删它自己检索回来的 id，adapter 再校验一次归属。
            #
            # #158：`store=` 传 `BoundedSearchStore`——manager 自己检索既有记忆（这就是
            # "retrieve-before-write" 的唯一路径）。这个代理做两件事：给模型**看到的**既有记忆
            # 设条数/字符上界并计数（AC3/AC4），以及把回写的截断投影还原成权威全文
            # （P0：它同时是 trustcall 的 patch 基线，见 `consolidation.py` 的类文档）。
            bounded = BoundedSearchStore(self._store, max_items=self._query_limit)
            # `query_model`（AC1 明确给出的选项）：不给它时上游走 `get_dialated_windows`——
            # 拿**最近消息本身**当 query 去检索，语义对立的旧记忆（"我改用 Go 了" vs "我喜欢
            # TypeScript"）实测召回不到（真机 `retrieved=0`）；给了它，上游改成"先生成一条
            # 与当前对话相关的**假想记忆**再检索"，这才是 AC7-1"新旧立场收敛"能成立的前提。
            # 代价是多一次 LLM 调用（用户已决策：质量优先、接受成本）。注意**口径**：这次
            # 调用发生在 langmem 内部，我们的计数里没有它——`queries` 是 `asearch` 次数
            # （query 模型一次工具都没发时会是 0），这次 LLM 调用只能从事件的
            # `latency_ms` 与"事件确实产生"侧面看出（真机实测事件里 queries=1..2）。
            manager = self._manager(self._model, schemas=[MemoryPayload], namespace=namespace,
                                    store=bounded, enable_deletes=True,
                                    query_model=self._model, query_limit=self._query_limit)
            started = asyncio.get_running_loop().time()
            budget = self._consolidation_timeout if budget_seconds is None else min(
                budget_seconds, self._consolidation_timeout)
            try:
                async with asyncio.timeout(budget):
                    puts = await manager.ainvoke({"messages": [{"role": "user", "content": json.dumps({
                        "content": content, "metadata": metadata}, ensure_ascii=False)}], "max_steps": 1})
            except BaseException as error:
                # 失败/取消也要留下**开销**痕迹（AC3）：这次多出来的检索其实已经发生，
                # 但超时那一刻我们没有机会记成功事件。只补日志，不改传播语义
                # （CancelledError 必须继续向外，否则外层预算失效）。
                self._log_consolidation(bounded, puts=None, started=started,
                                        status="failed", error=type(error).__name__)
                raise
            if puts:
                # 观测（#158 AC3）：这次写入多出来的检索 + 一次决策 LLM 调用都要看得见。
                self._log_consolidation(bounded, puts=puts, started=started, status="ok")
                return puts[0]["key"]
            # provider 判 no-op（没有工具调用）：没有变化时复用既有记忆；没有匹配时精确保留
            # 抽取候选。这次兜底检索同样是真实开销，所以：①计数在 await **之前**（与 `asearch`
            # 同一口径——检索抛错也必须记成一次）；②失败路径也发事件（AC3 的"失败也记"，
            # 否则这条路上"决策跑过 + 又检索了一次"全部不可见）。
            bounded.stats.fallback_searches += 1
            try:
                previous = await self.search(scope, content, 1)
            except BaseException as error:
                self._log_consolidation(bounded, puts=None, started=started,
                                        status="failed", error=type(error).__name__)
                raise
            self._log_consolidation(bounded, puts=puts, started=started, status="ok")
            if previous and previous[0].content == content and previous[0].metadata == metadata:
                return previous[0].id
        return await self._insert(scope, content, metadata)

    @staticmethod
    def _log_consolidation(bounded: BoundedSearchStore, *, puts: list | None,
                           started: float, status: str, error: str | None = None) -> None:
        """记一条消解开销事件（AC3）。**绝不抛**：它在异常处理路径上被调用。

        第三方 logging handler 抛异常会一路穿出 `log_event`（CPython 不替自定义 emit 兜底），
        那会把真正的降级原因换成 handler 的异常类型——观测面故障不得改写功能语义。
        """
        try:
            log_event(logger, "memory_consolidated", "memory consolidation ran",
                      status=status, error_type=error,
                      queries=bounded.stats.searches, retrieved=bounded.stats.retrieved_items,
                      truncated=bounded.stats.truncated_items, dropped=bounded.stats.dropped_items,
                      fallback_searches=bounded.stats.fallback_searches,
                      repaired=bounded.stats.repaired_items,
                      decisions=None if puts is None else len(puts),
                      latency_ms=round((asyncio.get_running_loop().time() - started) * 1000))
        except Exception:  # noqa: BLE001 — 观测失败不得改变写入/降级语义
            _warn_safely("Memory consolidation event dropped: %s", status)

    async def consolidate(self, scope: MemoryScope, content: str,
                          metadata: dict, *, budget_seconds: float | None = None) -> MemoryWriteOutcome:
        """#158 的写入入口：先检索（provider 内部完成）→ 决策 → 落 #156 的机制。

        **不丢写**：决策/检索阶段任何失败都降级成一条无条件写入，并把脱敏后的原因交给调用方
        （writeback 据此落 `memory/degraded`）。所以"本方法返回 ⟹ 已有记忆落盘"——这条保证正是
        本票存在的意义之一：否则 Milvus 一抖动就变成静默丢记忆。

        `budget_seconds` 由调用方按外层预算给（见 `MemoryWriteback._remaining_budget`）：
        预算耗尽 → 这里超时 → 降级写入，而不是被外层取消。
        """
        if self._model is None:
            return MemoryWriteOutcome(await self._insert(scope, content, metadata),
                                      degraded_reason=NO_DECISION_MODEL)
        # BUG-014：瞬时错误退避重试 1 次（同 extractor）——4xx 语义不重试直接降级。
        # 重试计入既有 budget_seconds（外层 writeback 剩余预算），不新增外层预算。
        retry_marker = ""
        for attempt in (0, 1):
            try:
                return MemoryWriteOutcome(await self.store(scope, content, metadata,
                                                          budget_seconds=budget_seconds))
            except Exception as error:  # noqa: BLE001 — 降级边界：绝不因为决策失败丢候选
                if attempt == 0 and _is_retryable(error):
                    await asyncio.sleep(CONSOLIDATION_RETRY_BACKOFF_SECONDS)
                    retry_marker = "after_1_retry"
                    continue
                # 只带类型名：原始异常消息可能含用户数据/凭据（脱敏不变量，同 extractor）。
                reason = type(error).__name__
                if retry_marker:
                    reason = f"{reason}({retry_marker})"
                _warn_safely("Memory consolidation degraded (%s); falling back to insert",
                             reason)
                return MemoryWriteOutcome(
                    await self._insert(scope, content, metadata),
                    degraded_reason=f"{CONSOLIDATION_DEGRADED_PREFIX}: {reason}",
                )
        raise AssertionError("unreachable")  # pragma: no cover

    async def _insert(self, scope: MemoryScope, content: str, metadata: dict) -> str:
        """**无条件**写入（不经检索/决策）：`store` 在没有决策模型时的路径，也是 `consolidate`
        的降级目标。与上游默认一致（#157）：只传 content，action 默认 create。"""
        namespace = MemoryNamespace.of(scope, get_identity_context()).as_tuple()
        tool = self._manage(namespace=namespace, schema=MemoryPayload,
                            actions_permitted=("create", "update", "delete"), store=self._store)
        result = await tool.ainvoke({"content": {"content": content, "metadata": metadata}})
        # SDK 返回形如 "created memory <uuid>"。校验后缀确为 UUID 形状；
        # 形状不符时降级为按 namespace 查最近一条同内容记录（不把任意文本当记录 ID）。
        suffix = result.removeprefix("created memory ").strip()
        try:
            return str(UUID(suffix))
        except (ValueError, TypeError):
            recent = await self.search(scope, content, 1)
            if recent and recent[0].content == content:
                return recent[0].id
            raise RuntimeError(f"memory tool returned unexpected shape: {result!r}") from None

    async def update(self, memory_id: str, scope: MemoryScope, content: str, metadata: dict) -> str:
        """按 id 覆盖写（#156 的**机制**）。

        写权威记录本身，索引由 outbox/relay 异步跟进。**刻意不**把 update 交给 LangMem
        的 manager/工具：上游的 update/delete 能力已在 #157 解禁，但那是"模型自己决定改哪条"
        的路径（走 manager → adapter）；本条是**调用方指定 id** 的确定性覆盖写，
        "记录主权在项目内"意味着它不需要 SDK 参与，也不该受模型决策影响。
        """
        entry = MemoryEntry(id=memory_id, content=content, metadata=metadata, scope=scope,
                            created_at=datetime.now(UTC).isoformat())
        return await self._records.store(entry, get_identity_context())

    async def forget(self, memory_id: str) -> bool:
        """硬删（记录行 + 异步传播到向量索引），契约见 `capability.py`。"""
        return await self._records.delete(memory_id, get_identity_context())

    async def list_entries(self, scope: MemoryScope, limit: int, offset: int = 0) -> list[MemoryEntry]:
        """按 namespace 分页列出（契约见 `capability.py`）。

        刻意**不走 embedding 检索**：用户管理界面要的是"我的记忆全都有哪些"，不是
        "哪几条最像某个 query"。读权威记录，先取 `limit + offset` 再切片（与 adapter 的
        SearchOp 同款做法）。
        """
        limit, offset = max(0, limit), max(0, offset)
        entries = await self._records.list_by_scope(scope, get_identity_context(), limit + offset)
        return entries[offset:offset + limit]

    async def search(self, scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]:
        namespace = MemoryNamespace.of(scope, get_identity_context()).as_tuple()
        if not query or limit <= 0:
            return []
        tool = self._search(namespace=namespace, store=self._store)
        serialized = await tool.ainvoke({"query": query, "limit": limit})
        result = []
        for row in json.loads(serialized):
            try:
                entry = await self._store.records.get(row["key"], get_identity_context())
            except KeyError:
                # 索引里还挂着、记录行已被删掉：解禁 provider 删除后这是**可达**状态
                # （删除先落记录行，向量由 relay 异步收敛）。跳过这一条而不是让整次检索炸掉
                # ——adapter 的 SearchOp 分支一直是这么容忍的，能力层不该比它更脆。
                continue
            result.append(entry.model_copy(update={
                "score": row.get("score"), "metadata": public_metadata(entry.metadata)}))
        return result

    async def recall(self, scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]:
        return await self.search(scope, query, limit)
