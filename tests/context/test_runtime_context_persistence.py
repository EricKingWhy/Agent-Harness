"""T7 快照的污染边界（**本票的灵魂**）——ADR-0023 D8。

快照的价值不在"多给模型几句话"，而在三个污染面一次性消失：

| 污染面 | 若快照落成事件会怎样 | 本文件的测试 |
|---|---|---|
| JSONL 持久化 | 快照变成历史事实，永久滞留并被后续会话回放 | `test_snapshot_not_in_jsonl_file` |
| `derive_messages()` 回放 | 每轮把快照当历史重放，累积多份 | `test_snapshot_not_in_derive_messages` |
| 记忆抽取 | `has_user_message` 一旦为真，LLM 声明的 USER 候选不再降级为 SESSION | `test_snapshot_not_visible_to_memory_extractor` |

**不需要新增任何过滤器**——"非持久化"这一个动作同时解决三者（ADR-0023 D8）。
最后一条测试是**防假绿**的：若扫描函数本身写错，前面几条会全绿而毫无意义。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agent_harness.context.builder import ContextBuilder
from agent_harness.memory.extractor import MemoryExtractor
from agent_harness.memory.types import MemoryScope
from agent_harness.session import TOOL_RESULT, USER_MESSAGE
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel

#: 唯一哨兵：快照文本里塞一个不会自然出现的串，扫不到它就说明真没落盘。
SENTINEL = "SNAPSHOT_SENTINEL_9f3a"


def _snapshot_text() -> str:
    return f"运行时事实：cwd=/tmp；随机标记 {SENTINEL}。"


def _contains_sentinel(value: Any) -> bool:
    """递归扫描任意嵌套结构（str / dict / list / 其他 → repr）。"""
    if isinstance(value, str):
        return SENTINEL in value
    if isinstance(value, dict):
        return any(
            _contains_sentinel(k) or _contains_sentinel(v) for k, v in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_contains_sentinel(v) for v in value)
    return SENTINEL in repr(value)


def _jsonl_path(tmp_path, session) -> Path:
    return tmp_path / session.session_id / "events.jsonl"


@pytest.mark.asyncio
async def test_snapshot_not_appended_to_session(tmp_path):
    """不调 session.append：事件条数完全相等，且没有任何事件的 content/data 含快照。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    before = len(session.events)

    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=_snapshot_text,
    )
    await builder.build(session)

    assert len(session.events) == before, "快照绝不能变成事件"
    for event in session.events:
        assert not _contains_sentinel(event.data), f"事件 {event.type} 携带了快照文本"


@pytest.mark.asyncio
async def test_snapshot_not_in_derive_messages(tmp_path):
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})

    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=_snapshot_text,
    )
    built = await builder.build(session)

    # 注入确实发生了（否则本测试是空转）
    assert any(SENTINEL in m.content for m in built)
    # 但投影看不见它
    assert not any(_contains_sentinel(m.content) for m in session.derive_messages())


@pytest.mark.asyncio
async def test_snapshot_not_in_jsonl_file(tmp_path):
    """真实落盘文件里不含快照文本——持久化面彻底干净。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})

    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=_snapshot_text,
    )
    built = await builder.build(session)

    # 前置：注入确实发生了——否则"盘上没有哨兵"是废话（空转）
    assert any(SENTINEL in m.content for m in built)
    assert SENTINEL not in _jsonl_path(tmp_path, session).read_text(encoding="utf-8"), (
        "快照不得出现在 events.jsonl 里"
    )


class _CapturingModel:
    """记录 ainvoke 收到的 messages（供断言抽取输入），并返回固定候选。"""

    def __init__(self, response: str) -> None:
        self._response = response
        self.seen: list = []

    async def ainvoke(self, messages, **kwargs):
        self.seen = list(messages)
        return AIMessage(content=self._response)


def _extract_response() -> str:
    return json.dumps([{"scope": "user", "content": "用户喜欢 TypeScript", "importance": 0.9}])


@pytest.mark.asyncio
async def test_snapshot_not_visible_to_memory_extractor(tmp_path):
    """抽取输入来自 session events，快照不在其中（模型收到的 messages 无哨兵）。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})

    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=_snapshot_text,
    )
    built = await builder.build(session)
    assert any(SENTINEL in m.content for m in built)  # 注入确实发生

    model = _CapturingModel(_extract_response())
    await MemoryExtractor(model).extract(session.events)

    assert model.seen, "抽取必须真的调用了模型"
    assert not any(_contains_sentinel(m.content) for m in model.seen), (
        "快照不得进入抽取 prompt"
    )


@pytest.mark.asyncio
async def test_extraction_outcome_unaffected_by_snapshot(tmp_path):
    """行为等价：build 过快照与没 build 过，抽取结果逐字段相同。

    **必须让"没有用户消息"这条降级路径保持活跃**（窗口里只有 tool/result），
    否则 `has_user_message` 恒为真、两边结果天然相同，本断言就检不出污染——
    快照真被 append 成 USER 事件时它也照样绿（空转）。

    有降级路径在，本断言才与污染耦合：若快照落成 USER 事件，
    `with_snapshot` 一侧 `has_user_message` 翻真 → 候选不再降级 → 两边不等 → 红。
    """
    def make(name: str):
        session = make_session(tmp_path / name)
        session.append(TOOL_RESULT, {"tool_call_id": "c1", "content": "ok"})
        return session

    plain = make("plain")
    with_snapshot = make("snapshot")

    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=_snapshot_text,
    )
    await builder.build(with_snapshot)

    model_a, model_b = _CapturingModel(_extract_response()), _CapturingModel(_extract_response())
    a = await MemoryExtractor(model_a).extract(plain.events)
    b = await MemoryExtractor(model_b).extract(with_snapshot.events)

    # 前置：降级路径确实被走到了（否则本测试退化为空转）
    assert a.candidates[0][0] is MemoryScope.SESSION, "无用户消息时 USER 候选必须降级"
    assert a.candidates == b.candidates
    assert a.degraded_reason == b.degraded_reason
    # 抽取输入里没有快照文本（否则下面的降级事实无从保证）
    assert not any(_contains_sentinel(m.content) for m in model_b.seen)


@pytest.mark.asyncio
async def test_user_message_demotion_still_applies(tmp_path):
    """**回归本质**：窗口内只有 tool/result 时，即使刚 build 过快照，
    LLM 声明的 USER 候选仍被降级为 SESSION（证明快照没把 has_user_message 变成 True）。"""
    session = make_session(tmp_path)
    session.append(TOOL_RESULT, {"tool_call_id": "c1", "content": "工具输出"})

    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=_snapshot_text,
    )
    await builder.build(session)

    outcome = await MemoryExtractor(_CapturingModel(_extract_response())).extract(session.events)

    assert outcome.candidates, "应有候选（否则本测试空转）"
    scope, _, metadata = outcome.candidates[0]
    assert scope is MemoryScope.SESSION, "无用户消息窗口里 USER 候选必须降级"
    assert metadata["provenance"] == "demoted_no_user_message"


@pytest.mark.asyncio
async def test_scanner_detects_planted_sentinel(tmp_path):
    """**防假绿**：同一套扫描手段对"真落盘的哨兵"必须报警。

    若这条红了，说明上面的扫描函数/路径写错了——那前几条"干净"结论全是假的。
    """
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": f"手写哨兵 {SENTINEL}"})

    # 事件层
    assert any(_contains_sentinel(e.data) for e in session.events)
    # 投影层
    assert any(_contains_sentinel(m.content) for m in session.derive_messages())
    # 落盘层
    assert SENTINEL in _jsonl_path(tmp_path, session).read_text(encoding="utf-8")
    # 抽取输入层
    model = _CapturingModel(_extract_response())
    await MemoryExtractor(model).extract(session.events)
    assert any(_contains_sentinel(m.content) for m in model.seen)


@pytest.mark.asyncio
async def test_snapshot_event_count_stable_across_repeated_builds(tmp_path):
    """连续 build 也不产生事件（"累积多份"的另一种表现形态）。"""
    session = make_session(tmp_path)
    session.append(USER_MESSAGE, {"content": "你好"})
    builder = ContextBuilder(
        ScriptedModel([]), runtime_context_provider=_snapshot_text,
    )

    counts = []
    for _ in range(3):
        await builder.build(session)
        counts.append(len(session.events))

    assert len(set(counts)) == 1, f"build 不得改变事件数：{counts}"
