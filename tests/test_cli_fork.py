"""CLI fork 命令（Phase 14 T5, #111, ADR-0017 决策 6/10）。

全链串联：boundary 校验 + seed + session/forked + meta（T2）→ copy-on-fork
（T3）→ tail summary 可选（T4，--no-summary 关）。fork 是 CLI 动作，模型
不可见——不注册任何工具。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.cli import _parse_fork_args, fork_command
from agent_harness.session import Session
from agent_harness.session.event import USER_MESSAGE
from agent_harness.session.store import JsonlSessionStore

pytestmark = pytest.mark.asyncio


def _prepare(tmp_path: Path) -> JsonlSessionStore:
    store = JsonlSessionStore(root=tmp_path / "sessions")
    parent = Session.start(store, session_id="parent")
    parent.append(USER_MESSAGE, {"content": "第一条"})
    parent.append(USER_MESSAGE, {"content": "第二条"})
    return store


async def test_fork_command_end_to_end(tmp_path: Path) -> None:
    store = _prepare(tmp_path)
    child_id = await fork_command(
        "parent", from_message=2, no_summary=True,
        workspace_dir=str(tmp_path), write=lambda _line: None,
    )
    # child JSONL 真实落盘且可 resume（resume 自身会追加 session/resumed）
    resumed = Session.resume(store, child_id)
    types = [e.type for e in resumed.events]
    assert "session/forked" in types
    assert resumed.events[-1].type == "session/resumed"
    # 输出指向 child（resume 提示里带 id）
    # —— child_id 即返回值，resume 成功本身就是端到端证明


async def test_fork_command_copies_workspace(tmp_path: Path) -> None:
    from agent_harness.sandbox import WorkspaceRegistry

    registry = WorkspaceRegistry(root=tmp_path)
    store = JsonlSessionStore(root=tmp_path / "sessions")
    parent = Session.start(
        store, session_id="wsparent", workspace_registry=registry
    )
    parent.sandbox.write_text("hello.txt", "world")
    parent.append(USER_MESSAGE, {"content": "分叉点"})

    child_id = await fork_command(
        "wsparent", from_message=parent.events[-1].seq, no_summary=True,
        workspace_dir=str(tmp_path), write=lambda _line: None,
    )
    child_registry = WorkspaceRegistry(root=tmp_path)
    child_sandbox = child_registry.get(child_id)
    assert child_sandbox.read_text("hello.txt") == "world"


async def test_fork_command_bad_boundary_raises(tmp_path: Path) -> None:
    """命令核心抛领域错误；SystemExit 转换在 _main_fork（CLI 边界）。"""
    _prepare(tmp_path)
    from agent_harness.session.fork import ForkBoundaryError

    with pytest.raises(ForkBoundaryError):
        await fork_command(
            "parent", from_message=999, no_summary=True,
            workspace_dir=str(tmp_path), write=lambda _line: None,
        )


async def test_fork_command_child_inherits_parent_model(tmp_path: Path) -> None:
    """T7 #137：CLI fork 的 child 继承父当前模型（与 Web / demo 同语义）。"""
    from agent_harness.session.service import current_model_selection

    store = JsonlSessionStore(root=tmp_path / "sessions")
    parent = Session.start(
        store, session_id="parent",
        started_data={"provider": "deepseek", "model_id": "gpt-4o"},
    )
    parent.append(USER_MESSAGE, {"content": "第一条"})
    parent.append(USER_MESSAGE, {"content": "第二条"})

    child_id = await fork_command(
        "parent", from_message=2, no_summary=True,
        workspace_dir=str(tmp_path), write=lambda _line: None,
    )

    assert current_model_selection(
        store.read_events(child_id)
    ) == ("deepseek", "gpt-4o")


def test_parse_fork_args() -> None:
    args = _parse_fork_args(["sess-1", "--from-message", "3"])
    assert (args.session_id, args.from_message, args.no_summary) == (
        "sess-1", 3, False
    )
    args = _parse_fork_args(
        ["sess-1", "--from-message", "3", "--no-summary"]
    )
    assert args.no_summary is True
    with pytest.raises(SystemExit):
        _parse_fork_args(["sess-1"])  # --from-message 必填
