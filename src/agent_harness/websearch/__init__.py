"""Web Search 域（Phase 12，ADR-0014）。

统一检索协议 RetrievalProvider 让 Knowledge 与 Web 平行（各自实现策略类）；
WebSearchProvider 是 Web 域专用协议（实现 RetrievalProvider 的 search）；
Tavily 默认 provider 见 tavily.py；Fake 见 fake.py（CI 零依赖）。
"""

from agent_harness.websearch.protocol import (
    RetrievalHit,
    RetrievalProvider,
    WebHit,
    WebSearchError,
    WebSearchProvider,
)

__all__ = [
    "RetrievalHit",
    "RetrievalProvider",
    "WebHit",
    "WebSearchError",
    "WebSearchProvider",
]
