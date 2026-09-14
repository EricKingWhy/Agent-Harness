"""#172 后端半：`DELETE /api/sessions/{id}` —— 用户显式硬删会话（ADR-0029）。

契约矩阵（ADR-0029 D4）：

| 条件 | 结果 |
| --- | --- |
| 会话不存在（无 `events.jsonl`） | 404 `SessionNotFound` |
| id 形态非法（含 `.` `/` 等） | 422 `InvalidSessionId` |
| 有 **fork 子会话** | 409（detail 带子会话数量；不级联、不静默 orphan） |
| 在途 run | 409 `ActiveRunConflict` |
| 正常 | 200 `{id, deleted, events, detached_from_projects}` |

**安全红线（ADR-0029 D2）**：删除面是**白名单**——只删 harness 用 `workspace_dir + session_id`
自己拼出来的三条路径（`sessions/<sid>/`、`workspaces/<sid>.json`、`workspaces/<sid>/`），
**永不读映射里的 `workspace_root`**（ADR-0027 之后它可能是用户的真实仓库）。
对应回归锁：`test_cwd_session_delete_never_touches_the_user_directory`。

顺序契约（ADR-0029 D3）：先删 DB 行、后删文件；每步幂等，**重跑即自愈**
（`test_rerun_heals_the_crash_window_where_db_rows_are_already_gone`）。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent_harness.config import Settings
from agent_harness.web.app import create_app
from agent_harness.web.runmanager import RunManager
from tests.scripted_model import ScriptedModel

_DATA_PREFIX = "data:"


def _app(tmp_path: Path, **overrides):
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        **overrides,
    )
    return create_app(settings, enable_cors=False)


def _client(tmp_path: Path, **overrides) -> TestClient:
    return TestClient(_app(tmp_path, **overrides))


def _create_session(client: TestClient, **payload: object) -> str:
    """建会话（真 runtime + 替身模型），返回 session_id。"""
    base: dict[str, object] = {"task": "hi", "max_steps": 1}
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


def _db_path(client: TestClient) -> Path:
    return Path(client.app.state.agent.harness_db)


def _query(client: TestClient, sql: str, args: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(_db_path(client))
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _seed_aux_rows(client: TestClient, session_id: str) -> None:
    """插三条**辅助表**的行，让"删干净了"这句话有可证伪的内容。

    真实跑一个 scripted 会话未必写出 checkpoint / operation 行，直接断言"删后为 0"
    会**假绿**（0 == 0 本来就没有东西可删）。所以先按真实 schema 造出行来，并在
    删除前**证实**每个面都至少有一行——`OR IGNORE` 是为了不与真 run 已经写下的行
    （例如 seq=1 的 USER_ACCEPTED checkpoint，表上有唯一约束）撞车。
    """
    tables = ("session_meta", "operations", "checkpoints")
    con = sqlite3.connect(_db_path(client))
    try:
        con.execute(
            "INSERT OR REPLACE INTO session_meta (session_id, created_at) VALUES (?, ?)",
            (session_id, "2026-09-13T00:00:00+00:00"),
        )
        con.execute(
            "INSERT OR IGNORE INTO operations"
            " (tool_call_id, session_id, tool_name, args_identity, state)"
            " VALUES (?, ?, ?, ?, 'PENDING')",
            ("call_seed", session_id, "read", "{}"),
        )
        con.execute(
            "INSERT OR IGNORE INTO checkpoints"
            " (session_id, boundary_type, event_seq, created_at)"
            " VALUES (?, 'USER_ACCEPTED', 1, ?)",
            (session_id, "2026-09-13T00:00:00+00:00"),
        )
        con.commit()
        counts = {
            table: con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            for table in tables
        }
    finally:
        con.close()
    assert all(n > 0 for n in counts.values()), f"辅助行没造出来：{counts}"


# ── 主路径：删干净 + 计数正确 ───────────────────────────────────────


def test_delete_removes_log_aux_rows_and_sandbox_artifacts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    session_id = _create_session(client)
    _seed_aux_rows(client, session_id)

    sessions_root = Path(client.app.state.agent.sessions_root)
    workspaces_root = Path(client.app.state.agent.workspaces_root)
    assert (sessions_root / session_id / "events.jsonl").is_file()
    assert (workspaces_root / f"{session_id}.json").is_file()
    assert (workspaces_root / session_id).is_dir()

    before = client.get(f"/api/sessions/{session_id}/events")
    assert before.status_code == 200, before.text
    event_count = len(before.json())

    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == session_id
    assert body["deleted"] is True
    # 计数不是装饰：前端要用它写"已删除 N 条事件、从 M 个项目解除"的确认回执
    assert body["events"] == event_count
    assert body["detached_from_projects"] == 0

    # 文件面
    assert not (sessions_root / session_id).exists()
    assert not (workspaces_root / f"{session_id}.json").exists()
    assert not (workspaces_root / session_id).exists()
    # DB 面（四个含 session_id 的表）
    assert _query(client, "SELECT 1 FROM session_meta WHERE session_id=?", (session_id,)) == []
    assert _query(client, "SELECT 1 FROM operations WHERE session_id=?", (session_id,)) == []
    assert _query(client, "SELECT 1 FROM checkpoints WHERE session_id=?", (session_id,)) == []
    assert _query(client, "SELECT 1 FROM workspace_sessions WHERE session_id=?", (session_id,)) == []
    # 列表面（文件系统驱动）
    rows = client.get("/api/sessions").json()
    assert all(r["session_id"] != session_id for r in rows)


def test_delete_detaches_from_project_but_keeps_the_project(tmp_path: Path) -> None:
    """项目成员资格只解账本：项目本身、目录都不许动（与软删项目的口径一致）。"""
    client = _client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    project = client.post("/api/projects", json={"path": str(repo)})
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]
    session_id = _create_session(client, cwd=str(repo))

    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["detached_from_projects"] == 1

    after = client.get(f"/api/projects/{project_id}")
    assert after.status_code == 200, after.text
    assert after.json()["session_ids"] == []
    assert repo.is_dir()  # 项目目录一个字没动


def test_events_count_reflects_what_was_actually_deleted(tmp_path: Path) -> None:
    """`events` 必须是**删除前**日志里的事件条数，而不是 0 / 常量。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    n = len(client.get(f"/api/sessions/{session_id}/events").json())
    assert n > 0
    assert client.delete(f"/api/sessions/{session_id}").json()["events"] == n


# ── 安全红线：绝不碰用户的真实目录（ADR-0029 D2）────────────────────


def test_cwd_session_delete_never_touches_the_user_directory(tmp_path: Path) -> None:
    """**回归锁**：cwd 会话的删除**绝不能** `rmtree` 用户的仓库。

    `WorkspaceRegistry.delete()` 会 `shutil.rmtree(mapping["workspace_root"])`，而
    ADR-0027 之后那个值可以是用户的任意真实目录——所以硬删路径不许调用它。
    这条测试就是那条红线的钉子：目录必须存在、内容必须逐字节不变。
    """
    client = _client(tmp_path)
    user_dir = tmp_path / "my-precious-repo"
    user_dir.mkdir()
    (user_dir / "main.py").write_text("print('do not delete me')\n", encoding="utf-8")
    nested = user_dir / "src"
    nested.mkdir()
    (nested / "a.py").write_text("A = 1\n", encoding="utf-8")

    session_id = _create_session(client, cwd=str(user_dir))
    # 映射里记的确实是用户目录（否则这条测试没测到东西）
    mapping = json.loads(
        (Path(client.app.state.agent.workspaces_root) / f"{session_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert Path(mapping["workspace_root"]) == user_dir.resolve()

    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 200, resp.text

    assert user_dir.is_dir(), "用户目录被删了——这正是 ADR-0029 D2 禁止的事"
    assert (user_dir / "main.py").read_text(encoding="utf-8") == "print('do not delete me')\n"
    assert (nested / "a.py").read_text(encoding="utf-8") == "A = 1\n"
    # harness 自己的字节照删
    assert not (Path(client.app.state.agent.sessions_root) / session_id).exists()
    assert not (Path(client.app.state.agent.workspaces_root) / f"{session_id}.json").exists()


# ── 错误矩阵 ────────────────────────────────────────────────────────


def test_delete_unknown_session_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.delete("/api/sessions/does-not-exist-0000")
    assert resp.status_code == 404, resp.text


def test_delete_invalid_session_id_is_422(tmp_path: Path) -> None:
    """形态校验是路径穿越防线的第一道：`.` / `\\` / NUL / 空格 一律 422。

    两种落点都要钉住，因为它们是**两道不同的防线**：

    - 走到形态校验的（`a.b` / `%20` / `%2E%2E` / `a%5Cb` / `%00`）→ 服务端 422。
      `%2E%2E` 是"服务端真的看见了 `..`"的测法（写 `..` 会被 httpx 在发送前规范化掉）；
      `a%5Cb` 是 win32 的反斜杠穿越，正则注释里点名的那个向量。
    - 连路由都没匹配上的（`..` → 被规范化成父目录、`a%2Fb` → 解码出真分隔符）→ 404。
      这里放宽断言（不是 200 即可）：安全属性是"什么都没发生"，不必钉住第三方库的
      规范化细节。

    落点是 `sessions_root` 仍然空——四道防线之外，这一步本身就是"没留下任何痕迹"的证明。
    """
    client = _client(tmp_path)
    sessions_root = Path(client.app.state.agent.sessions_root)
    for bad, expected in (
        ("a.b", 422),
        ("%20", 422),
        ("%2E%2E", 422),
        ("a%5Cb", 422),
        ("%00", 422),
        ("..", {404, 422}),
        ("a%2Fb", {404, 422}),
    ):
        resp = client.delete(f"/api/sessions/{bad}")
        allowed = {expected} if isinstance(expected, int) else expected
        assert resp.status_code in allowed, (bad, resp.status_code, resp.text)
    assert list(sessions_root.iterdir()) == []


def test_delete_refuses_when_run_is_busy(tmp_path: Path, monkeypatch) -> None:
    """在途 run → 409：不许在别人还在写日志时抽走地面。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    monkeypatch.setattr(RunManager, "is_busy", lambda self, sid: True)

    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 409, resp.text
    # 拒绝必须是"什么都没发生"，不能是"删了一半才发现忙"
    assert (Path(client.app.state.agent.sessions_root) / session_id / "events.jsonl").is_file()


class _PendingQueue:
    """只有 `pending_ids()` 的替身——守卫问的就是这一句。

    不造真的 `PendingApprovalQueue`：登记一个待审批会立刻 `create_future()`，因此
    **要求调用方已经在事件循环里**（脱离循环构造会在 pytest 的 loop 策略下抛
    `RuntimeError: no current event loop`，纯属测试自己的环境问题）。被测的是"有挂起项
    → 拒绝"这一句，替身比真身更准也更稳。
    """

    def pending_ids(self) -> list[str]:
        return ["approval-1"]


def test_delete_refuses_when_an_approval_is_pending(tmp_path: Path, monkeypatch) -> None:
    """挂起审批 → 409，即使 `RunManager` 已经说"不在途"。

    #172 要求这两道守卫**都要**：审批队列由 run 的 done-callback 弹出，那个回调可能
    滞后于 task 收尾，所以只靠 `is_busy` 会在那个滞后窗口里把一个"还有人等着被批准"
    的会话判成可删（这里把 `is_busy` 强制为 False，正是在模拟那个窗口）。
    """
    client = _client(tmp_path)
    session_id = _create_session(client)
    monkeypatch.setattr(RunManager, "is_busy", lambda self, sid: False)
    client.app.state.agent.approval_queues[session_id] = _PendingQueue()

    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 409, resp.text
    assert (
        Path(client.app.state.agent.sessions_root) / session_id / "events.jsonl"
    ).is_file()


def _insert_child(
    client: TestClient, parent: str, child: str, origin: str | None
) -> None:
    """插一条子会话行（照 `fork.py` / `lineage.py` 的真实形状）。"""
    con = sqlite3.connect(_db_path(client))
    try:
        con.execute(
            "INSERT OR REPLACE INTO session_meta"
            " (session_id, created_at, parent_session_id, origin) VALUES (?, ?, ?, ?)",
            (child, "2026-09-13T00:00:00+00:00", parent, origin),
        )
        con.commit()
    finally:
        con.close()


def test_delete_refuses_when_session_has_fork_children(tmp_path: Path) -> None:
    """有 fork 子会话 → 409 且 detail 里是**真实数量**（不是常量、不是 id 里的数字）。

    造**两个**子会话：断言用正则从文案里抠出数量再比 2——只写 `"1" in detail` 会因为
    父 id 是 UUID（自带数字）而在数量算错时照样通过，那是假绿。
    """
    client = _client(tmp_path)
    parent = _create_session(client)
    _insert_child(client, parent, "child-1", "fork")
    _insert_child(client, parent, "child-2", "fork")

    resp = client.delete(f"/api/sessions/{parent}")
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    found = re.search(r"fork parent of (\d+) session", detail)
    assert found is not None, detail
    assert found.group(1) == "2", detail
    assert (Path(client.app.state.agent.sessions_root) / parent / "events.jsonl").is_file()


def test_delete_can_remove_a_parent_of_delegation_children(tmp_path: Path) -> None:
    """**委派**子会话（内部子 Agent）不阻止删除——ADR-0029 D5 的取舍。

    判定靠 `origin`，而委派行的 origin 是 `"delegation"`（`lineage.py` 回填）：
    若不看这一列，任何用过子 Agent 的会话都会**在有人点开过家谱图之后**突然删不掉。

    代价与**补偿**都要钉住：该条父子边随父日志消失（子会话此后显示为根），所以删除
    必须**顺手清掉子行的父链接**——否则它指着死父，`build_lineage_tree` 会渲染成
    `(parent missing)`，而那条边永远无法自愈（`_scan_edges` 只能从父日志推出来）。
    """
    client = _client(tmp_path)
    parent = _create_session(client)
    _insert_child(client, parent, "delegated-1", "delegation")

    resp = client.delete(f"/api/sessions/{parent}")
    assert resp.status_code == 200, resp.text
    assert not (Path(client.app.state.agent.sessions_root) / parent).exists()

    child = _query(
        client,
        "SELECT parent_session_id, origin FROM session_meta WHERE session_id = ?",
        ("delegated-1",),
    )
    assert child == [(None, None)], "子行还指着已删的父——就是那个永远无法自愈的悬空链接"
    # 子会话本身仍然存在（不级联删除），只是回到了"根"
    assert client.get("/api/sessions/delegated-1/lineage").json()["ancestors"] == []


def test_delete_refuses_when_a_child_row_has_no_origin(tmp_path: Path) -> None:
    """父不为 NULL 但 origin 也为 NULL 的行（产品不该产出）→ **保守拒绝**。

    与委派相反的方向：形状无法识别时宁可让用户先去处理子会话，也不留悬空父链接。
    """
    client = _client(tmp_path)
    parent = _create_session(client)
    _insert_child(client, parent, "mystery-1", None)

    resp = client.delete(f"/api/sessions/{parent}")
    assert resp.status_code == 409, resp.text


def test_delete_is_blocked_by_origin_gate(tmp_path: Path) -> None:
    """本地信任模式下跨源请求被来源闸拒绝（与项目 / 记忆端点共用同一条规则）。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    resp = client.delete(
        f"/api/sessions/{session_id}", headers={"Origin": "http://evil.example"}
    )
    assert resp.status_code == 403, resp.text
    assert (Path(client.app.state.agent.sessions_root) / session_id / "events.jsonl").is_file()


# ── 幂等 / 崩溃窗口自愈（ADR-0029 D3）────────────────────────────────


def test_rerun_heals_the_crash_window_where_db_rows_are_already_gone(tmp_path: Path) -> None:
    """"DB 已删、文件还在"是唯一可自愈的崩溃窗口——重跑必须收敛。

    顺序契约（D3）就是为了这个：先删 DB 行、后删文件；若在这中间崩了，会话仍可见
    （列表是文件系统驱动的），用户再删一次即可完成。反过来（文件先删）会留下
    **无法自愈**的孤儿 `session_meta` 行 + lineage 幽灵父节点。
    """
    client = _client(tmp_path)
    session_id = _create_session(client)
    sessions_root = Path(client.app.state.agent.sessions_root)
    workspaces_root = Path(client.app.state.agent.workspaces_root)

    # 手工模拟"DB 行已删、文件还在"的中途状态
    con = sqlite3.connect(_db_path(client))
    try:
        con.execute("DELETE FROM session_meta WHERE session_id=?", (session_id,))
        con.execute("DELETE FROM checkpoints WHERE session_id=?", (session_id,))
        con.execute("DELETE FROM operations WHERE session_id=?", (session_id,))
        con.commit()
    finally:
        con.close()
    assert (sessions_root / session_id / "events.jsonl").is_file()

    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 200, resp.text
    assert not (sessions_root / session_id).exists()
    assert not (workspaces_root / f"{session_id}.json").exists()
    assert not (workspaces_root / session_id).exists()


def test_second_delete_after_success_is_404(tmp_path: Path) -> None:
    """真删完之后它就不存在了——第二次是 404，不是幂等 200（不伪装成"又删了一次"）。"""
    client = _client(tmp_path)
    session_id = _create_session(client)
    assert client.delete(f"/api/sessions/{session_id}").status_code == 200
    assert client.delete(f"/api/sessions/{session_id}").status_code == 404


# ── RunManager.is_busy：为什么不能复用 get_active（ADR-0029 D4）──────


def test_is_busy_covers_the_finalizer_window_that_get_active_ignores() -> None:
    """`get_active` 把"task 已 done / terminal 未及置位"的收尾窗口视为**非**在途；
    删除的前置必须是更严格的 `is_busy`——那个窗口正是 finalizer 还在跑的时刻。
    """
    rm = RunManager(disconnect_grace_seconds=1.0)
    assert rm.is_busy("s") is False  # 没有 run

    # terminal 已置位、task 仍未 done → get_active 说"不在途"，is_busy 必须说"忙"
    rm._runs["s"] = SimpleNamespace(terminal=True, task=SimpleNamespace(done=lambda: False))
    assert rm.get_active("s") is None
    assert rm.is_busy("s") is True

    # task 已 done → 两条判据一致：不忙
    rm._runs["s"] = SimpleNamespace(terminal=True, task=SimpleNamespace(done=lambda: True))
    assert rm.is_busy("s") is False

    # task 尚未挂上（launch 与赋值之间）→ 保守视为忙
    rm._runs["s"] = SimpleNamespace(terminal=False, task=None)
    assert rm.is_busy("s") is True


def test_hard_delete_discards_local_artifacts(tmp_path: Path) -> None:
    """硬删连带丢弃该会话的**本地** artifact 目录（#192）。

    与 `sessions/<sid>/`、`workspaces/<sid>/` 同一条纪律（ADR-0029 D2）：删除面是
    白名单，只删 harness 用 `setting + session_id` 自己拼出来的路径。artifact 根目录
    完全由 `artifact_dir` 拼成，只有 harness 会往里写，所以这条删除是安全的。

    "同 id 不同会话"是内容哈希寻址下最容易搞错的一点：两个会话可以有**同一个**
    artifact_id（同内容同哈希），所以删除必须按 session 前缀隔离——删 A 不能碰到 B。
    """
    artifacts_root = tmp_path / "artifacts"
    client = _client(tmp_path, artifact_dir=str(artifacts_root))
    session_id = _create_session(client)

    mine = artifacts_root / session_id
    mine.mkdir(parents=True)
    (mine / "0123456789abcdef").write_text("big output", encoding="utf-8")
    theirs = artifacts_root / "someone-else"
    theirs.mkdir(parents=True)
    (theirs / "0123456789abcdef").write_text("keep me", encoding="utf-8")

    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 200, resp.text

    assert not mine.exists(), "会话硬删后本地 artifact 目录应当消失（不然只剩不可达残留）"
    assert (theirs / "0123456789abcdef").read_text(encoding="utf-8") == "keep me"


def test_hard_delete_without_artifacts_is_noop(tmp_path: Path) -> None:
    """没有产物的会话硬删照常成功（幂等）；artifact 根目录不必预先存在。"""
    client = _client(tmp_path, artifact_dir=str(tmp_path / "artifacts"))
    session_id = _create_session(client)
    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 200, resp.text
