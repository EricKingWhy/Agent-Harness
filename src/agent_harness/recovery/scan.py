"""启动崩溃扫描（Phase Multiturn T8 / #138）。

进程重启时对每个 session 检查「无终态 run」：追加 ``run/interrupted``（诚实
记录中断事实），再强制跑一遍 RecoveryCoordinator（Ledger reconcile：终态精确
回填、PENDING 按策略、UNKNOWN 需人工裁决）。

顺序固定为「先标记中断，再 reconcile」：
- 标记中断只写 run 级事实，不猜工具终态（不变量 #12：Checkpoint ≠ 副作用恢复）；
- reconcile 才判定工具调用结果，且 UNKNOWN 在没有 ReconcileCallback 时**安全
  拒绝**（``ReconcileRequired``），扫描把它记为「需人工确认」，不伪造结果、
  不盲目重跑（不变量 #14）。

**单进程假设（V1）**：扫描在「持有会话的进程」启动时执行一次（web lifespan）。
不变量 #22 要求事件流只有一个真相，而 ``RunManager`` 的在途 run 只存在于
本进程内存里——另一个进程无法区分「run 在跑」与「run 被崩溃打断」，所以
**不要**在会与长驻服务并发的短命命令（CLI run / 子命令）里扫描：那会把别的
进程在途 run 误标中断，进而让两边各自推算 seq 撞号。多进程/多 worker 需要
跨进程 run lease，属后续 Phase。

该单进程假设已提升为正式架构约束，见 ``CONTEXT.md`` 的
**StartupInterruptionScan** 条目——它是本扫描**不能**被吸收进
``RecoveryCoordinator`` 的根本原因（另一原因是职责层次不同：扫描是
「批量 + 三分类结论 + 单会话隔离」，recover 是「单 session 8 步编排」）。

单个 session 失败不阻断整轮扫描（一个坏会话不该拖垮进程启动）；失败以
``ScanRecovery.FAILED`` + detail 如实上报。``run/interrupted`` 是终态，所以
失败的 session 不会被下一轮扫描重试——但它的悬空 tool_call 仍在，续聊/``/recover``
会再次进入 reconcile（Ledger reconcile 可安全重试），因此不会永久卡死。
同步 JSONL 读写（含 fsync）统一用 ``anyio.to_thread.run_sync`` 下放线程，
不阻塞事件循环。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import anyio.to_thread

from agent_harness.recovery.coordinator import (
    ReconcileRequired,
    RecoveryCoordinator,
    RecoveryError,
)
from agent_harness.recovery.reconcile import ReconcileCallback
from agent_harness.sandbox.registry import WorkspaceRegistry
from agent_harness.session.event import RUN_INTERRUPTED
from agent_harness.session.interrupt import InterruptedRun, detect_unterminated_runs
from agent_harness.session.session import Session
from agent_harness.session.store import JsonlSessionStore
from agent_harness.storage.operation import OperationLedger

logger = logging.getLogger("agent_harness.recovery.scan")


class ScanRecovery(str, Enum):
    """单个 session 的扫描结论。"""

    RECOVERED = "recovered"
    NEEDS_MANUAL_RECONCILE = "needs_manual_reconcile"
    FAILED = "failed"


@dataclass(frozen=True)
class InterruptionScanResult:
    """一个被打断 session 的扫描结论。

    ``interrupted`` = 追加 ``run/interrupted`` 的 run 列表；``recovery`` =
    recovered / needs_manual_reconcile / failed；``detail`` 仅在非 recovered 时有值。
    """

    session_id: str
    interrupted: list[InterruptedRun] = field(default_factory=list)
    recovery: ScanRecovery = ScanRecovery.RECOVERED
    detail: str | None = None


async def scan_interrupted_sessions(
    *,
    session_store: JsonlSessionStore,
    operation_ledger: OperationLedger,
    workspace_registry: WorkspaceRegistry | None,
    database_path: str | Path | None,
    reconcile_callback: ReconcileCallback | None = None,
    lock_timeout_seconds: float = 5.0,
) -> list[InterruptionScanResult]:
    """扫描全部 session，标记中断并 reconcile；返回被处理 session 的结论。

    无终态 run 的 session 才处理（幂等：``run/interrupted`` 本身是终态，
    重复扫描不会重复追加）。无中断的 session 不出现在返回值里。
    """
    results: list[InterruptionScanResult] = []
    session_ids = await anyio.to_thread.run_sync(session_store.list_session_ids)
    for session_id in session_ids:
        try:
            interrupted = await anyio.to_thread.run_sync(
                _mark_interrupted, session_store, session_id
            )
            if not interrupted:
                continue
            logger.warning(
                "启动扫描：session=%s 标记 %d 个中断 run（seq=%s）",
                session_id, len(interrupted),
                [r.interrupted_seq for r in interrupted],
            )
            coordinator = RecoveryCoordinator(
                session_store=session_store,
                workspace_registry=workspace_registry,
                operation_ledger=operation_ledger,
                reconcile_callback=reconcile_callback,
                database_path=database_path,
                lock_timeout_seconds=lock_timeout_seconds,
            )
            try:
                await coordinator.recover(session_id)
            except ReconcileRequired as error:
                # UNKNOWN 工具调用需人工裁决——如实标记，不伪造、不重跑。
                logger.warning(
                    "启动扫描：session=%s 需人工 reconcile：%s", session_id, error
                )
                results.append(InterruptionScanResult(
                    session_id=session_id, interrupted=interrupted,
                    recovery=ScanRecovery.NEEDS_MANUAL_RECONCILE,
                    detail=str(error),
                ))
            except RecoveryError as error:
                logger.exception(
                    "启动扫描：session=%s reconcile 失败", session_id,
                )
                results.append(InterruptionScanResult(
                    session_id=session_id, interrupted=interrupted,
                    recovery=ScanRecovery.FAILED, detail=str(error),
                ))
            else:
                results.append(InterruptionScanResult(
                    session_id=session_id, interrupted=interrupted,
                ))
        except Exception as error:  # 单会话失败不阻断整轮扫描
            logger.exception("启动扫描：session=%s 处理异常", session_id)
            results.append(InterruptionScanResult(
                session_id=session_id,
                recovery=ScanRecovery.FAILED,
                detail=str(error),
            ))
    return results


def _mark_interrupted(
    session_store: JsonlSessionStore, session_id: str
) -> list[InterruptedRun]:
    """同步块：读事件 → 检测无终态 run → 逐个补记 run/interrupted。

    整块（含 append 的 fsync）在调用方下放线程执行。
    """
    events = session_store.read_events(session_id)
    interrupted = detect_unterminated_runs(events)
    for run in interrupted:
        Session.append_event(
            session_store,
            session_id,
            RUN_INTERRUPTED,
            {
                "interrupted_seq": run.interrupted_seq,
                "reason": "process_restart",
            },
            run_id=run.run_id,
            agent_id=run.agent_id,
            step_id=run.step_id,
        )
    return interrupted
