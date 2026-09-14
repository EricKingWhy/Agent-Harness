"""WS-4 / #154：项目 CRUD API 验收（`/api/projects`）。

本票把 WS-2 的领域能力（`WorkspaceIndex`）暴露成 HTTP 面，两条语义是硬约束：

1. **软删除**：删除项目只解除分组——目录、用户文件、实时会话、已落盘日志一概不动，
   那些会话回到 Ungrouped（AC4/AC11）。本文件用**逐字节比对会话日志**来验，
   而不是只验"还能读到"。
2. **对模型不可见**：项目是宿主侧能力，不写任何 `SessionEvent`（非目标）。

另外三条本票特有的诚实性要求：
- create 只接受**已存在**的目录，且**不**顺带 mkdir（AC2）；
- attach 之前会话必须已存在且已带 cwd，不留"账本有 id 但会话无 cwd"的中间态（AC7）；
- 幂等：重复 create 同一规范路径返回既有实体（不重建、不重复入序）；重复 detach
  无副作用（AC5）。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent_harness.config import Settings
from agent_harness.session import Session
from agent_harness.web.app import create_app
from tests.scripted_model import ScriptedModel

_DATA_PREFIX = "data:"
_GOOD_PASSWORD_SECRET = "test-signing-secret-at-least-32-characters"


def _app(tmp_path: Path, **overrides):
    settings = Settings(
        _env_file=None,
        workspace_dir=str(tmp_path),
        model_api_key="sk-test",
        **overrides,
    )
    return create_app(settings, enable_cors=False)


def _create_session(client: TestClient, *, workspace: str | None = None) -> str:
    """建一个会话（真 runtime + 替身模型），返回 session_id（从 SSE 帧里取）。"""
    payload: dict[str, object] = {"task": "hi", "max_steps": 1}
    if workspace is not None:
        payload["workspace"] = workspace
    with patch(
        "agent_harness.assembly.create_chat_model",
        return_value=ScriptedModel(responses=[AIMessage(content="ok")]),
    ):
        resp = client.post("/api/sessions", json=payload)
    assert resp.status_code == 200, resp.text
    frames = [
        json.loads(line[len(_DATA_PREFIX) :].strip())
        for line in resp.text.splitlines()
        if line.startswith(_DATA_PREFIX)
    ]
    session_id = next((f["session_id"] for f in frames if f.get("session_id")), None)
    assert session_id, f"SSE 流里没有 session_id：{frames[:3]}"
    return session_id


def _projects_root(tmp_path: Path) -> Path:
    """命名 workspace 的物理目录（`AppState.workspaces_root`）。"""
    return tmp_path / "workspaces"


def _post_project(client: TestClient, path: Path | str, **extra) -> dict:
    """建好目录再注册（本 helper 只用于**合法**路径；AC2 的拒绝用例直接打端点）。"""
    Path(path).mkdir(parents=True, exist_ok=True)
    resp = client.post("/api/projects", json={"path": str(path), **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _find_by_path(client: TestClient, path: Path) -> dict | None:
    """按规范路径取项目（走 resolve 端点，覆盖 AC1 的"幂等解析"）。"""
    resp = client.post("/api/projects/resolve", json={"path": str(path)})
    if resp.status_code == 404:
        return None
    assert resp.status_code == 200, resp.text
    return resp.json()


def _session_log(client: TestClient, session_id: str) -> bytes:
    root = client.app.state.agent.sessions_root
    return (root / session_id / "events.jsonl").read_bytes()


# ── AC2：create 只接受已存在的目录 ──


def test_create_registers_an_existing_dir_and_is_idempotent(tmp_path: Path) -> None:
    """同一物理目录 → 同一项目（不重建、不重复入序），路径先规范化再比较。"""
    client = TestClient(_app(tmp_path))
    target = tmp_path / "myproj"
    target.mkdir()

    first = _post_project(client, target)
    assert first["title"] == "myproj"  # AC3：缺省标题 = 末段路径
    assert first["path"] == str(target.resolve())
    assert first["status"] == "ok"

    # 等价写法（尾斜杠 / 绕一圈的 ..）必须解析成同一实体
    again = _post_project(client, f"{target}{'/'}..{'/'}myproj")
    assert again["id"] == first["id"], "规范路径相同 → 必须返回既有实体"
    assert len(client.get("/api/projects").json()) == 1

    # 显式标题只在首次生效（幂等解析不改名）
    titled = _post_project(client, target, title="另一个名字")
    assert titled["id"] == first["id"]
    assert titled["title"] == "myproj"


def test_create_rejects_a_missing_path_and_creates_nothing(tmp_path: Path) -> None:
    """AC2：不存在的路径 → 报错，且**不**顺带 mkdir（AC9 明确反对"注册即创建"）。"""
    client = TestClient(_app(tmp_path))
    ghost = tmp_path / "does-not-exist"

    resp = client.post("/api/projects", json={"path": str(ghost)})
    assert resp.status_code == 404, resp.text
    assert not ghost.exists(), "被拒的请求不能在磁盘上留下痕迹"
    assert client.get("/api/projects").json() == []


def test_create_rejects_a_regular_file_with_422(tmp_path: Path) -> None:
    """存在但不是目录 → 入参非法（422），不是 404。"""
    client = TestClient(_app(tmp_path))
    f = tmp_path / "a-file.txt"
    f.write_text("x", encoding="utf-8")

    resp = client.post("/api/projects", json={"path": str(f)})
    assert resp.status_code == 422, resp.text
    assert client.get("/api/projects").json() == []


def test_create_file_path_detail_matches_the_directory_browser(tmp_path: Path) -> None:
    """同一个路径在"注册项目"与"目录浏览"必须说**同一句话**（API-01，2026-09-13 真机验收）。

    此前这里是裸 `str(OSError)`：`[Errno 20] 不是目录: '…\\a-file.txt'`
    （errno 前缀 + 反斜杠双重转义），而目录浏览器给的是 `不是目录：<规范路径>`。
    """
    client = TestClient(_app(tmp_path))
    f = tmp_path / "a-file.txt"
    f.write_text("x", encoding="utf-8")
    canonical = os.path.realpath(f)

    from_browser = client.get("/api/host/dirs", params={"path": str(f)})
    from_register = client.post("/api/projects", json={"path": str(f)})

    assert from_browser.status_code == from_register.status_code == 422, from_register.text
    assert from_register.json()["detail"] == f"不是目录：{canonical}"
    assert from_register.json()["detail"] == from_browser.json()["detail"]


def test_create_relative_path_speaks_chinese(tmp_path: Path) -> None:
    """相对路径 → 422，且 msg 是我们写的**中文**（API-02）。

    前端 `readErrorDetail()` 只剥掉 Pydantic 的 `Value error, ` 前缀、把 msg 原样渲染，
    所以这里断言的这句就是用户在对话框里看到的那句。
    """
    client = TestClient(_app(tmp_path))

    resp = client.post("/api/projects", json={"path": r"not-absolute\dir"})

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    msg = detail[0]["msg"] if isinstance(detail, list) else str(detail)
    assert "path 必须是绝对路径" in msg, msg
    assert "must be" not in msg, msg


def test_create_blank_title_speaks_chinese(tmp_path: Path) -> None:
    """空白标题 → 422 `title 不能为空`（同 API-02 口径：我们自己写的 msg 一律中文）。"""
    client = TestClient(_app(tmp_path))
    target = tmp_path / "a-dir"
    target.mkdir()

    resp = client.post("/api/projects", json={"path": str(target), "title": "   "})

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    msg = detail[0]["msg"] if isinstance(detail, list) else str(detail)
    assert "title 不能为空" in msg, msg


# ── AC1：端点集（list / get / resolve / rename / delete / attach / detach / reorder）──


def test_projects_are_listed_in_registry_order(tmp_path: Path) -> None:
    """列表顺序 = 注册表顺序（新建项目前插），不是按标题/路径排序。"""
    client = TestClient(_app(tmp_path))
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir()
    b.mkdir()

    first = _post_project(client, a)
    second = _post_project(client, b)
    ids = [p["id"] for p in client.get("/api/projects").json()]
    assert ids == [second["id"], first["id"]], "新建项目前插"

    one = client.get(f"/api/projects/{first['id']}")
    assert one.status_code == 200
    assert one.json()["path"] == str(a.resolve())


def test_unknown_project_id_is_404_on_every_verb(tmp_path: Path) -> None:
    """未知 id 在每种动词上都是 404（不能有的 500、有的 404）。"""
    client = TestClient(_app(tmp_path))
    ghost = "00000000-0000-0000-0000-000000000000"
    calls = [
        ("GET", f"/api/projects/{ghost}", None),
        ("PATCH", f"/api/projects/{ghost}", {"title": "x"}),
        ("DELETE", f"/api/projects/{ghost}", None),
        ("POST", f"/api/projects/{ghost}/sessions", {"session_id": "s"}),
        ("DELETE", f"/api/projects/{ghost}/sessions/s", None),
        ("POST", f"/api/projects/{ghost}/sessions/s/order", {"before": None}),
    ]
    for method, url, body in calls:
        resp = client.request(method, url, json=body)
        assert resp.status_code == 404, f"{method} {url} → {resp.status_code}"


def test_resolve_by_path_returns_the_registered_project_or_404(tmp_path: Path) -> None:
    """按路径解析（前端"这个目录是不是已有项目"的幂等入口）。"""
    client = TestClient(_app(tmp_path))
    target = tmp_path / "resolve-me"
    target.mkdir()

    assert _find_by_path(client, target) is None
    created = _post_project(client, target)
    assert _find_by_path(client, target)["id"] == created["id"]
    # 未注册但存在的目录 → 404（不是"顺便注册"）
    other = tmp_path / "unregistered"
    other.mkdir()
    resp = client.post("/api/projects/resolve", json={"path": str(other)})
    assert resp.status_code == 404


def test_rename_sets_the_title(tmp_path: Path) -> None:
    """重命名（`setTitle`）——标题是项目唯一的可变元数据。"""
    client = TestClient(_app(tmp_path))
    target = tmp_path / "rename-me"
    target.mkdir()
    created = _post_project(client, target)

    resp = client.patch(f"/api/projects/{created['id']}", json={"title": "新名字"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "新名字"
    assert client.get(f"/api/projects/{created['id']}").json()["title"] == "新名字"

    # 空 / 纯空白标题 → 422（不让 UI 把项目显示成空白）
    for bad in ("", "   "):
        assert client.patch(
            f"/api/projects/{created['id']}", json={"title": bad}
        ).status_code == 422


# ── AC7：attach 的前置校验 ──


def test_attach_requires_an_existing_session(tmp_path: Path) -> None:
    """会话不存在 → 404（不留"账本有 id 但会话不存在"的中间态）。"""
    client = TestClient(_app(tmp_path))
    project = _post_project(client, tmp_path / "proj-dir")

    resp = client.post(
        f"/api/projects/{project['id']}/sessions", json={"session_id": "no-such-session"}
    )
    assert resp.status_code == 404, resp.text
    assert client.get(f"/api/projects/{project['id']}").json()["session_ids"] == []


def test_attach_rejects_a_session_anchored_elsewhere(tmp_path: Path) -> None:
    """会话的 cwd 属于**别的**目录 → 409（项目归属由 cwd 决定，不能随便指派）。"""
    client = TestClient(_app(tmp_path))
    session_id = _create_session(client, workspace="proj-a")
    other = tmp_path / "proj-b"
    other.mkdir()
    project_b = _post_project(client, other)

    assert _session_log(client, session_id)  # 前置：会话真的存在
    resp = client.post(
        f"/api/projects/{project_b['id']}/sessions", json={"session_id": session_id}
    )
    assert resp.status_code == 409, resp.text
    assert client.get(f"/api/projects/{project_b['id']}").json()["session_ids"] == []


def test_attach_rejects_a_legacy_session_without_cwd(tmp_path: Path) -> None:
    """AC7：历史遗留（header 无 cwd）→ 409，不能凭"会话存在"就写进账本。

    这类会话只可能来自老日志（新会话的 cwd 与 `session/started` 同在第一事件里）。
    """
    client = TestClient(_app(tmp_path))
    project = _post_project(client, tmp_path / "legacy-proj")
    store = client.app.state.agent.store
    Session.start(store, session_id="legacy", started_data={"provider": "p"})  # 不传 cwd

    resp = client.post(
        f"/api/projects/{project['id']}/sessions", json={"session_id": "legacy"}
    )
    assert resp.status_code == 409, resp.text
    assert client.get(f"/api/projects/{project['id']}").json()["session_ids"] == []


# ── AC5/AC6：detach 幂等且不动日志 ──


def test_detach_is_idempotent_and_leaves_the_log_byte_identical(tmp_path: Path) -> None:
    """detach 只改账本；会话日志逐字节不变（AC6 要求"断言字节"，不是"还能读到"）。"""
    client = TestClient(_app(tmp_path))
    session_id = _create_session(client, workspace="proj-detach")
    project = _find_by_path(client, _projects_root(tmp_path) / "proj-detach")
    assert project is not None, "命名 workspace 的会话应已自动建出项目"
    assert session_id in project["session_ids"]

    before = _session_log(client, session_id)
    first = client.delete(f"/api/projects/{project['id']}/sessions/{session_id}")
    assert first.status_code == 200, first.text
    assert first.json()["session_ids"] == []
    assert _session_log(client, session_id) == before, "detach 不得触碰会话日志"

    # 幂等：再 detach 一次仍然 200 且无副作用
    second = client.delete(f"/api/projects/{project['id']}/sessions/{session_id}")
    assert second.status_code == 200, second.text
    assert second.json()["session_ids"] == []
    assert _session_log(client, session_id) == before

    # 会话仍在（未分组），且可重新 attach 回来
    rows = {r["session_id"]: r for r in client.get("/api/sessions").json()}
    assert rows[session_id]["workspace"] is None, "detach 后回到未分组（WS-3 契约）"
    again = client.post(
        f"/api/projects/{project['id']}/sessions", json={"session_id": session_id}
    )
    assert again.status_code == 200, again.text
    assert again.json()["session_ids"] == [session_id]
    assert _session_log(client, session_id) == before


def test_detach_via_the_wrong_project_does_not_touch_the_owner(tmp_path: Path) -> None:
    """URL 里的项目不是会话的归属 → 幂等空操作（不得借 `detach_session` 的全局语义改别人）。

    `WorkspaceIndex.detach_session` 的语义是"从**任何**账本移出"；端点必须先确认会话在
    URL 指定的项目里，否则会在 A 的 URL 下把 B 的账本改掉。
    """
    client = TestClient(_app(tmp_path))
    session_id = _create_session(client, workspace="owner")
    owner = _find_by_path(client, _projects_root(tmp_path) / "owner")
    other = _post_project(client, tmp_path / "bystander")
    assert owner is not None and session_id in owner["session_ids"]

    resp = client.delete(f"/api/projects/{other['id']}/sessions/{session_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["session_ids"] == []
    assert client.get(f"/api/projects/{owner['id']}").json()["session_ids"] == [session_id], (
        "旁观项目的 detach 不得动到真正拥有该会话的项目"
    )


def test_project_reads_run_off_the_event_loop(tmp_path: Path) -> None:
    """项目读路径的同步磁盘 I/O（账本成员 header / 项目视图）必须走 worker 线程。

    与 #153 列表路径同款的断言：`ensure_stores` 必然跑在事件循环线程上，索引读与
    会话 header 读必须**不与任何 loop 线程同线程**（TestClient 每个请求一个 portal）。
    """
    client = TestClient(_app(tmp_path))
    session_id = _create_session(client, workspace="offload")
    project = _find_by_path(client, _projects_root(tmp_path) / "offload")
    assert project is not None

    state = client.app.state.agent
    index = state.workspace_index
    store = state.store
    loop_threads: list[tuple[str, int]] = []
    index_threads: list[tuple[str, int]] = []
    header_threads: list[tuple[str, int]] = []

    def _here() -> tuple[str, int]:
        return (threading.current_thread().name, threading.get_ident())

    real_ensure, real_list, real_get = (state.ensure_stores, index.list, index.get)
    real_header = store.read_started_header

    async def _spy_ensure():
        loop_threads.append(_here())
        return await real_ensure()

    def _spy_list():
        index_threads.append(_here())
        return real_list()

    def _spy_get(workspace_id: str):
        index_threads.append(_here())
        return real_get(workspace_id)

    def _spy_header(sid: str):
        header_threads.append(_here())
        return real_header(sid)

    with (
        patch.object(state, "ensure_stores", _spy_ensure),
        patch.object(index, "list", _spy_list),
        patch.object(index, "get", _spy_get),
        patch.object(store, "read_started_header", _spy_header),
    ):
        _rows = client.get("/api/projects")
        assert _rows.status_code == 200, _rows.text
        # 先 detach：命名 workspace 建的会话**已经**是成员，不先摘掉的话 attach 会被
        # "已成员短路"提前返回，索引内部的 header 读根本不发生（这条 spy 就成了空测）。
        dropped = client.delete(f"/api/projects/{project['id']}/sessions/{session_id}")
        assert dropped.status_code == 200, dropped.text
        attached = client.post(
            f"/api/projects/{project['id']}/sessions", json={"session_id": session_id}
        )
        assert attached.status_code == 200, attached.text
        assert attached.json()["session_ids"] == [session_id]

    assert loop_threads, "前置条件：项目路径必须调用 ensure_stores（事件循环线程）"
    assert index_threads, "项目读/写必须经索引（且不得在事件循环线程上跑）"
    assert header_threads, "attach 必须读会话 header（且不得在事件循环线程上读）"
    off_loop = set(index_threads) | set(header_threads)
    assert not (off_loop & set(loop_threads)), (
        "索引/header 读与事件循环同线程 —— 必须 anyio.to_thread.run_sync 卸载："
        f"loop={loop_threads} index={index_threads} header={header_threads}"
    )


# ── AC1/AC5：reorder（insertSessionBefore 语义）──


def test_reorder_follows_insert_before_and_cannot_cross_projects(tmp_path: Path) -> None:
    """重排是显式手工序：`before` 指定锚点，None = 追加尾部；跨项目重排 → 409。"""
    client = TestClient(_app(tmp_path))
    first = _create_session(client, workspace="shared")
    second = _create_session(client, workspace="shared")
    project = _find_by_path(client, _projects_root(tmp_path) / "shared")
    assert project is not None
    assert set(project["session_ids"]) == {first, second}
    assert project["session_ids"][0] == second, "新会话前插"

    # 把 second 移到 first 之前
    moved = client.post(
        f"/api/projects/{project['id']}/sessions/{second}/order",
        json={"before": first},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["session_ids"] == [second, first]

    # 追加到尾部
    tail = client.post(
        f"/api/projects/{project['id']}/sessions/{second}/order", json={"before": None}
    )
    assert tail.status_code == 200, tail.text
    assert tail.json()["session_ids"] == [first, second]

    # 跨项目：other 项目里的会话不能在 shared 里重排；shared 里的会话也不能拿 other 的
    # 会话当锚点——两个方向的账本都必须原样不动
    other_session = _create_session(client, workspace="another")
    other = _find_by_path(client, _projects_root(tmp_path) / "another")
    assert other is not None
    cross = client.post(
        f"/api/projects/{project['id']}/sessions/{other_session}/order",
        json={"before": None},
    )
    assert cross.status_code == 409, cross.text
    foreign_anchor = client.post(
        f"/api/projects/{project['id']}/sessions/{first}/order",
        json={"before": other_session},
    )
    assert foreign_anchor.status_code == 409, foreign_anchor.text
    assert client.get(f"/api/projects/{project['id']}").json()["session_ids"] == [first, second]
    assert client.get(f"/api/projects/{other['id']}").json()["session_ids"] == [other_session]


# ── AC4/AC11：软删除 ──


def test_soft_delete_keeps_the_directory_and_ungroups_the_sessions(tmp_path: Path) -> None:
    """删除项目 = 只摘注册记录与账本：目录、文件、会话日志一概不动，会话变未分组。"""
    client = TestClient(_app(tmp_path))
    session_id = _create_session(client, workspace="proj-soft-delete")
    project_dir = _projects_root(tmp_path) / "proj-soft-delete"
    project = _find_by_path(client, project_dir)
    assert project is not None

    log_before = _session_log(client, session_id)
    other_file = project_dir / "user-file.txt"
    other_file.write_text("用户自己的文件", encoding="utf-8")

    resp = client.delete(f"/api/projects/{project['id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == project["id"]
    assert body["deleted"] is True
    assert body["sessions_detached"] == 1
    # AC4：响应必须明确说清"会话不会被删除"（避免调用方误以为连坐）
    assert "会话" in body["detail"] and "未" in body["detail"], body["detail"]

    # 目录 / 用户文件 / 会话日志逐字节不变
    assert project_dir.is_dir(), "软删除不得删目录"
    assert other_file.read_text(encoding="utf-8") == "用户自己的文件"
    assert _session_log(client, session_id) == log_before

    # 项目没了；会话仍在且以未分组出现（WS-3 契约）
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    assert client.get("/api/projects").json() == []
    rows = {r["session_id"]: r for r in client.get("/api/sessions").json()}
    assert rows[session_id]["workspace"] is None


# ── ADR-0025 D1：来源闸（项目写端点不接受跨源浏览器请求）──


def test_cross_origin_project_writes_are_rejected(tmp_path: Path) -> None:
    """未配置 JWT_SECRET（本地信任）时，跨源写请求 → 403；本机来源照常放行。

    这是 ADR-0025 D1 的 (b)：`create(path)` 接受任意已存在目录，是本票新增的能力面，
    不能只靠"来源可信"这句话——浏览器一定会为跨源写请求带 Origin，校验它就够。
    """
    client = TestClient(_app(tmp_path))
    target = tmp_path / "guarded"
    target.mkdir()

    evil = client.post(
        "/api/projects",
        json={"path": str(target)},
        headers={"Origin": "http://evil.example"},
    )
    assert evil.status_code == 403, evil.text
    assert client.get("/api/projects").json() == [], "被拒的跨源请求不能留下项目"

    for origin in ("http://localhost:5173", "http://127.0.0.1:8000"):
        ok = client.post(
            "/api/projects", json={"path": str(target)}, headers={"Origin": origin}
        )
        assert ok.status_code == 200, f"{origin} → {ok.text}"

    # 裸 "null" Origin（sandboxed iframe / file://）也没有 hostname → 拒绝
    null_origin = client.post(
        "/api/projects", json={"path": str(target)}, headers={"Origin": "null"}
    )
    assert null_origin.status_code == 403


def test_every_project_endpoint_is_behind_the_origin_gate(tmp_path: Path) -> None:
    """来源闸必须挂在**每一个**项目端点上（读 + 写）——逐个动词都不能漏。

    读端点也要挂：项目列表/详情里全是用户的绝对路径，CORS `*` 下"能被读"就等于
    "能被任意网页枚举"。本用例逐个动词探一遍，所以"某个端点漏挂依赖"会直接红
    （只测 `POST /api/projects` 那种写法抓不到 DELETE/PATCH/GET 上的遗漏）。
    """
    client = TestClient(_app(tmp_path))
    target = tmp_path / "gated"
    target.mkdir()
    pid = _post_project(client, target)["id"]
    sid = _create_session(client, workspace="gated")
    evil = {"Origin": "http://evil.example"}
    local = {"Origin": "http://localhost:5173"}

    calls = [
        ("GET", "/api/projects", None),
        ("POST", "/api/projects", {"path": str(target)}),
        ("POST", "/api/projects/resolve", {"path": str(target)}),
        ("GET", f"/api/projects/{pid}", None),
        ("PATCH", f"/api/projects/{pid}", {"title": "x"}),
        ("DELETE", f"/api/projects/{pid}", None),
        ("POST", f"/api/projects/{pid}/sessions", {"session_id": sid}),
        ("DELETE", f"/api/projects/{pid}/sessions/{sid}", None),
        ("POST", f"/api/projects/{pid}/sessions/{sid}/order", {"before": None}),
    ]
    for method, url, body in calls:
        blocked = client.request(method, url, json=body, headers=evil)
        assert blocked.status_code == 403, f"跨源 {method} {url} → {blocked.status_code}"
        allowed = client.request(method, url, json=body, headers=local)
        assert allowed.status_code != 403, f"本机来源被误拒：{method} {url} → {allowed.text}"


def test_path_must_be_absolute(tmp_path: Path) -> None:
    """相对路径 / 空白 / `.` / `..` / NUL 一律 422。

    这条不是形式主义：`canonical_workspace_path(".")` = **进程当前工作目录**、
    `("..")` = **盘根**——放行就等于允许"注册服务器碰巧启动的目录/整块盘"（静默锚定）。
    ADR-0025 D1 明确本端点收的是**绝对路径**。
    """
    client = TestClient(_app(tmp_path))
    for bad in (".", "..", "   ", "relative/dir", "C:relative", "../../etc", "\x00bad"):
        resp = client.post("/api/projects", json={"path": bad})
        assert resp.status_code == 422, f"{bad!r} → {resp.status_code} {resp.text}"
        resolved = client.post("/api/projects/resolve", json={"path": bad})
        assert resolved.status_code == 422, f"resolve {bad!r} → {resolved.status_code}"
    assert client.get("/api/projects").json() == []


def test_malformed_absolute_path_is_422_not_500(tmp_path: Path) -> None:
    """形态合法（绝对）但 OS 不接受的路径 → 422，不是 500。

    `os.stat` 对非法字符抛**裸 `OSError`**(EINVAL)、超长路径抛 ENAMETOOLONG——都不是
    `FileNotFoundError`；不登记就会变成"客户端可控路径换来 500"。
    """
    client = TestClient(_app(tmp_path))
    for bad in ("C:\\bad<name", "C:\\" + "x" * 5000):
        resp = client.post("/api/projects", json={"path": bad})
        assert resp.status_code == 422, f"{bad[:24]!r} → {resp.status_code} {resp.text[:120]}"


def test_unreadable_path_is_403(tmp_path: Path, monkeypatch) -> None:
    """`PermissionError` → 403（服务端无权访问），且**不**泄露服务端路径细节以外的东西。"""
    client = TestClient(_app(tmp_path))

    def _denied(path: str) -> None:
        raise PermissionError(13, "拒绝访问", path)

    monkeypatch.setattr("agent_harness.workspace.index.require_existing_directory", _denied)
    resp = client.post("/api/projects", json={"path": str(tmp_path)})
    assert resp.status_code == 403, resp.text


def test_origin_gate_defers_to_authentication_when_jwt_is_configured(tmp_path: Path) -> None:
    """配置了 JWT_SECRET → 认证层才是边界，来源闸不再另判（跨源网页拿不到签名 token）。"""
    from datetime import UTC, datetime

    client = TestClient(_app(tmp_path, jwt_secret=_GOOD_PASSWORD_SECRET))
    target = tmp_path / "authed"
    target.mkdir()

    # 匿名 + 跨源 → 401（认证层先拦）
    anon = client.post(
        "/api/projects", json={"path": str(target)}, headers={"Origin": "http://evil.example"}
    )
    assert anon.status_code == 401, anon.text

    token = jwt.encode(
        {
            "tenant_id": "local",
            "user_id": "local",
            "scopes": ["user"],
            "exp": int(datetime.now(UTC).timestamp()) + 600,
        },
        _GOOD_PASSWORD_SECRET,
    )
    authed = client.post(
        "/api/projects",
        json={"path": str(target)},
        headers={"Origin": "http://evil.example", "Authorization": f"Bearer {token}"},
    )
    assert authed.status_code == 200, authed.text


# ── 非目标：项目对模型不可见（不写任何 SessionEvent）──


def test_project_crud_writes_no_session_events(tmp_path: Path) -> None:
    """Workspace 是宿主侧能力：项目 CRUD 不得往任何会话日志里塞事件。"""
    client = TestClient(_app(tmp_path))
    session_id = _create_session(client, workspace="quiet")
    log_before = _session_log(client, session_id)
    project = _find_by_path(client, _projects_root(tmp_path) / "quiet")
    assert project is not None

    client.patch(f"/api/projects/{project['id']}", json={"title": "改名"})
    client.delete(f"/api/projects/{project['id']}/sessions/{session_id}")
    client.post(f"/api/projects/{project['id']}/sessions", json={"session_id": session_id})
    client.post(
        f"/api/projects/{project['id']}/sessions/{session_id}/order", json={"before": None}
    )
    client.delete(f"/api/projects/{project['id']}")

    assert _session_log(client, session_id) == log_before


def test_malformed_session_id_is_rejected_not_500(tmp_path: Path) -> None:
    """会话 id 在 URL 里也是**名字**不是路径（复用既有校验，不是新的一套）。"""
    client = TestClient(_app(tmp_path))
    project = _post_project(client, tmp_path / "ids")

    # 能到达 handler 的非法形态（点号）→ 422，由既有 validate_session_id 拒绝
    dotted = client.delete(f"/api/projects/{project['id']}/sessions/s.bad")
    assert dotted.status_code == 422, dotted.text
    assert client.get(f"/api/projects/{project['id']}").json()["session_ids"] == []

    # 会被 HTTP 路径层吃掉的形态：分隔符 → 路由不匹配的 404；空 id → 落到集合路由
    # `{id}/sessions`（DELETE 不在该集合上）→ 405。两者都不是 500。
    for bad in ("../escape", "a/b", ""):
        resp = client.delete(f"/api/projects/{project['id']}/sessions/{bad}")
        assert resp.status_code in (404, 405, 422), f"{bad!r} → {resp.status_code}"


# ── 幂等的严格性：重复 attach 不得打乱手工序；自锚点重排是 no-op ──


def test_repeated_attach_keeps_the_manual_order(tmp_path: Path) -> None:
    """已是成员的会话再 attach 一次 → 顺序**不变**（否则幂等重试会重置用户拖过的位置）。

    `index.attach_session` 是新会话前插（创建期语义）；HTTP 的 attach 必须对"已在本项目"
    的会话短路，不然一次重试就把手工序抹了。
    """
    client = TestClient(_app(tmp_path))
    first = _create_session(client, workspace="sticky")
    second = _create_session(client, workspace="sticky")
    project = _find_by_path(client, _projects_root(tmp_path) / "sticky")
    assert project is not None
    assert project["session_ids"] == [second, first], "新会话前插"

    # 手工把 first 拖到最前
    moved = client.post(
        f"/api/projects/{project['id']}/sessions/{first}/order", json={"before": second}
    )
    assert moved.json()["session_ids"] == [first, second]

    # 重 attach 的是**队尾**的 second：不做短路的话索引会把它前插（顺序被重置），
    # 而"重 attach 队首那个会话"是构造不出来的弱测（前插它本来就不改变顺序）。
    again = client.post(
        f"/api/projects/{project['id']}/sessions", json={"session_id": second}
    )
    assert again.status_code == 200, again.text
    assert again.json()["session_ids"] == [first, second], "重复 attach 不得重置手工序"


def test_reordering_a_session_before_itself_is_a_noop(tmp_path: Path) -> None:
    """`insertBefore(x, x)` 是 no-op，不是 409（索引内部先 remove 再从锚点找自己会找不到）。"""
    client = TestClient(_app(tmp_path))
    first = _create_session(client, workspace="selfanchor")
    second = _create_session(client, workspace="selfanchor")
    project = _find_by_path(client, _projects_root(tmp_path) / "selfanchor")
    assert project is not None
    before = project["session_ids"]

    resp = client.post(
        f"/api/projects/{project['id']}/sessions/{first}/order", json={"before": first}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["session_ids"] == before
    assert set(before) == {first, second}


def test_attach_tolerates_an_unreadable_session_log(tmp_path: Path, monkeypatch) -> None:
    """会话日志读不了（占用/被删）→ 按"不可 attach"处理（404），不是 500。

    与索引 `_read_header` 的降级同款：日志层的 OSError 不该把请求打成 500，更不该把
    服务端绝对路径原样放进错误详情（Windows 文件占用在本仓真实出现过）。
    """
    client = TestClient(_app(tmp_path))
    project = _post_project(client, tmp_path / "unreadable")

    def _boom(session_id: str):
        raise PermissionError(13, "被占用", f"C:/secret/{session_id}/events.jsonl")

    monkeypatch.setattr(
        client.app.state.agent.store, "read_started_header", _boom
    )
    resp = client.post(
        f"/api/projects/{project['id']}/sessions", json={"session_id": "busy"}
    )
    assert resp.status_code == 404, resp.text
    assert "secret" not in resp.text, "错误详情不得回显服务端路径"
    assert client.get(f"/api/projects/{project['id']}").json()["session_ids"] == []
