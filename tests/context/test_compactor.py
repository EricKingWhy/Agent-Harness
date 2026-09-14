"""ContextCompactor/Builder 的压缩与恢复不变量。"""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_harness.context.builder import ContextBuilder
from agent_harness.context.compactor import ContextCompactor, ContextWindowExceededError
from agent_harness.context.tokens import estimate_message_tokens
from agent_harness.session import MODEL_COMPLETED, USER_MESSAGE
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel

SUMMARY = {
    "facts": ["read completed"], "decisions": [], "constraints": ["keep Chinese"],
    "failed_attempts": [], "unresolved": [], "artifact_refs": ["abc123"],
    "citations": [], "tool_outcomes": ["call-1 succeeded"],
}

#: T4 (#134)：六段式摘要 fixture（Pi 风格结构化 Markdown）。
SIX_SECTION_SUMMARY = """## 目标
用户要求读取文件并总结内容。

## 约束
- 必须保持中文回答
- 文件路径必须在 workspace 内

## 进展
已成功读取 old.txt 文件，内容为历史记录。

## 决策
决定直接展示文件内容而非重新生成。

## 下一步
等待用户的新请求。

## 关键上下文
- 历史文件包含 6000 字的旧数据
- 用户已确认收到文件内容"""


@pytest.mark.asyncio
async def test_builder_compacts_old_turn_and_preserves_persistent_history(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "old " * 8000})
    session.append(MODEL_COMPLETED, {"content": "finished"})
    session.append(USER_MESSAGE, {"content": "current request"})
    before = session.events
    model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
    messages = await ContextBuilder(model, max_context_tokens=10000).build(session)
    assert isinstance(messages[0], SystemMessage)
    assert "## 目标" in messages[0].content or "目标" in messages[0].content
    assert messages[1:] == [HumanMessage(content="current request")]
    assert estimate_message_tokens(messages) < 5600
    assert session.events[:-3] == before  # 3 new events: START, COMPACTED, END
    # Verify all 3 bracket events were written
    new_events = session.events[len(before):]
    event_types = [e.type for e in new_events]
    assert "compaction/start" in event_types
    assert "context/compacted" in event_types
    assert "compaction/end" in event_types
    assert len(model.snapshots) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "timeout", "tool_call"])
async def test_summary_failure_falls_back_with_atomic_tool_block(failure):
    class Model:
        async def ainvoke(self, messages):
            if failure == "error":
                raise ConnectionError("offline")
            if failure == "timeout":
                await asyncio.Event().wait()
            if failure == "tool_call":
                return AIMessage(content=SIX_SECTION_SUMMARY, tool_calls=[
                    {"id": "unwanted", "name": "bash", "args": {}},
                ])
            return AIMessage(content="not a summary")

    messages = [
        HumanMessage(content="old " * 1000),
        AIMessage(content="reason", tool_calls=[{"id": "c1", "name": "read", "args": {}}]),
        ToolMessage(content="result " * 1000, tool_call_id="c1"),
        HumanMessage(content="current"),
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "read", "args": {}}]),
        ToolMessage(content="current result", tool_call_id="c2"),
    ]
    result = await ContextCompactor(Model(), max_context_tokens=8000,
                                    summary_timeout_seconds=0.01).compact(
        messages, estimate_message_tokens(messages),
    )
    assert result.fallback_used
    assert result.messages[1:] == messages[3:]
    rows = json.loads(result.messages[0].content)["mechanical_extract"]
    assert rows[0]["content"] == messages[0].content[:200]
    # args 截断为有界字符串（Round 6 加固）：id/name 保留，args 序列化封顶。
    assert rows[1]["tool_calls"] == [{"id": "c1", "name": "read", "args": "{}"}]
    assert rows[2]["tool_call_id"] == "c1"
    assert rows[2]["content"] == messages[2].content[:100]


@pytest.mark.asyncio
async def test_hard_guard_rejects_when_recent_turn_cannot_fit(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "old"})
    session.append(MODEL_COMPLETED, {"content": "done"})
    session.append(USER_MESSAGE, {"content": "current " * 2000})
    before = session.events
    with pytest.raises(ContextWindowExceededError):
        await ContextBuilder(ScriptedModel([]), max_context_tokens=1000).build(session)
    assert session.events == before


@pytest.mark.asyncio
async def test_oversized_summary_falls_back_and_system_constraints_survive():
    huge = {**SUMMARY, "facts": ["huge " * 4000]}
    model = ScriptedModel([AIMessage(content=json.dumps(huge))])
    messages = [SystemMessage(content="Never modify protected files"),
                HumanMessage(content="old"), AIMessage(content="done"),
                HumanMessage(content="current")]
    result = await ContextCompactor(model, max_context_tokens=1000).compact(
        messages, estimate_message_tokens(messages),
    )
    assert result.fallback_used
    assert result.messages[0] == messages[0]
    assert result.messages[-1] == messages[-1]
    assert result.token_estimate <= 850


@pytest.mark.asyncio
async def test_summary_request_over_budget_skips_model_and_records_fallback(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "large " * 10000})
    session.append(MODEL_COMPLETED, {"content": "done"})
    session.append(USER_MESSAGE, {"content": "current"})
    model = ScriptedModel([])
    messages = await ContextBuilder(model, max_context_tokens=1000).build(session)
    assert model.snapshots == []
    # T4 (#134): fallback 标记在 CONTEXT_COMPACTED 事件里
    compacted_event = next(
        e for e in session.events if e.type == "context/compacted"
    )
    assert compacted_event.data["fallback_used"] is True
    assert estimate_message_tokens(messages) <= 850


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed_as_summary_failure():
    class CancelledModel:
        async def ainvoke(self, messages):
            raise asyncio.CancelledError

    messages = [HumanMessage(content="old"), AIMessage(content="done"),
                HumanMessage(content="current")]
    with pytest.raises(asyncio.CancelledError):
        await ContextCompactor(CancelledModel()).compact(messages, 100)


@pytest.mark.asyncio
@pytest.mark.parametrize("results", [[], ["wrong"], ["c1", "c1"]])
async def test_invalid_tool_blocks_rejected_before_model_call(results):
    model = ScriptedModel([])
    messages = [HumanMessage(content="old"), AIMessage(content="", tool_calls=[
        {"id": "c1", "name": "read", "args": {}},
    ]), *[ToolMessage(content="result", tool_call_id=call_id) for call_id in results],
        HumanMessage(content="current")]
    with pytest.raises(ContextWindowExceededError, match="tool"):
        await ContextCompactor(model).compact(messages, 100)
    assert model.snapshots == []


@pytest.mark.asyncio
async def test_single_turn_between_auto_and_hard_guard_does_not_fake_compaction(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "single " * 300})
    count = estimate_message_tokens(session.derive_messages())
    model = ScriptedModel([])
    before = session.events
    messages = await ContextBuilder(model, max_context_tokens=int(count / 0.8)).build(session)
    assert messages == session.derive_messages()
    assert session.events == before
    assert model.snapshots == []


@pytest.mark.parametrize("kwargs", [
    {"max_context_tokens": 0}, {"auto_compact_threshold": 0.95},
    {"hard_guard_threshold": 1.5}, {"auto_compact_threshold": float("nan")},
])
def test_invalid_context_budget_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ContextBuilder(ScriptedModel([]), **kwargs)


@pytest.mark.asyncio
async def test_valid_summary_above_auto_target_uses_smaller_fallback():
    verbose = {**SUMMARY, "facts": ["fact " * 500]}
    response = AIMessage(content=json.dumps(verbose))
    model = ScriptedModel([response])
    messages = [HumanMessage(content="old " * 600), AIMessage(content="done"),
                HumanMessage(content="current")]
    result = await ContextCompactor(
        model, max_context_tokens=1500, auto_compact_threshold=0.3,
    ).compact(messages, estimate_message_tokens(messages))
    assert result.fallback_used
    assert result.token_estimate < 450


# ── Round 6 加固：mechanical 摘要有界性 + 围栏 JSON 容错 ──


def test_mechanical_summary_bounds_tool_call_args():
    """mechanical 摘要必须对 tool_call.args 截断——否则一条带大 payload 的
    tool call（如 write 大文件）会让摘要本身超硬护栏，compaction 永久失败，
    session 从此每次 run 都 context_window_exceeded（历史从不裁剪）。"""
    from agent_harness.context.compactor import _mechanical_summary

    huge_args = {"path": "big.txt", "content": "x" * 100_000}
    messages = [
        HumanMessage(content="old"),
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "write", "args": huge_args}]),
        HumanMessage(content="current"),
    ]
    summary = _mechanical_summary(messages)
    assert len(summary) < 2000  # 与摘要各字段 200/100 字符截断同级的有界性
    assert "x" * 100_000 not in summary  # 大 payload 不整段进入摘要
    rows = json.loads(summary)["mechanical_extract"]  # 整体仍是合法 JSON
    assert rows[1]["tool_calls"][0]["id"] == "c1"
    assert rows[1]["tool_calls"][0]["name"] == "write"


@pytest.mark.asyncio
async def test_huge_tool_call_args_fall_back_without_bricking():
    """大 args + 摘要模型故障 → mechanical 兜底成功，而非永久 ContextWindowExceeded。

    该场景此前一旦发生，历史从不裁剪、投影每轮重建，session 从此无法恢复。
    """
    class FailingModel:
        async def ainvoke(self, messages):
            raise ConnectionError("offline")

    huge_args = {"path": "big.txt", "content": "y" * 100_000}
    messages = [
        HumanMessage(content="old " * 2000),
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "write", "args": huge_args}]),
        ToolMessage(content="written", tool_call_id="c1"),
        HumanMessage(content="current"),
    ]
    result = await ContextCompactor(FailingModel(), max_context_tokens=8000).compact(
        messages, estimate_message_tokens(messages),
    )
    assert result.fallback_used
    assert result.token_estimate < 8000 * 0.85


@pytest.mark.asyncio
async def test_six_section_summary_passes_shrink_validation():
    """六段式摘要通过 shrink 校验（严格小于被压缩段）。"""
    model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
    messages = [
        HumanMessage(content="old " * 6000),
        AIMessage(content="done"),
        HumanMessage(content="current"),
    ]
    result = await ContextCompactor(
        model, max_context_tokens=8000,
    ).compact(messages, estimate_message_tokens(messages))
    assert not result.fallback_used
    assert result.summary == SIX_SECTION_SUMMARY
    assert result.bracket_id is not None
