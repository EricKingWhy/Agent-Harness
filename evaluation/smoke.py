"""Regression metadata（spec 12 §8）+ 真实模型 smoke（T8 #124）。

regression metadata：每次 Eval 记录版本语境，否则分数不可解释。原则——
**有什么记什么，没有的不伪造**：knowledge/memory 版本当前无版本化来源，
如实省略（缺键 = 未版本化），spec 字段以文档注释对齐。

smoke：真实模型链（senseaudio/zhipu fallback）手动触发，断言只做结构性
检查（dangling=0、usage 完整、trace 完整性），不评语义质量、不进默认 CI。
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_harness.agent import AgentRuntime
from agent_harness.config import Settings
from agent_harness.observability.tracer import git_commit
from evaluation.assertions import dangling_tool_call_ids
from evaluation.runner import CaseResult
from evaluation.support import AddTool

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPORTS_DIR = _REPO_ROOT / "evaluation" / "reports"


def dataset_version(dataset_path: str | Path) -> str:
    """数据集内容哈希（sha256 前 12 位）：内容即版本。"""
    return hashlib.sha256(
        Path(dataset_path).read_bytes(),
    ).hexdigest()[:12]


def regression_metadata(
    *,
    settings: Settings | None = None,
    dataset_path: str | Path | None = None,
) -> dict[str, Any]:
    """spec 12 §8 字段集。缺版本化来源的键如实省略（knowledge/memory）。"""
    settings = settings or Settings()
    metadata: dict[str, Any] = {
        "app_version": importlib.metadata.version("intelligence-agent"),
        "git_commit": git_commit(),
        "model_provider": settings.model_provider,
        "model_name": settings.model_name or None,
        "fallback_model_provider": settings.fallback_model_provider or None,
        "fallback_model_name": settings.fallback_model_name or None,
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
    }
    if dataset_path is not None:
        metadata["eval_dataset_version"] = dataset_version(dataset_path)
    # prompt_version / knowledge_version / memory_provider+version：当前无
    # 版本化来源，省略不伪造（后续接入版本管理后补键）。
    return {k: v for k, v in metadata.items() if v is not None}


def smoke_structural_ok(
    events: list, *, require_trace: bool = False,
) -> dict[str, Any]:
    """真实模型 smoke 的结构性断言（不评语义）：dangling=0、run 终态在场、
    usage/trace 完整性。返回逐项指标（给 report 与 Langfuse Scores）。"""
    metrics: dict[str, Any] = {
        "dangling_tool_calls": len(dangling_tool_call_ids(events)),
    }
    has_terminal = any(
        e.type in ("run/completed", "run/failed") for e in events
    )
    metrics["terminal_present"] = has_terminal
    usage_total: dict[str, int] = {}
    trace_id: str | None = None
    for event in events:
        if event.type == "run/completed":
            if event.data.get("usage_total"):
                usage_total = dict(event.data["usage_total"])
            trace_id = event.data.get("trace_id")
    metrics["usage_reported"] = bool(usage_total)
    metrics["trace_id_present"] = bool(trace_id)
    ok = has_terminal and metrics["dangling_tool_calls"] == 0 and metrics["usage_reported"]
    if require_trace:
        ok = ok and metrics["trace_id_present"]
    metrics["ok"] = ok
    return metrics


def run_real_model_smoke(
    task: str,
    *,
    settings: Settings | None = None,
    session_root: str | Path,
    require_trace: bool = False,
    runtime_factory: Callable[[Any], Any] | None = None,
    write_report: bool = True,
) -> CaseResult:
    """真实模型链 smoke（手动触发）：真实 provider + 真实 runtime + 结构断言。

    runtime_factory 注入 seam（测试用 fake runtime；生产用真实链构建）。
    """
    import asyncio

    from agent_harness.model.config import ModelConfig
    from agent_harness.model.provider import create_chat_model
    from agent_harness.tooling import ToolExecutor, ToolRegistry

    settings = settings or Settings()
    started = time.perf_counter()

    if runtime_factory is not None:
        runtime = runtime_factory(task)
    else:
        # from_settings 已解析两级链（primary + config.fallback），
        # 手动重建 fallback 会重复劳动且曾因字段名错配（name vs model_name）崩——
        # 直接消费 config.fallback 即可（ADR-0014 fallback 链语义不动）。
        model_config = ModelConfig.from_settings(settings)
        model = create_chat_model(model_config)
        fallback_model = (
            create_chat_model(model_config.fallback)
            if model_config.fallback is not None else None
        )
        registry = ToolRegistry()
        registry.register(AddTool())
        runtime = AgentRuntime(
            model, registry, ToolExecutor(registry),
            fallback_model=fallback_model,
            primary_model_name=settings.model_name,
            fallback_model_name=settings.fallback_model_name,
            observability_sink=_maybe_sink(settings),
        )

    from agent_harness.session import JsonlSessionStore, Session

    store = JsonlSessionStore(Path(session_root))
    session: Session = Session.start(store)
    error: str | None = None
    try:
        asyncio.run(runtime.run(session, task))
    except Exception as exc:  # noqa: BLE001 - smoke 失败如实记录
        error = f"{type(exc).__name__}: {exc}"

    events = list(session.events)
    structural = smoke_structural_ok(events, require_trace=require_trace)
    usage_total: dict[str, int] = {}
    for event in events:
        if event.type == "run/completed" and event.data.get("usage_total"):
            usage_total = dict(event.data["usage_total"])
    result = CaseResult(
        name="real-model-smoke", case_type="smoke",
        ok=bool(structural["ok"]) and error is None,
        metrics=structural, error=error, event_count=len(events),
        usage_total=usage_total,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    if write_report:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        import json

        payload = {
            "smoke": "real-model",
            "ran_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "regression_metadata": regression_metadata(settings=settings),
            "result": result.model_dump(),
        }
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        (_REPORTS_DIR / f"smoke-real-{stamp}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    return result


def _maybe_sink(settings: Settings) -> Any:
    from agent_harness.observability import get_observability_sink

    return get_observability_sink(settings)
