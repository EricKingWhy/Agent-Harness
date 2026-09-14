"""Owned background tasks for run-end extraction and capability writes."""

import asyncio
import logging
from typing import Any

from agent_harness.memory.capability import MemoryCapability
from agent_harness.memory.types import memory_session_var
from agent_harness.session import Session, SessionEvent
from agent_harness.session.event import MEMORY_DEGRADED

logger = logging.getLogger("agent_harness.memory")


def _append_degraded(session: Session, events: list[SessionEvent], data: dict) -> None:
    """落一条 `memory/degraded`；**观测写失败不得改写降级语义**。

    这几处 append 都在"降级已经发生、候选已经落盘"之后：若它抛出去，外层 except 会把事件流
    改写成 `writeback / unavailable: <TypeError>`，真实原因（`consolidation_failed: X`）与
    `partial: N/M` 一起被顶掉。与抽取分支的既有保护同款。
    """
    try:
        session.append(MEMORY_DEGRADED, data,
                       run_id=next((e.run_id for e in events if e.run_id), None))
    except Exception:  # noqa: BLE001 — 观测写失败不得吞掉候选（降级只在质量）
        logger.warning("Memory degradation event persistence unavailable")

#: 单次写回（抽取 + 全部候选）的运行级预算。必须**大于** provider 侧的默认决策预算
#: （`consolidation.CONSOLIDATION_TIMEOUT_SECONDS`），否则外层取消会抢在"超时 → 降级写"
#: 之前发生——见 `_remaining_budget`。
WRITEBACK_TIMEOUT_SECONDS = 60.0

#: 每个候选留给"降级写入 + 降级事件"的余量（秒）。候选拿到的决策预算 =
#: 外层剩余时间 − 本余量；余量耗尽时候选预算趋近 0，于是**立刻降级成只新增**，
#: 而不是被外层取消（`CancelledError` 不是 `Exception`，会穿过 `consolidate` 的降级边界，
#: 候选连写都写不进去）。
_FALLBACK_RESERVE_SECONDS = 2.0


class MemoryWriteback:
    def __init__(self, capability: MemoryCapability, extractor: Any,
                 timeout_seconds: float = WRITEBACK_TIMEOUT_SECONDS) -> None:
        # extractor 端口：``async extract(events) -> ExtractionOutcome``
        # （候选 + 降级原因；原因非 None 时落 memory/degraded，见 _write）。
        self._capability = capability
        self._extractor = extractor
        self._timeout = timeout_seconds
        self._tasks: set[asyncio.Task] = set()

    def submit(self, session: Session, events: list[SessionEvent]) -> None:
        # create_task snapshots the request IdentityContext before middleware resets it.
        task = asyncio.create_task(self._write(session, list(events)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _write(self, session: Session, events: list[SessionEvent]) -> None:
        token = memory_session_var.set(session.session_id)
        deadline = asyncio.get_running_loop().time() + self._timeout
        try:
            async with asyncio.timeout(self._timeout):
                outcome = await self._extractor.extract(events)
                candidates = outcome.candidates
                if outcome.degraded_reason is not None:
                    # 抽取回退必须可观测（BUG-012 真机验收发现）：LLM 路径失败会静默
                    # 把记忆质量降到"关键词 + 终答"的正则水平，此前只在日志里留痕、
                    # 事件流毫无痕迹。reason 只含阶段 + 异常类型名（脱敏不变量同上）。
                    logger.warning("Memory extraction degraded: %s", outcome.degraded_reason)
                    try:
                        session.append(
                            MEMORY_DEGRADED,
                            {"operation": "extraction", "reason": outcome.degraded_reason},
                            run_id=next((e.run_id for e in events if e.run_id), None),
                        )
                    except Exception:  # noqa: BLE001 — 观测写失败不得吞掉候选（降级只在质量）
                        logger.warning("Memory degradation event persistence unavailable")
                stored, failed = 0, 0
                degraded: list[str] = []
                for scope, content, metadata in candidates:
                    try:
                        # #158：走"检索后决策"入口。它保证"返回 ⟹ 已落盘"——所以下面的
                        # failed 只统计**真的写不进去**（连降级写入都失败）的候选。
                        outcome = await self._capability.consolidate(
                            scope, content, metadata,
                            budget_seconds=self._remaining_budget(deadline))
                        if outcome.degraded_reason is not None:
                            degraded.append(outcome.degraded_reason)
                        stored += 1
                    except Exception as item_error:  # noqa: BLE001 — 单候选失败隔离
                        # R7-4：逐候选隔离——第 N 个失败不再吞掉其余候选
                        #（此前顺序写、一个失败全部丢失，且 LLM 抽取不重跑）。
                        failed += 1
                        logger.warning(
                            "Memory candidate store failed (%s/%d): %s",
                            failed, len(candidates), type(item_error).__name__,
                        )
                if degraded:
                    # 消解降级：候选**已经写了**（不丢写），但"检索既有记忆后决策"这一步没跑成。
                    # 与抽取回退同一约定：只留脱敏后的 reason（阶段 + 异常类型名），
                    # 不把检索到的记忆内容或原始异常消息写进事件流。
                    distinct = sorted(set(degraded))
                    _append_degraded(
                        session, events,
                        {"operation": "consolidation",
                         "reason": distinct[0] if len(distinct) == 1 else f"mixed: {', '.join(distinct)}"},
                    )
                if failed:
                    # 部分失败诚实记录：数量 + 阶段可观察（类型名脱敏，与
                    # writeback 脱敏不变量一致）。已成功的候选不受影响。
                    _append_degraded(
                        session, events,
                        {"operation": "writeback",
                         "reason": f"partial: {failed}/{len(candidates)} candidates failed"},
                    )
        except Exception as error:
            # 根因（类型 + 消息 + 堆栈）只进日志；事件 reason 仅带异常类型名——
            # 原始异常消息可能含密钥，不得泄入事件流（见 redaction 测试）。
            logger.exception("Memory writeback failed")
            try:
                session.append(MEMORY_DEGRADED,
                               {"operation": "writeback", "reason": f"unavailable: {type(error).__name__}"},
                               run_id=next((e.run_id for e in events if e.run_id), None))
            except Exception:  # noqa: BLE001 — persistence can also be unavailable.
                logger.warning("Memory degradation event persistence unavailable")
        finally:
            memory_session_var.reset(token)

    @staticmethod
    def _remaining_budget(deadline: float) -> float:
        """本候选可用的决策预算：外层剩余时间 − 降级余量（下限 0，即"立刻降级写"）。

        这样"预算耗尽"表现为**降级**（provider 侧超时 → 无条件写入 + 可观测原因），
        而不是外层取消把候选整个丢掉。
        """
        return max(0.0, deadline - asyncio.get_running_loop().time() - _FALLBACK_RESERVE_SECONDS)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks))

    async def close(self, *, drain_timeout_seconds: float = 10.0) -> None:
        """收尾：先 drain 在途 writeback（等它们写完），超时才取消（R3-2）。

        此前直接 cancel——已抽取未存储的候选静默丢失。drain 有界：超时后
        仍然取消（进程退出不能被无限挂住），被取消的丢失是显式权衡。
        """
        tasks = list(self._tasks)
        if not tasks:
            return
        try:
            async with asyncio.timeout(drain_timeout_seconds):
                await asyncio.gather(*tasks, return_exceptions=True)
            return
        except TimeoutError:
            logger.warning("Memory writeback drain timed out; cancelling pending tasks")
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
