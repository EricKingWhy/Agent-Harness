"""RecoveryCoordinator：崩溃后按冻结顺序恢复 Session 的唯一编排入口。

07 §9 冻结的 8 步恢复顺序（ADR-0004 Round 4 §Q12）：
    1. load SessionEvent → Session（原始事件，不先做 dangling 占位）
    2. load Session-Sandbox mapping → WorkspaceRegistry.get()
    3. ensure Sandbox started（registry.get() 内部调用 ensure_started）
    4. load Operation Ledger → 未终止 Operation
    5. reconcile 未终止 operations：
       - 终态 3 种 → Ledger result_json 精确合成（#29）
       - PENDING → PendingPolicy 决策（默认 skip，#29）
       - RUNNING/UNKNOWN/NEED_RECONCILE → 状态推进至 NEED_RECONCILE 后
         交独立 ReconcileCallback 人工裁决（#30）；无 callback 安全拒绝
    6. restore tool result / message consistency → append 合成事件
    7. rebuild Runtime Context（derive_messages 从恢复后事件重新投影）
    8. return Session，交给 AgentRuntime 继续

关键设计（均来自 ADR-0004 / Issue #26）：
- Ledger-first 顺序保证 Ledger 永远比 SessionEvent 更完整：崩溃时 Ledger 有终态但
  SessionEvent 缺配对 → 本协调器用原 tool_call_id 合成 Recovery ToolResult。
- 先决策后写结果：确定性 reconcile 决策（读 Ledger + 投影）全部完成后再 append 事件；
  人工裁决（ReconcileCallback）本质是交互式决策，无法预先完成——它发生在写入段内，
  裁决失败时已写的 reconcile-required 事件只是"需要人工"这一事实的诚实记录，
  重试恢复会重新裁决（幂等收敛，不产生伪造结果）。
- 并发恢复串行化：SQLite 无行级锁——用 BEGIN EXCLUSIVE 事务在【数据库级】悲观串行化，
  第二个恢复方阻塞直到第一个完成或 busy_timeout 超时。WAL 模式下读者不被阻塞，
  恢复期间经 OperationLedger 的只读查询正常进行。
- UNKNOWN 永不自动验证 / 自动重跑（不变量 #14）：ReconcileHint 只是给用户的建议数据；
  RETRY 裁决只能来自用户，且表现为"原调用终止 + 可重试结果"，重跑由模型发起新 tool_call。
- Session.resume() 保持现状（只管 events）；本协调器自行组装 Session，
  避免 resume 的 Phase 1 dangling 占位抢在 Ledger reconcile 之前污染事件流。
  Ledger 不知道的 dangling call（如 validation 失败未建 Operation）仍回退
  Phase 1 占位语义（07 §8 不留 dangling call）。
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
from pydantic import ValidationError

from agent_harness.logging import log_event
from agent_harness.prompt import DEFAULT_REGISTRY
from agent_harness.recovery.reconcile import ReconcileCallback, ReconcileVerdict
from agent_harness.sandbox.registry import WorkspaceRegistry
from agent_harness.session import (
    OPERATION_RECONCILE_REQUIRED,
    SESSION_RESUMED,
    TOOL_CALL,
    TOOL_RESULT,
    JsonlSessionStore,
    Session,
)
from agent_harness.session.derive import DANGLING_TOOL_CONTENT, collect_dangling
from agent_harness.storage import Operation, OperationLedger, OperationState
from agent_harness.tooling import ErrorCode, ReconcileHint, ToolRegistry, ToolResult

logger = logging.getLogger("agent_harness.recovery")


def _try_parse_result_json(result_json: str, tool_name: str) -> ToolResult | None:
    """尝试从 Ledger 的 result_json 还原 ToolResult；腐烂数据返回 None 并落日志。

    Ledger 行可能被外部写入、迁移残留或写入中途崩溃污染成非法 JSON 或不符合
    ToolResult schema 的字典——恢复必须把这些视为"结果详情缺失"而不是向上抛
    ValidationError，否则整个 session 的恢复会被一行坏数据阻塞（#29 容错回归）。
    """
    try:
        return ToolResult.model_validate_json(result_json)
    except (ValidationError, ValueError):
        logger.warning(
            "Ledger result_json 解析失败（tool=%s），降级为结果详情缺失",
            tool_name,
            exc_info=True,
        )
        return None


def _args_from_identity(args_identity: str | None) -> dict | None:
    """从 Ledger 的 args_identity（JSON 字符串）还原 tool/call 的 args 字典。

    腐烂或缺失返回 None（由调用方退回 {}）：合成事件不能因入参快照损坏就拒绝
    恢复——args 缺失只是事实不完整，结果合成仍可基于 Ledger 终态。
    """
    if not args_identity:
        return None
    try:
        parsed = json.loads(args_identity)
    except (ValueError, TypeError):
        logger.warning(
            "args_identity 解析失败，合成 tool/call 退回空 args", exc_info=True
        )
        return None
    return parsed if isinstance(parsed, dict) else None


#: RUNNING / UNKNOWN / NEED_RECONCILE 需要人工裁决（#30）——
#: 不能为副作用状态未知的调用伪造结果（不变量 #14）。
_RECONCILE_STATES = frozenset(
    {OperationState.RUNNING, OperationState.UNKNOWN, OperationState.NEED_RECONCILE}
)

#: Ledger 终态：result_json 就是准确的恢复事实来源（07 §6）。
_TERMINAL_STATES = frozenset(
    {
        OperationState.SUCCEEDED,
        OperationState.FAILED,
        OperationState.CANCELLED,
    }
)


class RecoveryError(Exception):
    """恢复入口的确定性失败（如锁超时）。调用方可安全重试。"""


class ReconcileRequired(RecoveryError):
    """存在 UNKNOWN / RUNNING Operation 且没有 ReconcileCallback → 需人工裁决。

    与「恢复失败」区分：这不是基础设施故障，而是不变量 #14 要求的人工关卡。
    启动扫描据此把 session 标成「需人工确认」而不是「恢复失败」。
    """


class PendingPolicy(ABC):
    """PENDING Operation 的恢复策略 seam（ADR-0004 Round 3 §Q13）。

    Ledger-first 顺序下 PENDING 极罕见（微秒级窗口）；默认 skip 最安全，
    未来需要改 retry 时替换实现即可。
    """

    @abstractmethod
    def result_for(self, operation: Operation) -> ToolResult:
        """为 PENDING Operation 决定恢复时合成的 ToolResult（只做决策，不执行）。"""


class SkipPendingPolicy(PendingPolicy):
    """默认策略：skip——合成显式"未启动即跳过"结果，不自动执行。"""

    def result_for(self, operation: Operation) -> ToolResult:
        return ToolResult.failure(
            message=DEFAULT_REGISTRY.assemble(
                "frame:recovery_skipped", {"tool_name": operation.tool_name},
            ).fragment_text,
            error_code=ErrorCode.CANCELLED,
            retryable=False,
        )


@dataclass(frozen=True)
class _Synthesis:
    """一条已决策待写入的恢复结果（决策与写入分离的载体）。

    content 是 tool/result 事件的最终载荷文本：Ledger 终态 / PENDING 路径是
    ToolResult JSON；Ledger 无记录的占位路径与 Phase 1 逐字一致（原始文本）。
    """

    tool_call_id: str
    tool_name: str
    content: str
    needs_call_event: bool  # tool/call 事件缺失时一并补齐
    run_id: str | None
    agent_id: str | None
    args: dict | None = None  # 合成 tool/call 的入参；None 表示无可用 args_identity

    def call_event_args(self) -> dict:
        """tool/call 事件的 args 字段：有 args 用 args，否则空字典（不变量保持）。"""
        return self.args if self.args is not None else {}


class RecoveryCoordinator:
    """按 07 §9 冻结顺序恢复 Session 的唯一编排入口。

    注入：SessionStore + WorkspaceRegistry + OperationLedger + PendingPolicy
    + ReconcileCallback（#30）+ ToolRegistry（hint 解析，可选）。
    database_path 提供共享存储 SQLite 文件时启用悲观恢复锁——BEGIN EXCLUSIVE
    加在 sidecar 文件 <database_path>.recovery-lock 上（数据库级互斥，SQLite 无
    行级锁；主库对 Ledger 连接保持可写）；为 None 时不加锁（单进程/测试场景）。

    存在需要人工裁决的 UNKNOWN Operation 而未注入 ReconcileCallback 时，
    recover() 安全拒绝（RecoveryError），不写任何状态。
    """

    def __init__(
        self,
        *,
        session_store: JsonlSessionStore,
        workspace_registry: WorkspaceRegistry | None,
        operation_ledger: OperationLedger,
        pending_policy: PendingPolicy | None = None,
        reconcile_callback: ReconcileCallback | None = None,
        tool_registry: ToolRegistry | None = None,
        database_path: str | Path | None = None,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self._session_store = session_store
        self._workspace_registry = workspace_registry
        self._operation_ledger = operation_ledger
        self._pending_policy = pending_policy or SkipPendingPolicy()
        self._reconcile_callback = reconcile_callback
        self._tool_registry = tool_registry
        # 恢复锁用 sidecar 文件（#30：主库要保持对 Ledger 连接可写）。
        self._lock_path = (
            Path(str(database_path) + ".recovery-lock") if database_path else None
        )
        self._lock_timeout_seconds = lock_timeout_seconds

    async def recover(self, session_id: str) -> Session:
        """恢复一个 Session：8 步顺序执行，返回可直接交给 AgentRuntime 的 Session。"""
        async with self._recovery_lock():
            # 步骤 1：load SessionEvent（原始事件；dangling 占位留到步骤 6，
            # 避免 Phase 1 占位抢在 Ledger reconcile 之前）。
            events = self._session_store.read_events(session_id)
            if not events:
                raise RecoveryError(f"Session '{session_id}' 不存在或事件日志为空")

            # 步骤 2-3：load Session-Sandbox mapping + ensure Sandbox started。
            # 无映射记录（纯对话 session）优雅降级为 None，不让恢复失败。
            sandbox = None
            if self._workspace_registry is not None and self._workspace_registry.exists(
                session_id
            ):
                sandbox = self._workspace_registry.get(session_id)

            session = Session(
                session_id, self._session_store, list(events), sandbox=sandbox
            )

            # 步骤 4：load Operation Ledger。
            operations = await self._operation_ledger.list_for_session(session_id)
            operations_by_call_id = {op.tool_call_id: op for op in operations}

            # 步骤 5（决策阶段）：对每个 dangling tool_call 决定恢复结果。
            # 确定性决策（终态 / PENDING / 占位）全部完成前不写任何事件
            # （先决策后写结果）；需人工裁决的先收集——没有 ReconcileCallback
            # 时在这里整体安全拒绝，什么都不写（#30）。
            dangling_ids, call_event_ids = collect_dangling(session.events)
            plan: list[_Synthesis] = []
            reconcile_required: list[tuple[str, Operation]] = []
            callback = self._reconcile_callback
            for tool_call_id in sorted(dangling_ids):
                operation = operations_by_call_id.get(tool_call_id)
                if operation is not None and operation.state in _RECONCILE_STATES:
                    reconcile_required.append((tool_call_id, operation))
                    continue
                synthesis = self._decide(
                    tool_call_id,
                    operation,
                    needs_call_event=tool_call_id not in call_event_ids,
                )
                if synthesis is not None:
                    plan.append(synthesis)

            if reconcile_required and callback is None:
                detail = ", ".join(
                    f"{op.tool_name}(tool_call_id={tc})"
                    for tc, op in reconcile_required
                )
                raise ReconcileRequired(
                    f"存在需要人工裁决的 UNKNOWN Operation（{detail}）："
                    "未提供 ReconcileCallback，拒绝恢复——避免伪造结果或盲目重跑"
                    "高风险副作用（不变量 #14）。注入 ReconcileCallback 后可重试 recover()。"
                )

            # 步骤 6（写入阶段）：按决策 append 合成事件，restore 一致性。
            for item in plan:
                if item.needs_call_event:
                    session.append(
                        TOOL_CALL,
                        {
                            "tool_call_id": item.tool_call_id,
                            "tool_name": item.tool_name,
                            "args": item.call_event_args(),
                        },
                        run_id=item.run_id,
                        agent_id=item.agent_id,
                    )
                session.append(
                    TOOL_RESULT,
                    {"tool_call_id": item.tool_call_id, "content": item.content},
                    run_id=item.run_id,
                    agent_id=item.agent_id,
                )
                # PENDING 决策落地后同步推进 Ledger：session 已合成 CANCELLED
                # 语义的 tool/result，Ledger 行却永远停在 PENDING——两边对同一
                # tool_call 永久不一致（可观测性 + 后续 reconcile 重复触发）。
                operation = operations_by_call_id.get(item.tool_call_id)
                if (operation is not None
                        and operation.state is OperationState.PENDING
                        and self._operation_ledger is not None):
                    await self._operation_ledger.update_state(
                        session_id, item.tool_call_id,
                        OperationState.CANCELLED,
                        result_json=item.content,
                    )
            # 人工裁决项（#30）：状态推进 → reconcile-required 事件 → 用户裁决 →
            # Ledger 终态 + 合成 tool/result。裁决是交互式决策，发生在写入段内；
            # 中途失败留下的 reconcile-required 事件是"需要人工"的诚实记录，
            # 重试恢复会重新裁决（幂等收敛）。
            for tool_call_id, operation in reconcile_required:
                await self._reconcile_one(
                    session,
                    tool_call_id,
                    operation,
                    needs_call_event=tool_call_id not in call_event_ids,
                    callback=callback,
                )
            # 与 Session.resume 的事件契约对齐：恢复完成标记 session/resumed。
            session.append(SESSION_RESUMED, {})

            # 步骤 7：rebuild Runtime Context——从恢复后的持久事件重新投影。
            # derive_messages 是纯函数；此处调用一次验证投影一致（不留 dangling 警告）。
            session.derive_messages()

            # 步骤 8：返回 Session，交给 AgentRuntime 继续。
            return session

    # ── 内部实现 ──

    @asynccontextmanager
    async def _recovery_lock(self) -> AsyncIterator[None]:
        """SQLite 悲观恢复锁（sidecar 锁文件）。

        诚实声明（#29 AC 明确要求）：SQLite 没有行级锁。BEGIN EXCLUSIVE 在
        【数据库级】互斥——锁加在专用 sidecar 文件 <database_path>.recovery-lock
        上：既串行化并发恢复（所有恢复方抢同一把文件锁），又不阻塞主库上
        OperationLedger 自己的连接（#30 恢复期间协调器要经 Ledger 推进
        RUNNING → UNKNOWN → NEED_RECONCILE → 终态；若 EXCLUSIVE 加在主库上，
        Ledger 的写入会被自己的恢复锁饿死）。
        第二个恢复方阻塞直到第一个完成（commit）或 busy_timeout 超时（抛 RecoveryError）。

        崩溃安全：持锁进程死亡时 SQLite 回滚其事务、释放文件锁——无陈旧锁问题。
        """
        if self._lock_path is None:
            yield
            return
        connection = await aiosqlite.connect(
            self._lock_path, timeout=self._lock_timeout_seconds
        )
        try:
            try:
                await connection.execute("BEGIN EXCLUSIVE TRANSACTION")
            except aiosqlite.OperationalError as e:
                raise RecoveryError(
                    f"无法获取恢复锁（另一个恢复可能正在进行）：{e}。可安全重试。"
                ) from e
            try:
                yield
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        finally:
            await connection.close()

    def _decide(
        self,
        tool_call_id: str,
        operation: Operation | None,
        *,
        needs_call_event: bool,
    ) -> _Synthesis | None:
        """对一个 dangling tool_call 做【确定性】恢复决策（纯决策，不写任何状态）。

        - Ledger 终态 → 用 result_json 精确合成；
        - PENDING → PendingPolicy 决策（默认 skip）；
        - Ledger 无记录 → Phase 1 占位（不留 dangling call）。
        RUNNING/UNKNOWN/NEED_RECONCILE 不进本方法——recover() 已把它们
        分流到人工裁决路径（_reconcile_one，#30）。
        """
        run_id = operation.run_id if operation else None
        agent_id = operation.agent_id if operation else None

        if operation is None:
            # Phase 1 占位语义：Session.resume 的 content 就是 DANGLING_TOOL_CONTENT 原文。
            return _Synthesis(
                tool_call_id=tool_call_id,
                tool_name="unknown",
                content=DANGLING_TOOL_CONTENT,
                needs_call_event=needs_call_event,
                run_id=None,
                agent_id=None,
            )

        # 合成 tool/call 的入参：优先用 Ledger 冻结的 args_identity 快照，
        # 让 derive_messages 投出的 AIMessage.tool_calls 带真实入参而非空字典。
        args = _args_from_identity(operation.args_identity)

        if operation.state in _TERMINAL_STATES:
            return _Synthesis(
                tool_call_id=tool_call_id,
                tool_name=operation.tool_name,
                content=self._content_from_ledger(operation),
                needs_call_event=needs_call_event,
                run_id=run_id,
                agent_id=agent_id,
                args=args,
            )

        if operation.state is OperationState.PENDING:
            result = self._pending_policy.result_for(operation)
            return _Synthesis(
                tool_call_id=tool_call_id,
                tool_name=operation.tool_name,
                content=result.model_dump_json(),
                needs_call_event=needs_call_event,
                run_id=run_id,
                agent_id=agent_id,
                args=args,
            )

        return None

    @staticmethod
    def _content_from_ledger(operation: Operation) -> str:
        """从 Ledger 终态取恢复内容：result_json 优先；缺失或腐烂时按状态降级合成。"""
        if operation.result_json:
            parsed = _try_parse_result_json(operation.result_json, operation.tool_name)
            if parsed is not None:
                return parsed.model_dump_json()
            # 腐烂 result_json：视为"结果详情缺失"，落入下面的降级合成。
        if operation.state is OperationState.SUCCEEDED:
            return ToolResult.success(
                f"操作 '{operation.tool_name}' 已确认成功（Ledger 记录），"
                "但结果详情缺失。"
            ).model_dump_json()
        return ToolResult.failure(
            message=(
                f"操作 '{operation.tool_name}' 终态为 {operation.state.value}"
                "（Ledger 记录），结果详情缺失。"
            ),
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            retryable=False,
        ).model_dump_json()

    # ── 人工裁决（#30）──

    def _hint_for(self, tool_name: str) -> ReconcileHint:
        """解析 Tool 的 ReconcileHint；未注册 / 无 registry 时回退安全默认。

        hint 只是给 ReconcileCallback 的建议数据——本协调器永不自动执行
        验证动作，也永不自动重跑（不变量 #14）。
        """
        if self._tool_registry is None:
            return ReconcileHint()
        try:
            tool = self._tool_registry.get(tool_name)
        except KeyError:
            return ReconcileHint()
        return tool.reconcile_hint

    async def _reconcile_one(
        self,
        session: Session,
        tool_call_id: str,
        operation: Operation,
        *,
        needs_call_event: bool,
        callback: ReconcileCallback,
    ) -> None:
        """把一个需人工裁决的 Operation 推进到终态并补齐事件。

        顺序（07 §4/§6 + #30 AC）：
        1. 状态机两步推进：RUNNING → UNKNOWN → NEED_RECONCILE（Ledger 强制）；
        2. append operation/reconcile-required（"需要人工裁决"可观察、可持久）；
        3. ReconcileCallback 显式裁决（hint 仅建议；无 callback 不可能到达这里）；
        4. 应用裁决：Ledger 终态 + reconcile_meta + 合成 tool/result。
        """
        if operation.state is OperationState.RUNNING:
            await self._operation_ledger.update_state(
                operation.session_id, tool_call_id, OperationState.UNKNOWN
            )
            await self._operation_ledger.update_state(
                operation.session_id, tool_call_id, OperationState.NEED_RECONCILE
            )
        elif operation.state is OperationState.UNKNOWN:
            await self._operation_ledger.update_state(
                operation.session_id, tool_call_id, OperationState.NEED_RECONCILE
            )

        session.append(
            OPERATION_RECONCILE_REQUIRED,
            {
                "tool_call_id": tool_call_id,
                "tool_name": operation.tool_name,
                "args_identity": operation.args_identity,
                "state": OperationState.NEED_RECONCILE.value,
            },
            run_id=operation.run_id,
            agent_id=operation.agent_id,
        )

        hint = self._hint_for(operation.tool_name)
        verdict = await callback.resolve(operation, hint)

        result, ledger_state = self._verdict_outcome(operation, verdict)
        content = result.model_dump_json()
        await self._operation_ledger.update_state(
            operation.session_id, tool_call_id,
            ledger_state,
            result_json=content,
            reconcile_meta=json.dumps(
                {
                    "verdict": verdict.value,
                    "reconciled_at": datetime.now(UTC).isoformat(
                        timespec="milliseconds"
                    ),
                },
                ensure_ascii=False,
            ),
        )

        # reconcile reason 进 JSONL 诊断层（spec 12 §2）：裁决依据可 tail/grep，
        # 与 SessionEvent 流（operation/reconcile-required + 合成 tool/result）
        # 互补不替代（Event ≠ 诊断日志）。
        log_event(
            logging.getLogger("agent_harness.recovery"),
            "system_log",
            f"Operation {tool_call_id} reconcile 裁决完成",
            component="recovery",
            outcome="reconciled",
            reconcile_verdict=verdict.value,
            tool_call_id=tool_call_id,
            tool_name=operation.tool_name,
            session_id=operation.session_id,
            ledger_state=ledger_state.value,
        )

        if needs_call_event:
            session.append(
                TOOL_CALL,
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": operation.tool_name,
                    "args": _args_from_identity(operation.args_identity) or {},
                },
                run_id=operation.run_id,
                agent_id=operation.agent_id,
            )
        session.append(
            TOOL_RESULT,
            {"tool_call_id": tool_call_id, "content": content},
            run_id=operation.run_id,
            agent_id=operation.agent_id,
        )

    @staticmethod
    def _verdict_outcome(
        operation: Operation, verdict: ReconcileVerdict
    ) -> tuple[ToolResult, OperationState]:
        """把用户裁决映射为（合成 ToolResult，Ledger 目标状态）。

        CONFIRM_SUCCESS / CONFIRM_FAILURE：Ledger 已有 result_json 时以它为准
        （那是崩溃前记录的执行事实）；缺失时合成带"人工 reconcile"明示的结果。
        RETRY：原调用以 CANCELLED 终止，合成 retryable=True 的失败结果——
        重跑是模型之后发起新的 tool_call（新 Operation），不是协调器重执行。
        """
        if verdict is ReconcileVerdict.CONFIRM_SUCCESS:
            if operation.result_json:
                parsed = _try_parse_result_json(
                    operation.result_json, operation.tool_name
                )
                if parsed is not None:
                    return (parsed, OperationState.SUCCEEDED)
            return (
                ToolResult.success(
                    f"操作 '{operation.tool_name}' 崩溃时结果未知，"
                    "已由用户确认成功（人工 reconcile）。"
                ),
                OperationState.SUCCEEDED,
            )
        if verdict is ReconcileVerdict.CONFIRM_FAILURE:
            if operation.result_json:
                parsed = _try_parse_result_json(
                    operation.result_json, operation.tool_name
                )
                if parsed is not None:
                    return (parsed, OperationState.FAILED)
            return (
                ToolResult.failure(
                    message=(
                        f"操作 '{operation.tool_name}' 崩溃时结果未知，"
                        "已由用户确认失败（人工 reconcile）。"
                    ),
                    error_code=ErrorCode.TOOL_EXECUTION_ERROR,
                ),
                OperationState.FAILED,
            )
        if verdict is ReconcileVerdict.RETRY:
            return (
                ToolResult.failure(
                    message=(
                        f"操作 '{operation.tool_name}' 崩溃时结果未知；"
                        "用户已裁决重试。原调用已终止，请重新发起该工具调用。"
                    ),
                    error_code=ErrorCode.CANCELLED,
                    retryable=True,
                ),
                OperationState.CANCELLED,
            )
        return (
            ToolResult.failure(
                message=(
                    f"操作 '{operation.tool_name}' 崩溃时结果未知；"
                    "用户已裁决放弃，不再重跑。"
                ),
                error_code=ErrorCode.CANCELLED,
            ),
            OperationState.CANCELLED,
        )
