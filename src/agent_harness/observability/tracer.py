"""RunTracer——一次 agent run 的 Langfuse 生命周期映射（ADR-0018 D5/D6/D7）。

映射（不发明第二套 trace identity，spec 12 §4）：
- Langfuse trace 根 = 一次 agent run：name=``agent-run``，input=用户消息，
  metadata=run_id / session_id / agent_id / git_commit；
- generation = 每次 model call：model、input 消息、output 文本、usage
  （项目键 → Langfuse usage_details 键）、latency、fallback 履历；
- run 终态 → 根观测 update（output / level=ERROR）+ end。

内容边界（D6）：``full`` 原样；``redacted`` 截断——redaction 是本模块
``_redact`` 单一函数边界，未来接策略不改埋点。所有 span 操作零伪造
（无数据不带键）且绝不抛出：句柄操作失败经 ``sink.report_failure``
计数进熔断账本后吞掉。

热路径约束（D3 性能红线）：本模块全部是内存操作 + SDK 后台入队。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_harness.observability.sink import LangfuseSink

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REDACTED_TEXT_LIMIT = 500


@dataclass(frozen=True)
class TraceBinding:
    """嵌套子 run 的 trace 绑定（ADR-0018 D5 多 Agent 规则）。

    SubAgent 的 run 发生在父 run 的 delegate 工具执行内（同一异步上下文）：
    executor 在 agent 型观测存活期间设置本绑定，child runtime 的 RunTracer
    直接【认领】父侧 agent 观测作为自己的根——child 的 generation/span 全部
    挂在 agent 观测下（官方结构：无 dispatch/execution 双节点、递归嵌套）。
    根的生命周期归父侧 executor 所有（adopt 模式下 child 只 update 不 end）。
    """

    trace_id: str
    observation: Any


#: 嵌套绑定 contextvar：delegate 执行期间由 executor 设置、结束后还原。
current_trace_binding: ContextVar[TraceBinding | None] = ContextVar(
    "lf_trace_binding", default=None,
)

#: git_commit 惰性缓存：None=未取，False=取不到（不再重试），str=短哈希。
_git_commit_cache: str | bool | None = None


def git_commit() -> str | None:
    """仓库短哈希（regression metadata / trace metadata 用）；取不到如实 None。"""
    global _git_commit_cache
    if _git_commit_cache is None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=3, cwd=_REPO_ROOT,
                check=False,
            )
            _git_commit_cache = result.stdout.strip() or False
        except Exception:  # noqa: BLE001 - 观测元数据取不到不致命
            _git_commit_cache = False
    return str(_git_commit_cache) if _git_commit_cache else None


def _redact(value: Any) -> Any:
    """redacted 模式的内容收敛（D6 单一函数边界）：字符串截断，容器递归。"""
    if isinstance(value, str):
        if len(value) <= _REDACTED_TEXT_LIMIT:
            return value
        return value[:_REDACTED_TEXT_LIMIT] + "…"
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class RunTracer:
    """一次 run 的 Langfuse 映射。sink 缺席（未配置）时全部方法安全 no-op。"""

    def __init__(
        self,
        sink: LangfuseSink,
        *,
        session_id: str,
        run_id: str,
        agent_id: str,
        user_input: str,
        turn_index: int | None = None,
    ) -> None:
        self._sink = sink
        self._session_id = session_id
        self._run_id = run_id
        self._agent_id = agent_id
        self._user_input = user_input
        self._turn_index = turn_index
        self.trace_id: str | None = None
        #: trace_url 与 trace_id 并列（trace_url 契约，ADR-0018 D7 延伸）：
        #: 同一 trace 的可点击 URL，由官方 SDK 合成（不手拼）；终态时构造。
        #: trace_id 缺失 → trace_url 恒 None；两者不互替（机器可读 + 人类可点击并存）。
        self.trace_url: str | None = None
        self._root: Any = None
        self._owns_root = True

    def _content(self, value: Any) -> Any:
        if getattr(self._sink, "trace_content", "full") == "redacted":
            return _redact(value)
        return value

    def _quiet(self, operation: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - D3 异常边界：观测故障不传染
            self._sink.report_failure(operation, exc)
            return None

    def run_started(self) -> None:
        binding = current_trace_binding.get()
        if binding is not None:
            # 嵌套子 run：认领父侧 agent 观测为根（官方多 Agent 结构），不新建。
            self._root = binding.observation
            self.trace_id = binding.trace_id
            self._owns_root = False
            return
        # trace 级属性（session 聚合 + trace metadata）经官方 propagate
        # 通道挂在 trace 上；观测级 metadata 平行保留（可审计）。
        trace_meta = {
            "run_id": self._run_id,
            "agent_id": self._agent_id,
            "git_commit": git_commit(),
        }
        if self._turn_index is not None:
            trace_meta["turn_index"] = self._turn_index
        with self._sink.trace_attributes(
            session_id=self._session_id, trace_name="agent-run",
            metadata=trace_meta,
        ):
            root = self._sink.start_observation(
                name="agent-run",
                as_type="span",
                input=self._content(self._user_input),
                metadata={
                    "session_id": self._session_id,
                    **trace_meta,
                },
            )
        if root is None:
            return
        self._root = root
        # 真实 trace id 回填 run/completed（D7）；SDK 未暴露时如实保持 None。
        self.trace_id = getattr(root, "trace_id", None)

    def model_call_started(
        self, *, step: int, messages: Any, model: str | None = None,
    ) -> Any:
        if self._root is None:
            return None
        return self._quiet(
            "model_call_started",
            lambda: self._root.start_observation(
                name="model-call",
                as_type="generation",
                input=self._content(messages),
                model=model,
                metadata={"step": step},
            ),
        )

    def model_call_completed(
        self,
        generation: Any,
        *,
        output_text: str,
        usage: dict[str, int] | None = None,
        duration_ms: int | None = None,
        finish_reason: str | None = None,
        provider_request_id: str | None = None,
        response_model: str | None = None,
        fallback_transitions: list[Any] | None = None,
        tool_call_names: list[str] | None = None,
    ) -> None:
        if generation is None:
            return
        # Gap 5（D7 DEFER 批）：模型返回 tool_calls 但 content 空——Langfuse UI
        # 把空 output 显示成 None，tool_calls 轮在 trace 里不可读。这里兜底
        # 写结构化标记（仅空 content + 有 tool_calls 时），让观测层可读。
        effective_output = output_text
        if not effective_output and tool_call_names:
            effective_output = f"<tool_calls: {', '.join(tool_call_names)}>"
        metadata: dict[str, Any] = {}
        if duration_ms is not None:
            metadata["duration_ms"] = duration_ms
        if finish_reason:
            metadata["finish_reason"] = finish_reason
        if provider_request_id:
            metadata["provider_request_id"] = provider_request_id
        if response_model:
            metadata["response_model"] = response_model
        if fallback_transitions:
            first = fallback_transitions[0]
            metadata["fallback_from"] = first.from_model
            metadata["fallback_to"] = first.to_model
            metadata["fallback_reason"] = first.reason
        self._quiet("model_call_completed", lambda: generation.update(
            output=self._content(effective_output),
            **({"usage_details": _usage_details(usage)} if usage else {}),
            **({"metadata": metadata} if metadata else {}),
        ))
        self._quiet("model_call_end", generation.end)

    def model_call_failed(self, generation: Any, *, error_type: str) -> None:
        if generation is None:
            return
        self._quiet("model_call_failed", lambda: generation.update(
            level="ERROR", status_message=f"model call failed: {error_type}",
        ))
        self._quiet("model_call_end", generation.end)

    def run_completed(self, final_text: str, usage_total: dict[str, int] | None = None) -> None:
        if self._root is None:
            return
        self._quiet("run_completed", lambda: self._root.update(
            output=self._content(final_text),
            **({"metadata": {"usage_total": usage_total}} if usage_total else {}),
        ))
        if self._owns_root:
            self._quiet("run_end", self._root.end)
        self._finalize_trace_url()

    def run_failed(self, reason: str) -> None:
        if self._root is None:
            return
        self._quiet("run_failed", lambda: self._root.update(
            level="ERROR", status_message=reason,
        ))
        if self._owns_root:
            self._quiet("run_end", self._root.end)
        # 与 run_completed 对称：失败 run 在 Langfuse 也有可见 trace，跳转同样有
        # 排查价值；trace_id 缺失时构造降级为 None（同 completed 路径）。
        self._finalize_trace_url()

    def _finalize_trace_url(self) -> None:
        """终态时把 trace_id 经官方 SDK 合成可点击 URL 并缓存（trace_url 契约）。

        懒构造——只有终态时才合成（契约侧 runtime 在 tracer 收尾后读取
        ``tracer.trace_url`` 下发到 run/completed|failed.data）。trace_id 缺失
        时跳过，trace_url 保持 None；已构造过则不重复（幂等）。
        """
        if self.trace_url is not None or self.trace_id is None:
            return
        self.trace_url = self._sink.get_trace_url(trace_id=self.trace_id)

    # —— tool / agent 观测（T3 #119：D7 逐 attempt 链 + SubAgent agent 型） ——

    def tool_span_started(
        self, *, tool_name: str, tool_call_id: str, args: Any, is_delegate: bool,
    ) -> Any:
        """一次工具调用的观测。delegate 工具按官方多 Agent 规则用 ``agent``
        型 + 具体目标命名（绝不用 tool/span 隐藏 SubAgent 结构）。"""
        if self._root is None:
            return None
        return self._quiet(
            "tool_span_started",
            lambda: self._root.start_observation(
                name=tool_name,
                as_type="agent" if is_delegate else "tool",
                input=self._content(args),
                metadata={"tool_call_id": tool_call_id},
            ),
        )

    def tool_span_completed(
        self, span: Any, *, outcome: str, message: str | None = None,
        attempts: list[dict[str, Any]] | None = None,
        session_id: str | None = None, extra: dict[str, Any] | None = None,
    ) -> None:
        """工具调用终结：result message/data 摘要 + 全量 attempt 链 + ledger 关联键。"""
        if span is None:
            return
        metadata: dict[str, Any] = {"outcome": outcome}
        if attempts:
            metadata["attempts"] = attempts
        if session_id:
            metadata["session_id"] = session_id  # Operation Ledger 对账键
        if extra:
            metadata.update(extra)
        self._quiet("tool_span_completed", lambda: span.update(
            output=self._content(message) if message is not None else None,
            metadata=metadata,
            level=("DEFAULT" if outcome == "success" else "ERROR"),
        ))
        self._quiet("tool_span_end", span.end)

    # —— context 构建/压缩观测（D7 上下文态） ——

    def context_build_started(self, *, step: int) -> Any:
        if self._root is None:
            return None
        return self._quiet(
            "context_build_started",
            lambda: self._root.start_observation(
                name="context-build", as_type="span", metadata={"step": step},
            ),
        )

    def context_build_completed(self, span: Any, *, compacted_turn_count: int | None = None) -> None:
        if span is None:
            return
        metadata: dict[str, Any] = {}
        if compacted_turn_count is not None:
            metadata["compacted_turn_count"] = compacted_turn_count
        self._quiet("context_build_completed", lambda: span.update(
            **({"metadata": metadata} if metadata else {}),
        ))
        self._quiet("context_build_end", span.end)


def _usage_details(usage: dict[str, int]) -> dict[str, int]:
    """项目 usage 键（prompt/completion/total_tokens）→ Langfuse usage_details 键。"""
    details: dict[str, int] = {}
    if usage.get("prompt_tokens") is not None:
        details["input"] = usage["prompt_tokens"]
    if usage.get("completion_tokens") is not None:
        details["output"] = usage["completion_tokens"]
    if usage.get("total_tokens") is not None:
        details["total"] = usage["total_tokens"]
    return details
