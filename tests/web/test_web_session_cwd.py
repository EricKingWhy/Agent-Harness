"""WS-6 / #169 后端半：`POST /api/sessions` 的 `cwd` 契约（ADR-0027）+ 注册项目自动归入。

契约矩阵（PRD §4.1，detail 文案即契约）：

| 输入 | 结果 |
| --- | --- |
| `workspace` + `cwd` 同时非空 | 422 `workspace 与 cwd 只能二选一` |
| `cwd` 非绝对路径 | 422 `cwd 必须是绝对路径：'<原值>'` |
| `cwd` 不存在 | 422 `目录不存在：<规范路径>`（不代创建） |
| `cwd` 是文件 | 422 `不是目录：<规范路径>` |
| 合法 `cwd` | 会话 root = 规范路径；`started.data.cwd` = 规范路径；自动入组（幂等） |
| 都缺省 | 现行为逐字节不变（回归锁） |

以及 AC5：`POST /api/projects` 成功响应新增 `sessions_attached`，并补齐归入 cwd 匹配的既有会话
（软删除 → 重注册闭环）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent_harness.config import Settings
from agent_harness.web.app import create_app
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
    """建会话（真 runtime + 替身模型），返回 session_id。

    SSE 流里必须有带 session_id 的帧——这是"创建真的成功、且流接上了"的最小证据；
    之后所有事实断言一律读**落盘事件**（`_started_cwd`），不依赖流里的到达顺序。
    """
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


def _started_cwd(client: TestClient, session_id: str) -> str:
    """`session/started.data.cwd` 的**权威**读法：读落盘事件，而不是 SSE 流。

    create 端点的 SSE 是 run 的实时订阅（session/started 在订阅建立**之前**就已落盘，
    不在流里），所以断言必须走 `GET /api/sessions/{id}/events`——这也正是前端重连时
    重建 cwd 的同一条路（不变量 #22：真相只在 append-only 日志里）。
    """
    resp = client.get(f"/api/sessions/{session_id}/events")
    assert resp.status_code == 200, resp.text
    started = next(e for e in resp.json() if e["type"] == "session/started")
    cwd = started["data"].get("cwd")
    assert cwd, f"started 事件没有 cwd：{started}"
    return str(cwd)


def _rows(client: TestClient) -> list[dict]:
    resp = client.get("/api/sessions")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _row_of(client: TestClient, session_id: str) -> dict:
    return next(r for r in _rows(client) if r["session_id"] == session_id)


def _projects(client: TestClient) -> list[dict]:
    resp = client.get("/api/projects")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 校验矩阵（AC1）──


def test_cwd_and_workspace_are_mutually_exclusive(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post(
        "/api/sessions",
        json={"task": "hi", "workspace": "ws1", "cwd": str(tmp_path)},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "workspace 与 cwd 只能二选一"


def test_cwd_must_be_absolute(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/sessions", json={"task": "hi", "cwd": "relative/dir"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "cwd 必须是绝对路径：'relative/dir'"


def test_cwd_directory_must_exist_and_is_not_created(tmp_path: Path) -> None:
    client = _client(tmp_path)
    missing = tmp_path / "nope"
    resp = client.post("/api/sessions", json={"task": "hi", "cwd": str(missing)})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == f"目录不存在：{os.path.realpath(missing)}"
    # 不代创建：请求失败后目录依然不存在
    assert not missing.exists()


def test_cwd_must_be_a_directory(tmp_path: Path) -> None:
    client = _client(tmp_path)
    a_file = tmp_path / "a-file.txt"
    a_file.write_text("x", encoding="utf-8")
    resp = client.post("/api/sessions", json={"task": "hi", "cwd": str(a_file)})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == f"不是目录：{os.path.realpath(a_file)}"


def test_blank_and_nul_cwd_are_rejected_not_silently_ignored(tmp_path: Path) -> None:
    """矩阵外的两条形态分支（PRD §4.1 末尾补记）：显式传的字段必须报错，不能当缺省。

    空白 cwd 若被当成"没给"，用户会得到一个落在默认 scratch 目录的会话，而他明明
    传了 cwd——静默忽略是最坏的一种宽容。含 NUL 的路径必须在 realpath 之前挡住：
    POSIX 的 `realpath` 对 NUL 抛 `ValueError`（不是 OSError），会穿透成 500。
    """
    client = _client(tmp_path)

    resp = client.post("/api/sessions", json={"task": "hi", "cwd": ""})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "cwd 必须是绝对路径：''"

    nul = f"{tmp_path}{os.sep}x\x00y"
    resp = client.post("/api/sessions", json={"task": "hi", "cwd": nul})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == f"cwd 含非法字符（NUL）：{nul!r}"


def test_cwd_is_canonicalized_to_realpath(tmp_path: Path) -> None:
    """AC2 的规范化必须真的发生：用含 `..` 的写法请求，落盘值 = realpath（**字符串**相等）。

    为什么专门这一条：只断言 `Path(x) == proj.resolve()` 是**假绿**——`Path.__eq__` 在
    Windows 上大小写不敏感且会归一分隔符，实现即使原样存了未规范化的输入也能通过。
    """
    client = _client(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    messy = f"{proj}{os.sep}..{os.sep}proj"

    session_id = _create_session(client, cwd=messy)

    assert _started_cwd(client, session_id) == os.path.realpath(proj)


# ── 合法 cwd：真实目录 + 自动入组（AC2/AC3）──


def test_cwd_session_runs_in_real_directory_and_auto_groups(tmp_path: Path) -> None:
    client = _client(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "hello.txt").write_text("真实文件", encoding="utf-8")

    session_id = _create_session(client, cwd=str(proj))

    # started.data.cwd = 规范化后的目录（agent 的默认操作目录真的换过去了）
    assert Path(_started_cwd(client, session_id)) == proj.resolve()
    # 目录里的既有文件不被动（"自动入组"只写 Harness 自己的账本）
    assert (proj / "hello.txt").read_text(encoding="utf-8") == "真实文件"

    # 自动入组：项目注册表出现该目录（title=目录末段名），会话在该项目分组下
    projects = _projects(client)
    assert len(projects) == 1
    assert Path(projects[0]["path"]) == proj.resolve()
    assert projects[0]["title"] == "proj"
    row = _row_of(client, session_id)
    assert row["workspace"] is not None
    assert row["workspace"]["id"] == projects[0]["id"]


def test_cwd_registration_is_idempotent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()

    sid1 = _create_session(client, cwd=str(proj))
    sid2 = _create_session(client, cwd=str(proj))

    projects = _projects(client)
    assert len(projects) == 1, "同 cwd 的两次创建不得产生两个项目"
    grouped = [r["session_id"] for r in _rows(client) if r["workspace"] is not None]
    assert sorted(grouped) == sorted([sid1, sid2])


# ── 旧契约回归（AC4）──


def test_legacy_workspace_name_contract_unchanged(tmp_path: Path) -> None:
    client = _client(tmp_path)
    session_id = _create_session(client, workspace="ws1")

    expected_root = tmp_path / "workspaces" / "ws1"
    assert Path(_started_cwd(client, session_id)) == expected_root
    assert expected_root.is_dir(), "命名 workspace 仍由 Harness 创建"

    # 既有行为：命名 workspace 的规范路径注册为项目 + 会话归组（#152 D8 第 1 步）
    projects = _projects(client)
    assert [p["title"] for p in projects] == ["ws1"]
    assert Path(projects[0]["path"]) == expected_root.resolve()
    assert _row_of(client, session_id)["workspace"] is not None


def test_default_session_behavior_unchanged(tmp_path: Path) -> None:
    client = _client(tmp_path)
    session_id = _create_session(client)

    expected_root = tmp_path / "workspaces" / session_id
    assert Path(_started_cwd(client, session_id)) == expected_root
    # 未命名会话不注册项目（ADR-0025 D6：不给每个未命名会话凭空造项目）
    assert _projects(client) == []
    assert _row_of(client, session_id)["workspace"] is None


# ── AC5：create_project 自动归入 + sessions_attached ──


def test_register_project_adopts_matching_sessions_and_counts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    sid = _create_session(client, cwd=str(proj))
    assert _row_of(client, sid)["workspace"] is not None  # 建会话时已自动入组

    # 软删除 → 会话回到未分组（#154 既有语义），目录与会话都还在
    project_id = _projects(client)[0]["id"]
    resp = client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert _row_of(client, sid)["workspace"] is None

    # 重注册：补齐归入 + 计数=本次新归入的会话数
    resp = client.post("/api/projects", json={"path": str(proj)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sessions_attached"] == 1
    assert _row_of(client, sid)["workspace"] is not None

    # 幂等重放：没有新的匹配会话 → 计数 0
    resp = client.post("/api/projects", json={"path": str(proj)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["sessions_attached"] == 0


def test_register_project_counts_only_its_own_path(tmp_path: Path) -> None:
    client = _client(tmp_path)
    proj_a, proj_b = tmp_path / "a", tmp_path / "b"
    proj_a.mkdir(), proj_b.mkdir()
    sid_a = _create_session(client, cwd=str(proj_a))
    client.delete(f"/api/projects/{_projects(client)[0]['id']}")

    resp = client.post("/api/projects", json={"path": str(proj_b)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["sessions_attached"] == 0, "cwd 不匹配的会话不得被拉进来"
    assert _row_of(client, sid_a)["workspace"] is None


def test_register_project_adopts_several_sessions_at_once(tmp_path: Path) -> None:
    """N>1 的批量归入（`sessions_attached` 不只是 0/1 两个取值）。

    同时锁住新进成员的**顺序口径**：与 bootstrap 的 AC14 一致，最新的排前面。
    """
    client = _client(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    sid1 = _create_session(client, cwd=str(proj))
    sid2 = _create_session(client, cwd=str(proj))
    client.delete(f"/api/projects/{_projects(client)[0]['id']}")

    resp = client.post("/api/projects", json={"path": str(proj)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sessions_attached"] == 2
    # 账本 = 新归入者（最新在前）+ 原有成员；两者都在，且都是这 2 个
    assert sorted(body["session_ids"]) == sorted([sid1, sid2])
