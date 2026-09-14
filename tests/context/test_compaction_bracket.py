"""T4 #134：dsh 4-event compaction bracket 测试。

验证压缩从单个 CONTEXT_COMPACTED 升级为 replay 确定性 bracket：
  COMPACTION_START (source_seq_start, source_seq_end)
  → CONTEXT_COMPACTED (six_section summary + source 区间)
  → USER_MESSAGE(replace) — 摘要替代被压缩段
  → COMPACTION_END (bracket_id)

原始被压缩事件保留在 JSONL 里（shadowed），derive_messages 跳过。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_harness.context.builder import ContextBuilder
from agent_harness.context.compactor import ContextCompactor
from agent_harness.context.tokens import estimate_message_tokens
from agent_harness.session import (
    COMPACTION_END,
    COMPACTION_START,
    CONTEXT_COMPACTED,
    MODEL_COMPLETED,
    USER_MESSAGE,
    SessionEvent,
)
from agent_harness.session.derive import derive_messages
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel

# ── 六段式摘要 fixture ──────────────────────────────────────────────

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
- 用户已确认收到文件内容
- 当前工作目录为 /workspace"""


# ── derive_messages 识别 bracket 边界 ───────────────────────────────

class TestDeriveMessagesBracket:
    """derive_messages 正确识别 4-event bracket，跳过 shadowed 段。"""

    def test_shadowed_events_skipped(self):
        """COMPACTION_START..COMPACTION_END 之间的原始事件被跳过。"""
        events = [
            SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1",
                         data={"content": "old message"}),
            SessionEvent(seq=2, type=MODEL_COMPLETED, session_id="s1",
                         data={"content": "old reply"}),
            # bracket 开始：shadow seq 1-2
            SessionEvent(seq=3, type=COMPACTION_START, session_id="s1",
                         data={"source_seq_start": 1, "source_seq_end": 2}),
            SessionEvent(seq=4, type=CONTEXT_COMPACTED, session_id="s1",
                         data={"summary": SIX_SECTION_SUMMARY,
                               "schema": "six_section",
                               "source_seq_start": 1, "source_seq_end": 2}),
            SessionEvent(seq=5, type=COMPACTION_END, session_id="s1",
                         data={"bracket_id": "b1"}),
            # bracket 后的正常事件
            SessionEvent(seq=6, type=USER_MESSAGE, session_id="s1",
                         data={"content": "current request"}),
        ]
        messages = derive_messages(events)
        # shadowed 的 seq 1-2 不应出现；只有 summary + current request
        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert SIX_SECTION_SUMMARY in messages[0].content
        assert isinstance(messages[1], HumanMessage)
        assert messages[1].content == "current request"

    def test_no_bracket_passes_through(self):
        """没有 bracket 时，derive_messages 行为不变。"""
        events = [
            SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1",
                         data={"content": "hello"}),
            SessionEvent(seq=2, type=MODEL_COMPLETED, session_id="s1",
                         data={"content": "world"}),
        ]
        messages = derive_messages(events)
        assert len(messages) == 2

    def test_multiple_brackets(self):
        """多个不重叠的 bracket 都被正确跳过。"""
        events = [
            SessionEvent(seq=1, type=USER_MESSAGE, session_id="s1",
                         data={"content": "first old"}),
            # 第一个 bracket
            SessionEvent(seq=2, type=COMPACTION_START, session_id="s1",
                         data={"source_seq_start": 1, "source_seq_end": 1}),
            SessionEvent(seq=3, type=CONTEXT_COMPACTED, session_id="s1",
                         data={"summary": "first summary",
                               "schema": "six_section",
                               "source_seq_start": 1, "source_seq_end": 1}),
            SessionEvent(seq=4, type=COMPACTION_END, session_id="s1",
                         data={"bracket_id": "b1"}),
            # 中间的正常事件
            SessionEvent(seq=5, type=USER_MESSAGE, session_id="s1",
                         data={"content": "second old"}),
            # 第二个 bracket
            SessionEvent(seq=6, type=COMPACTION_START, session_id="s1",
                         data={"source_seq_start": 5, "source_seq_end": 5}),
            SessionEvent(seq=7, type=CONTEXT_COMPACTED, session_id="s1",
                         data={"summary": "second summary",
                               "schema": "six_section",
                               "source_seq_start": 5, "source_seq_end": 5}),
            SessionEvent(seq=8, type=COMPACTION_END, session_id="s1",
                         data={"bracket_id": "b2"}),
            # 最后的正常事件
            SessionEvent(seq=9, type=USER_MESSAGE, session_id="s1",
                         data={"content": "current"}),
        ]
        messages = derive_messages(events)
        # 两个 summary + 一个 current
        assert len(messages) == 3
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], SystemMessage)
        assert isinstance(messages[2], HumanMessage)


# ── ContextCompactor 产生 bracket 元数据 ────────────────────────────

class TestCompactorBracketMetadata:
    """ContextCompactor.compact() 返回 bracket 元数据。"""

    @pytest.mark.asyncio
    async def test_compact_returns_bracket_id_and_summary(self):
        """compact 返回 bracket_id 和 summary。"""
        model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
        messages = [
            HumanMessage(content="old " * 6000),
            AIMessage(content="done"),
            HumanMessage(content="current"),
        ]
        result = await ContextCompactor(
            model, max_context_tokens=8000,
        ).compact(messages, estimate_message_tokens(messages))
        assert result.bracket_id is not None
        assert result.summary == SIX_SECTION_SUMMARY

    @pytest.mark.asyncio
    async def test_compact_summary_is_six_section(self):
        """摘要采用六段式结构。"""
        model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
        messages = [
            HumanMessage(content="old " * 6000),
            AIMessage(content="done"),
            HumanMessage(content="current"),
        ]
        result = await ContextCompactor(
            model, max_context_tokens=8000,
        ).compact(messages, estimate_message_tokens(messages))
        # 摘要消息应该是 SystemMessage，内容包含六段式标记
        assert isinstance(result.messages[0], SystemMessage)
        content = result.messages[0].content
        assert "## 目标" in content or "目标" in content

    @pytest.mark.asyncio
    async def test_shrink_validation_rejects_larger_summary(self):
        """shrink 校验：摘要必须严格小于被压缩段。"""
        # 构造一个会产生超大摘要的场景
        huge_summary = "x" * 10000  # 比原始消息还大的摘要
        model = ScriptedModel([AIMessage(content=huge_summary)])
        messages = [
            HumanMessage(content="short old"),
            AIMessage(content="done"),
            HumanMessage(content="current"),
        ]
        result = await ContextCompactor(
            model, max_context_tokens=8000,
        ).compact(messages, estimate_message_tokens(messages))
        # 应该走 fallback（mechanical summary）
        assert result.fallback_used


# ── ContextBuilder 写 4-event bracket ───────────────────────────────

class TestBuilderWritesBracket:
    """ContextBuilder.build() 写 4-event bracket 而非单个 CONTEXT_COMPACTED。"""

    @pytest.mark.asyncio
    async def test_build_writes_four_event_bracket(self, tmp_path):
        """压缩触发后，session 里应有 COMPACTION_START → CONTEXT_COMPACTED → COMPACTION_END。"""
        session = make_session(tmp_path)
        session.append(USER_MESSAGE, {"content": "old " * 8000})
        session.append(MODEL_COMPLETED, {"content": "done"})
        session.append(USER_MESSAGE, {"content": "current request"})
        before_count = len(session.events)

        model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
        builder = ContextBuilder(model, max_context_tokens=10000)
        await builder.build(session)

        new_events = session.events[before_count:]
        event_types = [e.type for e in new_events]

        # 4-event bracket
        assert COMPACTION_START in event_types
        assert CONTEXT_COMPACTED in event_types
        assert COMPACTION_END in event_types

        # 顺序：START → COMPACTED → END
        start_idx = event_types.index(COMPACTION_START)
        compacted_idx = event_types.index(CONTEXT_COMPACTED)
        end_idx = event_types.index(COMPACTION_END)
        assert start_idx < compacted_idx < end_idx

    @pytest.mark.asyncio
    async def test_build_bracket_source_seq_matches(self, tmp_path):
        """bracket 的 source_seq_start/end 指向被压缩的原始事件。"""
        session = make_session(tmp_path)
        session.append(USER_MESSAGE, {"content": "old " * 8000})
        session.append(MODEL_COMPLETED, {"content": "done"})
        session.append(USER_MESSAGE, {"content": "current request"})
        before_count = len(session.events)

        model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
        builder = ContextBuilder(model, max_context_tokens=10000)
        await builder.build(session)

        new_events = session.events[before_count:]
        start_event = next(e for e in new_events if e.type == COMPACTION_START)
        compacted_event = next(e for e in new_events if e.type == CONTEXT_COMPACTED)

        # source_seq_start 和 source_seq_end 应该指向被压缩的事件
        assert start_event.data["source_seq_start"] == 1
        assert start_event.data["source_seq_end"] == 2
        assert compacted_event.data["source_seq_start"] == 1
        assert compacted_event.data["source_seq_end"] == 2

    @pytest.mark.asyncio
    async def test_build_bracket_has_bracket_id(self, tmp_path):
        """COMPACTION_END 包含 bracket_id。"""
        session = make_session(tmp_path)
        session.append(USER_MESSAGE, {"content": "old " * 8000})
        session.append(MODEL_COMPLETED, {"content": "done"})
        session.append(USER_MESSAGE, {"content": "current request"})
        before_count = len(session.events)

        model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
        builder = ContextBuilder(model, max_context_tokens=10000)
        await builder.build(session)

        new_events = session.events[before_count:]
        end_event = next(e for e in new_events if e.type == COMPACTION_END)
        assert "bracket_id" in end_event.data
        assert end_event.data["bracket_id"]  # non-empty

    @pytest.mark.asyncio
    async def test_build_bracket_context_compacted_has_six_section_schema(self, tmp_path):
        """CONTEXT_COMPACTED 事件包含 schema='six_section' 和 summary。"""
        session = make_session(tmp_path)
        session.append(USER_MESSAGE, {"content": "old " * 8000})
        session.append(MODEL_COMPLETED, {"content": "done"})
        session.append(USER_MESSAGE, {"content": "current request"})
        before_count = len(session.events)

        model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
        builder = ContextBuilder(model, max_context_tokens=10000)
        await builder.build(session)

        new_events = session.events[before_count:]
        compacted_event = next(e for e in new_events if e.type == CONTEXT_COMPACTED)
        assert compacted_event.data["schema"] == "six_section"
        assert "summary" in compacted_event.data

    @pytest.mark.asyncio
    async def test_second_build_after_bracket_skips_shadowed(self, tmp_path):
        """第一次压缩写 bracket 后，第二次 build 的 derive_messages 跳过 shadowed 段。"""
        session = make_session(tmp_path)
        session.append(USER_MESSAGE, {"content": "old " * 8000})
        session.append(MODEL_COMPLETED, {"content": "done"})
        session.append(USER_MESSAGE, {"content": "current request"})

        model = ScriptedModel([AIMessage(content=SIX_SECTION_SUMMARY)])
        builder = ContextBuilder(model, max_context_tokens=10000)
        await builder.build(session)

        # 第二次 build：应该看到 bracket，跳过 shadowed 的 old 消息
        messages = await builder.build(session)
        # 不应包含 "old " * 8000 的 HumanMessage
        old_messages = [m for m in messages if isinstance(m, HumanMessage)
                        and "old" in (m.content or "")]
        assert len(old_messages) == 0, "shadowed 段未被跳过"


# ── 参数融合 ────────────────────────────────────────────────────────

class TestFusedCompactionParameters:
    """PRD §3 参数融合：80% trigger, 90% hard guard, 20k keep recent, reserve max(15%, 16k)。"""

    @pytest.mark.asyncio
    async def test_default_parameters_match_prd(self):
        """ContextCompactor 默认参数匹配 PRD §3。"""
        compactor = ContextCompactor(ScriptedModel([]), max_context_tokens=200_000)
        assert compactor.auto_compact_threshold == 0.80
        assert compactor.hard_guard_threshold == 0.90
        assert compactor.keep_recent_tokens == 20_000
        # reserve = max(15% of 200k, 16384) = max(30000, 16384) = 30000
        assert compactor.reserve == max(int(200_000 * 0.15), 16384)

    @pytest.mark.asyncio
    async def test_builder_default_parameters_match_prd(self):
        """ContextBuilder 默认参数匹配 PRD §3。"""
        builder = ContextBuilder(ScriptedModel([]), max_context_tokens=200_000)
        assert builder.auto_compact_threshold == 0.80
        assert builder.hard_guard_threshold == 0.90
