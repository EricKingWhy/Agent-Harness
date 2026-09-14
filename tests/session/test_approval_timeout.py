"""T6 fail-closed：审批等待超时 → 默认拒绝（PRD #136 唯一未交付项）。

规格：`docs/integration/PRD_PHASE_MULTITURN_BACKEND.md` §2.2 C
「fail-closed：超时默认拒绝」+ §2.3 验收「审批 fail-closed（超时默认拒绝）」。

接缝：直接驱动 `_InteractiveCallbackHolder` + `PendingApprovalQueue`（不需要
真服务器；超时用 0.05s 而非默认 300s）。**不盲重跑**：超时是拒绝，不是放行。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agent_harness.config import Settings
from agent_harness.session.service import (
    SessionService,
    _InteractiveCallbackHolder,
)
from agent_harness.tooling.approval import (
    ApprovalRequest,
    ApprovalResponse,
    PermissionDecision,
)
from agent_harness.tooling.approval_queue import PendingApprovalQueue
from agent_harness.tooling.contract import PermissionPolicy, ToolPermission


def _request() -> ApprovalRequest:
    return ApprovalRequest(
        tool_name="bash",
        args={"command": "echo hi"},
        permission=ToolPermission.DANGER,
        policy=PermissionPolicy.WORKSPACE_WRITE,
        reason="danger 工具超出 workspace-write 策略",
        tool_call_id="call-1",
    )


def _mock_session() -> MagicMock:
    """审批 callback 只用到 session.session_id 与 session.append。"""
    session = MagicMock()
    session.session_id = "sess-1"
    return session


class _LateResolveQueue(PendingApprovalQueue):
    """复现竞态：/approve 在 wait_for 取消 future 的窗口内抢先写入决策。

    真实时序里 wait_for 先取消 future 再抛 TimeoutError，两者之间外部 /approve
    可能已 resolve()。这里用假 wait_for 确定性地构造该时序。
    """

    async def wait_for(self, approval_id: str, timeout: float | None = None):
        self.resolve(approval_id, ApprovalResponse(approved=True, reason="human"))
        raise TimeoutError


class TestFailClosedTimeout:
    """超时 → deny + 记 permission/resolved + 清理 pending。"""

    def test_timeout_denies_and_emits_resolved(self):
        queue = PendingApprovalQueue()
        holder = _InteractiveCallbackHolder(queue=queue, timeout_seconds=0.05)
        session = _mock_session()
        holder.bind_session(session)

        response = asyncio.run(holder(_request()))

        assert response.approved is False
        assert response.decision is PermissionDecision.DENY
        assert "超时" in response.reason
        assert "fail-closed" in response.reason
        assert queue.pending_ids() == [], "超时后不得残留 pending（防泄漏 / 防迟到 resolve）"

        # 两次 append：approval-requested → permission/resolved(deny)
        assert session.append.call_count == 2
        resolved_type, resolved_data = session.append.call_args.args
        assert resolved_type == "permission/resolved"
        assert resolved_data["decision"] == "deny"
        assert "超时" in resolved_data["reason"]

    def test_late_resolve_after_timeout_is_rejected(self):
        """一次性语义：超时已裁决 → 迟到 /approve 拿 409（queue 层 KeyError）。"""
        queue = PendingApprovalQueue()
        holder = _InteractiveCallbackHolder(queue=queue, timeout_seconds=0.05)
        session = _mock_session()
        holder.bind_session(session)

        asyncio.run(holder(_request()))
        approval_id = session.append.call_args_list[0].args[1]["approval_id"]

        with pytest.raises(KeyError):
            queue.resolve(approval_id, ApprovalResponse(approved=True))

    def test_late_resolve_in_cancel_window_wins(self):
        """竞态兜底：/approve 已抢先裁决时不覆盖人类决策，resolved 事件与之一致。"""
        queue = _LateResolveQueue()
        holder = _InteractiveCallbackHolder(queue=queue, timeout_seconds=0.05)
        session = _mock_session()
        holder.bind_session(session)

        response = asyncio.run(holder(_request()))

        assert response.approved is True
        assert response.decision is PermissionDecision.APPROVE_ONCE
        resolved_data = session.append.call_args.args[1]
        assert resolved_data["decision"] == "approve_once"

    def test_resolve_before_timeout_wins(self):
        """正常路径不被超时破坏：先 resolve → 用人类决策。"""
        queue = PendingApprovalQueue()
        holder = _InteractiveCallbackHolder(queue=queue, timeout_seconds=5.0)
        session = _mock_session()
        holder.bind_session(session)

        async def _drive() -> ApprovalResponse:
            task = asyncio.create_task(holder(_request()))
            while not queue.pending_ids():
                await asyncio.sleep(0)
            approval_id = queue.pending_ids()[0]
            queue.resolve(approval_id, ApprovalResponse(approved=True, reason="ok"))
            return await task

        response = asyncio.run(_drive())

        assert response.approved is True
        assert response.decision is PermissionDecision.APPROVE_ONCE

    def test_zero_timeout_keeps_waiting_behavior(self):
        """timeout=0 → 关闭 fail-closed（无限等待），人类决策仍生效。"""
        queue = PendingApprovalQueue()
        holder = _InteractiveCallbackHolder(queue=queue, timeout_seconds=0)
        holder.bind_session(_mock_session())

        async def _drive() -> ApprovalResponse:
            task = asyncio.create_task(holder(_request()))
            while not queue.pending_ids():
                await asyncio.sleep(0)
            queue.resolve(
                queue.pending_ids()[0],
                ApprovalResponse(approved=True, reason="ok"),
            )
            return await task

        response = asyncio.run(_drive())

        assert response.approved is True
        assert response.decision is PermissionDecision.APPROVE_ONCE


class TestQueueExpire:
    """`PendingApprovalQueue.expire`：超时裁决的队列原语。"""

    def test_expire_moves_to_resolved_and_clears_pending(self):
        async def _run() -> None:
            queue = PendingApprovalQueue()
            approval_id = queue.register(_request())
            deny = ApprovalResponse(
                approved=False, reason="approval timeout (fail-closed)"
            )

            assert queue.expire(approval_id, deny) is True
            assert queue.pending_ids() == []
            assert await queue.wait_for(approval_id) is deny
            assert queue.expire(approval_id, deny) is False  # 二次 expire 幂等失败

        asyncio.run(_run())

    def test_resolve_after_expire_raises(self):
        async def _run() -> None:
            queue = PendingApprovalQueue()
            approval_id = queue.register(_request())
            queue.expire(
                approval_id, ApprovalResponse(approved=False, reason="timeout")
            )

            with pytest.raises(KeyError):
                queue.resolve(approval_id, ApprovalResponse(approved=True))

        asyncio.run(_run())

    def test_resolved_response_reads_expire_and_resolve(self):
        async def _run() -> None:
            queue = PendingApprovalQueue()
            assert queue.resolved_response("missing") is None

            expired_id = queue.register(_request())
            deny = ApprovalResponse(approved=False, reason="timeout")
            queue.expire(expired_id, deny)
            assert queue.resolved_response(expired_id) is deny

            resolved_id = queue.register(_request())
            allow = ApprovalResponse(approved=True, reason="human")
            queue.resolve(resolved_id, allow)
            assert queue.resolved_response(resolved_id) is allow

        asyncio.run(_run())


class TestTimeoutConfig:
    """配置接线：默认 fail-closed + `_build_approval_callback` 真的用上它。"""

    def test_default_setting_is_fail_closed(self):
        settings = Settings(_env_file=None)
        assert settings.approval_timeout_seconds > 0, "默认必须开启 fail-closed"

    def test_build_approval_callback_passes_configured_timeout(self, tmp_path):
        state = MagicMock()
        state.settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path),
            model_api_key="sk-test",
            approval_timeout_seconds=12.5,
        )
        state.approval_queues = {}
        service = SessionService(state)

        callback = asyncio.run(
            service._build_approval_callback(
                interactive=True,
                auto_approve_explicit=False,
                permission_mode_explicit=True,
                auto_approve=False,
                session_id="sess-1",
            )
        )

        assert isinstance(callback, _InteractiveCallbackHolder)
        assert callback._timeout == 12.5
