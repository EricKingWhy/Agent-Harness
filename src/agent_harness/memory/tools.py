"""模型可调用的遗忘工具（#159 AC1–AC4）。

权限不靠 prompt（不变量 #11）：
- `permission = DANGER` —— 硬删不可逆，`needs_approval` 在除 `danger-full-access` 之外的
  所有策略下都为 True；没配 `ApprovalCallback` 时执行器直接拒绝（安全默认值）。
- `side_effect = MUTATING` —— 改外部状态：同批串行、超时后**不自动重试**（不变量 #14；
  不变量由 MUTATING 承担，DANGER 只承担"要不要审批"）。

Namespace 不来自参数（#159 AC3）：参数只有 `memory_id`，`extra="forbid"` 让"顺手塞一个
tenant_id/user_id"这类调用直接变成 INVALID_ARGUMENT，而不是被静默忽略。归属校验在领域层
（`MemoryRecordStore.delete` 的 namespace 匹配）——工具只负责把结果翻译成人话。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent_harness.memory.audit import (
    ENTRY_TOOL,
    OUTCOME_ABSENT,
    OUTCOME_DENIED,
    OUTCOME_FORGOTTEN,
    record_forget,
)
from agent_harness.memory.capability import MemoryCapability
from agent_harness.tooling import Tool, ToolResult, ToolSideEffect
from agent_harness.tooling.contract import ToolPermission
from agent_harness.tooling.reconcile import ReconcileHint
from agent_harness.tooling.result import ErrorCode


class _ForgetMemoryArgs(BaseModel):
    """只接受一个记忆 id。

    `extra="forbid"` 是**安全属性**而不是风格偏好：模型若能通过参数指定 namespace，
    就等于把跨租户删除的漏洞交到模型手里（#159 AC3）。这条约束由测试钉住。
    """

    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(..., min_length=1, description="要遗忘的记忆 id（通常来自检索结果）")


class ForgetMemoryTool(Tool):
    """`forget_memory`：硬删一条记忆（不可逆，必须审批）。"""

    def __init__(self, capability: MemoryCapability) -> None:
        # 依赖**契约**而不是 LangMem 类型：provider 可替换（#159 AC4，seam A / ARCH-6）。
        self._capability = capability

    @property
    def name(self) -> str:
        return "forget_memory"

    @property
    def description(self) -> str:
        return (
            "硬删除一条记忆（不可逆，会同时从检索索引中消失，没有回收站）。"
            "参数：memory_id 是要遗忘的那条记忆的 id（通常来自之前检索到的结果）。"
            "只作用于当前用户的记忆：别人的 id 会被拒绝。"
            "用户明确要求忘记某事时使用；不确定要删哪条时先检索确认。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return _ForgetMemoryArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.MUTATING

    @property
    def permission(self) -> ToolPermission:
        return ToolPermission.DANGER

    @property
    def reconcile_hint(self) -> ReconcileHint:
        return ReconcileHint(
            verifiable=True,
            suggested_action=(
                "读回该 id 或列出记忆核对是否还在：已消失说明删除已生效，仍在说明未执行。"
                "forget 幂等（再删一次返回 absent），重跑安全。"
            ),
        )

    async def execute(self, args: _ForgetMemoryArgs) -> ToolResult:
        try:
            forgotten = await self._capability.forget(args.memory_id)
        except PermissionError:
            # 领域层的归属校验拒绝了（别人的 tenant/user/scope）——返回"可读的拒绝结果"，
            # 不抛异常、也不假装成功。记忆完好无损由领域层保证。
            record_forget(entry_point=ENTRY_TOOL, memory_id=args.memory_id, outcome=OUTCOME_DENIED)
            return ToolResult.failure(
                message=f"记忆 {args.memory_id} 不属于当前用户，未删除。",
                error_code=ErrorCode.PERMISSION_DENIED,
            )

        if not forgotten:
            # 幂等：不存在的 id 不是错误（`forget` 契约），但审计仍要留痕。
            record_forget(entry_point=ENTRY_TOOL, memory_id=args.memory_id, outcome=OUTCOME_ABSENT)
            return ToolResult.success(
                message=f"记忆 {args.memory_id} 不存在（可能已被遗忘），无需处理。",
                data={"memory_id": args.memory_id, "forgotten": False},
            )

        record_forget(entry_point=ENTRY_TOOL, memory_id=args.memory_id, outcome=OUTCOME_FORGOTTEN)
        return ToolResult.success(
            message=f"已遗忘记忆 {args.memory_id}（硬删，不可恢复）。",
            data={"memory_id": args.memory_id, "forgotten": True},
        )
