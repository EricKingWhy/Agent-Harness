"""staged amend 数据载体（从 service.py 抽出，消除 model_switch ↔ service 循环）。

``AmendOptions`` 是无状态的纯数据载体，不依赖 ``SessionService`` 实例，也不依赖
session 事件流/配置——把它放在 ``service`` 里会迫使 ``model_switch`` 反向导入
``service``（而 ``service`` 又模块级导入 ``model_switch``），形成双向依赖环。

本模块只有 stdlib 依赖，位于依赖图底层：``model_switch`` 与 ``service`` 均可安全
导入它。``service.py`` 以 facade 形式重新导出，既有导入路径
（``from agent_harness.session.service import AmendOptions``）保持不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["AmendOptions"]


@dataclass(frozen=True)
class AmendOptions:
    """staged amend 字段：续跑/续聊时覆盖运行时可配置项。

    全部可空——None = 使用 session 既有配置（默认行为不变）。
    service 层 create / resume / send_message / drain 共用这一束，
    避免 4 个字段在每个签名里平铺（Data Clump）。
    """

    reasoning_effort: str | None = None
    agent_profile: str | None = None
    context_providers: list[str] | None = None
    model: str | None = None

    @classmethod
    def from_request(cls, request: Any) -> AmendOptions:
        """从请求模型组装（Pydantic 或任何带同名属性的对象）。

        web 层三个请求体（create / resume / messages）字段同形，组装逻辑
        收敛到这里，避免在 app.py 重复三遍。
        """
        return cls(
            reasoning_effort=getattr(request, "reasoning_effort", None),
            agent_profile=getattr(request, "agent_profile", None),
            context_providers=getattr(request, "context_providers", None),
            model=getattr(request, "model", None),
        )

    def to_runtime_kwargs(self) -> dict[str, Any]:
        """转成 ``build_runtime`` 的 amend 相关关键字参数。

        ``model`` → ``model_name``（build_runtime 的参数名）；四个字段总是
        全部给出（None 即默认行为），让调用点无需重复 None 判断。
        """
        return {
            "model_name": self.model,
            "reasoning_effort": self.reasoning_effort,
            "agent_profile": self.agent_profile,
            "context_providers": self.context_providers,
        }


def amend_kwargs(amend: AmendOptions | None) -> dict[str, Any]:
    """amend → build_runtime 关键字参数；None 等价于全 None（当前行为不变）。"""
    return (amend or AmendOptions()).to_runtime_kwargs()
