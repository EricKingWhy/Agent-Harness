"""#171 后端半：会话归档 / 取消归档 + 列表过滤（AC1–AC6）。

契约矩阵：

| 条件 | `POST .../archive` | `DELETE .../archive` |
| --- | --- | --- |
| 会话不存在（`events.jsonl` 缺失） | 404 `SessionNotFound` | 404 |
| id 形态非法 | 422 `InvalidSessionId` | 422 |
| 有**在途 run**（`RunManager.get_active`） | 409 `ActiveRunConflict` | ——（取消归档不成冲突） |
| 正常 / 已在该状态（幂等） | 200 `{id, archived: true}` | 200 `{id, archived: false}` |

**为什么归档用 `get_active` 而不是删除用的 `is_busy`**：`is_busy` 的额外一半覆盖的是
"task 已 done / terminal 旗标未及置位"的 finalizer 窗口——那个窗口对**硬删**是致命的
（不许在别人还在写日志时抽走地面，ADR-0029 D4）。归档不删任何东西、只写 session_meta
一行标记，那个窗口里归档无副作用，所以按票面用 `get_active`（"确实有一轮在跑"）。

三条口径要点：

1. **列表是文件系统驱动的**（扫 `<root>/<sid>/events.jsonl`），而 `archived` 在 DB
   （`session_meta`）⇒ 过滤必须 join 两边；**`session_meta` 无该行 = 未归档**
   （行由 lineage/fork 懒补，不是 1:1 恒成立）。本文件的
   `test_archive_creates_the_meta_row_lazily_...` 先证明"确实没有行"，再证明归档成功。
2. **归档不动事件日志**（spec 03 的硬约束：Full SessionEvent History MUST 保留）——
   只改列表可见性 + `session_meta` 一行；AC5 用"归档前后事件数逐字相同 + resume 仍成功"
   锁住它。
3. **归档不动项目账本**：与"在哪个项目"是两个正交轴（AC4）；项目视图与默认列表用
   **同一规则**过滤，避免"侧栏藏了、项目里还露着"。

审计（AC6）：一条 `session_archive` 结构化日志，**只带 id 与动作**——会话正文（标题 /
任务文本）一个字都不许进日志；且**不**进 SessionEvent 词汇表（归档不是会话真相，
ADR-0026 同款选择）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from agent_harness.config import Settings
from agent_harness.session.event import EVENT_TYPES as SESSION_EVENT_TYPES
from agent_harness.web.app import SessionSummary, create_app
from agent_harness.web.runmanager import RunManager
from tests.scripted_model import ScriptedModel

_DATA_PREFIX = "data:"

#: 会话标题用的正文——用来证明"审计日志里没有会话内容"（AC6）可证伪。
_SECRET_TASK = "绝密任务文本-171"


def _app(tmp_path: Path, **overrides):
    settings = Settings(
        _env_file=None, workspace_dir=str(tmp_path), model_api_key="sk-test", **overrides
    )
    return create_app(settings, enable_cors=False)


def _client(tmp_path: Path, **overrides) -> TestClient:
    return TestClient(_app(tmp_path, **overrides))


def _create_session(client: TestClient, **payload: object) -> str:
    """建会话（真 runtime + 替身模型），返回 session_id。"""
    base: dict[str, object] = {"task": _SECRET_TASK, "max_steps": 1}
    base.update(payload)
    with patch(
        "agent_harness.assembly.create_chat_model",
        return_value=ScriptedModel(responses=[AIMessage(content="ok")]),
    ):
        resp = client.post("/api/sessions", json=base)
    assert resp.status_code == 200, resp.text
    frames = [
        json.loads(line[len(_DATA_PREFIX) :].strip())
        for line in resp.text.splitlines()
        if line.startswith(_DATA_PREFIX)
    ]
    session_id = next((f["session_id"] for f in frames if f.get("session_id")), None)
    assert session_id, f"SSE 流里没有 session_id：{frames[:3]}"
    return str(session_id)


def _rows(client: TestClient, **params: str) -> list[dict]:
    resp = client.get("/api/sessions", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(client: TestClient, **params: str) -> set[str]:
    return {row["session_id"] for row in _rows(client, **params)}


def _query(client: TestClient, sql: str, args: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(Path(client.app.state.agent.harness_db))
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _execute(client: TestClient, sql: str, args: tuple = ()) -> None:
    con = sqlite3.connect(Path(client.app.state.agent.harness_db))
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def _drop_meta_row(client: TestClient, session_id: str) -> None:
    """把会话的 `session_meta` 行删掉，造出 AC3 说的"无行"状态。

    行是**懒补**的（lineage 建树 / fork 写 provenance / run 存 checkpoint 三处都会补，
    谁也不保证每个会话恒有一行——历史会话就是这样），所以"没有行"是真实可达的状态，
    直接构造它比绕一大圈更诚实。
    """
    _execute(client, "DELETE FROM session_meta WHERE session_id = ?", (session_id,))


def _meta_archived(client: TestClient, session_id: str) -> list[tuple]:
    """该会话在 session_meta 里的 archived 列（**没有行** → 空列表）。"""
    return _query(
        client, "SELECT archived FROM session_meta WHERE session_id = ?", (session_id,)
    )


# ── 契约字段：行必须带 archived（前端徽标的唯一来源）────────────────────


def test_response_model_requires_the_archived_key() -> None:
    """列表行的 `archived` **必填**——漏传必须响亮失败。

    给它默认值（`= False`）的话，将来某个构造点漏传会让"已归档"的行谎报成未归档：
    那是一条**假事实**，且前端徽标会静默消失。与 `workspace` 同一条既有理由
    （`test_session_list_workspace.py::test_response_model_requires_the_workspace_key`）——
    那条测试的注释同时说明了为什么"必填"只锁构造点、真正抓漏映射的还得是断言值的用例
    （本文件的 `test_archive_hides_the_row_and_include_archived_shows_it` 就是那条）。
    """
    with pytest.raises(ValidationError):
        SessionSummary(
            session_id="s",
            event_count=1,
            first_event_time=None,
            last_event_time=None,
            first_user_message=None,
            workspace=None,
        )


# ── AC1/AC2/AC3：归档隐藏 → 开关重现 → 取消归档回到默认 ────────────────


def test_archive_hides_the_row_and_include_archived_shows_it(tmp_path: Path) -> None:
    """AC3：默认列表不含已归档；`include_archived=true` 时照常返回且**带真值徽标**。"""
    client = _client(tmp_path)
    keep = _create_session(client)
    target = _create_session(client)

    # 基线：两行都在，且都如实带 `archived: false`（键恒在）
    rows = {row["session_id"]: row for row in _rows(client)}
    assert rows[target]["archived"] is False
    assert rows[keep]["archived"] is False

    resp = client.post(f"/api/sessions/{target}/archive")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": target, "archived": True}

    # 默认：整行消失（不是"变灰还在"）；开关打开：回来且徽标为真
    assert _ids(client) == {keep}
    with_archived = {row["session_id"]: row for row in _rows(client, include_archived="true")}
    assert set(with_archived) == {keep, target}
    assert with_archived[target]["archived"] is True
    assert with_archived[keep]["archived"] is False, "没归档的行不许被顺手标成已归档"


def test_unarchive_puts_the_row_back(tmp_path: Path) -> None:
    """AC2：取消归档 → 行回到默认列表，响应 `archived: false`。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    assert client.post(f"/api/sessions/{session_id}/archive").status_code == 200
    assert _ids(client) == set()

    resp = client.delete(f"/api/sessions/{session_id}/archive")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": session_id, "archived": False}
    assert _ids(client) == {session_id}


def test_archive_and_unarchive_are_idempotent(tmp_path: Path) -> None:
    """AC1/AC2 的幂等条款：重复归档 / 重复取消都 200，且不重复写行、不反复改状态。"""
    client = _client(tmp_path)
    session_id = _create_session(client)

    for expected in (True, True):
        resp = client.post(f"/api/sessions/{session_id}/archive")
        assert resp.status_code == 200, resp.text
        assert resp.json()["archived"] is expected
    assert _meta_archived(client, session_id) == [(1,)]
    assert _query(
        client, "SELECT COUNT(*) FROM session_meta WHERE session_id = ?", (session_id,)
    ) == [(1,)], "重复归档不许造出第二行"

    for expected in (False, False):
        resp = client.delete(f"/api/sessions/{session_id}/archive")
        assert resp.status_code == 200, resp.text
        assert resp.json()["archived"] is expected
    assert _meta_archived(client, session_id) == [(0,)]


def test_archive_creates_the_meta_row_lazily_and_missing_row_means_not_archived(
    tmp_path: Path,
) -> None:
    """AC3 的口径要点：`session_meta` 无行 = 未归档；归档时把行**懒补**出来。

    先**造出**"没有行"的状态（可能本来是有的：run 存 checkpoint 时会懒补一行），
    否则本用例会退化成"恰好有一行、恰好也能改"的空断言。这条口径不是理论问题——
    `set_archived` 对不存在的行抛 `KeyError`，服务层若不自建行，真机上第一次归档一个
    没有 meta 行的会话就是 500。
    """
    client = _client(tmp_path)
    session_id = _create_session(client)
    _drop_meta_row(client, session_id)
    assert _meta_archived(client, session_id) == [], "前置：此时不该有 session_meta 行"
    assert _ids(client) == {session_id}, "前置：无行 ≠ 已归档（默认列表里必须在）"

    assert client.post(f"/api/sessions/{session_id}/archive").status_code == 200
    assert _meta_archived(client, session_id) == [(1,)]


# ── 错误矩阵：404 / 422 / 409 ─────────────────────────────────────────


def test_archive_unknown_session_is_404(tmp_path: Path) -> None:
    """不存在（没有日志）→ 404，两个动词同一口径。

    **detail 逐字断言**（不只是状态码）：前端 `web/e2e/fixtures.ts` 的归档分支把
    这句话**照抄**进 mock 当"后端原句"用，那边的 e2e 也逐字断言它。后端若改词而这里
    只断状态码，两侧会各自绿着悄悄漂开——集成时才发现"界面显示的原文"根本不是后端
    现在说的那句。文案来自 `SessionNotFound.__str__` 的 `session '<id>' not found`。
    """
    client = _client(tmp_path)
    for method in (client.post, client.delete):
        resp = method("/api/sessions/no-such-session/archive")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "session 'no-such-session' not found"


def test_invalid_session_id_is_422(tmp_path: Path) -> None:
    """形态非法 → 422（路径穿越防线），且**先于** 404——否则 `../x` 会被说成"不存在"。"""
    client = _client(tmp_path)
    for method in (client.post, client.delete):
        resp = method("/api/sessions/bad.id/archive")
        assert resp.status_code == 422, resp.text


def test_archive_refuses_while_a_run_is_in_flight(tmp_path: Path, monkeypatch) -> None:
    """AC1：在途 run → 409，且**什么都没发生**（不是"写了一半才发现忙"）。

    detail 同样逐字断言（理由见 404 那条）：前端 e2e fixture 复制的就是这句话，
    包括 `archive it after it finishes` 这半句——它同时是给用户看的**下一步**
    （等它跑完再归档），改词等于改产品文案。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    before = _meta_archived(client, session_id)  # 建会话可能已懒补过一行 ⇒ 比"不变"
    monkeypatch.setattr(RunManager, "get_active", lambda self, sid: SimpleNamespace())

    resp = client.post(f"/api/sessions/{session_id}/archive")
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == (
        f"session '{session_id}' has a run in flight; archive it after it finishes"
    )
    assert _meta_archived(client, session_id) == before, "拒绝必须不留任何写痕迹"
    assert _ids(client) == {session_id}


def test_unarchive_is_allowed_while_a_run_is_in_flight(tmp_path: Path, monkeypatch) -> None:
    """非对称是刻意的：取消归档只是把行放回列表，不成冲突（AC2 只要求幂等）。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    assert client.post(f"/api/sessions/{session_id}/archive").status_code == 200
    monkeypatch.setattr(RunManager, "get_active", lambda self, sid: SimpleNamespace())

    assert client.delete(f"/api/sessions/{session_id}/archive").status_code == 200
    assert _ids(client) == {session_id}


def test_filter_rejects_non_boolean_switch(tmp_path: Path) -> None:
    """AC3：失效开关值 → 422（沿用 FastAPI 的 bool query 语义，不自造一套）。"""
    client = _client(tmp_path)
    assert client.get("/api/sessions", params={"include_archived": "maybe"}).status_code == 422


# ── AC4：项目视图同口径 + 归档不碰账本 ────────────────────────────────


def test_project_view_uses_the_same_rule_and_archive_keeps_membership(tmp_path: Path) -> None:
    """AC4：项目分组成员列表默认也藏已归档，开关打开时显示；**账本一个字不动**。"""
    client = _client(tmp_path)
    first = _create_session(client, workspace="proj")
    second = _create_session(client, workspace="proj")
    project_id = next(row["workspace"]["id"] for row in _rows(client) if row["workspace"])

    archived_id = first
    assert client.post(f"/api/sessions/{archived_id}/archive").status_code == 200

    assert _ids(client, workspace_id=project_id) == {second}
    with_archived = _ids(client, workspace_id=project_id, include_archived="true")
    assert with_archived == {first, second}

    # 账本（成员关系）与归档正交：归档后该项目仍**拥有**这个会话
    member_ids = next(
        p["session_ids"] for p in client.get("/api/projects").json() if p["id"] == project_id
    )
    assert set(member_ids) == {first, second}


# ── AC5：归档不损坏任何能力（不变量测试）──────────────────────────────


def test_archived_session_still_serves_events_resume_lineage_and_fork(tmp_path: Path) -> None:
    """AC5：归档只改列表可见性——日志一字不动，`/events`、`/resume`、`/lineage`、`/forks` 照常。

    "事件数逐字相同"是这条不变量的**可证伪**部分：归档若误走"移动/重写日志"的实现，
    这里会红。

    隐含没测的一条：`GET /stream`。它需要 `test_web_stream.py` 那套真 uvicorn 车道
    （SSE 分帧），本文件用的是 TestClient；而归档与它**不共享任何状态**——归档只写
    `session_meta`，而 stream 只读事件日志 + `RunManager`，两边无交集（`session_meta`
    在 stream 路径上没有任何读取点），所以这条省略是有依据的边界，不是漏测。
    """
    client = _client(tmp_path)
    session_id = _create_session(client)
    events_before = client.get(f"/api/sessions/{session_id}/events").json()
    assert client.post(f"/api/sessions/{session_id}/archive").status_code == 200

    assert client.get(f"/api/sessions/{session_id}/events").json() == events_before
    assert client.get(f"/api/sessions/{session_id}/lineage").status_code == 200

    with patch(
        "agent_harness.assembly.create_chat_model",
        return_value=ScriptedModel(responses=[AIMessage(content="ok")]),
    ):
        resp = client.post(f"/api/sessions/{session_id}/resume", json={"task": "继续"})
    assert resp.status_code == 200, resp.text
    # resume 之后事件当然变多（新一轮），但归档前的那批前缀逐字保留
    events_after = client.get(f"/api/sessions/{session_id}/events").json()
    assert events_after[: len(events_before)] == events_before
    # 归档态在 resume 之后仍成立（resume 不解除归档）
    assert _meta_archived(client, session_id) == [(1,)]
    assert _ids(client) == set()

    # fork：锚点必须是历史里的 user/message 的 **seq**（契约要求，不是轮次序号）
    anchor = next(
        event["seq"]
        for event in events_before
        if event["type"] == "user/message" and event.get("data", {}).get("content")
    )
    forked = client.post(f"/api/sessions/{session_id}/forks", json={"from_seq": anchor})
    assert forked.status_code == 200, forked.text
    assert forked.json()["session_id"] != session_id


# ── AC6：审计只带 id 与动作，且不进 SessionEvent ──────────────────────


def test_audit_records_id_and_action_without_session_content(
    tmp_path: Path, caplog
) -> None:
    """AC6：`session_archive` 只带 id / 动作 / 入口，会话正文一个字都不进日志。

    正文断言用**可证伪**的构造：建会话用的任务文本是 `_SECRET_TASK`，它必然出现在
    会话日志里；审计日志里若出现同一个字符串，说明有人把内容带进了审计面。
    """
    client = _client(tmp_path)
    session_id = _create_session(client)

    with caplog.at_level(logging.INFO, logger="agent_harness.session.service"):
        assert client.post(f"/api/sessions/{session_id}/archive").status_code == 200

    [record] = [r for r in caplog.records if getattr(r, "event_type", None) == "session_archive"]
    assert record.session_id == session_id
    assert record.archived is True
    assert record.entry_point == "api"
    assert _SECRET_TASK not in caplog.text, "审计日志里不许出现会话内容"

    # 归档不是会话真相：SessionEvent 词汇表里不许有它（有人将来想加，会先撞红这里）
    forbidden = [t for t in SESSION_EVENT_TYPES if "archiv" in t.lower()]
    assert forbidden == []
