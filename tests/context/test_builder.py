"""ContextBuilder 在预算内保持完整事件投影。"""

import logging

import pytest

from agent_harness.context.builder import ContextBuilder
from agent_harness.session import MODEL_COMPLETED, TOOL_RESULT, USER_MESSAGE
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel


@pytest.mark.asyncio
async def test_build_preserves_tool_pairs_and_persistent_history(tmp_path, caplog):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "读取文件，保留中文约束"})
    session.append(MODEL_COMPLETED, {
        "content": "",
        "tool_calls": [{"id": "read-1", "name": "read", "args": {"path": "x"}}],
    })
    session.append(TOOL_RESULT, {"tool_call_id": "read-1", "content": "文件内容"})
    before = session.events
    model = ScriptedModel([])
    builder = ContextBuilder(model)

    with caplog.at_level(logging.DEBUG, logger="agent_harness.context"):
        messages = await builder.build(session)

    assert messages == session.derive_messages()
    assert session.events == before
    assert model.snapshots == []
    assert any(getattr(record, "token_estimate", 0) > 0 for record in caplog.records)


@pytest.mark.asyncio
async def test_build_empty_session_returns_no_messages(tmp_path):
    session = make_session(tmp_path)
    assert await ContextBuilder(ScriptedModel([])).build(session) == []
