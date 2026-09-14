"""Eval Runner（spec 12 §5，ADR-0018 D9/D10）：项目所有，调真实 AgentRuntime。

- 数据集真相源：evaluation/datasets/*.jsonl（版本化在 repo，可 diff）；
- runner 把每条 case 喂给真实 AgentRuntime（deterministic 模式 =
  ScriptedModel + 真实 tool registry；真实模型 smoke = 真实链，手动触发）；
- deterministic assertions 全部代码判断（assertions.py），本地 JSON 报告
  恒产生；Langfuse Experiment 上报是可选旁路（未配置云则优雅跳过）。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_harness.agent import AgentRuntime
from agent_harness.model.scripted import ScriptedModel
from agent_harness.session import (
    RUN_COMPLETED,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
    SessionEvent,
)
from agent_harness.tooling import ToolExecutor, ToolRegistry
from evaluation.assertions import (
    dangling_tool_call_ids,
    kill_resume_ok,
    recovery_guard_ok,
    tool_selection_ok,
)
from evaluation.support import (
    AddTool,
    ModeledFailureAddTool,
    ReconcileVerdict,
    ScriptedReconcileCallback,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPORTS_DIR = _REPO_ROOT / "evaluation" / "reports"


class EvalCase(BaseModel):
    """数据集条目（evaluation/datasets/*.jsonl 的一行）。"""

    name: str
    case_type: str  # tool_selection | recovery | kill_resume | ...
    task: str
    # deterministic 模式的模型剧本（AIMessage 形状的 dict 列表）；
    # 真实模型 smoke 模式忽略此字段。
    script: list[dict[str, Any]] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    """单条 case 的归一化结果（Langfuse Scores 的本地真相）。"""

    name: str
    case_type: str
    ok: bool
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    event_count: int = 0
    usage_total: dict[str, int] = Field(default_factory=dict)
    duration_ms: int = 0


def load_dataset(path: str | Path) -> list[EvalCase]:
    """读 JSONL 数据集（每行一条 case；空行忽略）。"""
    cases: list[EvalCase] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(EvalCase.model_validate(json.loads(line)))
    return cases


def _build_script_model(case: EvalCase) -> ScriptedModel:
    from langchain_core.messages import AIMessage

    responses = [
        AIMessage(
            content=step.get("content", ""),
            tool_calls=[
                {**call, "type": "tool_call"} for call in step.get("tool_calls", [])
            ],
        )
        for step in case.script
    ]
    return ScriptedModel(responses)


def _registry_for_case(case: EvalCase) -> ToolRegistry:
    """case_type -> 真实 tool registry（deterministic P0 用加法工具域）。"""
    registry = ToolRegistry()
    if case.case_type == "tool_selection":
        registry.register(AddTool())
    elif case.case_type == "recovery":
        registry.register(ModeledFailureAddTool())
    # kill_resume 的 registry/kill 注入在 T7 落地。
    return registry


def run_case(
    case: EvalCase,
    *,
    session_root: str | Path,
    runtime_factory: Callable[[EvalCase], AgentRuntime] | None = None,
) -> tuple[CaseResult, list[SessionEvent]]:
    """跑一条 case：真实 AgentRuntime + 事件流归一化 + deterministic 断言。

    runtime_factory 可注入（真实模型 smoke 用真实链；默认 deterministic =
    ScriptedModel(case.script) + 真实 registry + 真实 executor）。返回
    (CaseResult, 事件流)——事件流供 Langfuse Scores/审计复用。
    """
    started = time.perf_counter()
    if case.case_type == "kill_resume":
        return _run_kill_resume_case(case, session_root, started)

    store = JsonlSessionStore(Path(session_root))
    session: Session = Session.start(store)

    if runtime_factory is not None:
        runtime = runtime_factory(case)
    else:
        registry = _registry_for_case(case)
        model = _build_script_model(case)
        runtime = AgentRuntime(model, registry, ToolExecutor(registry))

    metrics: dict[str, Any] = {}
    error: str | None = None
    result = None
    try:
        result = asyncio.run(runtime.run(session, case.task))
    except Exception as exc:  # noqa: BLE001 - 单条 case 失败不得炸掉整个实验
        error = f"{type(exc).__name__}: {exc}"

    events = list(session.events)
    metrics["dangling_tool_calls"] = len(dangling_tool_call_ids(events))
    metrics["status"] = result.status if result is not None else "error"

    ok = error is None and metrics["dangling_tool_calls"] == 0
    if case.case_type == "tool_selection":
        selection_ok = tool_selection_ok(events, list(case.expected.get("tools", [])))
        metrics["tool_selected"] = selection_ok
        ok = ok and selection_ok
    elif case.case_type == "recovery":
        recovered = recovery_guard_ok(events)
        metrics["recovered"] = recovered
        ok = ok and recovered

    usage_total: dict[str, int] = {}
    for event in events:
        if event.type == RUN_COMPLETED and event.data.get("usage_total"):
            usage_total = dict(event.data["usage_total"])
    return (
        CaseResult(
            name=case.name, case_type=case.case_type, ok=ok, metrics=metrics,
            error=error, event_count=len(events), usage_total=usage_total,
            duration_ms=int((time.perf_counter() - started) * 1000),
        ),
        events,
    )


def run_dataset(
    dataset_path: str | Path,
    *,
    session_root: str | Path,
    runtime_factory: Callable[[EvalCase], AgentRuntime] | None = None,
    write_report: bool = True,
) -> list[CaseResult]:
    """跑整个数据集并写本地 JSON 报告（真相恒落 repo reports/，云关也能看）。"""
    cases = load_dataset(dataset_path)
    results: list[CaseResult] = []
    for case in cases:
        case_result, _events = run_case(
            case, session_root=session_root, runtime_factory=runtime_factory,
        )
        results.append(case_result)

    if write_report:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report = {
            "dataset": Path(dataset_path).name,
            "ran_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "results": [r.model_dump() for r in results],
            "passed": sum(1 for r in results if r.ok),
            "total": len(results),
        }
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        (_REPORTS_DIR / f"{Path(dataset_path).stem}-{stamp}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    return results


def _run_kill_resume_case(
    case: EvalCase, session_root: str | Path, started: float,
) -> tuple[CaseResult, list[SessionEvent]]:
    """kill/resume Golden Case（spec 12 §11 硬要求，deterministic in-CI 版）：

    构造"崩溃窗口"事实——tool/call 已持久化、Ledger Operation 停在 RUNNING、
    tool/result 缺失（= kill 后未收口）——再走真实 RecoveryCoordinator 恢复：
    两步状态机 -> operation/reconcile-required -> 显式裁决 -> 合成 tool/result。
    断言：session/resumed 在场、无悬空 tool_call、Ledger 终态与裁决一致。
    """
    import asyncio

    from agent_harness.recovery import RecoveryCoordinator
    from agent_harness.storage import (
        SqliteOperationLedger,
    )
    from agent_harness.tooling import ToolResult

    root = Path(session_root)
    store = JsonlSessionStore(root / "sessions")
    session: Session = Session.start(store)
    session.append(USER_MESSAGE, {"content": case.task})

    verdict_value = str(case.expected.get("verdict", "CONFIRM_SUCCESS"))
    verdict = ReconcileVerdict(verdict_value)
    tool_result = ToolResult.success(
        message="migration applied (confirmed by user verdict)",
    )
    ledger = SqliteOperationLedger(root / "state.db")
    asyncio.run(_seed_running_op(
        ledger, session.session_id, "call-kill-1",
        tool_result.model_dump_json(),
    ))

    coordinator = RecoveryCoordinator(
        session_store=store,
        workspace_registry=None,
        operation_ledger=ledger,
        database_path=root / "state.db",
        reconcile_callback=ScriptedReconcileCallback(verdict),
    )
    error: str | None = None
    recovered: Session | None = None
    try:
        recovered = asyncio.run(coordinator.recover(session.session_id))
    except Exception as exc:  # noqa: BLE001 - 单条 case 失败不得炸掉实验
        error = f"{type(exc).__name__}: {exc}"

    events = list(recovered.events) if recovered is not None else []
    metrics: dict[str, Any] = {
        "dangling_tool_calls": len(dangling_tool_call_ids(events)),
        "kill_resume_ok": kill_resume_ok(events) if recovered is not None else False,
        "verdict": verdict_value,
    }
    ok = (
        error is None
        and recovered is not None
        and metrics["kill_resume_ok"]
        and metrics["dangling_tool_calls"] == 0
    )
    return (
        CaseResult(
            name=case.name, case_type=case.case_type, ok=ok, metrics=metrics,
            error=error, event_count=len(events),
            duration_ms=int((time.perf_counter() - started) * 1000),
        ),
        events,
    )


async def _seed_running_op(ledger: Any, session_id: str, tool_call_id: str,
                           result_json: str) -> None:
    from agent_harness.storage import Operation, OperationState

    await ledger.initialize()
    await ledger.create(Operation(
        tool_call_id=tool_call_id,
        session_id=session_id,
        run_id="run-kill",
        agent_id="default",
        tool_name="bash",
        args_identity='{"command": "apply-migration"}',
        state=OperationState.PENDING,
        started_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
    ))
    # 推进到 RUNNING（Ledger 强制 PENDING 起步）：模拟"kill 发生在执行中"。
    await ledger.update_state(session_id, tool_call_id, OperationState.RUNNING)
