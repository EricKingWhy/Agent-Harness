"""Reconcile 契约：UNKNOWN Operation 的人工裁决接口（#30）。

与 ApprovalCallback（Phase 3，事前授权）平行——ReconcileCallback 是
【事后裁决】（CONTEXT.md）：崩溃后副作用是否已发生 Ledger 无法判定，
用户拿到 Operation 全上下文返回显式裁决。

为什么是 async ABC 而不是 Callable：裁决可能要等真实用户输入
（CLI 阻塞读入 / Web UI 等 HTTP 回传），天然异步；具名契约比裸 Callable
更利于 Runtime 装配与测试替身。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from agent_harness.storage import Operation
from agent_harness.tooling import ReconcileHint


class ReconcileVerdict(str, Enum):
    """用户对 UNKNOWN Operation 的四种显式裁决（07 §6/§7）。

    RETRY 只能来自用户裁决：协调器任何自动路径都不得产生 retryable=True 的
    恢复结果（不变量 #14——UNKNOWN 高风险副作用不盲重跑）。
    """

    CONFIRM_SUCCESS = "CONFIRM_SUCCESS"  # 副作用已确认发生且符合预期 → SUCCEEDED
    CONFIRM_FAILURE = "CONFIRM_FAILURE"  # 副作用已确认失败/未达预期 → FAILED
    RETRY = "RETRY"  # 用户知情选择重跑：原调用终止，模型重新发起新 tool_call
    ABANDON = "ABANDON"  # 用户放弃：显式取消，不重跑


class ReconcileCallback(ABC):
    """Resume 时遇到 UNKNOWN / NEED_RECONCILE Operation 调用的用户裁决回调。

    实现方拿到 Operation 全上下文（tool_call_id / tool_name / args_identity /
    Ledger 状态）与 Tool 的 ReconcileHint（仅建议，Runtime 不自动执行验证），
    返回一个 ReconcileVerdict。没有 callback 时 RecoveryCoordinator 安全拒绝
    恢复，绝不伪造结果或盲目重跑。
    """

    @abstractmethod
    async def resolve(
        self, operation: Operation, hint: ReconcileHint
    ) -> ReconcileVerdict:
        """对一个 NEED_RECONCILE 的 Operation 返回用户的显式裁决。"""
