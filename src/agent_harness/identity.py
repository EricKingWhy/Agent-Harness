"""请求级身份；由可信入口绑定，Runtime 签名保持不变。"""

from collections.abc import Sequence
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IdentityContext:
    tenant_id: str
    user_id: str
    scopes: Sequence[str]

    def __post_init__(self) -> None:
        # ContextVar 子任务继承同一身份对象，权限集合也必须不可变。
        object.__setattr__(self, "scopes", tuple(self.scopes))


identity_context_var: ContextVar[IdentityContext | None] = ContextVar("identity", default=None)


def get_identity_context() -> IdentityContext:
    return identity_context_var.get() or IdentityContext("local", "local", ["user", "session"])


def set_identity_context(ctx: IdentityContext) -> Token:
    return identity_context_var.set(ctx)
