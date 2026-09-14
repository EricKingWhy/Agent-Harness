"""Langfuse Experiment 上报（ADR-0018 D9/D10）。

数据集在云端的实验走 Langfuse 原生 ``run_experiment``：task = 项目 runner
（调真实 AgentRuntime），evaluators = deterministic assertions（代码判断）。
Langfuse 未配置 → 优雅跳过（本地 run_dataset 报告恒产生，不受影响）。
真实模型 smoke 入口见 :func:`run_smoke_experiment`（T8：手动触发，结构性断言）。
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evaluation.runner import EvalCase, run_case


def _deterministic_evaluators() -> list[Callable[..., dict[str, Any]]]:
    """代码判断评分器：p0_pass（总闸）+ dangling_tool_calls（硬计数）。"""

    def p0_pass(*, output: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return {"name": "p0_pass", "value": 1 if output["result"]["ok"] else 0}

    def dangling(*, output: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return {
            "name": "dangling_tool_calls",
            "value": output["result"]["metrics"].get("dangling_tool_calls", 0),
        }

    return [p0_pass, dangling]


def _case_from_item(item: Any) -> EvalCase:
    """Langfuse DatasetItem → EvalCase（round-trip：metadata/name + input.task）。"""
    metadata = getattr(item, "metadata", None) or {}
    item_input = getattr(item, "input", None) or {}
    return EvalCase(
        name=str(metadata.get("name") or getattr(item, "id", "unnamed")),
        case_type=str(metadata.get("case_type") or "tool_selection"),
        task=str(item_input.get("task", "")),
        script=list(metadata.get("script", [])),
        expected=getattr(item, "expected_output", None) or {},
        tags=list(metadata.get("tags", [])),
    )


def run_langfuse_experiment(
    dataset_name: str,
    *,
    public_key: str,
    secret_key: str,
    base_url: str,
    experiment_name: str | None = None,
    runtime_factory: Callable[[EvalCase], Any] | None = None,
    session_root: str | Path | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """跑云端数据集实验（deterministic 模式默认 ScriptedModel）。"""
    if not public_key or not secret_key:
        return {
            "status": "skipped",
            "reason": "LANGFUSE_PUBLIC_KEY/SECRET_KEY 未配置——云端实验跳过（本地报告不受影响）",
        }
    from langfuse import Langfuse  # 云端操作前台执行，非旁路热路径

    factory = client_factory or (lambda **kwargs: Langfuse(**kwargs))
    client = factory(public_key=public_key, secret_key=secret_key, base_url=base_url)
    dataset = client.get_dataset(dataset_name)

    own_root = session_root is None
    root = Path(session_root) if session_root is not None else Path(
        tempfile.mkdtemp(prefix="eval-experiment-"),
    )

    def task(item: Any) -> dict[str, Any]:
        case = _case_from_item(item)
        case_session_root = root / case.name
        result, _events = run_case(
            case, session_root=case_session_root, runtime_factory=runtime_factory,
        )
        return {"result": result.model_dump()}

    client.run_experiment(
        name=experiment_name or f"eval-{dataset_name}",
        run_name=f"run-{dataset_name}",
        data=dataset.items,
        task=task,
        evaluators=_deterministic_evaluators(),
        max_concurrency=1,
    )
    return {"status": "ok", "experiment": experiment_name or f"eval-{dataset_name}",
            "session_root": str(root) if own_root else str(session_root)}
