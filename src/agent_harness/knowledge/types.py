"""Knowledge 域值对象与错误词汇（ADR-0013）。"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 规模防呆上限（ADR-0013 决策 12）：超限显式失败——静默截断会造成
# "以为建全了其实缺半篇"的语料损坏。
MAX_SOURCE_CHARS = 2_000_000
MAX_CHUNKS_PER_SOURCE = 2000

#: citation 前缀（kb:<source_name>#<chunk_index>，ADR-0013 决策 10）。
CITATION_PREFIX = "kb:"


class KnowledgeError(ValueError):
    """Knowledge 域显式错误（输入非法 / citation 不可解析 / 越界）——响亮失败。"""


@dataclass(frozen=True)
class KnowledgeChunk:
    """语料的检索单元：一段文本 + 溯源元数据。"""

    source_id: str
    source_name: str
    chunk_index: int
    content_hash: str
    content: str


@dataclass(frozen=True)
class KnowledgeSource:
    """注册表中的一等实体：chunk 的归属单位、增量判定与 citation 溯源的锚点。"""

    source_id: str
    tenant_id: str
    name: str
    content_hash: str
    chunk_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class KnowledgeHit:
    """一条检索证据：citation 可回读原文，score 如实透传（绝不伪造）。"""

    citation: str
    content: str
    score: float
    source_id: str
    chunk_index: int


@dataclass(frozen=True)
class KnowledgeIngestResult:
    source_id: str
    source_name: str
    chunk_count: int
    status: str  # created / rebuilt / skipped


@dataclass(frozen=True)
class KnowledgeSearchResult:
    query: str
    hits: list[KnowledgeHit] = field(default_factory=list)
    is_sufficient: bool = False


@dataclass(frozen=True)
class KnowledgeReadResult:
    source_name: str
    match: KnowledgeChunk
    context: list[KnowledgeChunk] = field(default_factory=list)
