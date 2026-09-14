"""遗忘工具（#159 A）：权限声明、审批闸门、归属翻译、审计留痕。

本文件钉的都是"不能靠 prompt 约束"的那些点（不变量 #11）——所以断言打在
**ToolExecutor 的真实执行路径**上（DANGER + 未配审批回调 → 拒绝），而不是"工具自己说自己
需要审批"。
"""

import logging

import pytest
from pydantic import ValidationError

from agent_harness.identity import (
    IdentityContext,
    identity_context_var,
    set_identity_context,
)
from agent_harness.memory.fake_capability import FakeMemoryCapability
from agent_harness.memory.tools import ForgetMemoryTool, _ForgetMemoryArgs
from agent_harness.memory.types import MemoryScope
from agent_harness.tooling import (
    ApprovalRequest,
    ApprovalResponse,
    ErrorCode,
    PermissionPolicy,
    ToolExecutor,
    ToolPermission,
    ToolRegistry,
    ToolSideEffect,
)


def _tc(memory_id: str, call_id: str = "c1") -> dict:
    """Executor 的 tool_call 形状（与 `tests/tooling/test_approval_gate.py` 同款）。"""
    return {"id": call_id, "name": "forget_memory", "args": {"memory_id": memory_id}}


ALICE = IdentityContext("acme", "alice", ["user"])
BOB = IdentityContext("acme", "bob", ["user"])


def _tool(capability=None) -> ForgetMemoryTool:
    return ForgetMemoryTool(capability or FakeMemoryCapability())


def _executor(tool: ForgetMemoryTool, **kwargs) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(tool)
    return ToolExecutor(registry, **kwargs)


class TestPermissionDeclaration:
    """AC1：权限必须在 Runtime 侧声明，且分类正确。"""

    def test_declares_danger_and_mutating(self):
        tool = _tool()
        assert tool.permission is ToolPermission.DANGER
        # MUTATING 承担"同批串行 + 超时后不自动重试"（不变量 #14）；DANGER 只承担审批。
        assert tool.side_effect is ToolSideEffect.MUTATING

    def test_arguments_accept_only_a_memory_id(self):
        """AC3：参数里不得接受任意 namespace——多塞一个字段直接是非法参数。"""
        assert set(_ForgetMemoryArgs.model_fields) == {"memory_id"}
        with pytest.raises(ValidationError):
            _ForgetMemoryArgs(memory_id="m1", tenant_id="other")


@pytest.mark.asyncio
async def test_danger_tool_is_denied_without_an_approval_callback(tmp_path):
    """AC1 的安全默认值：没有 ApprovalCallback 时**默认拒绝**，记忆必须原样在。"""
    capability = FakeMemoryCapability()
    token = set_identity_context(ALICE)
    try:
        memory_id = await capability.store(MemoryScope.USER, "alice 的偏好", {})
    finally:
        identity_context_var.reset(token)

    executor = _executor(_tool(capability), policy=PermissionPolicy.WORKSPACE_WRITE)
    result = (await executor.execute(_tc(memory_id))).result

    assert result.ok is False
    assert result.error_code is ErrorCode.PERMISSION_DENIED
    assert "审批" in result.message
    token = set_identity_context(ALICE)
    try:
        assert (await capability.list_entries(MemoryScope.USER, 10))[0].id == memory_id  # 没被删
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_denied_approval_leaves_the_memory_untouched():
    """AC2：审批被拒绝时工具根本没执行——返回可读拒绝结果，记忆未删。"""
    capability = FakeMemoryCapability()
    token = set_identity_context(ALICE)
    try:
        memory_id = await capability.store(MemoryScope.USER, "alice 的偏好", {})
    finally:
        identity_context_var.reset(token)

    async def deny(_req: ApprovalRequest) -> ApprovalResponse:
        return ApprovalResponse(approved=False, reason="用户拒绝")

    executor = _executor(_tool(capability), policy=PermissionPolicy.WORKSPACE_WRITE,
                         approval_callback=deny)
    result = (await executor.execute(_tc(memory_id))).result

    assert result.ok is False
    assert result.error_code is ErrorCode.PERMISSION_DENIED
    token = set_identity_context(ALICE)
    try:
        assert [entry.id for entry in await capability.list_entries(MemoryScope.USER, 10)] == [memory_id]
    finally:
        identity_context_var.reset(token)


@pytest.mark.asyncio
async def test_approved_call_really_forgets():
    """AC2 的正面：审批通过后删除真的发生（走的是同一个领域动词）。"""
    capability = FakeMemoryCapability()
    token = set_identity_context(ALICE)
    try:
        memory_id = await capability.store(MemoryScope.USER, "alice 的偏好", {})
    finally:
        identity_context_var.reset(token)

    async def approve(_req: ApprovalRequest) -> ApprovalResponse:
        return ApprovalResponse(approved=True, reason="用户同意")

    executor = _executor(_tool(capability), policy=PermissionPolicy.WORKSPACE_WRITE,
                         approval_callback=approve)
    # 工具真的执行时必须在身份上下文里（生产由 middleware / run 任务绑定；这里显式绑定，
    # 否则默认身份是 local/local，删 acme/alice 的记忆会被领域层正确地拒绝）。
    token = set_identity_context(ALICE)
    try:
        result = (await executor.execute(_tc(memory_id))).result
        assert result.ok is True
        assert result.data == {"memory_id": memory_id, "forgotten": True}
        assert await capability.list_entries(MemoryScope.USER, 10) == []
    finally:
        identity_context_var.reset(token)


class TestOwnershipTranslation:
    @pytest.mark.asyncio
    async def test_forgetting_someone_elses_memory_is_refused_readably(self):
        """AC3：别人的 id 被领域层拒绝 → 工具返回可读的拒绝结果，且对方的记忆完好。"""
        capability = FakeMemoryCapability()
        token = set_identity_context(BOB)
        try:
            bob_memory = await capability.store(MemoryScope.USER, "bob 的秘密", {})
        finally:
            identity_context_var.reset(token)

        token = set_identity_context(ALICE)
        try:
            result = await _tool(capability).execute(_ForgetMemoryArgs(memory_id=bob_memory))
        finally:
            identity_context_var.reset(token)

        assert result.ok is False
        assert result.error_code is not None and result.error_code.value == "PERMISSION_DENIED"
        assert bob_memory in result.message
        token = set_identity_context(BOB)
        try:
            assert [entry.id for entry in await capability.list_entries(MemoryScope.USER, 10)] == [bob_memory]
        finally:
            identity_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_unknown_id_is_a_readable_no_op_not_an_error(self):
        """幂等：不存在的 id 不是错误（`forget` 契约），但要如实告诉模型"没这条"。"""
        token = set_identity_context(ALICE)
        try:
            result = await _tool().execute(_ForgetMemoryArgs(memory_id="ghost"))
        finally:
            identity_context_var.reset(token)

        assert result.ok is True
        assert result.data == {"memory_id": "ghost", "forgotten": False}
        assert "不存在" in result.message


class TestAudit:
    """AC8：审计落 memory 侧结构化日志，且**不进** SessionEvent。"""

    @pytest.mark.asyncio
    async def test_forget_writes_a_structured_audit_line(self, caplog):
        capability = FakeMemoryCapability()
        token = set_identity_context(ALICE)
        try:
            memory_id = await capability.store(MemoryScope.USER, "alice 的偏好", {})
            with caplog.at_level(logging.INFO, logger="agent_harness.memory.audit"):
                await _tool(capability).execute(_ForgetMemoryArgs(memory_id=memory_id))
        finally:
            identity_context_var.reset(token)

        [record] = [r for r in caplog.records if getattr(r, "event_type", None) == "memory_forget"]
        assert record.memory_id == memory_id
        assert record.entry_point == "tool"
        assert record.outcome == "forgotten"
        assert record.tenant_id == "acme" and record.user_id == "alice"
        # 审计里不得出现记忆正文（只回答"谁动了哪条"）。
        assert "alice 的偏好" not in caplog.text

    @pytest.mark.asyncio
    async def test_denied_and_absent_attempts_are_audited_too(self, caplog):
        """"模型说要忘、其实什么都没发生"正是最需要查出来的情况——三态都要留痕。"""
        capability = FakeMemoryCapability()
        token = set_identity_context(BOB)
        try:
            bob_memory = await capability.store(MemoryScope.USER, "bob 的秘密", {})
        finally:
            identity_context_var.reset(token)

        token = set_identity_context(ALICE)
        try:
            with caplog.at_level(logging.INFO, logger="agent_harness.memory.audit"):
                await _tool(capability).execute(_ForgetMemoryArgs(memory_id=bob_memory))  # denied
                await _tool(capability).execute(_ForgetMemoryArgs(memory_id="ghost"))  # absent
        finally:
            identity_context_var.reset(token)

        outcomes = [r.outcome for r in caplog.records if getattr(r, "event_type", None) == "memory_forget"]
        assert outcomes == ["denied", "absent"]
