"""WS-3 / #153：会话列表契约补 `workspace` + 按项目列会话。

三条不变量必须同时为真（票面 AC1–AC5）：

1. **键恒在**：每行都有 `workspace`（未分组 = 显式 `null`）——前端 `types.ts` 把该键
   声明为非可选，后端漏掉键就是运行时违约；
2. **不伪造**：值必须是真项目（id + title）。Pydantic 默认值会让键恒在，所以只有断言
   **值**才能抓住"漏映射"（同 ARCH-4b `trace_url` 的既有套路，AC3）；
3. **顺序是手工序**：`?workspace_id=<id>` 的顺序 = 账本顺序，**不是**活动时间序
   （AC4）。本文件用"把旧会话的 mtime 改到最新"制造两者相反，让这条断言真的有判别力；
4. **项目视图只含本项目**：既不漏（账本 ∩ header 可见），也不串台——别的项目的会话与
   未分组会话一个都不出现（跨项目串台靠"两个项目 + 一个未分组"的构造才验得出来）。
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from agent_harness.config import Settings
from agent_harness.session.service import SessionService
from agent_harness.web.app import SessionSummary, create_app
from tests.scripted_model import ScriptedModel

#: 与前端 `types.ts` 的 `SESSION_STARTED` 无关——这里只是拿到 SSE 首帧的会话 id。
_DATA_PREFIX = "data:"


def _app(tmp_path: Path):
    settings = Settings(workspace_dir=str(tmp_path), model_api_key="sk-test")
    return create_app(settings, enable_cors=False)


def _create(client: TestClient, *, workspace: str | None = None) -> str:
    """建一个会话（真 runtime + 替身模型），返回它的 session_id（从 SSE 帧里取）。"""
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


def _rows(client: TestClient, **params: str) -> list[dict]:
    resp = client.get("/api/sessions", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_response_model_requires_the_workspace_key() -> None:
    """AC3：`workspace` 在响应模型里**必填**——漏传必须响亮失败，不能默认成"未分组"。

    给它默认值的话，将来某个构造点漏传 `workspace=` 会静默产出一条**假事实**
    （"这个会话不属于任何项目"，不变量 #21 同族）。本用例把"必填"这个决定钉住。
    """
    with pytest.raises(ValidationError):
        SessionSummary(
            session_id="s",
            event_count=1,
            first_event_time=None,
            last_event_time=None,
            first_user_message=None,
        )


# ── AC1/AC2/AC3/AC5：契约字段与真实值 ──


def test_rows_carry_real_workspace_and_ungrouped_is_null(tmp_path: Path) -> None:
    """每行都有 `workspace`；分组会话拿到真项目的 id + title，未分组是显式 null。"""
    app = _app(tmp_path)
    client = TestClient(app)

    first = _create(client, workspace="proj")
    second = _create(client, workspace="proj")
    lonely = _create(client)  # 未命名 workspace → 未分组

    rows = _rows(client)
    by_id = {row["session_id"]: row for row in rows}
    for row in rows:
        assert "workspace" in row, f"每行都必须带 workspace 键（前端类型非可选）：{row}"

    linked = by_id[first]["workspace"]
    assert linked == {"id": linked["id"], "title": "proj"}, linked
    assert by_id[second]["workspace"] == linked, "同名 workspace = 同一个项目"

    # 未分组 → 显式 null（AC1：绝不伪造），且仍在列表里（AC5）
    assert by_id[lonely]["workspace"] is None
    assert lonely in by_id

    # 值来自真索引（不是自洽的假 id）：id / title 与 WorkspaceIndex 逐字段一致
    projects = app.state.agent.workspace_index.list()
    assert [(p.id, p.title) for p in projects] == [(linked["id"], "proj")]


def test_workspace_is_null_when_no_index_is_wired() -> None:
    """装配里没有 workspace 索引（CLI / 无 header 的 RecoveryStores）→ 全部未分组。

    这是 AC1 的"未分组"分支里最容易漏的一种：不是"查不到"，而是**根本没有查的地方**。
    """
    assert SessionService._workspace_refs_by_session(None) == {}


# ── AC4：按项目列会话，顺序 = 账本手工序 ──


def test_list_by_workspace_follows_ledger_order_not_activity(tmp_path: Path) -> None:
    """`?workspace_id=` 的顺序是**账本**顺序；活动时间序只属于默认列表。

    构造相反：先把两个会话都建进项目（账本 = [后建的, 先建的]），再把**先建的**
    那个会话日志的 mtime 改成最新——默认列表因此把它排到最前，而项目视图必须仍按
    账本（用户手工序）返回 [后建的, 先建的]（DSH：activity never reorders）。
    """
    app = _app(tmp_path)
    client = TestClient(app)

    first = _create(client, workspace="proj")
    second = _create(client, workspace="proj")
    project_id = _rows(client)[0]["workspace"]["id"]

    # 另一个项目 + 一个未分组会话：项目视图必须**只**含本项目的会话。跨项目串台
    # 是本票最危险的回归（把 ref 提到 `_workspace_refs_by_session` 的循环外、或用错
    # record 做成员过滤，都能通过"只有一个项目两个会话"的弱构造）。
    other = _create(client, workspace="other-proj")
    third = _create(client)  # 未命名 workspace → 未分组
    refs_by_id = {row["session_id"]: row["workspace"] for row in _rows(client)}
    # 每个会话必须报**自己**那个项目的引用——而不是"第一个项目"或某个全局 ref
    assert refs_by_id[first] == refs_by_id[second] == {"id": project_id, "title": "proj"}
    assert refs_by_id[other] == {"id": refs_by_id[other]["id"], "title": "other-proj"}
    assert refs_by_id[other]["id"] != project_id, "两个项目必须是不同 id"
    assert refs_by_id[third] is None

    events = app.state.agent.sessions_root / first / "events.jsonl"
    future = time.time() + 60
    os.utime(events, (future, future))

    # 默认视图：按活动时间 → 被改过 mtime 的 first 在最前
    assert _rows(client)[0]["session_id"] == first

    # 项目视图：按账本手工序 → 后 attach 的 second 在最前（活动时间不参与），
    # 且**只**含本项目成员（既不漏、也不串台）
    scoped = _rows(client, workspace_id=project_id)
    assert [row["session_id"] for row in scoped] == [second, first]
    assert all(row["workspace"]["id"] == project_id for row in scoped)

    # 未分组的 third、别的项目的 other 都不在项目视图里，但都在默认列表里（AC5）
    flat_ids = {row["session_id"] for row in _rows(client)}
    assert {first, second, third, other} <= flat_ids


def test_workspace_index_reads_run_off_the_event_loop(tmp_path: Path) -> None:
    """索引读（每个账本候选真读一次 `events.jsonl` 头部）必须在 worker 线程上执行。

    `WorkspaceIndex._read_header` 有意**不缓存**（AC6），所以列表端点每来一次请求就
    做 O(账本) 次文件读；留在事件循环里会让一次 `GET /api/sessions` 阻塞整个 asyncio
    loop——与同函数里的 `read_session_summary`（`anyio.to_thread.run_sync`）不一致。
    断言方式：把"必然跑在事件循环上"的 `ensure_stores` 与索引读各自记线程身份，两者
    的集合必须**不相交**。注意不能只比较某一次的 loop 线程：`TestClient` 每个请求起
    自己的 portal（事件循环线程），拿第一个请求的 loop 线程去比对第二个请求的索引读
    会假绿——必须按"读线程 ∉ 任何 loop 线程"断言。
    """
    app = _app(tmp_path)
    client = TestClient(app)

    _create(client, workspace="proj")
    project_id = _rows(client)[0]["workspace"]["id"]

    state = app.state.agent
    index = state.workspace_index
    loop_thread: list[tuple[str, int]] = []
    list_threads: list[tuple[str, int]] = []
    get_threads: list[tuple[str, int]] = []

    def _here() -> tuple[str, int]:
        return (threading.current_thread().name, threading.get_ident())

    real_ensure, real_list, real_get = (
        state.ensure_stores,
        index.list,
        index.get,
    )

    async def _spy_ensure():
        loop_thread.append(_here())
        return await real_ensure()

    def _spy_list():
        list_threads.append(_here())
        return real_list()

    def _spy_get(workspace_id: str):
        get_threads.append(_here())
        return real_get(workspace_id)

    with (
        patch.object(state, "ensure_stores", _spy_ensure),
        patch.object(index, "list", _spy_list),
        patch.object(index, "get", _spy_get),
    ):
        _rows(client)  # 默认路径 → index.list()
        _rows(client, workspace_id=project_id)  # 项目路径 → index.get()

    assert loop_thread, "前置条件：列表路径必须调用 ensure_stores（事件循环线程）"
    assert list_threads, "默认列表路径必须经 index.list() 取项目引用"
    assert get_threads, "项目视图必须经 index.get() 校验项目存在"
    off_loop = set(list_threads) | set(get_threads)
    assert not (off_loop & set(loop_thread)), (
        "索引读与事件循环同线程 —— 必须 anyio.to_thread.run_sync 卸载："
        f"loop={loop_thread} list={list_threads} get={get_threads}"
    )


def test_unknown_workspace_id_is_404_not_an_empty_list(tmp_path: Path) -> None:
    """未注册的项目 → 404，**不能**伪装成"这个项目没有会话"（不变量 #21 同族）。"""
    client = TestClient(_app(tmp_path))
    resp = client.get(
        "/api/sessions", params={"workspace_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_blank_or_malformed_workspace_id_is_404(tmp_path: Path) -> None:
    """边界：空串（`is not None` → 走项目分支）与非 id 形态的串都按"未知项目"处理。"""
    client = TestClient(_app(tmp_path))
    for bad in ("", "proj", "not-a-uuid"):
        resp = client.get("/api/sessions", params={"workspace_id": bad})
        assert resp.status_code == 404, f"{bad!r} → {resp.status_code}"


def test_project_view_skips_sessions_whose_log_disappeared(tmp_path: Path) -> None:
    """账本里有、但会话日志没了的条目 → 不返回（绝不造行），项目视图退化为空列表。"""
    app = _app(tmp_path)
    client = TestClient(app)

    session_id = _create(client, workspace="proj")
    project_id = _rows(client)[0]["workspace"]["id"]

    shutil.rmtree(app.state.agent.sessions_root / session_id)

    assert _rows(client, workspace_id=project_id) == []
    assert _rows(client) == []
