"""UNKNOWN bash reconciliation + Phase 4 收口 integration tests（#33）。

bash 处于真实执行中途时 Kill 子进程（延迟退出 hook：Ledger 已写 RUNNING、
bash 子命令正在 sleep）→ 恢复后经人工裁决收口。

覆盖 #33 全部 AC：
- bash RUNNING 真实 Kill → 恢复驱动 RUNNING → UNKNOWN → NEED_RECONCILE
  （裁决回调在 resolve 时重读 Ledger 验证状态已是 NEED_RECONCILE）；
- 没有 ReconcileCallback 时 bash 不执行（安全拒绝、零写入）；
- 有 callback 时仅按显式 verdict 继续；
- operation/reconcile-required 事件可从【持久】SessionEvent 中观察；
- 并发 recover 不产生重复 Recovery ToolResult / 重复副作用 / 重复裁决；
- 最终 Gate 断言：duplicate confirmed side effect = 0、dangling tool call = 0、
  Workspace 恢复正确。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_harness.recovery import (
    ReconcileCallback,
    ReconcileVerdict,
    RecoveryCoordinator,
)
from agent_harness.sandbox.registry import WorkspaceRegistry
from agent_harness.session import (
    OPERATION_RECONCILE_REQUIRED,
    TOOL_RESULT,
    JsonlSessionStore,
    detect_dangling,
)
from agent_harness.storage import OperationState, SqliteOperationLedger
from agent_harness.tooling import ErrorCode, ReconcileHint, ToolResult
from tests.integration.test_kill_resume import _discover_session_id, _run_child

# 跨 shell（Windows cmd / POSIX sh）安全的 mid-flight 命令：
# 立刻产生可观察副作用，然后长时间 sleep —— 1 秒后 kill 时 sleep 仍在进行。
_BASH_MIDFLIGHT = (
    'echo ran-once >> sideeffect.log && python -c "import time; time.sleep(10)"'
)

_CHILD_CONFIG = {
    "root": "{root}",
    "calls": [{"id": "call-1", "name": "bash", "args": {"command": _BASH_MIDFLIGHT}}],
    "kill_stage": "running",
    "kill_call_id": "call-1",
    "kill_delay_seconds": 1.0,
}


def _kill_running_bash(root: Path) -> str:
    """真实子进程在 bash 执行中途崩溃；返回 session_id。"""
    config = dict(_CHILD_CONFIG)
    config["root"] = str(root)
    returncode = _run_child(root, config)
    assert returncode == 137
    return _discover_session_id(root)


def _sideeffect_count(root: Path, session_id: str) -> int:
    log = root / "ws" / "workspaces" / session_id / "sideeffect.log"
    if not log.exists():
        return 0
    return log.read_text(encoding="utf-8").count("ran-once")


def _persisted_events(root: Path, session_id: str) -> list:
    return JsonlSessionStore(root / "sessions").read_events(session_id)


class _LedgerWatchingAbandon(ReconcileCallback):
    """裁决时重读 Ledger（验证状态已被推进到 NEED_RECONCILE）并返回 ABANDON。"""

    def __init__(self, ledger: SqliteOperationLedger) -> None:
        self._ledger = ledger
        self.calls: list[str] = []
        self.states_at_resolve: list[OperationState] = []
        self.hints: list[ReconcileHint] = []

    async def resolve(
        self, operation, hint: ReconcileHint
    ) -> ReconcileVerdict:
        current = await self._ledger.get(operation.session_id, operation.tool_call_id)
        assert current is not None
        self.states_at_resolve.append(current.state)
        self.calls.append(operation.tool_call_id)
        self.hints.append(hint)
        return ReconcileVerdict.ABANDON


async def _recover(root: Path, session_id: str, **kwargs):
    ledger = SqliteOperationLedger(root / "state.db")
    await ledger.initialize()
    coordinator = RecoveryCoordinator(
        session_store=JsonlSessionStore(root / "sessions"),
        workspace_registry=WorkspaceRegistry(root / "ws", backend="local"),
        operation_ledger=ledger,
        database_path=root / "state.db",
        **kwargs,
    )
    return await asyncio.wait_for(coordinator.recover(session_id), timeout=30)


# ── bash RUNNING 真实 Kill → 人工裁决收口 ──


@pytest.mark.asyncio
async def test_running_bash_kill_requires_human_and_abandons_cleanly(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    session_id = _kill_running_bash(root)

    # 崩溃现场：Ledger RUNNING（UNKNOWN 语义：bash 可能已产生副作用），
    # 副作用恰好发生一次（mid-flight kill 的可观察证据）。
    ledger = SqliteOperationLedger(root / "state.db")
    await ledger.initialize()
    operation = await ledger.get(session_id, "call-1")
    assert operation is not None and operation.state is OperationState.RUNNING
    assert _sideeffect_count(root, session_id) == 1

    callback = _LedgerWatchingAbandon(ledger)
    recovered = await _recover(root, session_id, reconcile_callback=callback)

    # 裁决发生时状态已是 NEED_RECONCILE（RUNNING → UNKNOWN → NEED_RECONCILE 已推进）。
    assert callback.calls == ["call-1"]
    assert callback.states_at_resolve == [OperationState.NEED_RECONCILE]
    # bash 的 hint 保持默认 unverifiable（07 §7：不允许假装可验证）。
    assert callback.hints[0].verifiable is False

    # 显式 ABANDON 裁决 → CANCELLED、不可重试的 Recovery ToolResult。
    persisted = _persisted_events(root, session_id)
    results = {
        e.data["tool_call_id"]: e.data["content"]
        for e in persisted
        if e.type == TOOL_RESULT
    }
    abandoned = ToolResult.model_validate_json(results["call-1"])
    assert abandoned.ok is False
    assert abandoned.retryable is False
    assert abandoned.error_code is ErrorCode.CANCELLED

    # operation/reconcile-required 可从【持久】事件中观察。
    assert [
        e for e in persisted if e.type == OPERATION_RECONCILE_REQUIRED
    ], "reconcile-required 事件必须落盘"

    # 最终 Gate：副作用不重复（仍是 1 次）、dangling = 0、Workspace 恢复正确。
    assert _sideeffect_count(root, session_id) == 1
    assert detect_dangling(persisted) == []
    assert recovered.sandbox is not None
    assert Path(recovered.sandbox.workspace_root) == (
        root / "ws" / "workspaces" / session_id
    )
    final_op = await ledger.get(session_id, "call-1")
    assert final_op is not None and final_op.state is OperationState.CANCELLED


# ── 没有 callback：安全拒绝，bash 不执行 ──


@pytest.mark.asyncio
async def test_running_bash_without_callback_refuses_and_executes_nothing(
    tmp_path: Path,
) -> None:
    from agent_harness.recovery import RecoveryError

    root = tmp_path / "root"
    session_id = _kill_running_bash(root)
    events_before = _persisted_events(root, session_id)

    ledger = SqliteOperationLedger(root / "state.db")
    await ledger.initialize()
    coordinator = RecoveryCoordinator(
        session_store=JsonlSessionStore(root / "sessions"),
        workspace_registry=WorkspaceRegistry(root / "ws", backend="local"),
        operation_ledger=ledger,
        database_path=root / "state.db",
    )
    with pytest.raises(RecoveryError, match="ReconcileCallback"):
        await asyncio.wait_for(coordinator.recover(session_id), timeout=30)

    # bash 不执行：副作用计数不变、事件流零写入、Ledger 状态未被推进。
    assert _sideeffect_count(root, session_id) == 1
    assert _persisted_events(root, session_id) == events_before
    operation = await ledger.get(session_id, "call-1")
    assert operation is not None and operation.state is OperationState.RUNNING


# ── 并发 recover：无重复结果、无重复副作用、无重复裁决 ──


@pytest.mark.asyncio
async def test_concurrent_recover_produces_no_duplicates(tmp_path: Path) -> None:
    root = tmp_path / "root"
    session_id = _kill_running_bash(root)

    ledger = SqliteOperationLedger(root / "state.db")
    await ledger.initialize()
    callback = _LedgerWatchingAbandon(ledger)

    async def make_coordinator() -> RecoveryCoordinator:
        return RecoveryCoordinator(
            session_store=JsonlSessionStore(root / "sessions"),
            workspace_registry=WorkspaceRegistry(root / "ws", backend="local"),
            operation_ledger=SqliteOperationLedger(root / "state.db"),
            database_path=root / "state.db",
            reconcile_callback=callback,
            lock_timeout_seconds=10.0,
        )

    c1 = await make_coordinator()
    c2 = await make_coordinator()
    first, second = await asyncio.gather(
        asyncio.wait_for(c1.recover(session_id), timeout=60),
        asyncio.wait_for(c2.recover(session_id), timeout=60),
    )
    assert first is not None and second is not None

    # 以磁盘持久状态为准：call-1 恰一条 Recovery ToolResult、恰一条
    # reconcile-required、恰一次人工裁决、副作用恰一次。
    persisted = _persisted_events(root, session_id)
    result_events = [e for e in persisted if e.type == TOOL_RESULT
                     and e.data["tool_call_id"] == "call-1"]
    assert len(result_events) == 1
    assert len([e for e in persisted if e.type == OPERATION_RECONCILE_REQUIRED]) == 1
    assert callback.calls == ["call-1"]
    assert _sideeffect_count(root, session_id) == 1
    assert detect_dangling(persisted) == []
