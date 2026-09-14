"""OrchestrationAdapter：可插拔编排层接缝（ADR-0015 决策 1；不变量 #20）。

V1 只定义协议位：LangGraph 等图编排器未来以本协议的实现接入（supervisor
路由 / subgraph / interrupt-resume），Agent Loop 与本文件之外的 Core 零改动。
换编排器 = 换 adapter 实现；卸载 = 不配置，单代理照跑。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OrchestrationAdapter(Protocol):
    """图编排器适配协议（LangGraph 或其它）。

    契约（spec §10）：
    - 编排节点 MUST 通过既有 AgentRuntime 执行（不变量 #19），不得自建 Loop；
    - Graph State 只含可序列化字段；
    - Graph Checkpoint MUST NOT 替代 Operation Ledger（恢复单一事实源）；
    - 适配器故障不得拖垮 Core（不变量 #21——Core 路径零依赖本协议）。
    """

    async def run_graph(
        self,
        state: dict[str, Any],
        *,
        delegate: Callable[[str, str, list[str]], Awaitable[Any]],
    ) -> dict[str, Any]:
        """以初始 state 跑一张编排图；delegate(target, task, constraints)
        即 multiagent 的委派能力注入。返回最终 state。"""
        ...
