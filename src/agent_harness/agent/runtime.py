"""AgentRuntime：把两轮 tool-calling 协议收进一段可读的异步循环。

每轮固定顺序：
    1. messages = await context_builder.build(session)（按预算投影）
    2. 模型调用（ainvoke 一次性 / astream 流式逐 chunk）
    3. session.append(model/completed)（持久化完整 AIMessage）
    4. steps += 1
    5. 若无 tool_calls → 返回最终回答；若 steps >= max_steps → 返回兜底状态；否则执行工具回填进入下一轮

两个入口：
    - run(): 经典一次性调用，返回 AgentRunResult（向后兼容，252 现有测试不破）。
    - run_stream(): Phase 9 流式入口，async iterator 逐条 yield AgentEvent，
      含持久化 SessionEvent 的镜像 + ADR-0016 起合帧落盘的流式事实
      （model/delta、reasoning/*）+ 纯流式信号 model/started（不持久化）。

事件事实源：Session.append 同步写 JSONL；messages list 退化为运行期投影缓存。
Diagnostic Log（_log）保留不动——执行链路观察与 SessionEvent 分层并存。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk

from agent_harness.agent.guards import (
    GuardLevel,
    RepeatedToolFailureGuard,
)
from agent_harness.agent.streaming import BlockStreamer
from agent_harness.agent.types import (
    STATUS_COMPLETED,
    STATUS_CONTEXT_WINDOW_EXCEEDED,
    STATUS_FAILED,
    STATUS_IDENTICAL_TOOL_FAILURE_LOOP,
    STATUS_MAX_STEPS_EXCEEDED,
    AgentEvent,
    AgentRunResult,
    to_agent_event,
)
from agent_harness.context.builder import ContextBuilder, ContextWindowExceededError
from agent_harness.context.provider import ContextProvider
from agent_harness.logging import log_event, new_span_id
from agent_harness.memory.writeback import MemoryWriteback
from agent_harness.model.concurrency import ModelCallGate
from agent_harness.model.fallback import (
    FallbackPolicy,
    ModelFallbackCoordinator,
    TwoLevelFallbackPolicy,
)
from agent_harness.observability.tracer import RunTracer
from agent_harness.prompt import DEFAULT_REGISTRY
from agent_harness.session import (
    CONTEXT_COMPACTED,
    MODEL_COMPLETED,
    MODEL_FAILED,
    MODEL_FALLBACK,
    MODEL_STARTED,
    RUN_FAILED,
    RUN_STARTED,
    TOOL_FAILURE_GUARD,
    USER_MESSAGE,
    Session,
    SessionEvent,
    run_context_var,
)
from agent_harness.storage import (
    CheckpointBoundary,
    CheckpointPolicy,
    OnStableBoundary,
    OperationContext,
    SessionMeta,
)
from agent_harness.tooling import ToolCall, ToolExecutor, ToolRegistry

logger = logging.getLogger("agent_harness.agent")

#: DeepSeek 系（主/备 provider 均为 deepseek 模型）工具调用的协议保留标记。
#: 碎片化流下网关的 DSML 工具调用可能未被解析成结构化 tool_calls 而以乱码
#: content 泄漏（冒烟实测 session 7afd328a：流式标记混进最终回答）——含此
#: 标记的 content 绝不可能是合法模型回答，按模型故障处理（走统一失败兜底，
#: 决不伪造 run/completed）。用全角 ｜ 保留标记做判据以杜绝误伤正常讨论文本。
#: 记忆抽取排除的事件类型（ADR-0016 review 修复）：流式增量事实不进
#: MemoryWriteback——reasoning 是 provider 私有思考（隐私边界），text/tool
#: 增量与各自的终态事件（model/completed / tool/result）内容重复。
_MEMORY_EXCLUDED_EVENT_TYPES = frozenset({
    "reasoning/started", "reasoning/delta", "reasoning/completed",
    "reasoning/interrupted", "text/delta", "tool/output_delta",
})

_DSML_MARKUP_MARKER = "<｜DSML｜"

# provider 内容审查拒绝分类（阿里云 data_inspection_failed，2026-09-11 真实
# 案例：百炼端点对含检索网页文本的二次调用 400）。识别后失败事件升级为固定
# 可读文案，消费者（UI 事件检查器）无需翻服务端日志。只做分类——provider
# 回显原文绝不进事件（脱敏不变量，见 append_model_failed）。
CONTENT_MODERATION_REASON = "provider_content_moderation"
CONTENT_MODERATION_MESSAGE = "provider 内容审查拒绝输入（可能因检索到的网页文本）"
_CONTENT_MODERATION_MARKER = "data_inspection_failed"


def _classify_provider_failure(error: BaseException) -> str | None:
    """错误文本含内容审查错误码 → 返回分类 reason，否则 None（保持原行为）。

    按文本匹配而不是 SDK 异常属性：openai SDK 对 SSE 形状的错误响应
    （``data: {...}``）解析不出结构化 body，错误码只存在于 str(error) 里。
    """
    if _CONTENT_MODERATION_MARKER in str(error):
        return CONTENT_MODERATION_REASON
    return None


def _usage_from_response(ai: Any) -> dict[str, int] | None:
    """从模型响应如实抽取 token usage；响应没带就返回 None（绝不伪造）。

    负值条目直接丢弃：负 token 数对账无效，入账会污染 usage_total 聚合。
    丢弃遵循"缺失/无效时省略"语义，不是伪造；非数值形状已被 AIMessage 自身
    校验挡在构造期（归因 model 失败，语义正确），到不了这里。
    """
    meta = getattr(ai, "usage_metadata", None)
    if not isinstance(meta, dict):
        return None
    usage: dict[str, int] = {}
    for source_key, target_key in ({"input_tokens": "prompt_tokens",
                                    "output_tokens": "completion_tokens",
                                    "total_tokens": "total_tokens"}).items():
        value = meta.get(source_key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            usage[target_key] = value
    return usage or None


def _model_name_from_response(ai: Any) -> str | None:
    """从响应元数据取本次推理的模型名；拿不到就 None，不猜不编。"""
    meta = getattr(ai, "response_metadata", None) or {}
    name = meta.get("model_name") or meta.get("model")
    return name if isinstance(name, str) and name else None


def _extract_text(content: Any) -> str:
    """从模型 content 抽纯文本：str 直通；list（Anthropic 风格块）只拼 type=text 的块。

    绝不用 str(content) 兜底——那会把 Python repr（"[{'type': 'text', ..."）持久化
    进 model/completed / final_text / delta，derive_messages 再把 repr 文本当对话
    回灌给模型。非文本块（tool_use / image 等）与未知形状一律丢弃：宁可少，不可脏。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _extract_reasoning(chunk: Any) -> str:
    """从流式 chunk 抽第三方思考文本（D-B①，ADR-0016 §3.4）。

    ReasoningChatOpenAI 把网关的 delta.reasoning_content 抬进
    additional_kwargs["reasoning_content"]；非字符串/缺失 = 本 chunk 无思考，
    返回空串（调用方据此跳过，零伪造）。
    """
    kwargs = getattr(chunk, "additional_kwargs", None)
    if isinstance(kwargs, dict):
        raw = kwargs.get("reasoning_content")
        if isinstance(raw, str) and raw:
            return raw
    return ""


class _RunFinalizer:
    """一次 Run 的终态簿记 owner（批次 B / 架构候选 2）。

    _drive 的取消臂/异常臂此前各自维护近重复的 ~40 行收尾，"一个 run 至多
    一条终态事件"的不变量由散布在 360 行里的布尔旗执行——近期四次 bug 修复
    （1cfe795 终结事件 / 59e4425 checkpoint 不毒化 / 19d7e47 取消耐久 /
    4e47b90 空响应归失败）全落在两条臂的交互上。终态决策收拢到本类后，
    单终态由单点执行，终态收尾可脱离 ScriptedModel 全链单测。

    usage_total 是 _drive 聚合 dict 的引用（不复制）：终结时快照当时账目。
    """

    def __init__(self, session: Session, usage_total: dict[str, int]) -> None:
        self._session = session
        self._usage_total = usage_total
        self.run_id: str | None = None
        self.model_call_open = False
        self._terminal_written = False

    def begin_run(self, run_id: str) -> None:
        self.run_id = run_id

    def mark_terminal_written(self) -> None:
        """成功路径（completed / max-steps）写入终结事件后调用。"""
        self._terminal_written = True

    def append_model_failed(
        self, *, step: int, cancelled: bool, error_type: str | None = None,
        readable_message: str | None = None,
    ) -> SessionEvent:
        """模型在途失败/取消 → model/failed，把故障归因到具体一步。

        异常消息可能含 Provider 回显的敏感文本——事件只带类型名（与
        memory/writeback 的脱敏不变量一致），完整消息**与调用栈**只进结构化日志
        （OBS-008：`_log(..., exc_info=True)` 落 `stack_trace(调用栈)`；此前只记类型名，
        排障无从下手）。
        ``readable_message`` 是**已分类故障**的固定可读文案（如内容审查拒绝）——
        调用方只传本项目常量、绝不透传 provider 原文，脱敏边界不变。
        """
        if cancelled:
            message = "model call cancelled"
        else:
            message = readable_message or f"model call failed: {error_type}"
        return self._session.append(
            MODEL_FAILED,
            {"message": message},
            run_id=self.run_id, step_id=step + 1,
        )

    def cancelled_terminal(
        self, *, steps: int, reason: str = "cancelled", trace_id: str | None = None,
        trace_url: str | None = None,
    ) -> SessionEvent | None:
        """取消臂收尾（纯同步、不 yield——生成器关闭中禁止再产出）。

        run 未开始（begin_run 之前被取消）→ None，已写事件保持原样；
        已终结的 run 不补第二条终结（双终结 = 历史不可对账）。
        reason 区分取消来源（02 §17 错误语义分离）：显式 POST /cancel 与
        断连消费 = "cancelled"；孤儿回收 = "orphaned"（ADR-0016 §2.1）。"""
        if self.run_id is None or self._terminal_written:
            return None
        terminal_data: dict[str, Any] = {"reason": reason}
        if self._usage_total:
            # 取消也如实带上 token 消耗（Gap 1 契约，不因取消路径丢账）。
            terminal_data["usage_total"] = dict(self._usage_total)
        terminal_data["trace_id"] = trace_id
        terminal_data["trace_url"] = trace_url
        event = self._session.append(
            RUN_FAILED, terminal_data, run_id=self.run_id, step_id=steps,
        )
        self._terminal_written = True
        return event

    def failure_terminal(
        self, *, steps: int, reason: str | None = None,
        message: str | None = None, trace_id: str | None = None,
        trace_url: str | None = None,
    ) -> SessionEvent | None:
        """异常臂收尾 → run/failed（usage 如实，无数据省略）。单终态约束同上。

        reason 落事件 data（如 identical_tool_failure_loop）——消费者区分失败
        原因，与取消臂的 reason=cancelled 同一语义层。message 是已分类故障的
        固定可读文案（reason+message 成对，与上下文超限路径的 RUN_FAILED
        形状一致）；缺省两者都不落键（合同：缺省 = 模型/执行器异常）。
        """
        if self.run_id is None or self._terminal_written:
            return None
        event = self._session.end_run(
            self.run_id, status="failed",
            usage_total=dict(self._usage_total) or None,
            reason=reason,
            message=message,
            trace_id=trace_id,
            trace_url=trace_url,
        )
        self._terminal_written = True
        return event


@dataclass
class _TerminalContext:
    """取消臂 / 异常臂共享的收尾上下文（架构候选 1）。

    两条臂历史上各自维护近重复的收尾序列（streamer 收口 → 切换事实落盘 →
    model/failed 归因 → tracer 收口），差异只有「能否 yield」与 reason 取值。
    收拢到本对象后，重复收尾由单点方法执行，两条臂只决定 yield 策略。

    两个收尾方法都返回本次追加的持久化事件列表（按 append 顺序），调用方决定
    逐条镜像给流消费者（异常臂）还是丢弃（取消臂——生成器关闭中禁止 yield）。
    """

    session: Session
    run_id: str | None
    steps: int
    terminal: _RunFinalizer
    streamer: BlockStreamer | None
    model_coord: ModelFallbackCoordinator
    tracer: Any
    ctx_span: Any
    generation: Any

    def interrupt_streams(self) -> list[SessionEvent]:
        """流式块收口 + 切换事实落盘（取消臂与异常臂同一不变量）。

        顺序固定：interrupted（块级部分内容保留）先于 model/failed（调用级归因）；
        drain 幂等——成功路径已取走则此处为空。
        """
        events: list[SessionEvent] = []
        if self.streamer is not None:
            # 取消臂忽略返回值（生成器关闭中禁止 yield）；异常臂逐条镜像。
            events.extend(self.streamer.interrupt(step=self.steps + 1))
        for transition in self.model_coord.drain_transitions():
            events.append(self.session.append(
                MODEL_FALLBACK,
                {"from_model": transition.from_model,
                 "to_model": transition.to_model,
                 "reason": transition.reason},
                run_id=self.run_id, step_id=self.steps + 1,
            ))
        return events

    def close_observability(
        self, *, error_type: str | None, reason: str, cancelled: bool = False,
        readable_message: str | None = None,
    ) -> list[SessionEvent]:
        """model/failed 归因 + tracer 收口（ctx_span / generation / run_failed）。

        ``cancelled`` 区分取消臂（True）与异常臂（False）的 model/failed 消息；
        ``error_type`` 只落类型名（脱敏不变量）；完整消息与调用栈只进结构化日志
        （见 `_log` 的 `exc_info`，OBS-008）。``readable_message`` 是已分类故障
        的固定可读文案，透传给 model/failed（见 append_model_failed）。
        """
        events: list[SessionEvent] = []
        if self.terminal.model_call_open:
            events.append(self.terminal.append_model_failed(
                step=self.steps, cancelled=cancelled, error_type=error_type,
                readable_message=readable_message,
            ))
        if self.tracer is not None:
            if self.ctx_span is not None:
                self.tracer.context_build_completed(self.ctx_span)
                self.ctx_span = None
            if self.generation is not None:
                self.tracer.model_call_failed(
                    self.generation,
                    error_type=("cancelled" if cancelled else error_type),
                )
                self.generation = None
            self.tracer.run_failed(reason)
        return events


class AgentRuntime:
    """最小透明 Agent Loop。

    构造时绑定 model + registry + executor + max_steps；一次 run()/run_stream() 通过
    Session 驱动 event-sourced 循环。工具执行（校验/超时/重试/并发）下沉到
    ToolExecutor；本类只保留"驱动循环"这一份职责。
    """

    def __init__(
        self,
        model: Any,
        registry: ToolRegistry,
        executor: ToolExecutor,
        max_steps: int = 20,
        *,
        checkpoint_policy: CheckpointPolicy | None = None,
        session_meta_store: Any | None = None,
        context_builder: ContextBuilder | None = None,
        context_providers: list[ContextProvider] | None = None,
        system_prompt: str | None = None,
        memory_writer: MemoryWriteback | None = None,
        failure_guard: RepeatedToolFailureGuard | None = None,
        fallback_model: Any | None = None,
        fallback_policy: FallbackPolicy | None = None,
        primary_model_name: str = "primary",
        fallback_model_name: str = "fallback",
        stream_idle_timeout: float = 0.0,
        stream_total_timeout: float = 0.0,
        model_call_gate: ModelCallGate | None = None,
        agent_id: str = "default",
        observability_sink: Any | None = None,
    ) -> None:
        self.registry = registry
        self.executor = executor
        # 同错熔断护栏（ADR-0014 #69）：可选注入；默认每 run 一个新实例
        # （计数不跨 run 累积——每个 run 的循环各自干净起步）。
        self._failure_guard = failure_guard
        # Model Fallback（ADR-0014 决策 14-16）：两级 + FallbackPolicy seam。
        # 切换决策在 policy（瞬时性判断）；本类只编排调用序列并持久化
        # model/fallback 事件。切换状态按 run 独立（见 _drive）。
        self._fallback_policy = fallback_policy or TwoLevelFallbackPolicy()
        self._primary_model_name = primary_model_name
        self._fallback_model_name = fallback_model_name
        # 流式守卫（秒，逐项 ≤0 关闭）：idle=死连接，total=慢滴漏——所有 run
        # 都受保护（无 fallback 时走统一失败兜底），见 model/stall.py。
        self._stream_idle_timeout = stream_idle_timeout
        self._stream_total_timeout = stream_total_timeout
        # 进程级模型并发闸（#89）：assembly 创建，parent 与所有 child 共享
        # 同一引用（全局在飞模型调用数的语义），None = 不加闸。
        self._model_call_gate = model_call_gate
        # 归因身份（ADR-0015 决策 6）：child runtime 落 profile 名——run/started
        # 与 Ledger 条目不再全是 "default"（parent 保持 "default" 向后兼容）。
        self._agent_id = agent_id
        # Langfuse 旁路观测（ADR-0018 D2）：可选注入；None/缺席 = 零开销。
        # 埋点是添加性的：tracer 故障被 sink 边界吞掉，绝不影响 Loop 语义。
        self._observability_sink = observability_sink
        # max_steps 是"模型不收敛时的保险丝"，不是正常业务停止条件；
        # 正常停止由"模型不再返回 tool_calls"决定。
        self.max_steps = max_steps
        # Checkpoint seam（ADR-0004 Round 2）：默认策略 OnStableBoundary，
        # 但只有注入了 CheckpointStore 才真正落盘——Core 不被存储强制依赖。
        self._checkpoint_policy = checkpoint_policy or OnStableBoundary(None)
        self._session_meta_store = session_meta_store
        # 使用未绑定工具的原始 Provider 生成摘要，不让摘要调用请求工具。
        # system_prompt（ADR-0020a，agent_profile 运行时消费）：与 context_builder
        # 不同时传——context_builder 是更完整的注入点（调用方自管 system_prompt）；
        # 同时传时 context_builder 优先，system_prompt 被忽略并记一条 warning。
        if context_builder is not None and system_prompt is not None:
            logger.warning(
                "AgentRuntime 同时收到 context_builder 和 system_prompt——"
                "context_builder 优先，system_prompt 被忽略（调用方应在构造 "
                "context_builder 时注入 system_prompt）"
            )
        self._context_builder = context_builder or ContextBuilder(
            model, context_providers=context_providers, system_prompt=system_prompt,
        )
        if context_builder is not None and context_providers:
            # 双入口注入按身份去重：同一 provider 实例已在 builder 列表里时跳过
            # ——否则每 build 重复执行（重复注入内容 + 双倍搜索/超时风险）。
            existing_ids = {id(p) for p in self._context_builder.context_providers}
            self._context_builder.context_providers.extend(
                p for p in context_providers if id(p) not in existing_ids
            )
        self._memory_writer = memory_writer

        # 把 Registry 的工具定义绑定到模型——模型才会知道有哪些工具可选、
        # 并在回复里产出 tool_calls。bind_tools 是 LangChain 的标准接线点。
        # ScriptedModel 没有 bind_tools（测试用剧本直接构造 tool_calls），跳过绑定。
        definitions = registry.export_model_definitions()
        if definitions and hasattr(model, "bind_tools"):
            self.model = model.bind_tools(definitions)
        else:
            self.model = model
        # fallback 模型同样绑定工具：切换后仍能发 tool_calls（否则带工具的
        # 会话切到 fallback 后模型看不到工具，行为静默退化）。
        self._fallback_model: Any | None = None
        if fallback_model is not None:
            if definitions and hasattr(fallback_model, "bind_tools"):
                self._fallback_model = fallback_model.bind_tools(definitions)
            else:
                self._fallback_model = fallback_model

    async def run(self, session: Session, user_input: str) -> AgentRunResult:
        """跑完整条 Agent Loop，返回 AgentRunResult。

        所有交互历史通过 Session 的 append-only SessionEvent 持久化；
        messages list 退化为每轮从事件投影出的运行期缓存。
        用 ainvoke 一次性拿完整 AIMessage（非流式入口，向后兼容）。
        """
        # 结果经本次调用专属的 holder 回传，不经实例字段——一个 Runtime 并发
        # 跑多个 run 时各拿各的，绝不出现"谁后终结谁生效"的跨 run 串台。
        result_holder: list[AgentRunResult] = []
        async for _ in self._drive(session, user_input, stream=False, result_holder=result_holder):
            pass  # 丢弃流式事件，只要副作用（持久化 + 最终结果）
        return result_holder[-1]

    async def run_stream(
        self, session: Session, user_input: str,
        cancel_reason_supplier: Callable[[], str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """流式驱动 Agent Loop，逐条 yield AgentEvent。

        与 run() 的区别：用 model.astream() 逐 chunk 流式产出，思考/文本 chunk
        经 BlockStreamer 合帧持久化（ADR-0016：text/delta 与 reasoning/* 是
        durable 事实，断连重连可按 seq 重放恢复）；model/started 保持
        stream-only。每个被 session.append 持久化的事件，同时 yield 一个
        镜像 AgentEvent（带 seq）。

        cancel_reason_supplier（ADR-0016 §2.1）：取消臂收尾时调用来决定
        run/failed 的 reason（"cancelled" / "orphaned"），让 run 的宿主
        （web RunManager）区分取消来源；None = 默认 "cancelled"。

        SSE endpoint 直接消费这个 iterator；前端据此实时渲染。
        """
        drive = self._drive(
            session, user_input, stream=True,
            cancel_reason_supplier=cancel_reason_supplier,
        )
        try:
            async for event in drive:
                yield event
        finally:
            # 委托生成器不自动关闭内层（PEP 525）：消费者对 run_stream 直接
            # aclose / GC 时，内层 _drive 收不到 GeneratorExit，取消臂的持久化
            # 收尾（终结悬空 run/started）永远不会执行。这里显式收口——
            # 收尾中禁止再 yield，但允许 await；_drive 的取消臂是纯同步收尾。
            await drive.aclose()

    async def _drive(
        self, session: Session, user_input: str, *, stream: bool,
        result_holder: list[AgentRunResult] | None = None,
        cancel_reason_supplier: Callable[[], str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """共享的主循环——run 和 run_stream 的唯一实现，消除重复。

        stream=True 时用 astream + yield model/delta；stream=False 时用 ainvoke。
        每个持久化事件都 yield 镜像 AgentEvent（带 seq）；纯流式信号也 yield。
        终结时把 AgentRunResult 写进本次调用专属的 result_holder 供 run() 取用
        （不经实例字段：并发 run 共享同一个 Runtime 时结果互不串台）。
        """
        if result_holder is None:
            # run_stream 不读结果；终结路径统一写入载体，调用方各给各的。
            result_holder = []
        # ── 失败兜底所需的安全默认值：run 绝不能永久悬挂在悬空的 run/started 上 ──
        # 异常可能发生在 begin_run 之前（user 持久化 / checkpoint 阶段），此时
        # 没有可终结的 run；run_span / steps / usage_total 同理需要初值。
        run_id: str | None = None
        steps = 0
        # session 级 step 基数（前端 turn 定位键的单调性来源）。事件信封的
        # step_id 必须 session 级唯一递增，续聊 run 若再从 1 编号，第二轮的
        # model/* 会与首轮冲突——前端 withTurnAt 折叠进首轮 turn，首轮回答被
        # 清空、次轮回答错位（TICKET_STEP_ID_COLLISION_MULTI_TURN）。
        # 注意 steps 仍是 run 内轮次计数（max_steps 保险丝与 AgentRunResult.steps
        # 依赖它逐 run 从 0 起算），全局编号一律走 step_base + steps。
        step_base = 0
        # Langfuse 旁路（ADR-0018 D5/D7）：begin_run 后创建；六条终态臂统一
        # 经它收口 trace 并回填 trace_id。begin_run 之前异常 = 无 run 可观测。
        tracer: Any = None
        generation: Any = None
        ctx_span: Any = None
        # 流式块记账（ADR-0016 §3.3）：思考/文本合帧落盘 + reasoning 块生命周期。
        # begin_run 之前异常 = 没有可记账的 run，保持 None。
        streamer: BlockStreamer | None = None
        # 本轮 run 的 token 消耗聚合（Gap 1）：各轮 usage 如实累加，无数据则省略。
        usage_total: dict[str, int] = {}
        # 终态簿记 owner（批次 B 候选 2）：model 在途标记 + 单终态不变量 +
        # usage 记账收拢一处，取消臂/异常臂只做调用。
        terminal = _RunFinalizer(session, usage_total)
        # 同错熔断护栏：每 run 一个新实例（注入或新建）；计数不跨 run 累积。
        guard = self._failure_guard or RepeatedToolFailureGuard()
        guard.reset()
        # run 归因 token：嵌套运行（delegate→child 在同一父任务里跑）共享父
        # 上下文——child 的 set 会覆盖父值且不会随 child 完成消失，必须显式
        # 恢复，否则父后续的 Ledger/事件归因错挂到 child 的 run_id（#87 实锤）。
        run_context_token = None
        # Model Fallback + 卡流看门狗 + 并发闸：每 run 一个新 coordinator
        # （切换状态不跨 run 共享）。统一调用路径——未配 fallback 时 coordinator
        # 退化为透传（异常原样上抛），但看门狗/并发闸对所有 run 生效。
        model_coord = self._new_coordinator()
        run_span = new_span_id()
        try:
            # 写入 user 消息事件
            memory_event_start = session.mark()
            # 本 run 的 step 基数 = 前端此刻已分配的 turn 数，取两者较大：
            # max_step_id 覆盖前轮正常产出的步号；user_turn_count 覆盖前轮在
            # 首个 model 事件之前就终结（失败/取消/上下文超限）留下的空轮——
            # 只按 max_step_id 会让这种情况下第二轮再次与首轮撞号。
            # 必须在 append 本轮 user 消息之前算：本轮消息不计入基数。
            step_base = max(session.max_step_id, session.user_turn_count)
            user_event = session.append(USER_MESSAGE, {"content": user_input})
            yield to_agent_event(user_event)
            # USER_ACCEPTED 稳定边界：user/message 已持久化。
            await self._save_checkpoint(session, CheckpointBoundary.USER_ACCEPTED)

            run_id, turn_index = session.begin_run(agent_id=self._agent_id)
            terminal.begin_run(run_id)
            # Langfuse 旁路 trace 根（ADR-0018 D5）：trace=run、session 聚合。
            if self._observability_sink is not None and self._observability_sink.enabled:
                tracer = RunTracer(
                    self._observability_sink,
                    session_id=session.session_id,
                    run_id=run_id,
                    agent_id=self._agent_id,
                    user_input=user_input,
                    turn_index=turn_index,
                )
                tracer.run_started()
            # 流式块记账绑定本 run（ADR-0016 §3.3）：此后思考/文本 chunk 经
            # streamer 合帧成 durable delta；取消/失败臂负责 interrupt 收口。
            streamer = BlockStreamer(session)
            streamer.begin_run(run_id)
            # run 归因上下文（R3-7）：memory/context provider 等低层模块在
            # 事件降级时需要 run_id 对账，经 contextvar 传递。嵌套运行的恢复
            # 由外层 finally 兜底（token 捕获于下）。
            run_context_token = run_context_var.set(run_id)
            # 按类型选取本 run 的 run/started——不假设 begin_run 恰好只追加一条事件。
            run_started = next(e for e in session.since(memory_event_start) if e.type == RUN_STARTED)
            yield to_agent_event(run_started)

            self._log("agent_start", "Agent Loop 开始", span_id=run_span, step=0,
                      outcome="started", agent_name="agent_runtime")

            while True:
                # 第 1 步：ContextBuilder 是模型可见投影的唯一入口。
                context_event_start = session.mark()
                ctx_span = (
                    tracer.context_build_started(step=steps)
                    if tracer is not None else None
                )
                try:
                    messages = await self._context_builder.build(session)
                except ContextWindowExceededError as error:
                    if tracer is not None:
                        tracer.context_build_completed(ctx_span)
                        tracer.run_failed(STATUS_CONTEXT_WINDOW_EXCEEDED)
                    failed = session.append(
                        RUN_FAILED, {"reason": STATUS_CONTEXT_WINDOW_EXCEEDED, "message": str(error),
                                     "trace_id": tracer.trace_id if tracer else None,
                                     "trace_url": tracer.trace_url if tracer else None},
                        run_id=run_id, step_id=step_base + steps,
                    )
                    terminal.mark_terminal_written()
                    yield to_agent_event(failed)
                    result_holder.append(
                        AgentRunResult(status=STATUS_CONTEXT_WINDOW_EXCEEDED, final_text="", steps=steps),
                    )
                    # 模型在本轮从未被调用：没有可抽取的对话内容，跳过 writeback。
                    return
                new_events = list(session.since(context_event_start))
                if tracer is not None:
                    compaction = next(
                        (e for e in new_events if e.type == CONTEXT_COMPACTED), None,
                    )
                    tracer.context_build_completed(
                        ctx_span,
                        compacted_turn_count=(
                            compaction.data.get("compacted_turn_count")
                            if compaction is not None else None
                        ),
                    )
                    ctx_span = None
                for event in new_events:
                    yield to_agent_event(event)

                # 第 2 步：发起这一轮模型调用（按 stream 选 astream/ainvoke）
                llm_span = new_span_id()
                # 计时锚点：供 llm_call 诊断日志带 duration_ms（与 cli.py 的 llm_call 对齐）。
                llm_started = time.perf_counter()
                # generation 句柄（ADR-0018 D7）：与 llm_call 诊断行同源同时点，
                # 完成/失败时回填；异常臂/取消臂负责收口在途 generation。
                generation = (
                    tracer.model_call_started(
                        step=steps + 1, messages=messages,
                        model=self._primary_model_name,
                    )
                    if tracer is not None else None
                )

                # 在途标记：从发起调用到聚合完成，此间抛错按 model/failed 归因。
                # coordinator 统一编排（含 stall 看门狗）：瞬时失败内部切换
                # 重试，非瞬时/无 fallback 时异常照常上抛走统一失败兜底。
                terminal.model_call_open = True
                if stream:
                    # 流式：思考/文本 chunk 经 BlockStreamer 合帧落盘（S19），
                    # 聚合回完整 AIMessage。思考块（reasoning/*）与文本 delta
                    # 都是 durable 事实：断连重连按 seq 重放即可恢复（ADR-0016）。
                    yield AgentEvent(
                        type=MODEL_STARTED,
                        data={"step": step_base + steps + 1},
                        run_id=run_id, step_id=step_base + steps + 1,
                    )
                    assert streamer is not None
                    collected: list[AIMessageChunk] = []
                    async for chunk in model_coord.astream(messages):
                        collected.append(chunk)
                        reasoning_text = _extract_reasoning(chunk)
                        if reasoning_text:
                            for streamed in streamer.offer_reasoning(
                                reasoning_text, step=step_base + steps + 1,
                            ):
                                yield to_agent_event(streamed)
                        delta_text = _extract_text(chunk.content)
                        if delta_text:  # 空 content chunk（纯 tool_calls）不发 delta
                            for streamed in streamer.offer_text(
                                delta_text, step=step_base + steps + 1,
                            ):
                                yield to_agent_event(streamed)
                    # 流结束：关思考块（completed）+ 落文本残余（合帧尾部）
                    for streamed in streamer.end_step(step=step_base + steps + 1):
                        yield to_agent_event(streamed)
                    # 聚合 chunks 成完整 AIMessage：用 reduce 风格 + 累加。
                    # 空流（模型没吐任何 chunk）退化成空 content。
                    if collected:
                        ai: AIMessage = collected[0]
                        for c in collected[1:]:
                            ai = ai + c  # type: ignore[assignment]
                        # 聚合后保证是 AIMessage（AIMessageChunk + AIMessageChunk = AIMessageChunk，
                        # 后续逻辑期望 .tool_calls 属性，chunk 也有，但类型标注对齐成 AIMessage）
                        if not isinstance(ai, AIMessage):
                            ai = AIMessage(content=ai.content, tool_calls=ai.tool_calls)  # type: ignore[arg-type]
                    else:
                        ai = AIMessage(content="")
                else:
                    ai = await model_coord.ainvoke(messages)
                # R6-2（用户拍板）：空响应不是成功——content 与 tool_calls 双空
                # 意味着模型没有产出任何决策（内容过滤/上游静默失败）。在途标记
                # 仍开着时抛出，走统一失败兜底（model/failed + run/failed），
                # SSE 客户端因此能区分"模型答了空话"与"上游失败"。
                extracted_content = _extract_text(ai.content)
                if not extracted_content and not ai.tool_calls:
                    raise RuntimeError(
                        "model returned an empty response (no content, no tool calls)"
                    )
                # DSML 协议泄漏守卫（冒烟实测）：无结构化 tool_calls 且 content
                # 含协议保留标记 = 网关没把工具调用解析成结构化字段，绝不能把
                # 这段标记文本当最终回答持久化——与空响应同一失败语义。
                if not ai.tool_calls and _DSML_MARKUP_MARKER in extracted_content:
                    raise RuntimeError(
                        "model response contains malformed tool-call markup"
                        " (DSML protocol leak); treating as model failure"
                    )
                terminal.model_call_open = False  # 调用完整返回，后续异常不再归因 model
                # duration_ms 严格闭合模型调用本身（ainvoke/astream 区间），
                # 不含 normalize / usage 解析等后处理——与 spec 12 §2 的
                # "provider latency" 语义对齐（后处理是微秒级，但注释与字段语义
                # 要自洽）。
                llm_duration_ms = int((time.perf_counter() - llm_started) * 1000)

                # Model Fallback（ADR-0014 决策 18）：取走本步的切换事实；事件
                # 持久化放在下方 llm_log_fields 构造之后、model/completed 之前
                # ——SessionEvent 流里切换事实先于本步完成事件（llm_call 是
                # Diagnostic Log 通道，另一条观察线，不进 JSONL 顺序）。
                fallback_transitions = (
                    model_coord.drain_transitions() if model_coord is not None else []
                )

                # 第 3 步：把 AIMessage 持久化为 model/completed 事件
                # 值对象归一化（A2）：本循环内所有消费点读类型化字段，不再拆原始 dict。
                calls = ToolCall.normalize_all(ai.tool_calls or [])
                tool_calls = calls
                model_data: dict[str, Any] = {"content": extracted_content}
                model_name = _model_name_from_response(ai)
                if model_name:
                    model_data["model"] = model_name
                usage = _usage_from_response(ai)
                if usage:
                    model_data["usage"] = usage
                    for key, value in usage.items():
                        usage_total[key] = usage_total.get(key, 0) + value
                # llm_call 诊断日志带模型归因 + 时延 + 用量（与 cli.py 对齐，spec 02 §7/§10
                # 要求每步可在 Diagnostic Log 定位到具体 provider/model）。
                llm_log_fields: dict[str, Any] = {
                    "llm_input": user_input,
                    "llm_output": str(ai.content)[:200],
                    "duration_ms": llm_duration_ms,
                    "outcome": "success",
                }
                if model_name:
                    llm_log_fields["model_id"] = model_name
                if usage:
                    llm_log_fields["token_usage"] = usage
                # 切换事实持久化 + 诊断日志归因（ADR-0014 决策 18：llm_call 带
                # fallback_reason/from/to）。usage = 切换后实际产出本步回答的那次
                # 调用的用量（primary 失败一次的用量上游未结账，不可知，绝不
                # 伪造）；run 级 usage_total 统一归集不分主备。
                if fallback_transitions:
                    for transition in fallback_transitions:
                        fallback_event = session.append(
                            MODEL_FALLBACK,
                            {"from_model": transition.from_model,
                             "to_model": transition.to_model,
                             "reason": transition.reason,
                             **({"usage": usage} if usage else {})},
                            run_id=run_id, step_id=step_base + steps + 1,
                        )
                        yield to_agent_event(fallback_event)
                    llm_log_fields.update(
                        fallback_reason=fallback_transitions[0].reason,
                        fallback_from=fallback_transitions[0].from_model,
                        fallback_to=fallback_transitions[0].to_model,
                    )
                self._log("llm_call", f"第 {steps + 1} 轮模型调用完成",
                          span_id=llm_span, parent_span_id=run_span, step=steps + 1,
                          **llm_log_fields)
                # generation 回填（ADR-0018 D7）：与 llm_call 诊断行同源数据——
                # usage/时延/finish_reason/fallback 履历；无数据键省略零伪造。
                if tracer is not None:
                    response_meta = getattr(ai, "response_metadata", None) or {}
                    tracer.model_call_completed(
                        generation,
                        output_text=extracted_content,
                        usage=usage,
                        duration_ms=llm_duration_ms,
                        finish_reason=response_meta.get("finish_reason"),
                        provider_request_id=response_meta.get("id"),
                        response_model=model_name,
                        fallback_transitions=fallback_transitions,
                        tool_call_names=[c.name for c in calls] if calls else None,
                    )
                    generation = None
                if tool_calls:
                    model_data["tool_calls"] = [
                        {"id": c.id, "name": c.name, "args": c.args} for c in calls
                    ]
                will_execute_tools = bool(tool_calls) and steps + 1 < self.max_steps
                defer_model_event = (
                    will_execute_tools and self.executor.tracks_operations
                )
                model_event: SessionEvent | None = None
                if not defer_model_event:
                    model_event = session.append(
                        MODEL_COMPLETED,
                        model_data,
                        run_id=run_id,
                        step_id=step_base + steps + 1,
                    )
                    yield to_agent_event(model_event)
                    # MODEL_COMPLETED 稳定边界：本轮模型回复已持久化（无 tool_calls 或
                    # 无 Ledger 时，model/completed 立即写入，这里直接保存 Checkpoint）。
                    await self._save_checkpoint(session, CheckpointBoundary.MODEL_COMPLETED)
                # 第 4 步：这一轮算一步（数模型轮数，不是工具个数）
                steps += 1

                # 第 5 步：先判停止信号——若模型选择最终答复则立即返回。
                if not tool_calls:
                    final = _extract_text(ai.content)
                    self._log("agent_decision", "模型给出最终回答，Agent Loop 完成",
                              span_id=new_span_id(), parent_span_id=run_span, step=steps,
                              decision="finish", remaining_steps=0,
                              reason="本轮无 tool_calls，模型选择直接答复", outcome="success")
                    self._log("task_completed", "Agent Loop 正常结束", span_id=run_span,
                              step=steps, outcome="success")
                    if tracer is not None:
                        tracer.run_completed(final, usage_total=dict(usage_total) or None)
                    end_event = session.end_run(run_id, status="completed", final_text=final,
                                                usage_total=dict(usage_total) or None,
                                                cost_usd=None,   # TODO(spec 12): 费率表未定义，不伪造
                                                trace_id=(tracer.trace_id if tracer else None),
                                                trace_url=(tracer.trace_url if tracer else None))
                    terminal.mark_terminal_written()
                    self._write_memories(session, memory_event_start)
                    yield to_agent_event(end_event)
                    # FINAL_COMPLETED 稳定边界：Run 正常结束事件已持久化。
                    await self._save_checkpoint(session, CheckpointBoundary.FINAL_COMPLETED)
                    result_holder.append(
                        AgentRunResult(status=STATUS_COMPLETED, final_text=final, steps=steps),
                    )
                    return

                # 第 6 步：模型仍在请求工具——若已达 max_steps 则兜底返回。
                if steps >= self.max_steps:
                    self._log("agent_decision", "模型不收敛，撞 max_steps 兜底",
                              span_id=new_span_id(), parent_span_id=run_span, step=steps,
                              decision="max_steps_exceeded", remaining_steps=0,
                              reason=f"连续 {steps} 轮仍在请求工具，触发保险丝", outcome="success")
                    if tracer is not None:
                        tracer.run_failed("max_steps_exceeded")
                    end_event = session.end_run(run_id, status="failed",
                                                usage_total=dict(usage_total) or None,
                                                trace_id=(tracer.trace_id if tracer else None),
                                                trace_url=(tracer.trace_url if tracer else None))
                    terminal.mark_terminal_written()
                    self._write_memories(session, memory_event_start)
                    yield to_agent_event(end_event)
                    result_holder.append(
                        AgentRunResult(status=STATUS_MAX_STEPS_EXCEEDED, final_text="", steps=steps),
                    )
                    return

                # 第 7 步：用 ToolExecutor 执行整批 tool_call 并按原 id 回填。
                # ADR-0016 §4.1：tool/call 预持久化（执行前）——02 §8.3 状态机
                # 要求 call 先于 running/output_delta，前端在工具在途期间就有
                # 可关联的行；中断窗口也总是留下可配对修复的 call 事实。
                for call in calls:
                    call_event = self.executor.emit_call_event(
                        session, tool_call_id=call.id, tool_name=call.name,
                        args=call.args, run_id=run_id, step_id=step_base + steps,
                    )
                    yield to_agent_event(call_event)
                tool_event_start = session.mark()
                tool_error = None
                try:
                    executions = await self.executor.execute_batch(
                        calls,
                        tracer=tracer,
                        session=session,
                        operation_context=OperationContext(
                            session_id=session.session_id,
                            run_id=run_id,
                            agent_id=self._agent_id,
                        ),
                        step_id=step_base + steps,
                    )
                except Exception as error:  # noqa: BLE001
                    tool_error = error
                # 执行期间追加的事件（tool/output_delta 等）镜像给流式消费者；
                # web 订阅者经 session listener 实时收到（seq 幂等合并不重复）。
                for event in session.since(tool_event_start):
                    yield to_agent_event(event)
                if tool_error is not None:
                    raise tool_error
                if defer_model_event:
                    model_event = session.append(
                        MODEL_COMPLETED,
                        model_data,
                        run_id=run_id,
                        step_id=step_base + steps,
                    )
                    yield to_agent_event(model_event)
                    # MODEL_COMPLETED 稳定边界：延迟写入的 model/completed 已持久化。
                    await self._save_checkpoint(session, CheckpointBoundary.MODEL_COMPLETED)
                # execute_batch 契约保证返回顺序与输入一致（gather 保序 / 串行补 CANCELLED），
                # 因此按位置配对 call↔execution——空/重复 id 也不会串对。
                for call, execution in zip(calls, executions):
                    result = execution.result
                    content = result.model_dump_json()
                    outcome: str = "success" if result.ok else "failure"

                    # 持久化顺序（延迟事件 → TOOL_RESULT）的单一 owner 是
                    # ToolExecutor.emit_*（批次 C 候选 3 + ADR-0016 §4.1 拆分）：
                    # Runtime 只消费已持久化事件并镜像，不再自己 append。
                    for persisted_event in self.executor.emit_pending_events(
                        session,
                        pending_events=execution.pending_events,
                        run_id=run_id, step_id=step_base + steps,
                    ):
                        yield to_agent_event(persisted_event)
                    yield to_agent_event(self.executor.emit_result_event(
                        session, tool_call_id=execution.tool_call_id,
                        content=content, run_id=run_id, step_id=step_base + steps,
                    ))

                    self._log("tool_operation", f"工具回复 {outcome}",
                              span_id=new_span_id(), parent_span_id=run_span, step=steps,
                              tool_call_id=execution.tool_call_id,
                              tool_input=call.args,
                              tool_output=content[:200],
                              error_code=result.error_code,
                              retryable=result.retryable if not result.ok else None,
                              duration_ms=result.metadata.get("duration_ms"),
                              attempt=result.metadata.get("attempt"),
                              outcome=outcome)
                # TOOL_BATCH_COMPLETED 稳定边界：整批 tool_call/result 已回填。
                await self._save_checkpoint(
                    session, CheckpointBoundary.TOOL_BATCH_COMPLETED
                )

                # ── 同错熔断护栏（ADR-0014 #69）──
                # 工具回填后、下一轮模型调用前观察本轮工具结果；取最严重信号。
                worst_signal = None
                for call, execution in zip(calls, executions):
                    sig = guard.observe(call.name, call.args, execution.result.ok)
                    if sig.level != GuardLevel.NONE and (
                        worst_signal is None or sig.level > worst_signal.level
                    ):
                        worst_signal = sig
                if worst_signal is not None:
                    guard_span = new_span_id()
                    if worst_signal.level == GuardLevel.SOFT:
                        # 软熔断：注入 user 角色纠正消息——护栏是 runtime 行为
                        # 不污染固定 system prompt（ADR-0014 决策 4）。
                        soft_event = session.append(
                            TOOL_FAILURE_GUARD,
                            {"level": "soft",
                             "tool_name": worst_signal.tool_name,
                             "fingerprint": worst_signal.fingerprint,
                             "consecutive_failures": worst_signal.consecutive_failures},
                            run_id=run_id, step_id=step_base + steps,
                        )
                        yield to_agent_event(soft_event)
                        corrective = session.append(
                            USER_MESSAGE,
                            {"content": DEFAULT_REGISTRY.assemble(
                                "corrective:tool_failure_guard",
                                {
                                    "tool_name": worst_signal.tool_name,
                                    "consecutive_failures": str(
                                        worst_signal.consecutive_failures
                                    ),
                                },
                            ).fragment_text,
                             # runtime 注入的纠正消息不是真实用户发言——标记来源
                             # 供前端投影/审计区分（不变量 #22 边缘），**并供记忆
                             # 抽取剔除**（memory/extractor.py 按此标记单点过滤：
                             # 注入消息一旦被当成真实用户发言，工具输出里的注入指令
                             # 就能被洗成跨会话 USER 记忆）。
                             "injected_by": "tool_failure_guard"},
                            run_id=run_id, step_id=step_base + steps,
                        )
                        yield to_agent_event(corrective)
                        self._log("agent_decision", "同错熔断软触发",
                                  span_id=guard_span, parent_span_id=run_span, step=steps,
                                  decision="tool_failure_guard_soft",
                                  tool_name=worst_signal.tool_name,
                                  consecutive_failures=worst_signal.consecutive_failures)
                    elif worst_signal.level == GuardLevel.HARD:
                        # 硬熔断：强制 end_run(failed)，绝不伪造最终回答。
                        hard_event = session.append(
                            TOOL_FAILURE_GUARD,
                            {"level": "hard",
                             "tool_name": worst_signal.tool_name,
                             "fingerprint": worst_signal.fingerprint,
                             "consecutive_failures": worst_signal.consecutive_failures},
                            run_id=run_id, step_id=step_base + steps,
                        )
                        yield to_agent_event(hard_event)
                        self._log("agent_decision", "同错熔断硬触发，强制终止 run",
                                  span_id=guard_span, parent_span_id=run_span, step=steps,
                                  decision="tool_failure_guard_hard",
                                  tool_name=worst_signal.tool_name,
                                  consecutive_failures=worst_signal.consecutive_failures,
                                  outcome="failed")
                        # 与异常臂同一收尾语义（_RunFinalizer 单终态 owner），
                        # reason 落 run/failed data 供消费者区分失败原因。
                        if tracer is not None:
                            tracer.run_failed(STATUS_IDENTICAL_TOOL_FAILURE_LOOP)
                        end_event = terminal.failure_terminal(
                            steps=step_base + steps,
                            reason=STATUS_IDENTICAL_TOOL_FAILURE_LOOP,
                            trace_id=(tracer.trace_id if tracer else None),
                            trace_url=(tracer.trace_url if tracer else None),
                        )
                        self._write_memories(session, memory_event_start)
                        yield to_agent_event(end_event)
                        result_holder.append(
                            AgentRunResult(
                                status=STATUS_IDENTICAL_TOOL_FAILURE_LOOP,
                                final_text="", steps=steps,
                            ),
                        )
                        return
        except (asyncio.CancelledError, GeneratorExit):
            # 取消臂：客户端断连（SSE 生成器被取消/关闭）走这里——GeneratorExit /
            # CancelledError 是 BaseException，顶层 except Exception 兜不到，
            # durable 日志会永远停在悬空的 run/started 上（无结局的历史，web 层
            # 也不会调 resume 修复）。只做持久化收尾，不 yield：生成器关闭中
            # 禁止再产出（RuntimeError），取消中的 task 再 yield 也会被立即再取消。
            # 收尾后继续向上传播取消——吞掉取消会让 task 无法正确结束。
            try:
                ctx = _TerminalContext(
                    session=session, run_id=run_id, steps=step_base + steps,
                    terminal=terminal, streamer=streamer, model_coord=model_coord,
                    tracer=tracer, ctx_span=ctx_span, generation=generation,
                )
                # 收尾事件一律丢弃不 yield（生成器关闭中禁止产出）——这正是本臂
                # 与异常臂的唯一差异，收拢后由调用方决定 yield 策略。
                ctx.interrupt_streams()
                cancel_reason = (cancel_reason_supplier() if cancel_reason_supplier
                                 else "cancelled")
                ctx.close_observability(
                    error_type=None, reason=cancel_reason, cancelled=True,
                )
                terminal.cancelled_terminal(
                    steps=step_base + steps,
                    reason=cancel_reason,
                    trace_id=(tracer.trace_id if tracer else None),
                    trace_url=(tracer.trace_url if tracer else None),
                )
            except Exception as terminal_error:  # noqa: BLE001
                self._log("task_failed", "取消收尾事件写入失败（存储故障？）",
                          span_id=run_span, outcome="error",
                          error=str(terminal_error),
                          error_type=type(terminal_error).__name__, exc_info=True)
            self._log("task_failed", "Agent Loop 被取消（客户端断连？）",
                      span_id=run_span, outcome="cancelled")
            raise
        except Exception as error:  # noqa: BLE001
            # 顶层失败兜底：模型 / 执行器抛异常时，JSONL 绝不能停在悬空的
            # run/started 上（resume 后是一段没有结局的历史），SSE 消费者也
            # 必须收到终止帧。这里补齐终结事件后正常 return——不向上抛：
            # 失败事实由终结事件 + 结构化日志承载，流干净收尾。
            # task_failed 与正常结束的 task_completed 成对（logging.EVENT_TYPES 白名单）。
            self._log("task_failed", "Agent Loop 异常终止", span_id=run_span,
                      outcome="error", error=str(error),
                      error_type=type(error).__name__, exc_info=True)
            # 终结事件写入自身也可能失败（例如存储故障）：逐段防护，保证
            # result_holder 一定拿到终态结果——"run() 必返回失败结果"的契约
            # 不因二次故障被破坏。二次失败进日志，不再向上抛。
            try:
                ctx = _TerminalContext(
                    session=session, run_id=run_id, steps=step_base + steps,
                    terminal=terminal, streamer=streamer, model_coord=model_coord,
                    tracer=tracer, ctx_span=ctx_span, generation=generation,
                )
                # 本臂允许 yield——收尾事件（部分内容 + interrupted + 切换事实 +
                # model/failed）逐条镜像给流消费者（与取消臂的唯一差异）。
                # provider 内容审查拒绝（data_inspection_failed）→ 已分类 reason
                # + 固定可读文案（run/failed 与 model/failed 成对升级，形状同
                # 上下文超限路径）；其余异常保持类型名原行为。
                # 分类只在**模型调用在途**时进行（model_call_open 正是 model/failed
                # 的归因窗口）：本臂同时兜底工具/执行器异常，其错误文本可能恰好
                # 引用该错误码（如抓取阿里云文档），不得误标为内容审查。
                moderation_reason = (
                    _classify_provider_failure(error)
                    if terminal.model_call_open
                    else None
                )
                moderation_message = (
                    CONTENT_MODERATION_MESSAGE if moderation_reason else None
                )
                for streamed in ctx.interrupt_streams():
                    yield to_agent_event(streamed)
                for streamed in ctx.close_observability(
                    error_type=type(error).__name__,
                    reason=moderation_reason or type(error).__name__,
                    cancelled=False,
                    readable_message=moderation_message,
                ):
                    yield to_agent_event(streamed)
                # run_id 为 None 说明异常发生在 begin_run 之前：没有 run 可终结，
                # 已写入的事件保持原样，失败只能由日志承载。
                end_event = terminal.failure_terminal(
                    steps=step_base + steps,
                    reason=moderation_reason,
                    message=moderation_message,
                    trace_id=(tracer.trace_id if tracer else None),
                    trace_url=(tracer.trace_url if tracer else None),
                )
                if end_event is not None:
                    yield to_agent_event(end_event)
            except Exception as terminal_error:  # noqa: BLE001
                self._log("task_failed", "失败兜底事件写入失败（存储故障？）",
                          span_id=run_span, outcome="error",
                          error=str(terminal_error),
                          error_type=type(terminal_error).__name__, exc_info=True)
            result_holder.append(
                AgentRunResult(status=STATUS_FAILED, final_text="", steps=steps),
            )
            return
        finally:
            # 嵌套运行恢复：child 的 run 归因在 child _drive 结束时还原为父值
            # （或未设），父后续操作不再错挂 child 的 run_id。close/取消路径
            # 同样收口（reset 为同步操作，生成器关闭中安全）。
            if run_context_token is not None:
                try:
                    run_context_var.reset(run_context_token)
                except ValueError:
                    # SSE 消费方可能在【另一上下文】aclose 本生成器（断连路径）
                    # ——token 无法跨上下文 reset。该上下文随任务消亡，无需恢复；
                    # 正常路径（同任务）的 reset 一定成功。
                    pass

    def _new_coordinator(self) -> ModelFallbackCoordinator:
        """per-run coordinator 工厂（_drive 每调一次；测试可直取验证接线）。"""
        return ModelFallbackCoordinator(
            primary=self.model, fallback=self._fallback_model,
            policy=self._fallback_policy,
            primary_name=self._primary_model_name,
            fallback_name=self._fallback_model_name,
            idle_timeout=self._stream_idle_timeout,
            total_timeout=self._stream_total_timeout,
            gate=self._model_call_gate,
        )

    def _write_memories(self, session: Session, start: int) -> None:
        if self._memory_writer is not None:
            # 排除流式增量事实（ADR-0016 review 修复）：reasoning/* 是 provider
            # 思考（02 §15 / PRD §18 隐私硬边界——CoT 不得进记忆存储再回灌
            # 上下文）；text/delta 与 tool/output_delta 与 model/completed、
            # tool/result 内容重复，只会挤占抽取器的 50 条事件窗口。
            self._memory_writer.submit(
                session,
                [e for e in session.since(start)
                 if e.type not in _MEMORY_EXCLUDED_EVENT_TYPES],
            )

    async def _save_checkpoint(
        self,
        session: Session,
        boundary_type: CheckpointBoundary,
    ) -> None:
        """在稳定边界调 CheckpointPolicy.maybe_save；并在配了 SessionMetaStore 时
        同步更新 last_checkpoint_seq。

        关键不变量（#28 要求）：checkpoint 保存发生在对应 SessionEvent 已持久化【之后】；
        checkpoint/saved 绝不写入 SessionEvent（它只是存储层恢复辅助）。

        checkpoint 是恢复辅助（本方法定位即此），绝不能毒化 run 结果：存储故障若
        沿调用链传给顶层失败兜底，会给已持久化 run/completed 的 run 补一条矛盾的
        run/failed（双终结事件，历史不可对账）。这里吞掉异常只落日志，不向上抛。
        """
        try:
            checkpoint = await self._checkpoint_policy.maybe_save(
                session, boundary_type
            )
            if checkpoint is not None and self._session_meta_store is not None:
                try:
                    await self._session_meta_store.update_last_checkpoint_seq(
                        session.session_id, checkpoint.event_seq
                    )
                except KeyError:
                    # SessionMeta 尚未 upsert（首次 run）：惰性补建一行。
                    from datetime import UTC, datetime

                    await self._session_meta_store.upsert(
                        SessionMeta(
                            session_id=session.session_id,
                            created_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
                            agent_id="default",
                            last_checkpoint_seq=checkpoint.event_seq,
                        )
                    )
        except Exception:
            # 宽捕获理由：checkpoint 是恢复辅助，任何存储侧故障都不属于 run 语义。
            logger.exception(
                "checkpoint 保存失败（boundary=%s, session=%s）：不影响 run 结果",
                boundary_type.value,
                session.session_id,
            )

    def _log(self, event_type: str, message: str, *, exc_info: bool = False,
             **fields: Any) -> None:
        """打一条结构化日志；无 handler 时静默 no-op（不污染未配日志的调用方/测试）。

        `exc_info=True`（须在 except 块内调用）让 JSONL 落 `stack_trace(调用栈)`：
        durable 的 `model/failed` 事件按脱敏不变量**只带异常类型名**，完整消息与调用栈
        必须由日志承载；否则排障只剩一个类型名，「哪一帧、哪个 SDK 调用挂的」全丢
        （OBS-008：模型调用失败时 traceback 被吞）。

        ⚠ 调用栈含**绝对路径（含宿主用户名）、源码行、以及链式异常（`__cause__`/
        `__context__`）的消息**——比原先只记的 `error=str(...)` 更多。诊断 JSONL 是
        本地未脱敏详情汇聚处（不变量 #4：Event ≠ Diagnostic Log），但**不要原样附到
        issue / 上传**；需要外发时先脱敏。
        """
        if not logger.hasHandlers():
            return
        log_event(logger, event_type, message, exc_info=exc_info, **fields)
