"""递归字符切分（ADR-0013 决策 5）：stdlib 自实现，不引 LangChain text-splitter。"""

from __future__ import annotations

from agent_harness.knowledge.types import KnowledgeError

_SEPARATORS = ("\n\n", "\n", "。", ".", " ", "")


def split_text(
    text: str, *, chunk_size: int = 800, overlap: int = 100
) -> list[str]:
    """把文本切成 ≤ chunk_size 的块，相邻块携带 overlap 尾部保持边界语义。

    算法：先按分隔符从大到小递归拆成 ≤ chunk_size 的原子片段（超长片段按
    字符硬切），再贪心合并；合并放不下时 emits 当前块、携带其尾部 overlap
    作为下块前缀（carry + 片段仍超限时放弃 overlap——overlap 是尽力而为，
    内容绝不截断丢失）。
    """
    if chunk_size <= 0:
        raise KnowledgeError(f"chunk_size 必须为正：{chunk_size}")
    if overlap < 0 or overlap >= chunk_size:
        raise KnowledgeError(
            f"overlap 必须在 [0, chunk_size) 内：overlap={overlap}, chunk_size={chunk_size}"
        )

    pieces = _atomic_pieces(text, chunk_size)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > chunk_size:
            chunks.append(current)
            carry = current[-overlap:] if overlap else ""
            current = carry + piece if len(carry) + len(piece) <= chunk_size else piece
        else:
            current = current + piece if current else piece
    if current.strip():
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def _atomic_pieces(text: str, chunk_size: int) -> list[str]:
    pieces: list[str] = [text]
    for separator in _SEPARATORS:
        if all(len(piece) <= chunk_size for piece in pieces):
            break
        split: list[str] = []
        for piece in pieces:
            if len(piece) <= chunk_size:
                split.append(piece)
            elif separator:
                split.extend(piece.split(separator))
            else:
                split.extend(
                    piece[i : i + chunk_size] for i in range(0, len(piece), chunk_size)
                )
        pieces = split
    return [piece for piece in pieces if piece.strip()]
