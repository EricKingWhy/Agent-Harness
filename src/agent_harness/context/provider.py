"""Capability 提供按预算选择的 Context；Phase 6 实现具体 Provider。"""

from typing import Protocol

from langchain_core.messages import AnyMessage

from agent_harness.session import Session


class ContextProvider(Protocol):
    async def select(self, session: Session, token_budget: int) -> list[AnyMessage]: ...
