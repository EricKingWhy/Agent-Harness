"""ToolExecutor approval gate 测试：PermissionPolicy + 审批关卡 + per-call scoping。

测试缝 2（见 spec）：构造 ToolRegistry + ToolExecutor（带 policy/callback），
构造 tool_call dict 喂给 execute()，断言 ToolResult。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.tooling import (
    ApprovalRequest,
    ApprovalResponse,
    ErrorCode,
    PermissionPolicy,
    ToolExecutor,
    ToolRegistry,
)
from agent_harness.tools import BashTool, ReadTool, WriteTool


@pytest.fixture
def sandbox(tmp_path: Path) -> LocalSubprocessSandbox:
    return LocalSubprocessSandbox(workspace_root=tmp_path)


def _registry(sandbox: LocalSubprocessSandbox) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ReadTool(sandbox))
    reg.register(WriteTool(sandbox))
    reg.register(BashTool(sandbox))
    return reg


def _tc(name: str, args: dict, call_id: str = "c1") -> dict:
    return {"id": call_id, "name": name, "args": args}


async def _auto_approve(_req: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse(approved=True, reason="auto-approve")


async def _auto_deny(_req: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse(approved=False, reason="auto-deny")


# ============================================================================
# DANGER_FULL_ACCESS policy
# ============================================================================


class TestDangerFullAccess:
    @pytest.mark.asyncio
    async def test_bash_without_callback(self, sandbox: LocalSubprocessSandbox):
        """DANGER_FULL_ACCESS → bash(DANGER) 无需审批，无 callback 也放行。"""
        executor = ToolExecutor(
            _registry(sandbox), policy=PermissionPolicy.DANGER_FULL_ACCESS
        )
        result = await executor.execute(_tc("bash", {"command": "echo hi"}))

        assert result.result.ok is True
        assert "hi" in result.result.data["stdout"]


# ============================================================================
# WORKSPACE_WRITE policy（默认）
# ============================================================================


class TestWorkspaceWritePolicy:
    @pytest.mark.asyncio
    async def test_read_allowed(self, sandbox: LocalSubprocessSandbox):
        """WORKSPACE_WRITE + read(READ_ONLY) → 放行。"""
        sandbox.write_text("f.txt", "content")
        executor = ToolExecutor(_registry(sandbox))
        result = await executor.execute(_tc("read", {"path": "f.txt"}))

        assert result.result.ok is True

    @pytest.mark.asyncio
    async def test_write_allowed(self, sandbox: LocalSubprocessSandbox):
        """WORKSPACE_WRITE + write(WORKSPACE_WRITE) → 放行。"""
        executor = ToolExecutor(_registry(sandbox))
        result = await executor.execute(
            _tc("write", {"path": "f.txt", "content": "x"})
        )

        assert result.result.ok is True

    @pytest.mark.asyncio
    async def test_bash_denied_without_callback(
        self, sandbox: LocalSubprocessSandbox
    ):
        """WORKSPACE_WRITE + bash(DANGER) + 无 callback → PERMISSION_DENIED。"""
        executor = ToolExecutor(_registry(sandbox))
        result = await executor.execute(_tc("bash", {"command": "echo hi"}))

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_bash_approved_with_callback(
        self, sandbox: LocalSubprocessSandbox
    ):
        """WORKSPACE_WRITE + bash(DANGER) + auto-approve → 执行成功。"""
        executor = ToolExecutor(
            _registry(sandbox),
            approval_callback=_auto_approve,
        )
        result = await executor.execute(_tc("bash", {"command": "echo hi"}))

        assert result.result.ok is True
        assert "hi" in result.result.data["stdout"]

    @pytest.mark.asyncio
    async def test_bash_denied_with_deny_callback(
        self, sandbox: LocalSubprocessSandbox
    ):
        """WORKSPACE_WRITE + bash(DANGER) + auto-deny → PERMISSION_DENIED。"""
        executor = ToolExecutor(
            _registry(sandbox),
            approval_callback=_auto_deny,
        )
        result = await executor.execute(_tc("bash", {"command": "echo hi"}))

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.PERMISSION_DENIED


# ============================================================================
# READ_ONLY policy
# ============================================================================


class TestReadOnlyPolicy:
    @pytest.mark.asyncio
    async def test_read_allowed(self, sandbox: LocalSubprocessSandbox):
        """READ_ONLY + read(READ_ONLY) → 放行。"""
        sandbox.write_text("f.txt", "content")
        executor = ToolExecutor(
            _registry(sandbox), policy=PermissionPolicy.READ_ONLY
        )
        result = await executor.execute(_tc("read", {"path": "f.txt"}))

        assert result.result.ok is True

    @pytest.mark.asyncio
    async def test_write_denied(self, sandbox: LocalSubprocessSandbox):
        """READ_ONLY + write(WORKSPACE_WRITE) → PERMISSION_DENIED（超级别）。"""
        executor = ToolExecutor(
            _registry(sandbox), policy=PermissionPolicy.READ_ONLY
        )
        result = await executor.execute(
            _tc("write", {"path": "f.txt", "content": "x"})
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_bash_denied(self, sandbox: LocalSubprocessSandbox):
        """READ_ONLY + bash(DANGER) → PERMISSION_DENIED。"""
        executor = ToolExecutor(
            _registry(sandbox), policy=PermissionPolicy.READ_ONLY
        )
        result = await executor.execute(_tc("bash", {"command": "echo hi"}))

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.PERMISSION_DENIED


# ============================================================================
# Per-call scoping（核心安全不变量）
# ============================================================================


class TestPerCallScoping:
    @pytest.mark.asyncio
    async def test_each_call_independently_checked(
        self, sandbox: LocalSubprocessSandbox
    ):
        """连续两次 bash + auto-approve → callback 被调两次，两次都成功。

        核心不变量：审批只对当次生效，不存在"一次批准后第二次跳过审批"。
        """
        call_count = 0

        async def counting_approve(_req: ApprovalRequest) -> ApprovalResponse:
            nonlocal call_count
            call_count += 1
            return ApprovalResponse(approved=True)

        executor = ToolExecutor(
            _registry(sandbox),
            approval_callback=counting_approve,
        )

        await executor.execute(_tc("bash", {"command": "echo a"}, "c1"))
        await executor.execute(_tc("bash", {"command": "echo b"}, "c2"))

        # callback 被调了两次——每次 execute 都独立审批
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_approval_request_contains_correct_info(
        self, sandbox: LocalSubprocessSandbox
    ):
        """ApprovalRequest 包含正确的 tool_name/args/permission/policy/reason。"""
        captured: list[ApprovalRequest] = []

        async def capturing(req: ApprovalRequest) -> ApprovalResponse:
            captured.append(req)
            return ApprovalResponse(approved=True)

        executor = ToolExecutor(
            _registry(sandbox),
            approval_callback=capturing,
        )
        await executor.execute(
            _tc("bash", {"command": "rm -rf /tmp/test"}, "call_99")
        )

        assert len(captured) == 1
        req = captured[0]
        assert req.tool_name == "bash"
        assert req.args == {"command": "rm -rf /tmp/test"}
        assert req.policy == PermissionPolicy.WORKSPACE_WRITE
        assert "danger" in req.reason.lower() or "审批" in req.reason
