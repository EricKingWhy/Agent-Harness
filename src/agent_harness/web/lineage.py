"""Web lineage API（Phase 14 T7, #113, ADR-0017 决策 6/10）。

只读 lineage 查询面 + （T7 #137 起）fork 创建面。**独立 router 文件**：
本阶段 app.py 正被流式改造（ADR-0016）重刀，注册只经 create_app 里的一行
调用接入——把冲突面压到最小。fork 创建原为 CLI-only（ADR 决策 6），
T7 #137 按 PRD §2.4 重新启用 Web 端点，实现仍复用 `session/fork.py`。

形状（前端消费契约）：
{
  "session_id": ...,
  "ancestors": [{"session_id", "origin", "fork_point_seq"} ...],  # 顶层祖先 → 直接父
  "children":  [{"session_id", "origin", "fork_point_seq", "created_at"} ...],
  "edges":     [{"from", "to", "origin", "fork_point_seq"} ...],  # 收集到的全部边
}
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException
from pydantic import BaseModel, Field

from agent_harness.session.lineage import (
    LineageNode,
    build_lineage_index,
    build_lineage_tree,
)
from agent_harness.session.service import (
    ActiveRunConflict,
    InvalidForkBoundary,
    InvalidSessionId,
    SessionNotFound,
    SessionService,
)
from agent_harness.web.domain_errors import http_error

if TYPE_CHECKING:
    from fastapi import FastAPI


class ForkRequest(BaseModel):
    """POST /api/sessions/{id}/forks 的请求体（T7 #137，PRD §2.4）。

    from_seq 是父会话中用户消息的 seq（fork 锚点，锚点消息不进 child）。
    """

    from_seq: int = Field(ge=0)


def register_lineage_routes(
    app: FastAPI, *, validate_session_id: Callable[[str], str]
) -> None:
    """把 lineage 路由挂到既有 app（app.py 侧一行调用的接入面）。"""

    @app.get("/api/sessions/{session_id}/lineage")
    async def get_session_lineage(session_id: str) -> dict:
        validate_session_id(session_id)
        state = app.state.agent
        await state.ensure_stores()
        metas = await build_lineage_index(state.store, state.session_meta_store)
        by_id = {m.session_id: m for m in metas}
        if session_id not in by_id:
            raise HTTPException(
                status_code=404, detail=f"session '{session_id}' not found"
            )
        roots = build_lineage_tree(metas)

        # 定位目标节点：树上找，孤儿/缺口节点也在 roots 里
        target = _find(roots, session_id)
        assert target is not None  # by_id 已含 session_id，树必含节点

        # 祖先链（顶层 → 直接父）+ 后代（直接子件）；edges 覆盖收集到的全部边
        ancestors: list[dict] = []
        node = target
        while node.parent_session_id is not None:
            parent = _find(roots, node.parent_session_id)
            if parent is None:
                break  # orphan：链在此截断（provenance 仍在本节点字段里）
            ancestors.insert(0, {
                "session_id": parent.session_id,
                "origin": node.origin,
                "fork_point_seq": node.fork_point_seq,
            })
            node = parent
        descendants: list[dict] = []
        edges: list[dict] = []

        def _collect(n: LineageNode) -> None:
            for child in n.children:
                descendants.append({
                    "session_id": child.session_id,
                    "origin": child.origin,
                    "fork_point_seq": child.fork_point_seq,
                    "created_at": child.created_at,
                })
                edges.append({
                    "from": n.session_id, "to": child.session_id,
                    "origin": child.origin,
                    "fork_point_seq": child.fork_point_seq,
                })
                _collect(child)

        _collect(target)
        return {
            "session_id": session_id,
            "ancestors": ancestors,
            "children": descendants,
            "edges": edges,
        }

    @app.post("/api/sessions/{session_id}/forks")
    async def fork_session(session_id: str, req: ForkRequest) -> dict:
        """从历史用户消息 seq 派生 child session（T7 #137，PRD §2.4）。

        404 = session 不存在；409 = 在途 run（历史未 settled）；
        422 = from_seq 不是合法 fork 锚点。
        """
        service = SessionService(app.state.agent)
        try:
            child_id = await service.fork(
                session_id=session_id, from_seq=req.from_seq
            )
        except (
            InvalidSessionId,
            SessionNotFound,
            ActiveRunConflict,
            InvalidForkBoundary,
        ) as e:
            raise http_error(e) from e
        return {"session_id": child_id, "from_seq": req.from_seq}


def _find(roots: list[LineageNode], session_id: str) -> LineageNode | None:
    for root in roots:
        found = _find_in(root, session_id)
        if found is not None:
            return found
    return None


def _find_in(node: LineageNode, session_id: str) -> LineageNode | None:
    if node.session_id == session_id:
        return node
    for child in node.children:
        found = _find_in(child, session_id)
        if found is not None:
            return found
    return None
