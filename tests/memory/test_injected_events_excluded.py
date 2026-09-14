"""T8 缺陷修复回归：运行时注入的 `user/message` 不得参与记忆抽取（**本票的灵魂**）。

缺陷：`memory/extractor.py` 的 `has_user_message = any(e.type == USER_MESSAGE for e in events)`
只认事件**类型**。而同错熔断的纠偏消息正是 runtime 自己 append 的 `USER_MESSAGE`
（带 `injected_by` 标记）——于是"窗口里有用户消息"恒真，LLM 声明的 USER 候选
**不再降级**为 SESSION。后果：工具输出里的一句注入指令，只要熔断触发过一次，就能被
洗成 USER 作用域（跨会话存活）的记忆，并在此后每个 session 的 SystemMessage 里回灌。

修法是 `extract()` 入口的**单点结构化过滤**（剔出 `injected_by` 非空的事件），
不是内容启发式。本文件同时锁"修好了"与"没修过头"两个方向。

【票面一处自相矛盾，已按实际语义实现】票面测试表写 `events = [一条带
injected_by 的 user/message]` 期望得到被降级的 SESSION 候选；但票面同时要求
"过滤后空集必须提前返回、不调模型"。单条注入事件过滤后就是空集，因此遍历
那一条期望得到候选在票面自身约束下不可达。本文件的处理：空集形态由
`test_all_injected_returns_empty_outcome` 固定，降级保护由"非注入内容 + 注入
消息"的混合窗口固定（这也是真实攻击形态）。
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from agent_harness.memory.extractor import MemoryExtractor
from agent_harness.memory.types import MemoryScope
from agent_harness.session import TOOL_RESULT, USER_MESSAGE, SessionEvent

SENTINEL = "INJECTED_SENTINEL_7c41"

USER_CANDIDATE = json.dumps(
    [{"scope": "user", "content": "用户喜欢 TypeScript", "importance": 0.9}]
)


def _event(
    seq: int, event_type: str, data: dict, session_id: str = "s",
) -> SessionEvent:
    return SessionEvent(seq=seq, type=event_type, session_id=session_id, data=data)


def _injected(seq: int = 0, content: str = f"注入样板 {SENTINEL}") -> SessionEvent:
    return _event(seq, USER_MESSAGE, {"content": content, "injected_by": "tool_failure_guard"})


def _real_user(seq: int = 0, content: str = "我喜欢 TypeScript") -> SessionEvent:
    return _event(seq, USER_MESSAGE, {"content": content})


class _CapturingModel:
    def __init__(self, response: str = USER_CANDIDATE) -> None:
        self._response = response
        self.calls = 0
        self.seen: list = []

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        self.seen = list(messages)
        return AIMessage(content=self._response)


# —— 正向回归：缺陷本身 ——

@pytest.mark.asyncio
async def test_injected_user_message_does_not_satisfy_has_user_message():
    """**修复前这条是红的**：窗口里有工具输出（夹带注入指令）+ 一条注入的
    user/message 时，LLM 的 USER 候选必须被降级为 SESSION。

    形状说明：**不能只用那一条注入消息**——过滤后为空集会走提前返回
    （见 `test_all_injected_returns_empty_outcome`），那样测的是"空集"而不是
    "降级保护"。要让降级路径活跃，窗口里必须有非注入内容（此处是工具输出），
    这也正是真实攻击形态：工具输出夹带注入指令 + 熔断注入了纠偏消息。
    """
    events = [
        _event(0, TOOL_RESULT, {"tool_call_id": "c1", "content": "工具输出"}),
        _injected(1),
    ]
    outcome = await MemoryExtractor(_CapturingModel()).extract(events)

    assert outcome.candidates == [
        (MemoryScope.SESSION, "用户喜欢 TypeScript", {
            "importance": 0.9, "provenance": "demoted_no_user_message",
        })
    ]


@pytest.mark.asyncio
async def test_missing_user_message_with_injected_only():
    """同一保护的另一种窗口形态（run/completed + 注入消息）→ 降级仍生效。"""
    events = [
        _event(0, "run/completed", {"final_text": "完成了"}),
        _injected(1),
    ]
    outcome = await MemoryExtractor(_CapturingModel()).extract(events)

    assert outcome.candidates[0][0] is MemoryScope.SESSION
    assert outcome.candidates[0][2]["provenance"] == "demoted_no_user_message"


# —— 反向回归：不能修过头 ——

@pytest.mark.asyncio
async def test_real_user_message_still_allows_user_scope():
    """真实用户消息（无标记）仍然有效——USER 候选保持 USER。"""
    outcome = await MemoryExtractor(_CapturingModel()).extract([_real_user()])

    assert outcome.candidates[0][0] is MemoryScope.USER
    assert "provenance" not in outcome.candidates[0][2]


@pytest.mark.asyncio
async def test_real_events_still_visible_to_llm():
    """过滤只剔注入：同一批里的真实事件必须仍在 transcript 里。"""
    model = _CapturingModel()
    events = [_real_user(0), _injected(1)]

    await MemoryExtractor(model).extract(events)

    blob = json.dumps([m.content for m in model.seen], ensure_ascii=False)
    assert "我喜欢 TypeScript" in blob
    assert SENTINEL not in blob


@pytest.mark.asyncio
async def test_injected_events_excluded_from_llm_transcript():
    model = _CapturingModel()
    await MemoryExtractor(model).extract([_injected(), _real_user(1)])

    blob = json.dumps([m.content for m in model.seen], ensure_ascii=False)
    assert SENTINEL not in blob


@pytest.mark.asyncio
async def test_injected_only_never_reaches_heuristic_path():
    """全注入 → 入口过滤成空集 → 提前返回，**连规则路径都不进**。

    注意本用例走的是 `if not events` 提前返回，不是 `_heuristic_extract`。
    规则路径自身的过滤覆盖在
    `test_heuristic_path_ignores_injected_but_keeps_real_preference`。
    """
    class _Failing:
        async def ainvoke(self, messages, **kwargs):
            raise ValueError("boom")

    injected = _injected(content=f"我喜欢被注入 {SENTINEL}")
    outcome = await MemoryExtractor(_Failing()).extract([injected])

    assert outcome.candidates == []
    assert outcome.degraded_reason is None, "过滤后空集应提前返回，不进降级路径"


@pytest.mark.asyncio
async def test_heuristic_path_ignores_injected_but_keeps_real_preference():
    """规则路径的正向对照：真实偏好抽得出，注入的同类文案抽不出。"""
    class _Failing:
        async def ainvoke(self, messages, **kwargs):
            raise ValueError("boom")

    events = [
        _injected(0, "我喜欢被注入"),
        _real_user(1, "我喜欢 Rust"),
    ]
    outcome = await MemoryExtractor(_Failing()).extract(events)

    assert outcome.candidates
    assert all("被注入" not in row[1] for row in outcome.candidates)
    assert any(row[1] == "我喜欢 Rust" for row in outcome.candidates)


# —— 空集与语义边界 ——

@pytest.mark.asyncio
async def test_all_injected_returns_empty_outcome():
    model = _CapturingModel()
    outcome = await MemoryExtractor(model).extract([_injected(0), _injected(1)])

    assert outcome.candidates == []
    assert outcome.degraded_reason is None
    assert model.calls == 0, "全注入 → 提前返回，不该白烧一次模型调用"


@pytest.mark.asyncio
async def test_injected_marker_with_whitespace_treated_as_not_injected():
    """**语义边界**：`injected_by="  "` 是纯空白 → 不算标记。"""
    model = _CapturingModel()
    event = _event(0, USER_MESSAGE, {"content": f"空白标记 {SENTINEL}", "injected_by": "  "})

    outcome = await MemoryExtractor(model).extract([event])

    assert model.calls == 1, "空白标记不算注入 → 事件照常参与"
    assert outcome.candidates[0][0] is MemoryScope.USER, "真实用户消息语义保持"


@pytest.mark.asyncio
async def test_empty_marker_not_injected():
    """`injected_by=""` 不算注入（键存在 ≠ 是注入）。"""
    model = _CapturingModel()
    event = _event(0, USER_MESSAGE, {"content": "我喜欢 Go", "injected_by": ""})

    outcome = await MemoryExtractor(model).extract([event])

    assert model.calls == 1
    assert outcome.candidates[0][0] is MemoryScope.USER


@pytest.mark.asyncio
async def test_non_dict_data_is_not_injected():
    """`data` 非 dict（异常形态）→ 不抛错、不视为注入。"""
    model = _CapturingModel()
    event = SessionEvent(seq=0, type=USER_MESSAGE, session_id="s", data="not-a-dict")

    outcome = await MemoryExtractor(model).extract([event])

    assert model.calls == 1
    assert outcome.candidates[0][0] is MemoryScope.USER


@pytest.mark.asyncio
async def test_non_string_marker_is_not_injected():
    """`injected_by` 非字符串（异常形态）→ 不视为注入。"""
    model = _CapturingModel()
    event = _event(0, USER_MESSAGE, {"content": "我喜欢 Elixir", "injected_by": 1})

    outcome = await MemoryExtractor(model).extract([event])

    assert model.calls == 1
    assert outcome.candidates[0][0] is MemoryScope.USER


def test_filter_helper_semantics_directly():
    """直接钉判定函数本身（避免只靠端到端间接覆盖）。"""
    from agent_harness.memory.extractor import _is_runtime_injected

    assert _is_runtime_injected(_injected()) is True
    assert _is_runtime_injected(_real_user()) is False
    assert _is_runtime_injected(
        _event(0, USER_MESSAGE, {"content": "x", "injected_by": ""})
    ) is False
    assert _is_runtime_injected(
        _event(0, USER_MESSAGE, {"content": "x", "injected_by": "   "})
    ) is False
    assert _is_runtime_injected(
        _event(0, USER_MESSAGE, {"content": "x", "injected_by": 1})
    ) is False
