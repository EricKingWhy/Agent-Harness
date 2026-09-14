"""#158 冲突消解的 provider 侧机件：交给 LLM 的既有记忆**有界**，且这次额外开销**可见**。

为什么单独一个模块：这里定义的是"provider 检索回来的记忆以什么形状进 prompt"——既不属于记忆契约
（`capability.py`），也不属于 LangMem 能力的实现细节（`langmem_capability.py`）。收在一处，
"注入 prompt 的东西有上界"这条性质才只有一个定义点。

与 `extractor._clip_events` 同一思路（#158 AC4 点名的先例）：单条上限与那里单事件的 1000 字符同数；
条数上界（`CONSOLIDATION_QUERY_LIMIT`）在本模块真正执行，`query_limit` 只是同时告诉上游"别取太多"。
"""

import asyncio
import copy
from dataclasses import dataclass
from typing import Any

#: 单条注入 prompt 的记忆正文上限（字符）。与 `extractor._clip_events` 的单事件上限同数。
INJECTED_MEMORY_CHAR_LIMIT = 1000

#: provider 检索既有记忆的条数上界（LangMem 的 `query_limit`）。
CONSOLIDATION_QUERY_LIMIT = 5

#: 单次"检索后决策"的默认时间预算（秒）。实测真模型 3–26s（#158 探针 D/E 与真机 gate），
#: 所以沿用旧的 15s 会把相当一部分决策判成超时；超时**不再丢写**——`consolidate` 会降级为
#: 无条件写入并如实报告。
#:
#: 它是**默认值**而非硬上限：writeback 会按"外层预算的剩余时间"给每次调用一个更小的
#: `budget_seconds`（见 `writeback._FALLBACK_RESERVE_SECONDS`）。这样多个候选时，靠后的候选
#: 会**降级成只新增**，而不是被外层取消连写都没写（CancelledError 越过降级边界）。
#: 必须小于 writeback 的运行级预算（`writeback.WRITEBACK_TIMEOUT_SECONDS`），这条顺序由
#: `test_consolidation_budget_nests_inside_writeback` 钉住。
CONSOLIDATION_TIMEOUT_SECONDS = 30.0

#: 截断标记：让模型知道"这条记忆还有后半段"，而不是把截断当成完整内容去 Compare & Update。
TRUNCATION_MARKER = "…[已截断]"

#: 降级原因前缀（`MemoryWriteOutcome.degraded_reason`）。只带阶段 + 异常类型名，不带异常消息。
CONSOLIDATION_DEGRADED_PREFIX = "consolidation_failed"

#: 瞬时错误退避重试（BUG-014）：决策失败后先重试一次再降级——与 extractor 同款。
#: 预算走既有 budget_seconds（重试计入其中），不新增外层预算。
CONSOLIDATION_RETRY_BACKOFF_SECONDS = 2.0


def _is_retryable(error: BaseException) -> bool:
    """异常是否值得重试：4xx 语义（认证/权限/请求非法）与**预算超时**不重试。

    与 ``extractor._is_retryable`` 同判据（白名单类型会在换 provider 后静默失效，
    用"有无 4xx 状态"判定）；判定不了（无状态信息）按瞬时处理。
    额外排除 ``asyncio.TimeoutError``：consolidation 的超时来自内部
    ``asyncio.timeout(budget)``——是**预算耗尽**语义，重试注定再超时还白等退避。
    """
    if isinstance(error, asyncio.TimeoutError):
        return False
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        status = getattr(cause, "status_code", None) or getattr(cause, "code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return False
        response = getattr(cause, "response", None)
        resp_status = getattr(response, "status_code", None) or getattr(response, "status", None)
        if isinstance(resp_status, int) and 400 <= resp_status < 500:
            return False
        cause = cause.__cause__ if cause.__cause__ is not cause else None
    return True


@dataclass
class ConsolidationStats:
    """一次写入里 provider 侧检索的观测面（#158 AC3）：检索几次、取回几条、截断/丢弃几条。"""

    searches: int = 0
    retrieved_items: int = 0
    truncated_items: int = 0
    #: 超过条数上界被**丢掉**的条数。真机 gate 发现：`query_limit` 只让上游在**事后**裁剪
    #: 结果集，交给 manager 的结果可能更多（实测一次检索回来 6 条、上限 5），所以条数上界
    #: 必须在这里真正执行，否则 AC4 的"条数有界"依赖上游内部实现。
    dropped_items: int = 0
    #: 决策之后那次兜底检索（no-op 时按 id 复用既有记忆）的次数与取回条数——它同样是
    #: 一次真实的 embedding + 向量查询，不记进观测面就是系统性低报（code-review P2）。
    fallback_searches: int = 0
    #: 被"截断投影修复"救回来的回写次数（见 `aput`）。
    repaired_items: int = 0


class BoundedSearchStore:
    """包住 provider 用的 BaseStore：**检索结果有界 + 计数**，写路径带截断投影修复。

    覆盖两个方法：
    - `asearch`：既有记忆进 prompt 的唯一入口 → 条数（`max_items`）与每条字符数
      （`max_chars`）两个上界都在这里执行，并计数（AC3/AC4）。
    - `aput`：manager 的回写入口 → **把截断投影还原成权威全文**（见下）。
    其余（`adelete`/`aget`/`abatch`…）经 `__getattr__` 原样透传，namespace 授权与归属校验
    一点没少。

    **为什么必须处理 `aput`（code-review P0，已复现）**：manager 检索回来的 item 既是 prompt
    *也是* trustcall 打 patch 的基线（`langmem/knowledge/extraction.py` 的 `store_map` →
    `store_based` → `final_puts`）。若不处理，一次**只改 metadata** 的 PatchDoc 也会因为
    "value 变了"把"前 1000 字符 + …[已截断]"当成新正文回写，静默吃掉长记忆的尾部。所以回写时
    若正文是我们的截断投影（以标记结尾、且被截断行仍以该投影开头），就用行内全文替换它：
    上界只影响**模型看到的投影**，不影响**落盘的事实**。

    已知限度（不修，属方案的固有代价）：模型**重写**正文时（不以标记结尾）以投影为基线，
    尾部无从还原——它只能改写自己看见的部分。这是"注入有界"与"允许 provider 改写"共同决定
    的，已在集成提示词里记为限度。
    """

    def __init__(self, inner: Any, *, max_chars: int = INJECTED_MEMORY_CHAR_LIMIT,
                 max_items: int = CONSOLIDATION_QUERY_LIMIT) -> None:
        self._inner = inner
        self._max_chars = max_chars
        self._max_items = max_items
        self.stats = ConsolidationStats()

    async def asearch(self, namespace_prefix: tuple[str, ...], /, *, query: str | None = None,
                      filter: dict | None = None, limit: int = 10,
                      offset: int = 0, **kwargs: Any) -> list:
        # 计数在 await **之前**：检索抛错时 AC3 也必须看得见"这次检索发生过"（否则超时/
        # 不可用路径的 queries 永远是 0，成本被系统性低报——code-review P2）。
        self.stats.searches += 1
        items = await self._inner.asearch(namespace_prefix, query=query, filter=filter,
                                         limit=limit, offset=offset, **kwargs)
        self.stats.retrieved_items += len(items)
        if len(items) > self._max_items:
            self.stats.dropped_items += len(items) - self._max_items
            items = items[:self._max_items]
        return [self._bounded(item) for item in items]

    def _bounded(self, item: Any) -> Any:
        value = getattr(item, "value", None)
        content = _payload_content(value)
        if not isinstance(content, str) or len(content) <= self._max_chars:
            return item
        self.stats.truncated_items += 1
        # 浅拷贝 + 换掉 `value`（新 dict，原对象与其嵌套 dict 都不动）：保留**具体类型**
        # （`SearchItem` 的 `score`、子类等）而不 import langgraph —— 本模块由此不越
        # 不变量 #20 的 seam（`tests/orchestration/test_seam.py` 全 src 树扫描）。
        bounded = copy.copy(item)
        bounded.value = {**value, "content": {**value["content"],
                                             "content": content[:self._max_chars] + TRUNCATION_MARKER}}
        return bounded

    async def aput(self, namespace: tuple[str, ...], key: str, value: Any,
                   *args: Any, **kwargs: Any) -> Any:
        prepared, repaired = await self._without_truncated_projection(namespace, key, value)
        result = await self._inner.aput(namespace, key, prepared, *args, **kwargs)
        # 只有**真的写下去**才记"修过一次"：写失败时那次修复没有落盘，记了就是虚报（AC3）。
        if repaired:
            self.stats.repaired_items += 1
        return result

    async def _without_truncated_projection(self, namespace: tuple[str, ...], key: str,
                                            value: Any) -> tuple[Any, bool]:
        """回写值若是本代理的截断投影，换成该行的权威全文；返回 `(写入值, 是否修过)`。

        **读不到权威正文时抛错，而不是原样写入**（code-review P0）：原样写入等于把
        "前 1000 字符 + 标记"当成事实落盘——正是本修复要消灭的静默截尾，读失败时"猜投影就是
        正文"更是毫无依据。抛出去由 `consolidate` 的降级边界接住：整条候选另起一行新增，
        既有行原封不动（宁可多一条，不可少一截）。
        """
        content = _payload_content(value)
        if not isinstance(content, str) or not content.endswith(TRUNCATION_MARKER):
            return value, False
        head = content[: -len(TRUNCATION_MARKER)]
        if not head:
            # 正文恰好只有标记：空串恒为前缀，会把**任何**既有行顶掉。不猜（P2）。
            return value, False
        existing = await self._inner.aget(namespace, key)  # 读失败 → 抛，交降级边界
        stored = _payload_content(getattr(existing, "value", None))
        if isinstance(stored, str) and len(stored) > len(head) and stored.startswith(head):
            return {**value, "content": {**value["content"], "content": stored}}, True
        return value, False

    def __getattr__(self, name: str) -> Any:
        # adelete / aget / abatch…：原样透传给真 store。
        return getattr(self._inner, name)


def _payload_content(value: Any) -> Any:
    """`{"content": {"content": ...}}`（MemoryPayload）里的正文；形状不符返回 `None`。"""
    payload = value.get("content") if isinstance(value, dict) else None
    return payload.get("content") if isinstance(payload, dict) else None
