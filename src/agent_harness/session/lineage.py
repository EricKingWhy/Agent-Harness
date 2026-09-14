"""lineage 树（Phase 14 T6, ADR-0017 决策 7）：双层模型的读取侧。

事件 = 真相（agent/delegation-started 的 child_session_id、child 文件里的
session/forked），SessionMetaStore = 索引（parent_session_id / origin /
fork_point_seq）。建树查索引 O(1)；索引缺口查询时惰性回填——只做
NULL→具体值 的升级，绝不覆盖既有 origin=fork（fork 语义由 fork 流程独占）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent_harness.session.event import AGENT_DELEGATION_STARTED
from agent_harness.session.store import JsonlSessionStore
from agent_harness.storage.session_meta import SessionMeta, SessionMetaStore


def _scan_edges(
    store: JsonlSessionStore, all_ids: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """同步扫描全部会话事件：delegation 边 + created_at（线程池内执行）。"""
    edges: dict[str, str] = {}  # child_session_id -> parent_session_id
    created_at_by_id: dict[str, str] = {}
    for sid in all_ids:
        events = store.read_events(sid)
        if events:
            created_at_by_id.setdefault(sid, events[0].time)
        for event in events:
            if event.type == AGENT_DELEGATION_STARTED:
                child_id = event.data.get("child_session_id")
                if child_id:
                    edges.setdefault(str(child_id), sid)
    return edges, created_at_by_id


@dataclass
class LineageNode:
    """lineage 树的一个节点（一棵树 = 一个 root 及其后代）。"""

    session_id: str
    created_at: str
    origin: str | None = None
    parent_session_id: str | None = None
    fork_point_seq: int | None = None
    parent_link_missing: bool = False
    children: list[LineageNode] = field(default_factory=list)


async def build_lineage_index(
    store: JsonlSessionStore, meta_store: SessionMetaStore
) -> list[SessionMeta]:
    """惰性回填索引并返回全量行（幂等）。

    缺口来源：Phase 13 的 delegation child（checkpoint 时代可能已有 origin
    全 NULL 的行，或完全没有行）。回填只允许 NULL→delegation 的升级——
    origin=fork 的行永远不动。完全无缺口时零扫描零写入。
    """
    existing = {m.session_id: m for m in await meta_store.list_all()}
    all_ids = store.list_session_ids()
    missing = [sid for sid in all_ids if sid not in existing]
    needs_upgrade = [
        m for m in existing.values()
        if m.origin is None and m.parent_session_id is None
    ]
    if not missing and not needs_upgrade:
        return list(existing.values())

    # 扫描事件真相（同步磁盘 IO 走线程卸载——web 读取面也复用本函数）：
    # delegation-started 边（parent → child_session_id）+ 各会话 created_at
    edges, created_at_by_id = await asyncio.to_thread(
        _scan_edges, store, all_ids
    )

    now = datetime.now(UTC).isoformat(timespec="milliseconds")
    # 缺行的会话：delegation child 按边回填，其余按 root 建行
    for sid in missing:
        if sid in edges:
            await meta_store.upsert(
                SessionMeta(
                    session_id=sid, created_at=created_at_by_id.get(sid, now),
                    parent_session_id=edges[sid], origin="delegation",
                )
            )
        else:
            await meta_store.upsert(
                SessionMeta(
                    session_id=sid, created_at=created_at_by_id.get(sid, now)
                )
            )
    # 已有行但 origin 全 NULL：若是 delegation child，升级为 delegation 边
    for meta in needs_upgrade:
        parent_id = edges.get(meta.session_id)
        if parent_id is not None:
            await meta_store.upsert(
                SessionMeta(
                    session_id=meta.session_id, created_at=meta.created_at,
                    agent_id=meta.agent_id,
                    last_checkpoint_seq=meta.last_checkpoint_seq,
                    archived=meta.archived,
                    parent_session_id=parent_id, origin="delegation",
                    fork_point_seq=meta.fork_point_seq,
                )
            )
    return await meta_store.list_all()


def build_lineage_tree(metas: list[SessionMeta]) -> list[LineageNode]:
    """索引行 → 树（O(n)）。parent 缺失的节点按 root 呈现但保留 provenance。"""
    nodes = {
        m.session_id: LineageNode(
            session_id=m.session_id, created_at=m.created_at, origin=m.origin,
            parent_session_id=m.parent_session_id,
            fork_point_seq=m.fork_point_seq,
        )
        for m in metas
    }
    roots: list[LineageNode] = []
    for node in nodes.values():
        parent = (
            nodes.get(node.parent_session_id)
            if node.parent_session_id is not None
            else None
        )
        if parent is None:
            # root：无父，或 parent 行缺失（orphan——provenance 保留在字段里）
            node.parent_link_missing = node.parent_session_id is not None
            roots.append(node)
        else:
            parent.children.append(node)
    roots.sort(key=lambda n: (n.created_at, n.session_id))
    for node in nodes.values():
        node.children.sort(key=lambda n: (n.created_at, n.session_id))
    return roots


def render_lineage_tree(roots: list[LineageNode]) -> str:
    """ASCII 树渲染（origin 标注：[fork @seq] / [delegation]）。"""
    lines: list[str] = []

    def _walk(node: LineageNode, prefix: str, is_last: bool, is_root: bool) -> None:
        if is_root:
            lines.append(f"{node.session_id} (root)")
        else:
            connector = "└── " if is_last else "├── "
            tag = ""
            if node.origin == "fork":
                tag = f" [fork @{node.fork_point_seq if node.fork_point_seq is not None else '?'}]"
            elif node.origin == "delegation":
                tag = " [delegation]"
            orphan = " (parent missing)" if node.parent_link_missing else ""
            lines.append(f"{prefix}{connector}{node.session_id}{tag}{orphan}")
        child_prefix = "" if is_root else prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(node.children):
            _walk(child, child_prefix, i == len(node.children) - 1, False)

    for root in roots:
        _walk(root, "", True, True)
    return "\n".join(lines)
