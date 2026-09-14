"""ContextBuilder 运行时上下文快照注入（T7 / ADR-0023 D8）。

快照是 runtime 装配期上下文（**非事件**）：不写 JSONL、不进 derive_messages、
不进记忆抽取。这些测试覆盖注入位置、开关、callable 语义与预算计入。

污染边界（不落盘 / 不进 derive / 不被抽取）另见
`tests/context/test_runtime_context_persistence.py`。
"""

from __future__ import annotations

import logging

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_harness.context.builder import ContextBuilder
from agent_harness.context.tokens import estimate_message_tokens
from agent_harness.session import (
    COMPACTION_START,
    MODEL_COMPLETED,
    TOOL_RESULT,
    USER_MESSAGE,
)
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel

SNAPSHOT = "RUNTIME_SNAPSHOT_TEXT_9f3a"


class _RecordingProvider:
    """记录每次 select 拿到的 remaining_tokens（验证预算扣减），不注入任何内容。

    `remaining` 由 `hard_guard * max_context_tokens - token_estimate` 算出，所以
    它的差值就是"这次 build 认为已被占用的 token 数"——比断言内部字段更硬。
    """

    def __init__(self) -> None:
        self.remaining: list[int] = []

    async def select(self, session, remaining_tokens):
        self.remaining.append(remaining_tokens)
        return []


class _StaticProvider:
    """返回一条固定 SystemMessage（duck-type Protocol）。"""

    async def select(self, session, remaining_tokens):
        return [SystemMessage(content="[provider 注入]")]


def _snapshot_tokens() -> int:
    return estimate_message_tokens([HumanMessage(content=SNAPSHOT)])


@pytest.mark.asyncio
async def test_runtime_context_injected_before_last_user_message(tmp_path):
    """位置断言：快照紧贴当前用户消息**之前**。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=lambda: SNAPSHOT,
    )

    messages = await builder.build(session)

    assert len(messages) == 2
    assert messages[-1].content == "你好"
    assert messages[-2].content == SNAPSHOT


@pytest.mark.asyncio
async def test_runtime_context_absent_by_default(tmp_path):
    """不传 provider → 行为与 T7 之前逐字节一致（向后兼容）。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    builder = ContextBuilder(ScriptedModel([]))

    assert await builder.build(session) == session.derive_messages()


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
async def test_runtime_context_provider_returning_blank_is_skipped(tmp_path, blank):
    """空串 / 纯空白归一为 None：不插空消息。

    只挡空串不够——`"   "` 在 Python 里为真，会让模型收到一条内容只有空白的
    user 消息，白占预算且语义为零。
    """
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    builder = ContextBuilder(ScriptedModel([]), runtime_context_provider=lambda: blank)

    messages = await builder.build(session)

    assert messages == session.derive_messages()


@pytest.mark.asyncio
async def test_runtime_context_keeps_volatile_text_at_the_tail(tmp_path):
    """prefix cache 稳定性（PRD §224）：易变快照只影响**尾部**。

    两次 build 之间快照文本变化（模拟跨午夜日期滚动），快照**之前**的消息
    序列必须逐字段相同——若把快照放到开头，整条序列都错位，缓存全废。
    """
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    session.append(MODEL_COMPLETED, {"content": "回复一"})

    first = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=lambda: f"{SNAPSHOT}_v1",
    )
    second = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=lambda: f"{SNAPSHOT}_v2",
    )

    messages_a = await first.build(session)
    messages_b = await second.build(session)

    assert len(messages_a) == len(messages_b)
    index_a = next(i for i, m in enumerate(messages_a) if SNAPSHOT in str(m.content))
    index_b = next(i for i, m in enumerate(messages_b) if SNAPSHOT in str(m.content))
    assert index_a == index_b, "快照位置必须稳定，否则前缀照样错位"
    assert messages_a[index_a].content.endswith("_v1")
    assert messages_b[index_b].content.endswith("_v2")
    # 稳定前缀逐字段相同；只有快照那一条变
    assert messages_a[:index_a] == messages_b[:index_b]
    assert messages_a[index_a + 1:] == messages_b[index_b + 1:]


@pytest.mark.asyncio
async def test_runtime_context_midtolloop_position(tmp_path):
    """多步 run 中途（工具回合中）的注入位置（PRD §279 要求 T7 定死并测试）。

    events = user/message → model/completed(tool_calls) → tool/result 时，
    最后一条 HumanMessage 是本回合开头的用户消息 → 快照落在整段历史之前。
    这是 PRD 选定的语义；关键是**不切开** AI(tool_calls)/ToolResult 配对。
    """
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "用工具查一下"})
    session.append(MODEL_COMPLETED, {
        "content": "", "tool_calls": [{"id": "c1", "name": "read", "args": {}}],
    })
    session.append(TOOL_RESULT, {"tool_call_id": "c1", "content": "文件内容"})

    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=lambda: SNAPSHOT,
    )
    messages = await builder.build(session)

    contents = [m.content for m in messages]
    assert contents == [SNAPSHOT, "用工具查一下", "", "文件内容"]

    # 配对未被切开：带 tool_calls 的 AIMessage 紧跟其 ToolMessage
    ai_index = next(
        i for i, m in enumerate(messages)
        if isinstance(m, AIMessage) and m.tool_calls
    )
    assert messages[ai_index + 1].content == "文件内容"
    assert messages[ai_index + 1].tool_call_id == "c1"


@pytest.mark.asyncio
async def test_runtime_context_after_system_prompt_and_providers(tmp_path):
    """完整顺序：[System(system_prompt), System(provider), …历史, Human(快照), Human(当前用户)]。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    builder = ContextBuilder(
        ScriptedModel([]),
        context_providers=[_StaticProvider()],
        system_prompt="你是 coding agent。",
        runtime_context_provider=lambda: SNAPSHOT,
    )

    messages = await builder.build(session)

    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "你是 coding agent。"
    assert isinstance(messages[1], SystemMessage)
    assert messages[1].content == "[provider 注入]"
    assert messages[2].content == SNAPSHOT
    assert messages[3].content == "你好"


@pytest.mark.asyncio
async def test_runtime_context_token_estimated(tmp_path, caplog):
    """快照的 token 成本计入 token_estimate（预算不漏算）。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    session.append(MODEL_COMPLETED, {"content": "你好！"})

    baseline_builder = ContextBuilder(ScriptedModel([]))
    with caplog.at_level(logging.DEBUG, logger="agent_harness.context"):
        await baseline_builder.build(session)
    baseline = next(
        getattr(r, "token_estimate", 0) for r in caplog.records
        if getattr(r, "token_estimate", None)
    )

    caplog.clear()
    with_snapshot_builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=lambda: SNAPSHOT,
    )
    with caplog.at_level(logging.DEBUG, logger="agent_harness.context"):
        await with_snapshot_builder.build(session)
    with_snapshot = next(
        getattr(r, "token_estimate", 0) for r in caplog.records
        if getattr(r, "token_estimate", None)
    )

    assert with_snapshot > baseline


@pytest.mark.asyncio
async def test_runtime_context_rendered_per_build(tmp_path):
    """callable 每次 build 重新取值——日期之类的易变内容不会过期。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    calls: list[int] = []

    def provider() -> str:
        calls.append(len(calls))
        return f"{SNAPSHOT}_v{len(calls)}"

    builder = ContextBuilder(ScriptedModel([]), runtime_context_provider=provider)

    first = await builder.build(session)
    session.append(MODEL_COMPLETED, {"content": "好的。"})
    second = await builder.build(session)

    assert len(calls) == 2, "provider 必须每 build 恰好调用一次"
    assert f"{SNAPSHOT}_v1" in [m.content for m in first]
    assert f"{SNAPSHOT}_v2" in [m.content for m in second]


@pytest.mark.asyncio
async def test_runtime_context_not_duplicated_across_builds(tmp_path):
    """连续 build 不累积（对比"若把快照 append 成事件"会出现的增长）。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=lambda: SNAPSHOT,
    )

    for i in range(3):
        messages = await builder.build(session)
        assert [m.content for m in messages].count(SNAPSHOT) == 1, f"第 {i + 1} 次 build 出现多份快照"
        session.append(MODEL_COMPLETED, {"content": f"回复 {i}"})


@pytest.mark.asyncio
async def test_runtime_context_compaction_path_includes_cost(tmp_path):
    """压缩路径也必须把快照的 token 成本计入 provider 预算。

    断言方式：比对 provider 实际拿到的 `remaining_tokens`——有快照时应恰好少
    一个快照的 token 数。这直接验证"预算没被超发"，而不是只看内部字段。
    """
    def fill(session):
        for i in range(5):
            session.append(USER_MESSAGE, {"content": f"这是第 {i} 条用户消息，内容稍长以触发压缩。"})
            session.append(MODEL_COMPLETED, {"content": f"这是第 {i} 条模型回复，同样稍长一些。"})

    def builder_with(**kwargs) -> ContextBuilder:
        return ContextBuilder(
            ScriptedModel([]), max_context_tokens=500,
            auto_compact_threshold=0.70, hard_guard_threshold=0.85, **kwargs,
        )

    session_a = make_session(tmp_path / "a")
    fill(session_a)
    provider_a = _RecordingProvider()
    builder_a = builder_with(
        context_providers=[provider_a], runtime_context_provider=lambda: SNAPSHOT,
    )
    await builder_a.build(session_a)

    # 控制断言：必须真的走了压缩路径，否则本测试测的是另一条分支
    assert any(e.type == COMPACTION_START for e in session_a.events), "未触发压缩路径"

    session_b = make_session(tmp_path / "b")
    fill(session_b)
    provider_b = _RecordingProvider()
    builder_b = builder_with(context_providers=[provider_b])
    await builder_b.build(session_b)
    assert any(e.type == COMPACTION_START for e in session_b.events), "未触发压缩路径"

    assert provider_a.remaining and provider_b.remaining
    assert len(provider_a.remaining) == 1, "压缩路径 provider 也只应被调用一次"
    assert provider_a.remaining[0] == provider_b.remaining[0] - _snapshot_tokens(), (
        f"压缩路径的 provider 预算必须扣掉快照成本："
        f"有快照={provider_a.remaining[0]} 无快照={provider_b.remaining[0]}"
    )


@pytest.mark.asyncio
async def test_runtime_context_does_not_change_derive_count(tmp_path):
    """注入前后 `derive_messages()` 长度不变——证明快照没被当成事件投影。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    before = len(session.derive_messages())

    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=lambda: SNAPSHOT,
    )
    await builder.build(session)

    assert len(session.derive_messages()) == before
