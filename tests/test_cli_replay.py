"""CLI replay 命令（Phase 14 T8, #114, ADR-0017 决策 4）。

逻辑回放契约（spec 03 §6）：从已持久化事件重新派生视图，tool result 一律
冻结终态；**零副作用**——不触发模型调用、工具执行、workspace 写、新事件
（连 Session.resume 都不走，那会追加 session/resumed）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.cli import render_replay_event, replay_command
from agent_harness.session import Session
from agent_harness.session.event import (
    AGENT_DELEGATION_FINISHED,
    AGENT_DELEGATION_STARTED,
    MODEL_COMPLETED,
    MODEL_FAILED,
    RUN_FAILED,
    SESSION_FORKED,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
)
from agent_harness.session.store import JsonlSessionStore

pytestmark = pytest.mark.asyncio


def _session_with_tools(tmp_path: Path) -> Session:
    store = JsonlSessionStore(root=tmp_path / "sessions")
    s = Session.start(store, session_id="hist")
    s.append(USER_MESSAGE, {"content": "列出文件"})
    s.append(TOOL_CALL, {"tool_call_id": "c1", "tool_name": "bash",
                         "args": {"command": "ls"}})
    s.append(TOOL_RESULT, {"tool_call_id": "c1", "content": "a.txt\nb.txt"})
    s.append(MODEL_COMPLETED, {"content": "有两个文件"})
    return s


async def test_replay_renders_frozen_history(tmp_path: Path) -> None:
    _session_with_tools(tmp_path)
    out = await replay_command("hist", workspace_dir=str(tmp_path))
    assert "[用户]" in out and "列出文件" in out
    assert "[assistant]" in out and "有两个文件" in out
    assert "bash" in out
    assert "a.txt" in out  # 冻结终态的 tool result 可见


async def test_replay_zero_side_effects(tmp_path: Path) -> None:
    """回放后：事件一字不变、无 workspace 写、无模型调用（结构保证）。"""
    store = JsonlSessionStore(root=tmp_path / "sessions")
    s = Session.start(store, session_id="hist")
    s.append(USER_MESSAGE, {"content": "列出文件"})
    before = [e.to_dict() for e in store.read_events("hist")]

    await replay_command("hist", workspace_dir=str(tmp_path))

    after = [e.to_dict() for e in store.read_events("hist")]
    assert after == before  # 连 session/resumed 都没有追加


async def test_replay_missing_session(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不存在"):
        await replay_command("ghost", workspace_dir=str(tmp_path))


def test_render_replay_event_delegation_and_failures(tmp_path: Path) -> None:
    store = JsonlSessionStore(root=tmp_path / "sessions")
    s = Session.start(store, session_id="d")
    s.append(USER_MESSAGE, {"content": "x"})
    s.append(AGENT_DELEGATION_STARTED, {"target": "coding", "task": "t",
                                        "child_session_id": "c1"})
    s.append(AGENT_DELEGATION_FINISHED, {"target": "coding", "task": "t",
                                         "child_session_id": "c1",
                                         "status": "completed", "summary": "写好了"})
    s.append(RUN_FAILED, {"reason": "identical_tool_failure_loop"})
    events = store.read_events("d")

    lines = [render_replay_event(e) for e in events]
    joined = "\n".join(line for line in lines if line)
    assert "[委派→coding]" in joined and "c1" in joined
    assert "completed" in joined and "写好了" in joined
    assert "[run 失败]" in joined and "identical_tool_failure_loop" in joined
    # session/started 等生命周期事件不渲染
    assert all("session/started" not in (line or "") for line in lines)


def test_render_replay_event_session_forked(tmp_path: Path) -> None:
    store = JsonlSessionStore(root=tmp_path / "sessions")
    s = Session.start(store, session_id="fk")
    s.append(SESSION_FORKED, {"parent_session_id": "p", "fork_point_seq": 3,
                              "boundary_user_message_seq": 4})
    event = store.read_events("fk")[-1]
    line = render_replay_event(event)
    assert "[fork]" in line and "p" in line and "@3" in line


def test_render_replay_event_ignores_lifecycle(tmp_path: Path) -> None:

    store = JsonlSessionStore(root=tmp_path / "sessions")
    s = Session.start(store, session_id="lc")
    s.append(USER_MESSAGE, {"content": "hi"})
    s.append(MODEL_FAILED, {"message": "boom"})
    events = store.read_events("lc")
    assert render_replay_event(events[0]) is None  # session/started
    # model/failed 渲染为失败行（replay 要如实呈现失败事实）
    assert render_replay_event(events[2]) is not None
