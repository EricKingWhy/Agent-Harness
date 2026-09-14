"""Session 层的请求上下文 ContextVar（跨层传 run 归因，不改变 Provider 协议）。

为什么放 session 层：memory / context provider 比 agent 层低，不能反向 import
agent；它们只需要"当前 run 是谁"。runtime 在 begin_run 之后设置，可选消费方
（如 MEMORY_DEGRADED 的 run_id 归因）读取；不读则零影响。
"""

from __future__ import annotations

from contextvars import ContextVar

#: 当前 run 的 id（begin_run 之后有效）；None = 不在 run 上下文中。
run_context_var: ContextVar[str | None] = ContextVar("run_context", default=None)
