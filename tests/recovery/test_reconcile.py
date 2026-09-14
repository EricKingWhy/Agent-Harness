"""ReconcileCallback 人工裁决 contract tests（#30）。

覆盖 #30 全部 AC：
- RUNNING 崩溃状态进入 UNKNOWN，再进入 NEED_RECONCILE（两步状态机被 Ledger 强制）；
- UNKNOWN 与 NEED_RECONCILE 始终调用 ReconcileCallback；没有 callback 时安全拒绝；
- CONFIRM_SUCCESS / CONFIRM_FAILURE / RETRY / ABANDON 四种显式裁决；
- 进入 NEED_RECONCILE 时追加 operation/reconcile-required SessionEvent；
- UNKNOWN bash 永不自动重跑（协调器没有执行器，也无 callback 时拒绝恢复）；
- checkpoint/saved 仍不进入事件流。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_harness.recovery import (
    ReconcileCallback,
    ReconcileVerdict,
    RecoveryCoordinator,
    RecoveryError,
)
from agent_harness.sandbox.local import LocalSubprocessSandbox
from agent_harness.session import (
    MODEL_COMPLETED,
    SESSION_RESUMED,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
)
from agent_harness.storage import (
    Operation,
    OperationState,
    SqliteOperationLedger,
)
from agent_harness.tooling import ErrorCode, ReconcileHint, ToolRegistry, ToolResult
from agent_harness.tools import WriteTool

# ── 事件类型常量（#30 新增词汇） ──

OPERATION_RECONCILE_REQUIRED = "operation/reconcile-required"

# ── 测试夹具 ──

_SEED_CHAIN: dict[OperationState, list[OperationState]] = {
    OperationState.RUNNING: [OperationState.RUNNING],
    OperationState.UNKNOWN: [OperationState.RUNNING, OperationState.UNKNOWN],
    OperationState.NEED_RECONCILE: [
        OperationState.RUNNING,
        OperationState.UNKNOWN,
        OperationState.NEED_RECONCILE,
    ],
    OperationState.SUCCEEDED: [OperationState.RUNNING, OperationState.SUCCEEDED],
    OperationState.FAILED: [OperationState.RUNNING, OperationState.FAILED],
    OperationState.CANCELLED: [OperationState.RUNNING, OperationState.CANCELLED],
}


def _make_crashed_session(
    store: JsonlSessionStore,
    call_id: str = "call-1",
    tool_name: str = "bash",
) -> Session:
    """tool 执行后、结果写回前崩溃的 session（tool/call 已在，无 tool/result）。"""
    session = Session.start(store)
    session.append(USER_MESSAGE, {"content": "run the migration"})
    session.append(
        MODEL_COMPLETED,
        {
            "content": "",
            "tool_calls": [{"id": call_id, "name": tool_name, "args": {}}],
        },
        run_id="run-1",
        step_id=1,
    )
    session.append(
        TOOL_CALL,
        {"tool_call_id": call_id, "tool_name": tool_name, "args": {}},
        run_id="run-1",
        step_id=1,
    )
    return session


async def _seed_operation(
    ledger: SqliteOperationLedger,
    session_id: str,
    tool_call_id: str,
    state: OperationState,
    *,
    tool_name: str = "bash",
    result_json: str | None = None,
) -> None:
    await ledger.create(
        Operation(
            tool_call_id=tool_call_id,
            session_id=session_id,
            run_id="run-1",
            agent_id="default",
            tool_name=tool_name,
            args_identity='{"command": "migrate"}',
            state=OperationState.PENDING,
            started_at="2026-09-04T00:00:00+00:00",
        )
    )
    chain = _SEED_CHAIN[state]
    for step in chain:
        await ledger.update_state(
            session_id,
            tool_call_id,
            step,
            result_json=result_json if step is chain[-1] else None,
        )


class _ScriptedCallback(ReconcileCallback):
    """记录调用并返回预设裁决的 fake callback。"""

    def __init__(self, verdict: ReconcileVerdict) -> None:
        self.verdict = verdict
        self.calls: list[tuple[Operation, ReconcileHint]] = []

    async def resolve(
        self, operation: Operation, hint: ReconcileHint
    ) -> ReconcileVerdict:
        self.calls.append((operation, hint))
        return self.verdict


def _make_coordinator(
    store: JsonlSessionStore,
    ledger: SqliteOperationLedger,
    database_path: Path,
    *,
    reconcile_callback: ReconcileCallback | None = None,
    tool_registry: ToolRegistry | None = None,
) -> RecoveryCoordinator:
    return RecoveryCoordinator(
        session_store=store,
        workspace_registry=None,
        operation_ledger=ledger,
        database_path=database_path,
        reconcile_callback=reconcile_callback,
        tool_registry=tool_registry,
        lock_timeout_seconds=1.0,
    )


def _result_events(session: Session) -> dict[str, str]:
    return {
        event.data["tool_call_id"]: event.data["content"]
        for event in session.events
        if event.type == TOOL_RESULT
    }


def _reconcile_required_events(session: Session) -> list:
    return [
        event
        for event in session.events
        if event.type == OPERATION_RECONCILE_REQUIRED
    ]


# ── 状态机：RUNNING → UNKNOWN → NEED_RECONCILE 两步强制 ──


@pytest.mark.asyncio
async def test_ledger_enforces_two_step_unknown_transition(tmp_path: Path) -> None:
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    session_id = "session-ledger"
    await _seed_operation(
        ledger, session_id, "call-a", OperationState.RUNNING
    )

    # 两步链合法：RUNNING → UNKNOWN → NEED_RECONCILE → 终态。
    await ledger.update_state(session_id, "call-a", OperationState.UNKNOWN)
    await ledger.update_state(session_id, "call-a", OperationState.NEED_RECONCILE)
    final = await ledger.update_state(session_id, "call-a", OperationState.SUCCEEDED)
    assert final.state is OperationState.SUCCEEDED

    # 跳步非法：RUNNING 不允许直达 NEED_RECONCILE。
    await _seed_operation(ledger, session_id, "call-b", OperationState.RUNNING)
    with pytest.raises(ValueError, match="RUNNING -> NEED_RECONCILE"):
        await ledger.update_state(session_id, "call-b", OperationState.NEED_RECONCILE)


# ── 四种裁决 ──


@pytest.mark.asyncio
async def test_running_crash_reaches_callback_and_confirms_success(
    tmp_path: Path,
) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store, tool_name="bash")
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    result_json = ToolResult.success("migration applied").model_dump_json()
    await _seed_operation(
        ledger,
        session.session_id,
        "call-1",
        OperationState.RUNNING,
        result_json=result_json,
    )
    callback = _ScriptedCallback(ReconcileVerdict.CONFIRM_SUCCESS)

    recovered = await _make_coordinator(
        store, ledger, tmp_path / "state.db", reconcile_callback=callback
    ).recover(session.session_id)

    # 裁决结果落 Ledger：SUCCEEDED + 原 result_json。
    op = await ledger.get(session.session_id, "call-1")
    assert op is not None and op.state is OperationState.SUCCEEDED
    # reconcile-required 事件可观察，携带 tool_call_id 与 NEED_RECONCILE。
    events = _reconcile_required_events(recovered)
    assert len(events) == 1
    assert events[0].data["tool_call_id"] == "call-1"
    assert events[0].data["state"] == "NEED_RECONCILE"
    # 恢复结果复用原 tool_call_id，内容来自 Ledger result_json。
    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.ok is True
    assert synthesized.message == "migration applied"


@pytest.mark.asyncio
async def test_callback_receives_operation_and_hint(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store, tool_name="write")
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger, session.session_id, "call-1", OperationState.RUNNING,
        tool_name="write",
    )
    registry = ToolRegistry()
    registry.register(WriteTool(LocalSubprocessSandbox(workspace_root=tmp_path)))
    callback = _ScriptedCallback(ReconcileVerdict.CONFIRM_SUCCESS)

    await _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        reconcile_callback=callback,
        tool_registry=registry,
    ).recover(session.session_id)

    operation, hint = callback.calls[0]
    assert operation.tool_call_id == "call-1"
    assert operation.tool_name == "write"
    assert hint.verifiable is True  # write 覆写了 verifiable hint
    assert hint.suggested_action


@pytest.mark.asyncio
async def test_confirm_success_without_ledger_result_synthesizes_confirmed(
    tmp_path: Path,
) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, session.session_id, "call-1", OperationState.RUNNING)

    recovered = await _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        reconcile_callback=_ScriptedCallback(ReconcileVerdict.CONFIRM_SUCCESS),
    ).recover(session.session_id)

    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.ok is True
    assert "确认成功" in synthesized.message
    op = await ledger.get(session.session_id, "call-1")
    assert op is not None
    assert op.state is OperationState.SUCCEEDED
    assert op.result_json is not None  # 裁决结果回写 Ledger


@pytest.mark.asyncio
async def test_confirm_failure_marks_failed(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, session.session_id, "call-1", OperationState.RUNNING)

    recovered = await _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        reconcile_callback=_ScriptedCallback(ReconcileVerdict.CONFIRM_FAILURE),
    ).recover(session.session_id)

    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.ok is False
    assert "确认失败" in synthesized.message
    op = await ledger.get(session.session_id, "call-1")
    assert op is not None and op.state is OperationState.FAILED


@pytest.mark.asyncio
async def test_retry_verdict_produces_user_authorized_retryable_result(
    tmp_path: Path,
) -> None:
    """RETRY 只能来自用户裁决：合成 retryable=True 的失败结果，
    模型看到后重新发起【新的】tool_call（新 Operation），原调用终止。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, session.session_id, "call-1", OperationState.RUNNING)

    recovered = await _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        reconcile_callback=_ScriptedCallback(ReconcileVerdict.RETRY),
    ).recover(session.session_id)

    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.ok is False
    assert synthesized.retryable is True
    assert synthesized.error_code is ErrorCode.CANCELLED
    op = await ledger.get(session.session_id, "call-1")
    assert op is not None and op.state is OperationState.CANCELLED
    assert op.reconcile_meta is not None
    assert json.loads(op.reconcile_meta)["verdict"] == "RETRY"


@pytest.mark.asyncio
async def test_abandon_verdict_marks_cancelled_non_retryable(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, session.session_id, "call-1", OperationState.RUNNING)

    recovered = await _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        reconcile_callback=_ScriptedCallback(ReconcileVerdict.ABANDON),
    ).recover(session.session_id)

    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.ok is False
    assert synthesized.retryable is False
    assert synthesized.error_code is ErrorCode.CANCELLED
    op = await ledger.get(session.session_id, "call-1")
    assert op is not None and op.state is OperationState.CANCELLED
    assert json.loads(op.reconcile_meta)["verdict"] == "ABANDON"


# ── 既有 UNKNOWN / NEED_RECONCILE 状态 ──


@pytest.mark.asyncio
async def test_preexisting_unknown_operation_flows_through_callback(
    tmp_path: Path,
) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, session.session_id, "call-1", OperationState.UNKNOWN)
    callback = _ScriptedCallback(ReconcileVerdict.CONFIRM_SUCCESS)

    recovered = await _make_coordinator(
        store, ledger, tmp_path / "state.db", reconcile_callback=callback
    ).recover(session.session_id)

    assert len(callback.calls) == 1
    assert len(_reconcile_required_events(recovered)) == 1
    op = await ledger.get(session.session_id, "call-1")
    assert op is not None and op.state is OperationState.SUCCEEDED


@pytest.mark.asyncio
async def test_preexisting_need_reconcile_also_asks_user(tmp_path: Path) -> None:
    """上次恢复在裁决前崩溃遗留 NEED_RECONCILE：本次恢复再次询问用户。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger, session.session_id, "call-1", OperationState.NEED_RECONCILE
    )
    callback = _ScriptedCallback(ReconcileVerdict.ABANDON)

    recovered = await _make_coordinator(
        store, ledger, tmp_path / "state.db", reconcile_callback=callback
    ).recover(session.session_id)

    assert len(callback.calls) == 1
    assert len(_reconcile_required_events(recovered)) == 1
    assert "call-1" in _result_events(recovered)


# ── 安全默认：没有 callback 时拒绝 ──


@pytest.mark.asyncio
async def test_missing_callback_refuses_safely(tmp_path: Path) -> None:
    """没有 ReconcileCallback：安全拒绝——不合成、不改状态、不写事件。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, session.session_id, "call-1", OperationState.RUNNING)
    events_before = store.read_events(session.session_id)

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    with pytest.raises(RecoveryError, match="ReconcileCallback"):
        await coordinator.recover(session.session_id)

    # Ledger 状态未被推进（安全拒绝 = 完全不写）。
    op = await ledger.get(session.session_id, "call-1")
    assert op is not None and op.state is OperationState.RUNNING
    # 事件流零写入。
    assert store.read_events(session.session_id) == events_before


@pytest.mark.asyncio
async def test_unknown_bash_never_reruns_automatically(tmp_path: Path) -> None:
    """UNKNOWN bash 永不自动重跑：无 callback → 拒绝；有 callback → 只有合成结果，
    协调器没有执行器，不可能执行任何命令。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store, tool_name="bash")
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, session.session_id, "call-1", OperationState.RUNNING)

    # 无 callback：拒绝恢复，bash 不执行。
    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    with pytest.raises(RecoveryError):
        await coordinator.recover(session.session_id)

    # 有 callback（RETRY）：合成的结果只是"请重新发起"的裁决表达，
    # 不含任何真实命令输出（stdout/exit_code 字段不存在）。
    recovered = await _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        reconcile_callback=_ScriptedCallback(ReconcileVerdict.RETRY),
    ).recover(session.session_id)
    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.data is None  # 没有真实执行数据
    assert "重新发起" in synthesized.message


@pytest.mark.asyncio
async def test_no_reconcile_required_recovery_unaffected_by_missing_callback(
    tmp_path: Path,
) -> None:
    """没有 UNKNOWN 需求时，缺 callback 不影响普通恢复（#29 行为不回退）。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        session.session_id,
        "call-1",
        OperationState.SUCCEEDED,
        result_json=ToolResult.success("done").model_dump_json(),
    )

    recovered = await _make_coordinator(store, ledger, tmp_path / "state.db").recover(
        session.session_id
    )

    assert "call-1" in _result_events(recovered)
    assert recovered.events[-1].type == SESSION_RESUMED


# ── 事件流契约 ──


@pytest.mark.asyncio
async def test_reconcile_required_event_observable_and_no_checkpoint_events(
    tmp_path: Path,
) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, session.session_id, "call-1", OperationState.RUNNING)

    recovered = await _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        reconcile_callback=_ScriptedCallback(ReconcileVerdict.CONFIRM_SUCCESS),
    ).recover(session.session_id)

    types = [event.type for event in recovered.events]
    assert OPERATION_RECONCILE_REQUIRED in types
    # checkpoint/saved 仍不进入事件流（不变量：checkpoint 不是 SessionEvent）。
    assert not [t for t in types if t.startswith("checkpoint")]


@pytest.mark.asyncio
async def test_mixed_recovery_resolves_terminal_and_reconciles_unknown(
    tmp_path: Path,
) -> None:
    """同一批：终态走 #29 精确合成，RUNNING 走 #30 人工裁决，互不干扰。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    session = Session.start(store)
    session.append(USER_MESSAGE, {"content": "run two tools"})
    session.append(
        MODEL_COMPLETED,
        {
            "content": "",
            "tool_calls": [
                {"id": "call-a", "name": "bash", "args": {}},
                {"id": "call-b", "name": "bash", "args": {}},
            ],
        },
        run_id="run-1",
        step_id=1,
    )
    for call_id in ("call-a", "call-b"):
        session.append(
            TOOL_CALL,
            {"tool_call_id": call_id, "tool_name": "bash", "args": {}},
            run_id="run-1",
            step_id=1,
        )
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        session.session_id,
        "call-a",
        OperationState.SUCCEEDED,
        result_json=ToolResult.success("a done").model_dump_json(),
    )
    await _seed_operation(ledger, session.session_id, "call-b", OperationState.RUNNING)

    recovered = await _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        reconcile_callback=_ScriptedCallback(ReconcileVerdict.ABANDON),
    ).recover(session.session_id)

    results = _result_events(recovered)
    assert ToolResult.model_validate_json(results["call-a"]).message == "a done"
    assert ToolResult.model_validate_json(results["call-b"]).retryable is False
    assert len(_reconcile_required_events(recovered)) == 1
    # 恢复后投影无 dangling。
    recovered.derive_messages()


# ── 损坏 result_json 不阻塞人工裁决（#30 容错回归）──


@pytest.mark.asyncio
async def test_confirm_success_with_corrupt_ledger_result_falls_back(
    tmp_path: Path,
) -> None:
    """裁决 CONFIRM_SUCCESS 时若 Ledger 的 result_json 不是合法 ToolResult，
    不能让 ValidationError 冒泡——回调已裁决、协调器不能因数据腐烂拒绝恢复。

    _verdict_outcome 在 CONFIRM_SUCCESS/CONFIRM_FAILURE 两路都直调
    ToolResult.model_validate_json(operation.result_json)：这里钉住两路守卫都
    降级到"已由用户确认"的合成结果。
    """
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        session.session_id,
        "call-1",
        OperationState.RUNNING,
        result_json="not-json",
    )
    callback = _ScriptedCallback(ReconcileVerdict.CONFIRM_SUCCESS)

    recovered = await _make_coordinator(
        store, ledger, tmp_path / "state.db", reconcile_callback=callback
    ).recover(session.session_id)

    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.ok is True
    assert "用户确认成功" in synthesized.message


@pytest.mark.asyncio
async def test_confirm_failure_with_corrupt_ledger_result_falls_back(
    tmp_path: Path,
) -> None:
    """CONFIRM_FAILURE + 损坏 result_json：降级到"已由用户确认失败"合成结果。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        session.session_id,
        "call-1",
        OperationState.RUNNING,
        result_json="{garbage",
    )
    callback = _ScriptedCallback(ReconcileVerdict.CONFIRM_FAILURE)

    recovered = await _make_coordinator(
        store, ledger, tmp_path / "state.db", reconcile_callback=callback
    ).recover(session.session_id)

    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.ok is False
    assert "用户确认失败" in synthesized.message


# ── T4 #120：reconcile reason 进 JSONL 诊断层（spec 12 §2）──


@pytest.mark.asyncio
async def test_reconcile_verdict_recorded_in_jsonl_diagnostic_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    store = JsonlSessionStore(tmp_path / "sessions")
    session = _make_crashed_session(store, tool_name="bash")
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    result_json = ToolResult.success("migration applied").model_dump_json()
    await _seed_operation(
        ledger,
        session.session_id,
        "call-1",
        OperationState.RUNNING,
        result_json=result_json,
    )

    with caplog.at_level(logging.INFO, logger="agent_harness.recovery"):
        await _make_coordinator(
            store, ledger, tmp_path / "state.db",
            reconcile_callback=_ScriptedCallback(ReconcileVerdict.CONFIRM_SUCCESS),
        ).recover(session.session_id)

    verdict_lines = [
        r for r in caplog.records
        if getattr(r, "outcome", None) == "reconciled"
        and getattr(r, "reconcile_verdict", None) == "CONFIRM_SUCCESS"
    ]
    assert len(verdict_lines) == 1, "reconcile 裁决必须恰好一条 JSONL 诊断行"
    line = verdict_lines[0]
    assert getattr(line, "tool_call_id", None) == "call-1"
    assert getattr(line, "component", None) == "recovery"
    assert getattr(line, "ledger_state", None) == "SUCCEEDED"
