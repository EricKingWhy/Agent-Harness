"""Langfuse 旁路观测（ADR-0018）：``Degradation.OPTIONAL_OBSERVABILITY`` 档首个实现。

对外只暴露 :class:`LangfuseSink`——所有方法故障隔离，调用方零感知。
装配入口（runtime / CLI / web）用 ``Settings`` 门控：key 空 = disabled sink。
"""

from __future__ import annotations

from typing import Any

from agent_harness.observability.sink import LangfuseSink
from agent_harness.observability.tracer import RunTracer

__all__ = ["LangfuseSink", "RunTracer", "flush_process_sink", "get_observability_sink"]

_process_sink: LangfuseSink | None = None


def get_observability_sink(settings: Any) -> LangfuseSink:
    """进程级 sink 单例（ADR-0018 D2 装配）：key 空 = disabled sink（零开销缺席）。

    Disabled sink 的全部方法仍是安全 no-op，调用方无需判空。
    """
    global _process_sink
    if _process_sink is None:
        _process_sink = LangfuseSink(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
            trace_content=settings.langfuse_trace_content,
            tracing_environment=settings.langfuse_tracing_environment,
            release=settings.langfuse_release,
        )
    return _process_sink

def flush_process_sink() -> None:
    """进程收尾 flush（ADR-0018 D3）：CLI 退出 / web graceful shutdown 调用。

    只 flush 本进程已装配的单例；未装配（CLI 短命令未跑 run）或 disabled
    时是 no-op。有超时上限（sink 默认 5s），退出节奏不被旁路拖死。
    """
    if _process_sink is not None and _process_sink.enabled:
        _process_sink.flush()
