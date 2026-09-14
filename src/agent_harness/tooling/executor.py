"""ToolExecutor：Tool 的【执行域】--把 tool_call 跑成结构化 ToolResult。

为什么独立成 executor.py（和 registry.py 分开）：
- Registry 是"配置时"对象：注册什么、查什么，纯静态。
- Executor 是"运行时"对象：按一条 tool_call 跑完 lookup->validate->execute，
  并把任意失败映射成稳定 ErrorCode。两者生命周期、可替换性、测试边界都不同，
  耦合会让"换执行策略"变成"动注册表"。

职责演进：
- Task 2：单次执行链（Validation-first）--校验在 execute 之前，参数非法则 execute 次数=0。
- Task 3：阶段3 外包两层边界--Timeout（asyncio.timeout + tool.timeout_seconds）
  和唯一 Retry Layer（只看 retryable 位，MAX_ATTEMPTS 上限）。
- Task 4：批次调度 execute_batch（全 READ_ONLY 并发 / 含 MUTATING 整批串行）+ 严格保序。
- Phase 4 Ticket E：串行永久失败后取消剩余调用；并行读失败互不影响。
  每条 tool_call 仍走单条 execute()，批次层只决定并发还是串行。

明确【不做】：
- 不做细粒度 DAG / 读写冲突分析（整批串行一刀切即可）；
- 不做并发上限（信号量）、批次级超时、部分失败回滚（都进 Backlog）；
- 不做 Backoff / Circuit Breaker / Retry Budget（重试间隔为立即；复杂度进 Backlog）；
- 不产出 ToolMessage（那是 AgentRuntime 在 Task 5 的接线活）；
- 不调 LLM、不决定 Agent 是否停止、不维护 Session。

设计铁律一：Tool 执行域失败对外【永远返回 ToolExecution】。
找不到工具、参数非法、超时与工具内部异常都被映射成失败 ToolResult，
不让异常冒泡。调用方配置错误和 Ledger 持久化失败不属于 Tool 结果：前者在副作用前
快速失败，后者必须中断 Runtime，让恢复流程按已提交的 Ledger 状态处理，不能伪装成
一个普通 ToolResult 后继续执行。

设计铁律二：Executor 是 Tool 执行域的【唯一 Retry Layer】。
往内：模型 SDK 层应关闭自己的重试；往外：AgentRuntime 只消费 ToolResult、不重试。
多层各重试 3 次 = 最坏 27 次真实执行（Retry Amplification），一个慢工具足以打爆下游。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from agent_harness.logging import log_event
from agent_harness.observability.tracer import TraceBinding, current_trace_binding
from agent_harness.session import TOOL_CALL, TOOL_RESULT, Session, SessionEvent
from agent_harness.storage import (
    Operation,
    OperationContext,
    OperationLedger,
    OperationState,
)
from agent_harness.tooling.approval import (
    ApprovalCallback,
    ApprovalRequest,
    ApprovalResponse,
    approval_reason,
    needs_approval,
)
from agent_harness.tooling.contract import (
    PermissionPolicy,
    Tool,
    ToolCall,
    ToolSideEffect,
)
from agent_harness.tooling.output_stream import ToolOutputStream, tool_output_sink_var
from agent_harness.tooling.overflow import OverflowHandler
from agent_harness.tooling.registry import ToolRegistry
from agent_harness.tooling.result import ErrorCode, ToolResult

logger = logging.getLogger("agent_harness.tooling.executor")

#: 一次 tool_call 在执行域内最多尝试几次（含第一次）。
#: 为什么是模块级常量而不是可配置项：重试上限必须收敛在【唯一 Retry Layer】
#: 一处可见可调；一旦可配置，"到底重试几次"会重新散落回各层，铁律二就被架空。
MAX_ATTEMPTS = 3

#: 阶段3 异常分类表：异常类型 -> (error_code, retryable)。
#: 分类是确定性的【类型判断】，绝不解析错误字符串（字符串会变，类型不会）。
#: - TimeoutError 不在表里：asyncio.timeout 到点抛它，单独捕获成 TIMEOUT；
#: - PermissionError -> 权限问题重试也不会有权限，确定性失败；
#: - ConnectionError -> 网络抖动重试可能自愈，暂时性失败；
#: - 其余异常 -> 工具内部错误，默认不重试（工具作者想声明"值得重试"，
#:   应自己返回带 retryable=True 的 ToolResult，重试循环同样尊重这个位）。
_EXCEPTION_CLASSIFICATION: dict[type[Exception], tuple[ErrorCode, bool]] = {
    PermissionError: (ErrorCode.PERMISSION_DENIED, False),
    ConnectionError: (ErrorCode.TRANSIENT_ERROR, True),
}


@dataclass(frozen=True)
class _ToolFailure:
    """一次尝试失败的**单一事实**：error_code / retryable / message 同源产出。

    为什么要有它：这三者在旧实现里由各自的分支分别拼装，OBS-009/014 的缺陷正是
    文案（对 MUTATING 也写「可稍后重试」）与 `retryable=False` 矛盾——而失败文案是
    **模型可见指令**，等于教模型盲重跑副作用状态未知的命令（不变量 #14）。收成一个
    值对象后，三者由构造入口一次性决定，`ToolResult` 只是它的投影（`to_result`）；
    要制造矛盾必须先绕过本类型，而不再是「两个分支各写各的」。

    与行为无关：分类仍是确定性的**类型判断**，绝不解析错误字符串。

    为什么 timeout 的 retryable 看 `tool.side_effect` 而不是错误码：超时后副作用
    状态未知，是否可重跑取决于工具是否有副作用，同一 TIMEOUT 码因此有两种取值。
    """

    error_code: ErrorCode
    retryable: bool
    message: str

    def to_result(self) -> ToolResult:
        """投影成对外 ToolResult（唯一出口）。"""
        return ToolResult.failure(
            message=self.message,
            error_code=self.error_code,
            retryable=self.retryable,
        )

    @classmethod
    def from_timeout(cls, tool: Tool, name: str) -> _ToolFailure:
        """`asyncio.timeout` 到点：READ_ONLY 超时是暂时的、重跑安全 → 可重试；
        MUTATING 超时意味着第 1 次尝试的副作用状态未知（进程可能仍在跑、写可能已
        落盘）——不自动重试，交模型决定是否重发（不变量 #14：UNKNOWN 高风险工具
        不盲重跑）。

        注意本路径**不**产生 NEED_RECONCILE：run 内该操作按终态 FAILED 落盘；
        UNKNOWN / ReconcileCallback 是**崩溃恢复**侧的对应机制
        （recovery/coordinator.py）——两者同源（未知副作用不盲重跑）不同触发面。
        """
        retryable = tool.side_effect is not ToolSideEffect.MUTATING
        limit = tool.timeout_seconds
        if retryable:
            message = (
                f"工具 '{name}' 执行超时（上限 {limit} 秒），"
                "可能是外部依赖暂时无响应，可稍后重试。"
            )
        else:
            # 文案与实际 retryable 一致：不可重试就绝不写「可稍后重试」。
            # 措辞不写死「改动 workspace」：MUTATING 是保守分类（bash 无法静态判定
            # 只读），且 MCP 工具的副作用可能在**远端**（如 GitHub）——对这两类
            # 说「会改动 workspace」都是假陈述。
            message = (
                f"工具 '{name}' 执行超时（上限 {limit} 秒），"
                "该工具被判定为有副作用（bash 命令无法静态区分只读，"
                "远端工具的影响也可能不在 workspace 内），"
                "本次执行的副作用状态未知"
                "（命令可能仍在运行，或已部分生效）——不要直接重跑；"
                f"请先确认当前状态，或把操作拆成不超过 {limit} 秒的更短步骤。"
            )
        return cls(error_code=ErrorCode.TIMEOUT, retryable=retryable, message=message)

    @classmethod
    def from_exception(cls, error: Exception, name: str) -> _ToolFailure:
        """查确定性类型分类表；未命中即工具内部错误、默认不重试。"""
        error_code, retryable = ErrorCode.TOOL_EXECUTION_ERROR, False
        for exc_type, (mapped_code, mapped_retryable) in (
            _EXCEPTION_CLASSIFICATION.items()
        ):
            if isinstance(error, exc_type):
                error_code, retryable = mapped_code, mapped_retryable
                break
        return cls(
            error_code=error_code,
            retryable=retryable,
            message=f"工具 '{name}' 执行异常: {type(error).__name__}: {error}",
        )


class ToolExecution(BaseModel):
    """一次 tool_call 的执行产出：结果 + 它回答的是哪个 tool_call。

    为什么需要这一层（而不是 Executor 直接返回 ToolResult）：
    - ToolResult 本身不知道"我是回答哪个 tool_call 的"；
    - 但 ToolMessage 协议要求 tool_call_id 和 assistant 的 tool request 严格配对，
      批次调度（Task 4）也要按原 call 顺序回填。所以"id↔结果"的配对必须显式保留。

    model_config 关闭校验后口子：ToolResult 是嵌套 Pydantic，默认会深度校验，
    这里我们只在 Executor 内部构造、字段已确定合法，关掉无关校验更省。
    """

    model_config = {"arbitrary_types_allowed": True}

    tool_call_id: str
    result: ToolResult
    # OverflowHandler 产出的延迟会话事件 (event_type, data)：Runtime 在
    # tool/call 落盘之后追加（R6-7，消除 artifact/created 前向引用）。
    pending_events: list[tuple[str, dict[str, Any]]] = []


class ToolExecutor:
    """Tool 执行域：Validation-first 三阶段 + Timeout 边界 + 唯一 Retry Layer。

    构造时绑定一个 ToolRegistry（静态路由）；execute() 跑一条 tool_call。
    阶段3 内部由 _execute_with_retry 驱动：每次尝试受 tool.timeout_seconds 约束，
    是否重试只看 ToolResult.retryable 位，上限 MAX_ATTEMPTS。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        policy: PermissionPolicy = PermissionPolicy.WORKSPACE_WRITE,
        approval_callback: ApprovalCallback | None = None,
        operation_ledger: OperationLedger | None = None,
        kill_hook: Callable[[str, str], None] | None = None,
        overflow_handler: OverflowHandler | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._approval_callback = approval_callback
        self._operation_ledger = operation_ledger
        self._kill_hook = kill_hook
        self._overflow_handler = overflow_handler

    @property
    def tracks_operations(self) -> bool:
        """Whether this Executor enforces the durable Operation lifecycle."""
        return self._operation_ledger is not None

    async def execute(
        self,
        tool_call: ToolCall | dict[str, Any],
        *,
        operation_context: OperationContext | None = None,
        session: Session | None = None,
        step_id: int | None = None,
        tracer: Any = None,
    ) -> ToolExecution:
        """跑完一条 tool_call，将 Tool 域内成功或失败映射为 ToolExecution。

        调用配置或 Ledger 持久化失败会抛出异常并中断执行，避免在没有 durable
        Operation 状态的情况下继续产生真实副作用。

        tool_call 接受 ToolCall 值对象或 LangChain 形状的 dict
        （{"id": str, "name": str, "args": dict}）——入口一次性归一化。

        三阶段 + 三失败出口（Validation-first 的核心）：
          [1] Registry.get(name)        找不到     -> KeyError     -> TOOL_NOT_FOUND
          [2] args_schema.model_validate(args)  校验失败 -> ValidationError -> INVALID_ARGUMENT
          [3] tool.execute(validated)   成功/失败  -> 透传 ToolResult / 异常分类映射
        阶段 [1][2] 失败时，tool.execute【根本不被调用】（execute 次数=0）。
        阶段 [3]（Task 3）外包 Timeout 边界 + retryable 驱动的重试循环：
        为什么只包阶段3：查字典、跑 Pydantic 都是本地瞬时操作，真正会慢、会挂
        （HTTP/文件/DB）的只有 execute 这一步。
        """
        call = ToolCall.normalize(tool_call)
        tool_call_id = call.id
        name = call.name
        raw_args = call.args

        # -- 阶段 1：lookup -- Registry 找不到抛 KeyError，由本层映射成 TOOL_NOT_FOUND。
        # 为什么不抛自定义异常：见 registry.py 注释--Registry 只管查，映射成执行域语义是 Executor 的活。
        try:
            tool: Tool = self._registry.get(name)
        except KeyError:
            return ToolExecution(
                tool_call_id=tool_call_id,
                result=ToolResult.failure(
                    message=f"工具 '{name}' 未注册，无法执行。请检查工具名拼写或从可用工具中选择。",
                    error_code=ErrorCode.TOOL_NOT_FOUND,
                    retryable=False,
                ),
            )

        # -- 阶段 2：validation -- Validation-first 的核心位置。
        # 校验发生在 execute【之前】：参数非法 -> tool.execute 根本不被调用（execute 次数=0）。
        # 这条边界以后喂给所有 Tool（Local/Knowledge/MCP），是最锋利的一刀。
        try:
            validated: BaseModel = tool.args_schema.model_validate(raw_args)
        except ValidationError as e:
            # ValidationError -> INVALID_ARGUMENT：取 e.errors() 前 2 条拼进 message，
            # 让模型知道哪个字段、错在哪，够自纠错又不灌满上下文窗口。
            details = "; ".join(
                f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}"
                for err in e.errors()[:2]
            )
            return ToolExecution(
                tool_call_id=tool_call_id,
                result=ToolResult.failure(
                    message=f"工具 '{name}' 参数校验失败：{details}。请修正参数后重新调用。",
                    error_code=ErrorCode.INVALID_ARGUMENT,
                    retryable=False,  # 参数错是确定性的，重试也是同样的错
                ),
            )

        # -- 阶段 2.5：approval gate -- 05_SANDBOX_CODING_TOOLS.md §6 的 REQUIRE_APPROVAL。
        # 在 validate 之后、execute 之前：参数已合法，但授权关卡决定是否能跑。
        # per-call scoping 由设计保证：每次 execute 独立检查，不存储"已批准"状态。
        denied = await self._check_approval(tool_call_id, name, tool, raw_args)
        if denied is not None:
            return denied

        # 配置错误必须在任何真实副作用之前拒绝。
        if self._overflow_handler is not None and session is None:
            raise ValueError("session is required when OverflowHandler is configured")
        if (session is not None and operation_context is not None
                and session.session_id != operation_context.session_id):
            raise ValueError("session and operation_context must identify the same session")

        if self._operation_ledger is not None:
            assert operation_context is not None
            session_id = operation_context.session_id
            await self._create_pending_operation(
                tool_call_id=tool_call_id,
                name=name,
                raw_args=raw_args,
                operation_context=operation_context,
                tool=tool,
            )
            self._maybe_kill("pending", tool_call_id)
            await self._operation_ledger.update_state(
                session_id, tool_call_id, OperationState.RUNNING
            )
            self._maybe_kill("running", tool_call_id)

        # -- Langfuse 工具观测（ADR-0018 D7）：与 JSONL tool_operation 同点平行。
        # delegate 工具按官方多 Agent 规则用 agent 型 + 目标命名，并在其存活
        # 期间设置嵌套绑定——child runtime 的 RunTracer 认领该观测为根。
        obs_span = None
        attempts: list[dict[str, Any]] = []
        is_delegate = getattr(tool, "is_subagent_dispatch", False)
        if tracer is not None:
            obs_span = tracer.tool_span_started(
                tool_name=name, tool_call_id=tool_call_id, args=raw_args,
                is_delegate=is_delegate,
            )
        binding_token = None
        if tracer is not None and obs_span is not None and is_delegate and tracer.trace_id:
            binding_token = current_trace_binding.set(
                TraceBinding(trace_id=tracer.trace_id, observation=obs_span),
            )

        # -- 阶段 2.7：输出流 sink（ADR-0016 §4.2）--
        # 执行期 stdout/stderr 增量：工具（经 contextvar）从 sandbox reader
        # 线程 push → 本 loop 的 drain task 合帧落盘 tool/output_delta。
        # 非流式工具不读 contextvar → 零 delta（02 §7.5）。drain task 与
        # 执行并发，finally 先关入队口再等最终 flush。
        sink: ToolOutputStream | None = None
        drain_task: asyncio.Task[list] | None = None
        sink_token = None
        if session is not None:
            sink = ToolOutputStream(
                session,
                tool_call_id=tool_call_id,
                run_id=operation_context.run_id if operation_context else None,
                step_id=step_id,
            )
            sink_token = tool_output_sink_var.set(sink)
            drain_task = asyncio.create_task(sink.drain())

        # -- 阶段 3：execute + Timeout 边界 + 唯一 Retry Layer（Task 3）--
        # 三阶段顺序不变；Timeout/Retry 只包住 tool.execute 这一步。
        try:
            try:
                result = await self._execute_with_retry(
                    tool_call_id, name, tool, validated,
                    tracer=tracer, attempts=attempts,
                )
            except asyncio.CancelledError:
                if self._operation_ledger is not None:
                    await self._operation_ledger.update_state(
                        session_id, tool_call_id, OperationState.CANCELLED
                    )
                raise
        finally:
            if binding_token is not None:
                current_trace_binding.reset(binding_token)
            if sink_token is not None:
                tool_output_sink_var.reset(sink_token)
            if sink is not None and drain_task is not None:
                sink.close()
                try:
                    await drain_task
                except asyncio.CancelledError:
                    # 二次取消到达：放弃最终 flush（增量已周期性落盘），停泵收口。
                    drain_task.cancel()
                    with suppress(BaseException):
                        await drain_task
                    raise

        # 存储失败不属于 Tool failure，不能重跑已成功执行的 Tool。
        # 异常或取消直接传播，Ledger 保留 RUNNING，交 Recovery reconcile。
        deferred_events: list[tuple[str, dict[str, Any]]] = []
        if self._overflow_handler is not None:
            assert session is not None
            result, deferred_events = await self._overflow_handler.maybe_overflow(
                session, tool_call_id, name, result,
            )

        if self._operation_ledger is not None:
            terminal_state = (
                OperationState.SUCCEEDED if result.ok else OperationState.FAILED
            )
            await self._operation_ledger.update_state(
                session_id, tool_call_id,
                terminal_state,
                result_json=result.model_dump_json(),
                artifact_ref=result.artifact_ref,
            )
            self._maybe_kill("terminal", tool_call_id)
        # 工具自产的延迟事件（如 delegation）在前，overflow 在后。
        pending = [*result.pending_events, *deferred_events]
        if tracer is not None:
            tracer.tool_span_completed(
                obs_span, outcome="success" if result.ok else "failure",
                message=result.message, attempts=attempts or None,
                session_id=(operation_context.session_id if operation_context else None),
                extra={"artifact_ref": result.artifact_ref} if result.artifact_ref else None,
            )
        return ToolExecution(tool_call_id=tool_call_id, result=result,
                             pending_events=pending)

    def _maybe_kill(self, stage: str, tool_call_id: str) -> None:
        """精确故障注入点（#32 Kill 集成测试专用；生产 kill_hook=None 行为不变）。

        每个注入点都在对应 Ledger 状态【已持久化之后】触发——hook 内 os._exit
        即可构造"状态已落盘、后续步骤未发生"的真实崩溃窗口（如 terminal 态
        已写、tool/result 事件未写的 Ledger-first 恢复窗口）。
        """
        if self._kill_hook is not None:
            self._kill_hook(stage, tool_call_id)

    async def execute_batch(
        self,
        tool_calls: list[ToolCall | dict[str, Any]],
        *,
        operation_context: OperationContext | None = None,
        session: Session | None = None,
        step_id: int | None = None,
        tracer: Any = None,
    ) -> list[ToolExecution]:
        """执行一批 tool_calls，返回 ToolExecution 列表（顺序 = 输入顺序）。

        一条可解释规则决定调度与失败传播：
          - 全 READ_ONLY → asyncio.gather 并发执行（独立读操作可安全重叠）；
          - 任一 MUTATING → 整批按原顺序串行（保守默认，避免副作用乱序/部分失败难归因）。
          - 串行调用永久失败 → 后续调用不执行，返回并持久化 CANCELLED；
          - 并行调用失败 → 其他 READ_ONLY 调用继续独立完成。
        无论并发还是串行，结果列表都按【输入 tool_calls 的顺序】返回，不是完成顺序。

        为什么这是 Task 5 的接线点：
          AgentRuntime 的 `for tc in tool_calls` 串行循环会被这一句替换。
          每条 tool_call 仍走完整 execute()（lookup→validate→timeout→retry 全复用），
          execute_batch 只在【批次层】决定并发还是串行，不重复执行域逻辑。

        并发为什么用 gather 而不是 TaskGroup：
          gather 最关键的特性是【返回顺序 = 喂入顺序，与完成顺序无关】--
          这正是"并发跑、保序返"的天然实现，也是 ToolMessage 配对的安全网。
          TaskGroup（3.11+）侧重结构化异常传播，返回顺序语义不如 gather 直观；
          部分失败的传播策略也不同（gather(return_exceptions=True) 可兜底，TaskGroup 取消其余）。
          这里要的是"每条都跑完、结果按序排"，gather 更贴。

        mode 决策：
          扫描本批所有 tool_call 的 side_effect：
          - 某工具名查不到（将 TOOL_NOT_FOUND）→ 按 READ_ONLY 算，不影响并发决策、让其走正常 execute 报错；
          - 全部 READ_ONLY → "parallel"；
          - 任一 MUTATING → "serial"。
        """
        if not tool_calls:
            return []

        mode = self._decide_mode(tool_calls)

        if mode == "parallel":
            # gather 的顺序保持：即使第 3 个先完成，返回列表仍是 [结果1, 结果2, 结果3]。
            results = await asyncio.gather(
                *(
                    self.execute(tc, operation_context=operation_context,
                            session=session, step_id=step_id, tracer=tracer)
                    for tc in tool_calls
                ),
                return_exceptions=True,
            )
            # 存储异常不能让批次提前返回，留下仍会追加 Artifact 事件的后台调用。
            # 等所有已启动调用结束，再传播异常；不重跑任何 Tool。
            for result in results:
                if isinstance(result, BaseException):
                    # 首个异常（输入顺序）维持原抛出契约；其余异常若不落日志，
                    # 会随 raise 一起从诊断视野里消失——一次基础设施故障常伴随
                    # 多个连锁失败，只看第一个会误判根因。这里补日志线索。
                    self._log_secondary_exceptions(results, tool_calls)
                    # 已完成执行的 committed 延迟事件（artifact/created 等）必须
                    # 在异常传播前落盘，不能随异常一起消失（R6-7；TOOL_CALL 由
                    # runtime 预持久化，见 emit_call_event）。
                    self._flush_committed_events(
                        results, session,
                        run_id=operation_context.run_id if operation_context else None,
                    )
                    raise result
            return results

        # serial：永久失败后停止真实执行，剩余调用返回并持久化 CANCELLED。
        executions: list[ToolExecution] = []
        try:
            for index, tool_call in enumerate(tool_calls):
                execution = await self.execute(
                    tool_call, operation_context=operation_context,
                    session=session, step_id=step_id, tracer=tracer,
                )
                executions.append(execution)
                if execution.result.ok:
                    continue
                for remaining in tool_calls[index + 1 :]:
                    executions.append(
                        await self._cancel_without_execution(
                            remaining, operation_context=operation_context
                        )
                    )
                break
            return executions
        except BaseException:
            # 存储故障等真实异常传播前，已完成执行的 committed 事件先落盘（R6-7）。
            self._flush_committed_events(
                executions, session,
                run_id=operation_context.run_id if operation_context else None,
            )
            raise

    def emit_call_event(
        self,
        session: Any,
        *,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        run_id: str | None,
        step_id: int | None,
    ) -> SessionEvent:
        """持久化 TOOL_CALL（执行前，ADR-0016 §4.1）。

        02 §8.3 状态机要求 call 先于执行：前端（及重连重放）在工具在途期间
        就有可关联的 tool_call（output_delta 按 tool_call_id 挂靠）。调用方
        （AgentRuntime step 7）在每个 call 执行前调用并镜像 yield。
        """
        return session.append(
            TOOL_CALL,
            {"tool_call_id": tool_call_id, "tool_name": tool_name, "args": args},
            run_id=run_id, step_id=step_id,
        )

    def emit_pending_events(
        self,
        session: Any,
        *,
        pending_events: list[tuple[str, dict[str, Any]]],
        run_id: str | None,
        step_id: int | None,
    ) -> list[SessionEvent]:
        """持久化延迟事件（R6-7：artifact/created 等，在 tool/call 之后、
        tool/result 之前）。与 emit_call_event / emit_result_event 共同构成
        顺序知识的单一 owner。"""
        return [
            session.append(event_type, data, run_id=run_id, step_id=step_id)
            for event_type, data in pending_events
        ]

    def emit_result_event(
        self,
        session: Any,
        *,
        tool_call_id: str,
        content: str,
        run_id: str | None,
        step_id: int | None,
    ) -> SessionEvent:
        """持久化 TOOL_RESULT（content = ToolResult JSON，与旧契约一致）。"""
        return session.append(
            TOOL_RESULT,
            {"tool_call_id": tool_call_id, "content": content},
            run_id=run_id, step_id=step_id,
        )

    def _flush_committed_events(
        self,
        results: list[ToolExecution | BaseException],
        session: Any,
        *,
        run_id: str | None,
    ) -> None:
        """批次异常传播前，把已完成执行的延迟事件落盘（R6-7）。

        artifact 已写存储、Ledger 已终态——事件若随异常一起丢弃，store 里的
        artifact 就成了无引用孤儿（旧缺陷：partial batch 失败丢已提交的
        artifact/created 事件）。TOOL_CALL 不在这里补：ADR-0016 §4.1 起由
        Runtime 在批次启动前预持久化（emit_call_event），补发即重复。
        run 归因走显式参数；无 session 时（纯执行场景）无事可做。
        """
        if session is None:
            return
        try:
            for result in results:
                if isinstance(result, BaseException):
                    continue
                self.emit_pending_events(
                    session,
                    pending_events=result.pending_events,
                    run_id=run_id, step_id=None,
                )
        except Exception:
            # flush 自身失败（存储故障）不得掩盖原始批次异常——原始异常是
            # 调用方失败归因的依据；flush 失败由日志承载。
            logger.exception("Flushing committed tool events failed during batch abort")
            raise

    @staticmethod
    def _log_secondary_exceptions(
        results: list[ToolExecution | BaseException],
        tool_calls: list[ToolCall | dict[str, Any]],
    ) -> None:
        """把批次里除首个异常外的其余异常按 tool_call_id 落日志（不改变抛出契约）。

        gather(return_exceptions=True) 只允许 raise 一个异常，其余异常若不在此
        记录就永远丢失。首个异常由调用方原样抛出，不在这里重复记录。
        """
        primary = next(
            index
            for index, result in enumerate(results)
            if isinstance(result, BaseException)
        )
        for index, result in enumerate(results):
            if index == primary or not isinstance(result, BaseException):
                continue
            call_id = ToolCall.normalize(tool_calls[index]).id
            # 不走 self._log/log_event：EVENT_TYPES 是冻结白名单（诊断事件不该
            # 为它动日志协议），ERROR 级别也需直达 module logger。
            # exc_info=result 让 traceback 携带消息，避免在消息体里渲染异常字符串
            # （某些工具会把入参/URL/凭据拼进异常文本）。
            logger.error(
                "并行批次除首个异常外还有其它调用失败（首个异常照常抛出，其余仅记录）："
                "tool_call_id=%s，%s",
                call_id,
                type(result).__name__,
                exc_info=result,
            )

    async def _create_pending_operation(
        self,
        *,
        tool_call_id: str,
        name: str,
        raw_args: dict[str, Any],
        operation_context: OperationContext | None,
        tool: Tool | None = None,
    ) -> None:
        """Persist the shared PENDING boundary before execute or cancellation."""
        if self._operation_ledger is None:
            return
        if operation_context is None:
            raise ValueError(
                "operation_context is required when OperationLedger is configured"
            )
        if tool is None:
            try:
                tool = self._registry.get(name)
            except KeyError:
                pass
        args_identity = (
            tool.args_identity(raw_args)
            if tool is not None
            else json.dumps(raw_args, sort_keys=True, ensure_ascii=False)
        )
        await self._operation_ledger.create(
            Operation(
                tool_call_id=tool_call_id,
                session_id=operation_context.session_id,
                run_id=operation_context.run_id,
                agent_id=operation_context.agent_id,
                tool_name=name,
                args_identity=args_identity,
                state=OperationState.PENDING,
                started_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
            )
        )

    async def _cancel_without_execution(
        self,
        tool_call: ToolCall | dict[str, Any],
        *,
        operation_context: OperationContext | None,
    ) -> ToolExecution:
        """Represent a serially cascaded call without invoking its Tool."""
        call = ToolCall.normalize(tool_call)
        tool_call_id = call.id
        name = call.name
        raw_args = call.args
        result = ToolResult.failure(
            message=(
                f"工具 '{name}' 未执行：串行批次中的前序工具已永久失败。"
            ),
            error_code=ErrorCode.CANCELLED,
            retryable=False,
        )

        if self._operation_ledger is not None:
            assert operation_context is not None
            await self._create_pending_operation(
                tool_call_id=tool_call_id,
                name=name,
                raw_args=raw_args,
                operation_context=operation_context,
            )
            await self._operation_ledger.update_state(
                operation_context.session_id, tool_call_id,
                OperationState.CANCELLED,
                result_json=result.model_dump_json(),
            )

        return ToolExecution(tool_call_id=tool_call_id, result=result)

    def _decide_mode(self, tool_calls: list[ToolCall | dict[str, Any]]) -> str:
        """扫描批次，决定并发还是串行。

        一条可解释规则：全 READ_ONLY 才并发；任一 MUTATING 整批串行。
        未注册的工具名按 READ_ONLY 算（不影响调度，让其走 execute 正常报错）。
        """
        for call in ToolCall.normalize_all(tool_calls):
            name = call.name
            try:
                tool = self._registry.get(name)
            except KeyError:
                # 工具不存在：不该用它干扰并发决策（可能只是本批其它工具合法地并发）。
                # 让它走正常 execute() 报 TOOL_NOT_FOUND，mode 只看合法工具的 side_effect。
                continue
            # 任一 MUTATING 即整批串行：一个就够，无需扫剩下的工具。
            # 判断钉在 side_effect 枚举位上（与 should_retry 只看 retryable 同理）：
            # 确定性语义，不猜工具名、不解析描述。
            if tool.side_effect == ToolSideEffect.MUTATING:
                return "serial"

        # 全部扫完没命中 MUTATING → 全 READ_ONLY → 并发。
        return "parallel"

    async def _check_approval(
        self,
        tool_call_id: str,
        name: str,
        tool: Tool,
        raw_args: dict[str, Any],
    ) -> ToolExecution | None:
        """阶段 2.5：审批关卡。返回 None 表示放行，返回 ToolExecution 表示拒绝。

        逻辑（05_SANDBOX_CODING_TOOLS.md §6）：
        - DANGER_FULL_ACCESS → 放行。
        - tool.permission 级别在 policy 允许范围内 → 放行。
        - 超级别或 DANGER 在受限 policy 下 → 需要 approval：
          - 无 callback → PERMISSION_DENIED（安全默认）。
          - 有 callback → 调 callback；approved → 放行；denied → PERMISSION_DENIED。
        """
        tool_perm = tool.permission
        if not needs_approval(tool_perm, self._policy):
            return None

        reason = approval_reason(tool_perm, self._policy)
        request = ApprovalRequest(
            tool_name=name,
            args=raw_args,
            permission=tool_perm,
            policy=self._policy,
            reason=reason,
            tool_call_id=tool_call_id,
        )

        if self._approval_callback is None:
            # 安全默认值：无审批回调 → 拒绝。绝不静默放行高风险操作。
            return ToolExecution(
                tool_call_id=tool_call_id,
                result=ToolResult.failure(
                    message=f"工具 '{name}' 需要审批但未配置审批回调，已被拒绝。{reason}",
                    error_code=ErrorCode.PERMISSION_DENIED,
                    retryable=False,
                ),
            )

        response: ApprovalResponse = await self._approval_callback(request)
        if response.approved:
            # per-call scoping：批准只对这次 execute 生效，不存状态。
            return None

        return ToolExecution(
            tool_call_id=tool_call_id,
            result=ToolResult.failure(
                message=f"工具 '{name}' 的执行请求已被拒绝。{response.reason or reason}",
                error_code=ErrorCode.PERMISSION_DENIED,
                retryable=False,
            ),
        )

    async def _execute_with_retry(
        self, tool_call_id: str, name: str, tool: Tool, validated: BaseModel,
        *, tracer: Any = None, attempts: list[dict[str, Any]] | None = None,
    ) -> ToolResult:
        """阶段3 主体：每次尝试被 timeout 包住，retryable 位驱动是否再来一轮。

        一轮 attempt 的数据流：
          t0 = perf_counter()
          asyncio.timeout(tool.timeout_seconds) 包住 await tool.execute(validated)
            -> 正常返回 ToolResult  -> 透传（尊重工具自己的 ok/retryable 语义）
            -> 抛 TimeoutError      -> 映射 TIMEOUT（READ_ONLY 可重试；MUTATING 不可——
                                      副作用状态未知不盲重跑，见 except TimeoutError 注释）
            -> 抛其它 Exception     -> 查 _EXCEPTION_CLASSIFICATION 分类
          记 duration_ms -> 写一条 tool_operation 日志 -> 回填 metadata
          -> 重试决策（失败且 retryable 且未用完 MAX_ATTEMPTS 才重试）-> 决定重试则写一条 retry 日志
        """
        total_ms = 0.0
        result: ToolResult | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            t0 = perf_counter()
            try:
                # Timeout 边界：只包 execute 这一行；到点未返回即被取消并抛 TimeoutError。
                async with asyncio.timeout(tool.timeout_seconds):
                    result = await tool.execute(validated)
            except TimeoutError:
                # asyncio.timeout 到点把 execute 掐断——映射细节（含 retryable 为何
                # 取决于 side_effect）集中在 _ToolFailure.from_timeout。
                result = _ToolFailure.from_timeout(tool, name).to_result()
            except Exception as e:  # noqa: BLE001
                # 宽捕获理由同 Task 2：工具是开放世界，无法预知会抛什么。
                # 分类表查找（isinstance 连子类一起认）在 _ToolFailure.from_exception。
                result = _ToolFailure.from_exception(e, name).to_result()

            duration_ms = round((perf_counter() - t0) * 1000, 1)
            total_ms += duration_ms
            assert result is not None  # 三个分支必赋值

            # 把执行元数据回填进 metadata（model_copy 复制，不改工具返回的原对象）。
            # 模型和测试都能从这里读出"第几次尝试、花了多久"。
            result = result.model_copy(
                update={
                    "metadata": {
                        **result.metadata,
                        "attempt": attempt,
                        "max_attempts": MAX_ATTEMPTS,
                        "duration_ms": duration_ms,
                        "total_duration_ms": round(total_ms, 1),
                    }
                }
            )

            if attempts is not None:
                attempts.append({
                    "attempt": attempt, "duration_ms": duration_ms,
                    "error_code": result.error_code, "retryable": result.retryable,
                    "ok": result.ok,
                })
            # 每个 attempt 一条 tool_operation：JSONL 靠它还原完整重试链。
            self._log(
                "tool_operation",
                f"工具 {name} 第 {attempt}/{MAX_ATTEMPTS} 次尝试"
                f"{'成功' if result.ok else '失败'}",
                tool_call_id=tool_call_id,
                tool_name=name,
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS,
                timeout_ms=round(tool.timeout_seconds * 1000),
                duration_ms=duration_ms,
                error_code=result.error_code,
                retryable=result.retryable if not result.ok else None,
                outcome="success" if result.ok else "failure",
            )

            # -- 重试决策：唯一 Retry Layer 的心脏 --
            # 反向取补集：三种必须停的情况（成功 / retryable=False / 用完上限）
            # 都不成立时才再来一轮。
            should_retry: bool = (
                not result.ok  # a. 已成功 -> 停
                and result.retryable  # b. 确定性失败 -> 停
                and attempt < MAX_ATTEMPTS  # c. 用完上限 -> 停，防无限重试
            )

            if not should_retry:
                break

            # 决定重试：写一条 retry 事件，JSONL 里"为什么再试"有据可查。
            self._log(
                "retry",
                f"工具 {name} 第 {attempt} 次尝试失败且可重试，准备第 {attempt + 1} 次尝试",
                tool_call_id=tool_call_id,
                tool_name=name,
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS,
                error_code=result.error_code,
                retryable=True,
                outcome="pending",
            )

        assert result is not None
        return result

    def _log(self, event_type: str, message: str, **fields: Any) -> None:
        """打一条结构化日志；无 handler 时零成本 no-op。

        同 AgentRuntime 的做法：测试里高频跑 execute()，没有 handler 时
        短路掉 log_event，日志彻底零成本；调用方 setup_logging() 后正常写 JSONL。
        """
        if not logger.hasHandlers():
            return
        log_event(logger, event_type, message, **fields)
