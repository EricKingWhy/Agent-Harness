"""Approval 类型：审批关卡的数据模型。

05_SANDBOX_CODING_TOOLS.md §6 的 REQUIRE_APPROVAL 机制：
- ApprovalRequest：ToolExecutor 在执行高风险 Tool 前产生的审批请求。
- ApprovalResponse：人类（或自动 callback）的批准/拒绝决定。
- ApprovalCallback：可插拔的审批接口（CLI / Web UI / 自动批准 / 自动拒绝）。

审批只针对当次 Tool Call（per-call scoping 由设计保证：
每次 execute 都独立检查，不存储任何"已批准"状态）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

from agent_harness.tooling.contract import PermissionPolicy, ToolPermission


class PermissionDecision(str, Enum):
    """审批决策的四种粒度（03_RUNTIME_EVENT_CONTRACT.md §9 PermissionDecision）。

    当前 runtime 只兑现 deny / approve_once（per-call scoping，不存状态）。
    approve_session / approve_policy 留后续批次（需要 session 级授权缓存）。
    """

    DENY = "deny"
    APPROVE_ONCE = "approve_once"
    APPROVE_SESSION = "approve_session"
    APPROVE_POLICY = "approve_policy"


@dataclass(frozen=True)
class ApprovalRequest:
    """ToolExecutor 向审批方发出的请求。

    包含足够让人类做判断的信息：工具名、参数、授权级别、当前策略、风险原因，
    以及 tool_call_id（前端把审批事件与随后的 tool/call + tool/result 配对用）。
    """

    tool_name: str
    args: dict
    permission: ToolPermission
    policy: PermissionPolicy
    reason: str
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ApprovalResponse:
    """审批方的决定。

    approved 是兼容字段（现有 runtime 读它决定放行/拒绝）。
    decision 是 spec 契约（03 §9 PermissionDecision），用于审计 trail。
    不传 decision 时由 __post_init__ 从 approved 推导（True→approve_once，
    False→deny）。后续批次支持 approve_session/approve_policy 时显式传 decision。
    """

    approved: bool
    reason: str = ""
    decision: PermissionDecision | None = None

    def __post_init__(self) -> None:
        if self.decision is None:
            # frozen dataclass：用 object.__setattr__ 在 post_init 里设默认
            object.__setattr__(
                self, "decision",
                PermissionDecision.APPROVE_ONCE if self.approved else PermissionDecision.DENY,
            )


#: 可插拔审批回调：接收 ApprovalRequest，返回 ApprovalResponse。
#: 不提供时 ToolExecutor 对超级别或 DANGER 级别默认拒绝（安全默认值）。
#:
#: Phase 5：async 化以支持交互式审批（run 暂停等外部 /approve 决策）。
ApprovalCallback = Callable[[ApprovalRequest], Awaitable[ApprovalResponse]]


def needs_approval(
    tool_permission: ToolPermission, policy: PermissionPolicy
) -> bool:
    """检查工具的授权级别是否超出 Session 当前策略允许的范围。

    层级关系：READ_ONLY ≤ WORKSPACE_WRITE ≤ DANGER_FULL_ACCESS（policy），
    对应 READ_ONLY ≤ WORKSPACE_WRITE ≤ DANGER（tool permission）。

    policy 覆盖范围内的工具直接放行，超出范围的需审批：
    - DANGER_FULL_ACCESS → 任何工具都放行。
    - WORKSPACE_WRITE → READ_ONLY 和 WORKSPACE_WRITE 放行，DANGER 需审批。
    - READ_ONLY → 只有 READ_ONLY 放行，WORKSPACE_WRITE 和 DANGER 需审批。
    """
    if policy == PermissionPolicy.DANGER_FULL_ACCESS:
        return False

    if tool_permission == ToolPermission.READ_ONLY:
        return False

    if tool_permission == ToolPermission.WORKSPACE_WRITE:
        # WORKSPACE_WRITE 工具在 WORKSPACE_WRITE policy 下放行，在 READ_ONLY 下需审批
        return policy == PermissionPolicy.READ_ONLY

    # tool_permission == DANGER：在非 DANGER_FULL_ACCESS policy 下都需审批
    return True


def approval_reason(
    tool_permission: ToolPermission, policy: PermissionPolicy
) -> str:
    """生成人类可读的审批原因。"""
    if policy == PermissionPolicy.READ_ONLY:
        return f"工具授权级别为 {tool_permission.value}，但当前策略为只读（{policy.value}），操作被拒绝。"
    return f"工具授权级别为 {tool_permission.value}，当前策略为 {policy.value}，此操作需要审批。"
