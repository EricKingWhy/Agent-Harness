"""SessionService 领域层测试（T1 / #131）。

测试 SessionService 在隔离环境下正确封装 session 生命周期操作。
行为与原 Web handler 完全一致——这是纯重构，无行为变化。

Seams:
- SessionService 的公开方法（list_sessions / get_events / has_session /
  create_and_launch / resume_and_launch / stream_reconnect / cancel /
  resolve_approval / recover）。
- 领域异常（SessionNotFound / ActiveRunConflict / InvalidSessionId / 等）
  在正确的场景下被抛出。
"""

from __future__ import annotations

import pytest

from agent_harness.session import USER_MESSAGE, Session
from agent_harness.session.service import (
    ActiveRunConflict,
    ApprovalQueueMissing,
    ApprovalRequestMissing,
    InvalidDecision,
    InvalidSessionId,
    RecoveryConflict,
    SessionNotFound,
    SessionService,
    SessionServiceError,
    WorkspaceNameInvalid,
)
from agent_harness.session.store import SessionSummaryStats

# ── 异常层级 ──────────────────────────────────────────────────────────


class TestExceptionHierarchy:
    """所有领域异常都继承 SessionServiceError，便于调用方统一 catch。"""

    @pytest.mark.parametrize("exc_class", [
        SessionNotFound,
        InvalidSessionId,
        ActiveRunConflict,
        ApprovalQueueMissing,
        ApprovalRequestMissing,
        InvalidDecision,
        RecoveryConflict,
        WorkspaceNameInvalid,
    ])
    def test_inherits_session_service_error(self, exc_class):
        assert issubclass(exc_class, SessionServiceError)


# ── SessionService 实例化 + 属性透传 ─────────────────────────────────


class TestServiceConstruction:
    def test_exposes_store_and_run_manager(self, app_state):
        """SessionService 正确透传 AppState 的核心属性。"""
        service = SessionService(app_state)
        assert service.store is app_state.store
        assert service.run_manager is app_state.run_manager
        assert service.approval_queues is app_state.approval_queues
        assert service.workspaces_root is app_state.workspaces_root
        assert service.settings is app_state.settings
        assert service.workspace_registry is app_state.workspace_registry


# ── session_id 安全校验 ──────────────────────────────────────────────


class TestSessionIdValidation:
    """session_id 含路径分隔符 / 绝对路径 / 点点时必须拒绝。"""

    @pytest.mark.parametrize("bad_id", [
        "../etc/passwd",
        "..",
        "C:\\Users\\me",
        "/absolute/path",
        "a/b",
        "a\\b",
    ])
    @pytest.mark.asyncio
    async def test_get_events_rejects_unsafe_id(self, app_state, bad_id):
        service = SessionService(app_state)
        with pytest.raises(InvalidSessionId):
            await service.get_events(bad_id)

    @pytest.mark.asyncio
    async def test_has_session_rejects_unsafe_id(self, app_state):
        service = SessionService(app_state)
        with pytest.raises(InvalidSessionId):
            await service.has_session("../etc/passwd")

    @pytest.mark.asyncio
    async def test_cancel_rejects_unsafe_id(self, app_state):
        service = SessionService(app_state)
        with pytest.raises(InvalidSessionId):
            await service.cancel("../etc/passwd")


# ── get_events / has_session ──────────────────────────────────────────


class TestReadOperations:
    @pytest.mark.asyncio
    async def test_get_events_raises_not_found_for_missing(self, app_state):
        service = SessionService(app_state)
        with pytest.raises(SessionNotFound):
            await service.get_events("nonexistent-uuid-here")

    @pytest.mark.asyncio
    async def test_has_session_false_for_missing(self, app_state):
        service = SessionService(app_state)
        result = await service.has_session("nonexistent-uuid-here")
        assert result is False

    @pytest.mark.asyncio
    async def test_has_session_true_for_existing(self, app_state, existing_session):
        service = SessionService(app_state)
        result = await service.has_session(existing_session)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_events_returns_events_for_existing(
        self, app_state, existing_session
    ):
        service = SessionService(app_state)
        events = await service.get_events(existing_session)
        assert len(events) >= 1
        assert events[0].type == "session/started"


# ── list_sessions ────────────────────────────────────────────────────


class TestListSessions:
    @pytest.mark.asyncio
    async def test_empty_when_no_sessions(self, app_state):
        service = SessionService(app_state)
        result = await service.list_sessions()
        assert result == []

    @pytest.mark.asyncio
    async def test_lists_existing_session(self, app_state, existing_session):
        service = SessionService(app_state)
        result = await service.list_sessions()
        assert len(result) == 1
        assert result[0].session_id == existing_session
        assert result[0].event_count >= 1

    @pytest.mark.asyncio
    async def test_returns_domain_dataclass_not_dict(self, app_state, existing_session):
        """ARCH-4：列表行是领域 dataclass（不再是 dict 中转）——类型系统能抓住字段漂移。"""
        service = SessionService(app_state)
        result = await service.list_sessions()
        assert isinstance(result[0], SessionSummaryStats)

    @pytest.mark.asyncio
    async def test_carries_terminal_trace_id(self, app_state, existing_session):
        """OBS-010 + ARCH-4b：列表行回填最近一次 run 终结事件的 trace_id 与 trace_url。"""
        session = Session.resume(app_state.store, existing_session)
        run_id, _ = session.begin_run()
        session.append(USER_MESSAGE, {"content": "hi"}, run_id=run_id)
        session.end_run(run_id, status="completed", final_text="ok",
                        trace_id="tr-list",
                        trace_url="https://lf.example/trace/tr-list")

        service = SessionService(app_state)
        result = await service.list_sessions()
        row = next(r for r in result if r.session_id == existing_session)
        assert (row.trace_id, row.trace_url) == (
            "tr-list", "https://lf.example/trace/tr-list")

    @pytest.mark.asyncio
    async def test_trace_id_none_without_terminal_event(self, app_state, existing_session):
        """只有 session/started（无 run 终态）→ trace_id / trace_url 都为 None，不伪造。"""
        service = SessionService(app_state)
        result = await service.list_sessions()
        row = next(r for r in result if r.session_id == existing_session)
        assert (row.trace_id, row.trace_url) == (None, None)


# ── cancel ───────────────────────────────────────────────────────────


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_raises_not_found_for_missing(self, app_state):
        service = SessionService(app_state)
        with pytest.raises(SessionNotFound):
            await service.cancel("nonexistent-uuid-here")

    @pytest.mark.asyncio
    async def test_cancel_returns_false_when_no_active_run(
        self, app_state, existing_session
    ):
        """没有在途 run 时幂等返回 False。"""
        service = SessionService(app_state)
        result = await service.cancel(existing_session)
        assert result is False


# ── resolve_approval ──────────────────────────────────────────────────


class TestResolveApproval:
    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_session(self, app_state):
        service = SessionService(app_state)
        with pytest.raises(SessionNotFound):
            await service.resolve_approval(
                session_id="nonexistent-uuid-here",
                approval_id="some-id",
            )

    @pytest.mark.asyncio
    async def test_raises_when_no_queue(self, app_state, existing_session):
        """session 存在但没有交互式审批队列 → ApprovalQueueMissing。"""
        service = SessionService(app_state)
        with pytest.raises(ApprovalQueueMissing):
            await service.resolve_approval(
                session_id=existing_session,
                approval_id="some-id",
            )


# ── workspace name 校验 ──────────────────────────────────────────────


class TestWorkspaceNameValidation:
    @pytest.mark.parametrize("bad_name", [
        "../etc",
        "..",
        "C:\\Users\\me",
        "/absolute",
        "a/b",
        "a\\b",
    ])
    def test_workspace_validation_rejects_paths(self, app_state, bad_name):
        """workspace 含路径 → WorkspaceNameInvalid。"""
        service = SessionService(app_state)
        with pytest.raises(WorkspaceNameInvalid):
            service._validate_workspace_name(bad_name)

    def test_workspace_none_returns_none(self, app_state):
        """workspace=None → 返回 None（向后兼容）。"""
        service = SessionService(app_state)
        assert service._validate_workspace_name(None) is None
