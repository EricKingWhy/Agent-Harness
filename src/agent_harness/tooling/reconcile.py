"""ReconcileHint：Tool 对"我怎么验证自己是否成功执行"的封装。

为什么放在 tooling 而不是 recovery：
- Tool ABC 要提供 reconcile_hint 安全默认值，依赖方向必须是 tooling ← recovery；
- hint 是 Tool 契约的元数据（与 side_effect / permission 同类），不是恢复编排逻辑。

安全语义（spec 07 §7 + 不变量 #14）：
- 默认 unverifiable——安全默认即 NEED_RECONCILE；
- hint 只是给 ReconcileCallback 的【建议】数据：协调器永不自动验证、永不自动重跑。
"""

from __future__ import annotations

from pydantic import BaseModel


class ReconcileHint(BaseModel):
    """一次 UNKNOWN Operation 的可验证性提示（供 ReconcileCallback 参考）。"""

    verifiable: bool = False
    suggested_action: str | None = None
