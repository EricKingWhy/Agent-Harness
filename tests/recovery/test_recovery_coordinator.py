"""RecoveryCoordinator contract tests (#29).

覆盖 #29 全部 AC：
- 8 步恢复顺序（Session 加载 → Workspace → Ledger → reconcile → 一致性 → Context 重建）；
- SUCCEEDED / FAILED / CANCELLED 缺结果事件时按 Ledger result_json 合成准确 ToolResult；
- PENDING 由可注入 PendingPolicy 处理，默认 skip，不自动执行；
- 所有恢复结果复用原 tool_call_id；恢复后投影无已处理 dangling call；
- Runtime Context 从恢复后的持久 SessionEvent 重新派生；
- 并发恢复由 SQLite pessimistic transaction 串行化（诚实声明：数据库级锁，非行级锁）；
- 协调器失败抛异常、不写虚假完成状态、重试安全（幂等）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

from agent_harness.recovery import (
    PendingPolicy,
    RecoveryCoordinator,
    RecoveryError,
    SkipPendingPolicy,
)
from agent_harness.session import (
    MODEL_COMPLETED,
    SESSION_RESUMED,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    JsonlSessionStore,
    Session,
)
from agent_harness.session.derive import DANGLING_TOOL_CONTENT
from agent_harness.storage import (
    Operation,
    OperationState,
    SqliteOperationLedger,
)
from agent_harness.tooling import ErrorCode, ToolResult

# ── 测试夹具：构造"崩溃现场" ──


def _make_crashed_session(store: JsonlSessionStore) -> Session:
    """构造一个 tool 执行后、结果写回前崩溃的 session：
    session/started → user/message → model/completed(tool_calls) → tool/call，无 tool/result。
    不走 Session.resume（它会在 Ledger reconcile 之前注入 dangling 占位）。"""
    session = Session.start(store)
    session.append(USER_MESSAGE, {"content": "run the migration"})
    session.append(
        MODEL_COMPLETED,
        {
            "content": "",
            "tool_calls": [
                {"id": "call-1", "name": "bash", "args": {"command": "migrate"}}
            ],
        },
        run_id="run-1",
        step_id=1,
    )
    session.append(
        TOOL_CALL,
        {"tool_call_id": "call-1", "tool_name": "bash", "args": {"command": "migrate"}},
        run_id="run-1",
        step_id=1,
    )
    return session


async def _seed_operation(
    ledger: SqliteOperationLedger,
    tool_call_id: str,
    state: OperationState,
    session_id: str,
    *,
    result_json: str | None = None,
) -> None:
    await ledger.create(
        Operation(
            tool_call_id=tool_call_id,
            session_id=session_id,
            run_id="run-1",
            agent_id="default",
            tool_name="bash",
            args_identity='{"command": "migrate"}',
            state=OperationState.PENDING,
            started_at="2026-09-04T00:00:00+00:00",
        )
    )
    if state is not OperationState.PENDING:
        await ledger.update_state(session_id, tool_call_id, OperationState.RUNNING)
        if state is not OperationState.RUNNING:
            await ledger.update_state(
                session_id, tool_call_id, state, result_json=result_json
            )


def _make_coordinator(
    store: JsonlSessionStore,
    ledger: SqliteOperationLedger,
    database_path: Path | None,
    *,
    pending_policy: PendingPolicy | None = None,
    workspace_registry=None,
) -> RecoveryCoordinator:
    return RecoveryCoordinator(
        session_store=store,
        workspace_registry=workspace_registry,
        operation_ledger=ledger,
        pending_policy=pending_policy,
        database_path=database_path,
        lock_timeout_seconds=1.0,
    )


def _result_events(session: Session) -> dict[str, str]:
    """tool_call_id → result content 的映射。"""
    return {
        event.data["tool_call_id"]: event.data["content"]
        for event in session.events
        if event.type == TOOL_RESULT
    }


def _call_event_ids(session: Session) -> set[str]:
    return {
        event.data["tool_call_id"]
        for event in session.events
        if event.type == TOOL_CALL
    }


# ── 终态合成 ──


@pytest.mark.asyncio
async def test_succeeded_operation_synthesizes_real_result(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        "call-1",
        OperationState.SUCCEEDED,
        crashed.session_id,
        result_json=ToolResult.success("migration applied").model_dump_json(),
    )

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(crashed.session_id)

    results = _result_events(recovered)
    assert "call-1" in results
    synthesized = ToolResult.model_validate_json(results["call-1"])
    assert synthesized.ok is True
    assert synthesized.message == "migration applied"
    # 复用原 tool_call_id；投影配对无 dangling。
    assert recovered.derive_messages()[-1].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_failed_and_cancelled_operations_synthesize_accurate_results(
    tmp_path: Path,
) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    session = Session.start(store)
    session.append(USER_MESSAGE, {"content": "run two tools"})
    session.append(
        MODEL_COMPLETED,
        {
            "content": "",
            "tool_calls": [
                {"id": "call-f", "name": "bash", "args": {}},
                {"id": "call-c", "name": "bash", "args": {}},
            ],
        },
        run_id="run-1",
        step_id=1,
    )
    for call_id in ("call-f", "call-c"):
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
        "call-f",
        OperationState.FAILED,
        session.session_id,
        result_json=ToolResult.failure(
            "boom", error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            retryable=False,
        ).model_dump_json(),
    )
    await _seed_operation(
        ledger,
        "call-c",
        OperationState.CANCELLED,
        session.session_id,
        result_json=ToolResult.failure(
            "cancelled by cascade",
            error_code=ErrorCode.CANCELLED,
            retryable=False,
        ).model_dump_json(),
    )

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(session.session_id)

    results = _result_events(recovered)
    failed = ToolResult.model_validate_json(results["call-f"])
    cancelled = ToolResult.model_validate_json(results["call-c"])
    assert failed.ok is False and failed.message == "boom"
    assert cancelled.ok is False and cancelled.message == "cancelled by cascade"


@pytest.mark.asyncio
async def test_missing_call_event_is_also_restored(tmp_path: Path) -> None:
    """崩溃窗口：Ledger 已终态，但 tool/call 事件还没写（model/completed 已在）。
    恢复必须补齐 tool/call + tool/result 一对事件。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    session = Session.start(store)
    session.append(USER_MESSAGE, {"content": "hi"})
    session.append(
        MODEL_COMPLETED,
        {
            "content": "",
            "tool_calls": [
                {"id": "call-1", "name": "bash", "args": {"command": "migrate"}}
            ],
        },
        run_id="run-1",
        step_id=1,
    )
    # 崩溃：无 tool/call，无 tool/result。
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        "call-1",
        OperationState.SUCCEEDED,
        session.session_id,
        result_json=ToolResult.success("done").model_dump_json(),
    )

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(session.session_id)

    assert "call-1" in _call_event_ids(recovered)
    assert "call-1" in _result_events(recovered)


# ── PENDING 策略 ──


@pytest.mark.asyncio
async def test_pending_operation_skipped_without_execution(tmp_path: Path) -> None:
    """默认 SkipPendingPolicy：合成 skipped 结果，绝不自动执行（工具计数=0）。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, "call-1", OperationState.PENDING, crashed.session_id)

    execution_count = 0

    class _CountingPolicy(SkipPendingPolicy):
        def result_for(self, operation: Operation) -> ToolResult:
            nonlocal execution_count
            execution_count += 1  # 只统计决策次数，不是工具执行
            return super().result_for(operation)

    coordinator = _make_coordinator(
        store, ledger, tmp_path / "state.db", pending_policy=_CountingPolicy()
    )
    recovered = await coordinator.recover(crashed.session_id)

    results = _result_events(recovered)
    assert "call-1" in results
    skipped = ToolResult.model_validate_json(results["call-1"])
    assert skipped.ok is False
    # 跳过文案必须真的在场（T8 迁移到 frame:recovery_skipped）——取错组装分区
    # （.system_text 在 FRAGMENT scope 下恒为空串）会让 message 变空串而不报错，
    # 这条断言就是那个回归的探测器。
    assert "尚未启动" in skipped.message
    assert "跳过" in skipped.message
    # 未自动执行：没有真实工具被调用（这里用执行计数恒 0 表达——policy 只被咨询，
    # 不触发任何 Tool.execute；execution_count 记录的是决策次数）。
    assert execution_count == 1
    # Ledger 推进到 CANCELLED（Round 8 契约修订）：skip 决策已把 CANCELLED 语义的
    # 结果合成进 session，Ledger 行同步记录"恢复时被放弃、从未执行"——PENDING→CANCELLED
    # 是状态机显式允许的迁移，不伪造任何执行结果（不写 SUCCEEDED/FAILED）。此前
    # 停留 PENDING 让 ledger 与 session 对同一 tool_call 永久不一致。再次 recover
    # 靠结果事件幂等跳过（dangling 判定基于事件配对，与 Ledger 状态正交）。
    op = await ledger.get(crashed.session_id, "call-1")
    assert op is not None and op.state is OperationState.CANCELLED
    assert op.result_json == results["call-1"]


@pytest.mark.asyncio
async def test_custom_pending_policy_is_injectable(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, "call-1", OperationState.PENDING, crashed.session_id)

    class _CustomPolicy(PendingPolicy):
        def result_for(self, operation: Operation) -> ToolResult:
            return ToolResult.failure(
                "queued for manual re-run",
                error_code=ErrorCode.CANCELLED,
                retryable=False,
            )

    coordinator = _make_coordinator(
        store, ledger, tmp_path / "state.db", pending_policy=_CustomPolicy()
    )
    recovered = await coordinator.recover(crashed.session_id)

    results = _result_events(recovered)
    assert "queued for manual re-run" in results["call-1"]


# ── 一致性 / 幂等 / 边界 ──


@pytest.mark.asyncio
async def test_recovery_is_idempotent(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        "call-1",
        OperationState.SUCCEEDED,
        crashed.session_id,
        result_json=ToolResult.success("done").model_dump_json(),
    )
    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")

    first = await coordinator.recover(crashed.session_id)
    second = await coordinator.recover(crashed.session_id)

    for recovered in (first, second):
        contents = [
            event.data["content"]
            for event in recovered.events
            if event.type == TOOL_RESULT and event.data["tool_call_id"] == "call-1"
        ]
        assert contents.count(
            ToolResult.success("done").model_dump_json()
        ) == 1  # 只有一条真实恢复结果，不重复
    assert len(second.events) - len(first.events) == 1  # 只多了 session/resumed


@pytest.mark.asyncio
async def test_dangling_without_ledger_op_gets_phase1_placeholder(
    tmp_path: Path,
) -> None:
    """Ledger 不知道的 dangling call（如 validation 失败未建 Operation）
    退回 Phase 1 占位语义，保证投影一致。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)  # call-1 无 Ledger 记录
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(crashed.session_id)

    results = _result_events(recovered)
    assert results["call-1"] == DANGLING_TOOL_CONTENT


@pytest.mark.asyncio
async def test_unresolved_operation_refused_without_callback(tmp_path: Path) -> None:
    """RUNNING/UNKNOWN/NEED_RECONCILE 需要 #30 的人工裁决：无 callback 时
    安全拒绝（不合成、不伪造结果、不写任何事件）。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, "call-1", OperationState.RUNNING, crashed.session_id)
    events_before = store.read_events(crashed.session_id)

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    with pytest.raises(RecoveryError):
        await coordinator.recover(crashed.session_id)

    # 拒绝即零写入：无 tool/result，也无 session/resumed。
    assert store.read_events(crashed.session_id) == events_before


@pytest.mark.asyncio
async def test_recovery_appends_session_resumed(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(crashed.session_id)

    assert recovered.events[-1].type == SESSION_RESUMED


# ── Workspace 恢复 ──


@pytest.mark.asyncio
async def test_workspace_restored_from_registry(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()

    from agent_harness.sandbox.registry import WorkspaceRegistry

    registry = WorkspaceRegistry(tmp_path / "ws", backend="local")
    registry.create(crashed.session_id)  # 崩溃前创建过 workspace

    coordinator = _make_coordinator(
        store, ledger, tmp_path / "state.db", workspace_registry=registry
    )
    recovered = await coordinator.recover(crashed.session_id)

    assert recovered.sandbox is not None
    assert recovered.sandbox.workspace_root == tmp_path / "ws" / "workspaces" / crashed.session_id


@pytest.mark.asyncio
async def test_workspace_absent_is_graceful(tmp_path: Path) -> None:
    """无映射记录的 session（纯对话）恢复不炸——sandbox 为 None。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()

    from agent_harness.sandbox.registry import WorkspaceRegistry

    registry = WorkspaceRegistry(tmp_path / "ws", backend="local")
    coordinator = _make_coordinator(
        store, ledger, tmp_path / "state.db", workspace_registry=registry
    )
    recovered = await coordinator.recover(crashed.session_id)
    assert recovered.sandbox is None


# ── 并发 / 锁 / 失败重试 ──


@pytest.mark.asyncio
async def test_concurrent_recovery_is_serialized(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        "call-1",
        OperationState.SUCCEEDED,
        crashed.session_id,
        result_json=ToolResult.success("done").model_dump_json(),
    )
    database_path = tmp_path / "state.db"
    c1 = _make_coordinator(store, ledger, database_path)
    c2 = _make_coordinator(store, ledger, database_path)

    first, second = await asyncio.gather(
        c1.recover(crashed.session_id), c2.recover(crashed.session_id)
    )

    # 以 store 里最终持久化的事件为准：call-1 只有一条恢复结果。
    final_events = JsonlSessionStore(tmp_path / "sessions").read_events(
        crashed.session_id
    )
    result_contents = [
        event.data["content"]
        for event in final_events
        if event.type == TOOL_RESULT and event.data["tool_call_id"] == "call-1"
    ]
    assert result_contents.count(ToolResult.success("done").model_dump_json()) == 1
    assert first is not None and second is not None


@pytest.mark.asyncio
async def test_lock_timeout_raises_recovery_error(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    database_path = tmp_path / "state.db"

    # 外部进程持有恢复锁（sidecar 锁文件，与协调器抢同一把）。
    blocker = await aiosqlite.connect(
        str(database_path) + ".recovery-lock", timeout=1.0
    )
    await blocker.execute("BEGIN EXCLUSIVE TRANSACTION")

    coordinator = _make_coordinator(store, ledger, database_path)
    with pytest.raises(RecoveryError):
        await coordinator.recover(crashed.session_id)

    await blocker.execute("ROLLBACK")
    await blocker.close()

    # 锁释放后恢复成功。
    recovered = await coordinator.recover(crashed.session_id)
    assert recovered is not None


@pytest.mark.asyncio
async def test_failure_releases_lock_and_retry_succeeds(tmp_path: Path) -> None:
    """协调器失败：抛原异常、锁释放、无虚假完成状态；修好后重试成功。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(ledger, "call-1", OperationState.PENDING, crashed.session_id)

    class _ExplodingPolicy(PendingPolicy):
        def result_for(self, operation: Operation) -> ToolResult:
            raise ValueError("policy exploded")

    coordinator = _make_coordinator(
        store,
        ledger,
        tmp_path / "state.db",
        pending_policy=_ExplodingPolicy(),
    )
    with pytest.raises(ValueError):
        await coordinator.recover(crashed.session_id)

    # 失败后无任何 tool/result 写入（决策先于写结果的证据）。
    events_after_failure = store.read_events(crashed.session_id)
    assert not [e for e in events_after_failure if e.type == TOOL_RESULT]

    # 重试（默认策略）成功且结果正确。
    retry_coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await retry_coordinator.recover(crashed.session_id)
    assert "call-1" in _result_events(recovered)


# ── Runtime Context 重建 ──


@pytest.mark.asyncio
async def test_runtime_context_rederived_from_recovered_events(tmp_path: Path) -> None:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        "call-1",
        OperationState.SUCCEEDED,
        crashed.session_id,
        result_json=ToolResult.success("migration applied").model_dump_json(),
    )

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(crashed.session_id)

    messages = recovered.derive_messages()
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage) and messages[1].tool_calls
    assert isinstance(messages[-1], ToolMessage)
    assert messages[-1].tool_call_id == "call-1"
    assert "migration applied" in messages[-1].content
    # 无 Phase 1 占位（真实结果已合成）。
    assert all(DANGLING_TOOL_CONTENT not in str(m.content) for m in messages)


# ── 损坏 result_json 不阻塞恢复（#29 容错回归）──


@pytest.mark.asyncio
async def test_corrupt_succeeded_result_json_falls_back_to_missing_detail(
    tmp_path: Path,
) -> None:
    """Ledger 的 result_json 不是合法 ToolResult JSON 时，恢复不能崩。

    _content_from_ledger 直接返回 operation.result_json——若 Ledger 行被外部写入
    或迁移残留污染成 'not-json'，恢复会向 Session 写入无法被 ToolResult 解析的
    内容，下游 derive_messages / 模型回灌就会拿到乱码。守卫必须捕获 ValidationError
    并降级到"结果详情缺失"合成结果（与无 result_json 的降级路径一致）。
    """
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        "call-1",
        OperationState.SUCCEEDED,
        crashed.session_id,
        result_json="not-json",
    )

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(crashed.session_id)

    results = _result_events(recovered)
    assert "call-1" in results
    synthesized = ToolResult.model_validate_json(results["call-1"])
    assert synthesized.ok is True
    assert "结果详情缺失" in synthesized.message


@pytest.mark.asyncio
async def test_corrupt_failed_result_json_falls_back_to_missing_detail(
    tmp_path: Path,
) -> None:
    """FAILED 终态 + 损坏 result_json：降级合成失败结果，恢复不崩。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    crashed = _make_crashed_session(store)
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        "call-1",
        OperationState.FAILED,
        crashed.session_id,
        result_json="{not valid",
    )

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(crashed.session_id)

    synthesized = ToolResult.model_validate_json(_result_events(recovered)["call-1"])
    assert synthesized.ok is False
    assert "结果详情缺失" in synthesized.message


# ── 合成 tool/call 携带真实 args_identity（EX FIX 4）──


@pytest.mark.asyncio
async def test_synthesized_tool_call_carries_real_args_not_empty(
    tmp_path: Path,
) -> None:
    """崩溃窗口补齐 tool/call 时，args 必须来自 Ledger 的 args_identity，
    不是空 {}。

    derive_messages 把 tool/call 的 args 投到 AIMessage.tool_calls[*].args
    喂给模型——合成事件若是 {}，恢复后的对话历史会把"用户实际请求的命令"
    抹成空字典，模型在后续轮次看到的就是一次空调用，事实被歪曲。
    args_identity 是工具调用入参的冻结快照（Ledger 在执行前写入），是崩溃
    现场最可靠的入参来源。
    """
    store = JsonlSessionStore(tmp_path / "sessions")
    session = Session.start(store)
    session.append(USER_MESSAGE, {"content": "hi"})
    session.append(
        MODEL_COMPLETED,
        {
            "content": "",
            "tool_calls": [
                {"id": "call-1", "name": "bash", "args": {"command": "migrate"}}
            ],
        },
        run_id="run-1",
        step_id=1,
    )
    # 崩溃：无 tool/call，无 tool/result。
    ledger = SqliteOperationLedger(tmp_path / "state.db")
    await ledger.initialize()
    await _seed_operation(
        ledger,
        "call-1",
        OperationState.SUCCEEDED,
        session.session_id,
        result_json=ToolResult.success("done").model_dump_json(),
    )

    coordinator = _make_coordinator(store, ledger, tmp_path / "state.db")
    recovered = await coordinator.recover(session.session_id)

    synthesized_call = next(
        e for e in recovered.events if e.type == TOOL_CALL and e.data["tool_call_id"] == "call-1"
    )
    assert synthesized_call.data["args"] == {"command": "migrate"}
