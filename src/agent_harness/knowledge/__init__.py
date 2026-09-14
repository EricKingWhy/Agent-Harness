"""Knowledge 域（Phase 11，ADR-0013）：显式摄入的文档语料检索。

与 Memory 域平行且互不依赖（CONTEXT.md Knowledge 层）：Memory 是随对话
自动抽取的个性化事实（被动注入），Knowledge 是显式摄入的文档语料（只在
模型调用检索工具时被查询，Agentic RAG）。两域各有独立的向量协议与
Collection，仅共享 Milvus 部署与 embeddings 工厂。
"""

from agent_harness.knowledge.service import KnowledgeService
from agent_harness.knowledge.store import FakeKnowledgeVectorStore, KnowledgeVectorStore
from agent_harness.knowledge.types import (
    MAX_CHUNKS_PER_SOURCE,
    MAX_SOURCE_CHARS,
    KnowledgeChunk,
    KnowledgeError,
    KnowledgeHit,
    KnowledgeIngestResult,
    KnowledgeReadResult,
    KnowledgeSearchResult,
    KnowledgeSource,
)

__all__ = [
    "MAX_CHUNKS_PER_SOURCE",
    "MAX_SOURCE_CHARS",
    "FakeKnowledgeVectorStore",
    "KnowledgeChunk",
    "KnowledgeError",
    "KnowledgeHit",
    "KnowledgeIngestResult",
    "KnowledgeReadResult",
    "KnowledgeSearchResult",
    "KnowledgeService",
    "KnowledgeSource",
    "KnowledgeVectorStore",
]
