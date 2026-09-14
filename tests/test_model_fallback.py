"""Model Fallback 单元测试（T5, #80, ADR-0014 决策 14/15/16）。

覆盖三层：
1. is_transient_model_error：错误分类 helper（httpx / openai 风格 / 内建）；
2. TwoLevelFallbackPolicy：瞬时切换、非瞬时直接失败；
3. ModelFallbackCoordinator：调用编排（切换、never 切回、事件外漏）。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from langchain_core.messages import AIMessage

from agent_harness.model.concurrency import ModelCallGate
from agent_harness.model.fallback import (
    FallbackTransition,
    ModelFallbackCoordinator,
    TwoLevelFallbackPolicy,
    is_transient_model_error,
)
from tests.scripted_model import ScriptedModel

# ---- 1. is_transient_model_error（决策 15：共享 helper，policy 复用） ----


class _OpenAIStyleError(Exception):
    """模拟 openai.APIStatusError 形状：带 status_code 属性。"""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code


class APITimeoutError(Exception):
    """模拟 openai.APITimeoutError：无 status_code，按类名识别（与真实 SDK 同名）。"""


class APIConnectionError(Exception):
    """模拟 openai.APIConnectionError：无 status_code，按类名识别（与真实 SDK 同名）。"""


class TestIsTransientModelError:
    @pytest.mark.parametrize("exc", [
        httpx.TimeoutException("t"),
        httpx.ConnectTimeout("t"),
        httpx.ReadTimeout("t"),
        httpx.ConnectError("refused"),
        httpx.ReadError("reset"),
    ])
    def test_httpx_transport_failures_are_transient(self, exc):
        assert is_transient_model_error(exc) is True

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
    def test_5xx_and_429_are_transient(self, status):
        request = httpx.Request("POST", "https://api.example.com/v1/chat")
        response = httpx.Response(status, request=request)
        assert is_transient_model_error(httpx.HTTPStatusError(
            "server error", request=request, response=response,
        )) is True
        assert is_transient_model_error(_OpenAIStyleError(status)) is True

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_auth_and_argument_errors_are_not_transient(self, status):
        request = httpx.Request("POST", "https://api.example.com/v1/chat")
        response = httpx.Response(status, request=request)
        assert is_transient_model_error(httpx.HTTPStatusError(
            "client error", request=request, response=response,
        )) is False
        # 认证错/参数错换一台模型也没用——直接失败，绝不盲切（决策 1）。
        assert is_transient_model_error(_OpenAIStyleError(status)) is False

    @pytest.mark.parametrize("exc", [
        APITimeoutError("t"),
        APIConnectionError("c"),
        TimeoutError("asyncio timeout"),
        ConnectionError("socket refused"),
    ])
    def test_timeout_and_connection_shaped_errors_are_transient(self, exc):
        assert is_transient_model_error(exc) is True

    @pytest.mark.parametrize("exc", [
        ValueError("bad args"),
        KeyError("missing"),
        RuntimeError("unknown"),
    ])
    def test_unclassified_errors_are_not_transient(self, exc):
        assert is_transient_model_error(exc) is False


# ---- 2. TwoLevelFallbackPolicy（决策 14：默认实现） ----


class TestTwoLevelFallbackPolicy:
    def test_transient_errors_pass(self):
        policy = TwoLevelFallbackPolicy()
        assert policy.should_fallback(httpx.ConnectError("refused")) is True
        assert policy.should_fallback(TimeoutError("t")) is True

    def test_non_transient_errors_blocked(self):
        policy = TwoLevelFallbackPolicy()
        assert policy.should_fallback(ValueError("bad")) is False


# ---- 3. ModelFallbackCoordinator（决策 14/16：编排 + never 切回） ----


class _FlakyModel:
    """第 fail_times 次 ainvoke 抛指定异常，之后委托 inner。"""

    def __init__(self, inner: ScriptedModel, fail_times: int, error: Exception) -> None:
        self._inner = inner
        self._fail_times = fail_times
        self._error = error
        self.calls = 0

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return await self._inner.ainvoke(messages, **kwargs)

    async def astream(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        async for chunk in self._inner.astream(messages, **kwargs):
            yield chunk


class _BrokenStreamModel:
    """astream 先吐一个 chunk 再抛瞬时异常（测流中途切换）。"""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        raise NotImplementedError

    async def astream(self, messages, **kwargs):
        yield AIMessageChunk(content="partial ")
        raise self._error


from langchain_core.messages import AIMessageChunk


def _answer(text: str) -> ScriptedModel:
    return ScriptedModel([AIMessage(content=text)])


class TestCoordinatorAinvoke:
    @pytest.mark.asyncio
    async def test_primary_success_no_transition(self):
        coordinator = ModelFallbackCoordinator(
            primary=_answer("from primary"), fallback=_answer("from fallback"),
            primary_name="primary-model", fallback_name="fallback-model",
        )
        ai = await coordinator.ainvoke([])
        assert ai.content == "from primary"
        assert coordinator.drain_transitions() == []

    @pytest.mark.asyncio
    async def test_transient_failure_switches_to_fallback(self):
        primary = _FlakyModel(_answer("unused"), 1, TimeoutError("t"))
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=_answer("from fallback"),
            primary_name="primary-model", fallback_name="fallback-model",
        )
        ai = await coordinator.ainvoke([])
        assert ai.content == "from fallback"
        transitions = coordinator.drain_transitions()
        assert transitions == [FallbackTransition(
            from_model="primary-model", to_model="fallback-model",
            reason="TimeoutError",
        )]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            (TimeoutError("t"), "TimeoutError"),
            # 真实事故的错误形状：provider 5xx（按 status_code 判瞬时）
            (_OpenAIStyleError(500), "_OpenAIStyleError"),
        ],
    )
    async def test_ainvoke_fallback_retry_reacquires_concurrency_slot(self, error, reason):
        """回归（真实事故 2026-09-11）：**带并发闸时**回退重试必须能再拿一次槽位。

        事故形状：`ainvoke` 把 `gate.slot()` 的返回值（`@asynccontextmanager` 产物）
        复用给第二次 `async with`。那是**一次性** CM，二次进入抛
        `AttributeError: '_AsyncGeneratorContextManager' object has no attribute 'args'`
        → 非流式 run（`runtime.py` 的 `if stream:` else 分支，含 delegate 子会话）
        在主模型瞬断时**永远回退不了**，直接 `model/failed` + `run/failed`。

        为什么既有用例一直是绿的：`gate=None` 时走 `nullcontext`，而 `nullcontext`
        可重复进入；生产恒带闸（`model_max_concurrency` 默认 3）。本用例是**唯一**
        覆盖「闸 + ainvoke 回退重试」组合的地方，且两种错误形状都要覆盖——5xx 走
        `status_code` 分支判瞬时，若哪天包装层丢掉该属性，子会话会静默不再回退。
        """
        gate = ModelCallGate(limit=1)
        primary = _FlakyModel(_answer("unused"), 1, error)
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=_answer("from fallback"),
            primary_name="primary-model", fallback_name="fallback-model",
            gate=gate,
        )
        ai = await coordinator.ainvoke([])
        assert ai.content == "from fallback"
        assert coordinator.drain_transitions() == [FallbackTransition(
            from_model="primary-model", to_model="fallback-model", reason=reason,
        )]
        # 槽位不得泄漏：两次尝试都必须已释放，否则并发上限被永久吃掉。
        # 这是**前向守卫**（原缺陷在取槽前就抛，故它抓不到原缺陷本身）；
        # limit=1 时真泄漏会在这里拿不到槽位而超时。
        async with asyncio.timeout(1):
            async with gate.slot():
                pass

    @pytest.mark.asyncio
    async def test_ainvoke_retry_once_when_fallback_also_fails(self):
        """回退也瞬时失败：只重试一次、上抛回退的异常，且两个 arm 都不泄漏槽位。"""
        gate = ModelCallGate(limit=1)
        primary = _FlakyModel(_answer("unused"), 1, TimeoutError("primary down"))
        fallback = _FlakyModel(_answer("unused"), 1, TimeoutError("fallback down"))
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=fallback,
            primary_name="primary-model", fallback_name="fallback-model",
            gate=gate,
        )
        with pytest.raises(TimeoutError, match="fallback down"):
            await coordinator.ainvoke([])
        assert primary.calls == 1, "primary 只应尝试一次"
        assert fallback.calls == 1, "fallback 只应尝试一次（不无限重试）"
        async with asyncio.timeout(1):
            async with gate.slot():
                pass

    @pytest.mark.asyncio
    async def test_non_transient_failure_reraises(self):
        primary = _FlakyModel(_answer("unused"), 1, ValueError("bad args"))
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=_answer("from fallback"),
        )
        with pytest.raises(ValueError, match="bad args"):
            await coordinator.ainvoke([])
        assert coordinator.drain_transitions() == []

    @pytest.mark.asyncio
    async def test_no_fallback_reraises(self):
        primary = _FlakyModel(_answer("unused"), 1, TimeoutError("t"))
        coordinator = ModelFallbackCoordinator(primary=primary)
        with pytest.raises(TimeoutError):
            await coordinator.ainvoke([])
        assert coordinator.drain_transitions() == []

    @pytest.mark.asyncio
    async def test_never_switch_back_after_switch(self):
        """切换后本 run 后续调用沿用 fallback，且不产生新 transition。"""
        primary = _FlakyModel(_answer("unused"), 1, TimeoutError("t"))
        fallback = ScriptedModel([
            AIMessage(content="from fallback"),
            AIMessage(content="from fallback 2"),
        ])
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=fallback,
        )
        await coordinator.ainvoke([])
        assert len(coordinator.drain_transitions()) == 1  # 第一次切换的事实
        second = await coordinator.ainvoke([])
        assert second.content == "from fallback 2"  # fallback 剧本第 2 条
        assert primary.calls == 1  # 第二次不再碰 primary
        assert len(coordinator.drain_transitions()) == 0  # 无第二条事件

    @pytest.mark.asyncio
    async def test_fallback_failure_propagates(self):
        """fallback 也失败 → 异常上抛（Runtime 走统一失败兜底）。"""
        broken_fallback = _FlakyModel(_answer("x"), 99, RuntimeError("down"))
        primary = _FlakyModel(_answer("unused"), 1, TimeoutError("t"))
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=broken_fallback,
        )
        with pytest.raises(RuntimeError, match="down"):
            await coordinator.ainvoke([])


class TestCoordinatorAstream:
    @pytest.mark.asyncio
    async def test_stream_switch_midway(self):
        """流中途瞬时失败 → 切 fallback 继续产出（前缀 + fallback 续写）。"""
        primary = _BrokenStreamModel(TimeoutError("t"))
        fallback = ScriptedModel([AIMessage(content="hello world")])
        fallback.chunk_size = 6
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=fallback,
        )
        pieces = []
        async for chunk in coordinator.astream([]):
            pieces.append(chunk.content)
        assert "".join(pieces).startswith("partial ")
        assert "hello world" in "".join(pieces)
        transitions = coordinator.drain_transitions()
        assert len(transitions) == 1
        assert transitions[0].reason == "TimeoutError"

    @pytest.mark.asyncio
    async def test_stream_non_transient_reraises(self):
        primary = _BrokenStreamModel(ValueError("bad"))
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=_answer("x"),
        )
        with pytest.raises(ValueError, match="bad"):
            async for _chunk in coordinator.astream([]):
                pass


class TestFallbackTransition:
    def test_is_frozen(self):
        import dataclasses

        t = FallbackTransition(from_model="a", to_model="b", reason="TimeoutError")
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.from_model = "c"  # type: ignore[misc]
