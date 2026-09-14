"""Web lineage API 测试（Phase 14 T7, #113, ADR-0017 决策 6/10）。

独立 router 文件接入面 + 只读形状契约。app.py 主体零改动（仅一行注册）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_harness.config import Settings
from agent_harness.session import Session
from agent_harness.session.event import (
    AGENT_DELEGATION_STARTED,
    USER_MESSAGE,
)
from agent_harness.web.app import create_app


def _client(tmp_path):
    settings = Settings(workspace_dir=str(tmp_path), model_api_key="sk-test")
    app = create_app(settings, enable_cors=False)
    return TestClient(app)


def _build_family(tmp_path) -> None:
    """r(root) → fork f1（经 meta 行模拟）→ d1（delegation 边）。"""
    settings = Settings(workspace_dir=str(tmp_path), model_api_key="sk-test")
    app = create_app(settings, enable_cors=False)
    store = app.state.agent.store
    meta_store = app.state.agent.session_meta_store

    import asyncio

    async def _seed():
        await meta_store.initialize()
        root = Session.start(store, session_id="r")
        root.append(USER_MESSAGE, {"content": "x"})
        Session.start(store, session_id="f1")
        child = Session.start(store, session_id="d1")
        child.append(USER_MESSAGE, {"content": "delegated"})
        root.append(AGENT_DELEGATION_STARTED, {
            "target": "coding", "task": "t", "child_session_id": "d1",
        })
        # fork 边：直接写 meta（fork 流程的产物形态）
        from agent_harness.storage.session_meta import SessionMeta

        await meta_store.upsert(SessionMeta(
            session_id="f1", created_at="2026-09-06T00:00:02Z",
            parent_session_id="r", origin="fork", fork_point_seq=2,
        ))

    asyncio.run(_seed())


def test_lineage_endpoint_shape(tmp_path) -> None:
    _build_family(tmp_path)
    client = _client(tmp_path)
    resp = client.get("/api/sessions/r/lineage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "r"
    # 惰性回填把 delegation child 挂上；fork child 来自 meta
    child_ids = {c["session_id"] for c in body["children"]}
    assert child_ids == {"f1", "d1"}
    origins = {c["session_id"]: c["origin"] for c in body["children"]}
    assert origins["f1"] == "fork"
    assert origins["d1"] == "delegation"
    assert origins["f1"] and any(
        e["origin"] == "fork" and e["fork_point_seq"] == 2 for e in body["edges"]
    )


def test_lineage_endpoint_ancestors_chain(tmp_path) -> None:
    _build_family(tmp_path)
    client = _client(tmp_path)
    body = client.get("/api/sessions/d1/lineage").json()
    # d1 的祖先链：直接父 r（origin=delegation 是 d1 自己的边语义）
    assert [a["session_id"] for a in body["ancestors"]] == ["r"]
    assert body["ancestors"][0]["origin"] == "delegation"
    assert body["children"] == []


def test_lineage_endpoint_404(tmp_path) -> None:
    _client(tmp_path)
    client = _client(tmp_path)
    resp = client.get("/api/sessions/nonexistent/lineage")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_lineage_endpoint_rejects_path_traversal(tmp_path) -> None:
    client = _client(tmp_path)
    resp = client.get("/api/sessions/..%2F..%2Fetc%2Fpasswd/lineage")
    assert resp.status_code in (400, 404, 422)
