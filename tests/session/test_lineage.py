"""lineage 树组装 + 惰性回填（Phase 14 T6, #112, ADR-0017 决策 7）。

双层 lineage 的读取侧：事件 = 真相（delegation-started / session/forked）、
SessionMetaStore = 索引。建树 O(1) 查索引；存量会话（Phase 13 delegation
child、checkpoint 时代惰性行）查询时惰性回填，只做 NULL→具体值 的升级，
绝不覆盖既有 origin=fork。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.session import Session
from agent_harness.session.event import (
    AGENT_DELEGATION_FINISHED,
    AGENT_DELEGATION_STARTED,
    USER_MESSAGE,
)
from agent_harness.session.lineage import (
    build_lineage_index,
    build_lineage_tree,
    render_lineage_tree,
)
from agent_harness.session.store import JsonlSessionStore
from agent_harness.storage.session_meta import SessionMeta
from agent_harness.storage.sqlite import SqliteSessionMetaStore

pytestmark = pytest.mark.asyncio


def _meta(sid: str, **overrides: object) -> SessionMeta:
    fields: dict = {"session_id": sid, "created_at": "2026-09-06T00:00:00Z"}
    fields.update(overrides)
    return SessionMeta(**fields)


async def test_build_lineage_index_backfills_delegation_children(tmp_path: Path) -> None:
    """存量 delegation child（有事件无 meta 行 / NULL origin 行）回填为 delegation 边。"""
    store = JsonlSessionStore(tmp_path / "sessions")
    meta_store = SqliteSessionMetaStore(tmp_path / "harness.db")
    await meta_store.initialize()

    # 父会话 P： delegation-started 指向 c1（c1 有事件无 meta 行）
    parent = Session.start(store, session_id="p")
    parent.append(USER_MESSAGE, {"content": "委派任务"})
    parent.append(AGENT_DELEGATION_STARTED, {"target": "coding", "task": "t",
                                             "child_session_id": "c1"})
    parent.append(AGENT_DELEGATION_FINISHED, {"target": "coding", "task": "t",
                                              "child_session_id": "c1",
                                              "status": "completed", "summary": "s"})
    Session.start(store, session_id="c1")  # child 有文件无 meta

    # checkpoint 时代存量：meta 行存在但 origin/parent 全 NULL，实为 delegation child
    await meta_store.upsert(_meta("legacy-child"))
    legacy_parent = Session.start(store, session_id="legacy-parent")
    legacy_parent.append(USER_MESSAGE, {"content": "x"})
    legacy_parent.append(AGENT_DELEGATION_STARTED, {"target": "research_review",
                                                    "task": "t",
                                                    "child_session_id": "legacy-child"})

    metas = await build_lineage_index(store, meta_store)
    by_id = {m.session_id: m for m in metas}

    assert by_id["c1"].origin == "delegation"
    assert by_id["c1"].parent_session_id == "p"
    assert by_id["legacy-child"].origin == "delegation"
    assert by_id["legacy-child"].parent_session_id == "legacy-parent"
    assert by_id["p"].origin is None  # 父是 root
    # 幂等：二次回填不改变结果
    again = await build_lineage_index(store, meta_store)
    by_id2 = {m.session_id: m for m in again}
    assert (by_id2["c1"].origin, by_id2["c1"].parent_session_id) == ("delegation", "p")


async def test_build_lineage_index_never_overwrites_fork_origin(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    meta_store = SqliteSessionMetaStore(tmp_path / "harness.db")
    await meta_store.initialize()
    await meta_store.upsert(
        _meta("forked", parent_session_id="p0", origin="fork", fork_point_seq=3)
    )
    Session.start(store, session_id="forked")
    decoy = Session.start(store, session_id="decoy")
    decoy.append(AGENT_DELEGATION_STARTED, {"target": "coding", "task": "t",
                                            "child_session_id": "forked"})

    metas = await build_lineage_index(store, meta_store)
    by_id = {m.session_id: m for m in metas}
    assert by_id["forked"].origin == "fork"
    assert by_id["forked"].parent_session_id == "p0"


def test_build_lineage_tree_mixed_edges() -> None:
    """fork + delegation 两类边同树：多级、一父多子。"""
    metas = [
        _meta("r1", created_at="2026-09-06T00:00:01Z"),
        _meta("f1", created_at="2026-09-06T00:00:02Z", parent_session_id="r1",
              origin="fork", fork_point_seq=3),
        _meta("d1", created_at="2026-09-06T00:00:03Z", parent_session_id="r1",
              origin="delegation"),
        _meta("g1", created_at="2026-09-06T00:00:04Z", parent_session_id="f1",
              origin="fork", fork_point_seq=1),
    ]
    roots = build_lineage_tree(metas)
    assert len(roots) == 1
    root = roots[0]
    assert root.session_id == "r1"
    assert {c.session_id for c in root.children} == {"f1", "d1"}
    fork_child = next(c for c in root.children if c.session_id == "f1")
    assert fork_child.fork_point_seq == 3
    assert {g.session_id for g in fork_child.children} == {"g1"}


def test_build_lineage_tree_orphan_parent_treated_as_root() -> None:
    """parent 记录缺失：节点按 root 呈现但保留 provenance（明确标注）。"""
    metas = [_meta("lonely", parent_session_id="ghost", origin="fork")]
    roots = build_lineage_tree(metas)
    assert len(roots) == 1
    assert roots[0].session_id == "lonely"
    assert roots[0].parent_link_missing is True


def test_render_lineage_tree_marks_origins() -> None:
    metas = [
        _meta("r1", created_at="2026-09-06T00:00:01Z"),
        _meta("f1", created_at="2026-09-06T00:00:02Z", parent_session_id="r1",
              origin="fork", fork_point_seq=3),
        _meta("d1", created_at="2026-09-06T00:00:03Z", parent_session_id="r1",
              origin="delegation"),
    ]
    roots = build_lineage_tree(metas)
    text = render_lineage_tree(roots)
    assert "r1" in text
    assert "[fork @3]" in text
    assert "[delegation]" in text
    assert "f1" in text and "d1" in text


async def test_sessions_command_tree(tmp_path: Path) -> None:
    """CLI sessions --tree：真实 store + meta 走一遍端到端渲染。"""
    from agent_harness.cli import sessions_command

    store = JsonlSessionStore(tmp_path / "sessions")
    meta_store = SqliteSessionMetaStore(tmp_path / "harness.db")
    await meta_store.initialize()
    parent = Session.start(store, session_id="cliroot")
    parent.append(USER_MESSAGE, {"content": "x"})
    parent.append(AGENT_DELEGATION_STARTED, {"target": "coding", "task": "t",
                                             "child_session_id": "clichild"})
    Session.start(store, session_id="clichild")

    out = await sessions_command(tree=True, workspace_dir=str(tmp_path))
    assert "cliroot" in out
    assert "clichild" in out
    assert "[delegation]" in out
