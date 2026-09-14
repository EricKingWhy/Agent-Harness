"""Model stall watchdog 单元测试（冒烟实测收尾，TDD）。

冒烟实测（session 7afd328a）：上游代理瞬态劣化时，流式 body 以碎片缓速
10 分钟而不断开——fallback 只对"错误"生效，对"还在慢慢流"是盲区。
契约：
- ModelStallError 被分类为瞬时错误（fallback 决策复用同一口径）；
- 看门狗逐 chunk 计时：N 秒无新 chunk → 断开底层流 + 抛 ModelStallError；
- 正常流零干扰（chunk 原样透传、顺序不变）；
- timeout ≤0 时完全旁路（零行为变化）；
- coordinator 集成：primary 卡流 → 判瞬时 → 切 fallback 续流（一条
  transition 事件）；未配 fallback → 异常上抛走统一失败兜底。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from agent_harness.model.fallback import (
    ModelFallbackCoordinator,
    is_transient_model_error,
)
from agent_harness.model.stall import ModelStallError, stream_with_stall_guard
from tests.scripted_model import ScriptedModel


class _ChunkyStreamModel:
    """按剧本产出 chunk 的流式替身：每次 yield 前可注入可控延迟。"""

    def __init__(self, chunks: list[tuple[float, str]], stall_after: bool = False):
        self._chunks = chunks
        self._stall_after = stall_after
        self.closed = False

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        raise NotImplementedError

    async def astream(self, messages, **kwargs) -> AsyncIterator[AIMessageChunk]:
        try:
            for delay, text in self._chunks:
                await asyncio.sleep(delay)
                yield AIMessageChunk(content=text)
            if self._stall_after:
                await asyncio.sleep(9999)
        finally:
            self.closed = True


class TestModelStallErrorClassification:
    def test_stall_error_is_transient(self):
        assert is_transient_model_error(ModelStallError(60.0)) is True


class TestStreamStallGuard:
    @pytest.mark.asyncio
    async def test_normal_stream_passes_through_in_order(self):
        model = _ChunkyStreamModel([(0.01, "你"), (0.01, "好"), (0.01, "！")])
        pieces = [chunk.content async for chunk in stream_with_stall_guard(
            model.astream([]), idle_timeout=1.0,
        )]
        assert pieces == ["你", "好", "！"]
        assert model.closed, "流结束必须关闭底层生成器"

    @pytest.mark.asyncio
    async def test_stall_between_chunks_raises_and_closes(self):
        """chunk 间隔超过 timeout → ModelStallError + 底层流被关闭。"""
        model = _ChunkyStreamModel([(0.01, "a"), (0.5, "b")])
        pieces = []
        with pytest.raises(ModelStallError) as exc_info:
            async for chunk in stream_with_stall_guard(model.astream([]), idle_timeout=0.1):
                pieces.append(chunk.content)
        assert pieces == ["a"]  # 卡住前已产出的 chunk 照常到达
        assert exc_info.value.kind == "idle"
        assert model.closed

    @pytest.mark.asyncio
    async def test_stall_before_first_chunk_raises(self):
        model = _ChunkyStreamModel([(5.0, "late")])
        with pytest.raises(ModelStallError):
            async for _chunk in stream_with_stall_guard(model.astream([]), idle_timeout=0.1):
                pass
        assert model.closed

    @pytest.mark.asyncio
    async def test_disabled_timeout_is_pure_passthrough(self):
        """timeout ≤0 → 完全旁路：慢流原样通过（行为与旧版一致）。"""
        model = _ChunkyStreamModel([(0.05, "a"), (0.05, "b")])
        pieces = [chunk.content async for chunk in stream_with_stall_guard(
            model.astream([]), idle_timeout=0,
        )]
        assert pieces == ["a", "b"]


class TestCoordinatorStallIntegration:
    @pytest.mark.asyncio
    async def test_primary_stall_switches_to_fallback(self):
        """primary 卡流 → 判瞬时 → fallback 续流 + transition 记录。"""
        primary = _ChunkyStreamModel([(0.01, "pri"), (5.0, "x")])
        fallback = _ChunkyStreamModel([(0.01, "back")])
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=fallback,
            idle_timeout=0.1,
            primary_name="primary-model", fallback_name="fallback-model",
        )

        pieces = [chunk.content async for chunk in coordinator.astream([])]

        assert "".join(pieces).startswith("pri")  # 卡流前的前缀保留
        assert "back" in "".join(pieces)          # fallback 续写
        transitions = coordinator.drain_transitions()
        assert len(transitions) == 1
        assert transitions[0].reason == "ModelStallError"

    @pytest.mark.asyncio
    async def test_stall_without_fallback_propagates(self):
        primary = _ChunkyStreamModel([(5.0, "x")])
        coordinator = ModelFallbackCoordinator(primary=primary, idle_timeout=0.1)
        with pytest.raises(ModelStallError):
            async for _chunk in coordinator.astream([]):
                pass

    @pytest.mark.asyncio
    async def test_fallback_stall_also_propagates(self):
        """fallback 也卡流 → 异常上抛（Runtime 统一失败兜底），绝不无限重试。"""
        primary = _ChunkyStreamModel([(5.0, "x")])
        fallback = _ChunkyStreamModel([(5.0, "y")])
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=fallback, idle_timeout=0.1,
        )
        with pytest.raises(ModelStallError):
            async for _chunk in coordinator.astream([]):
                pass

    @pytest.mark.asyncio
    async def test_ainvoke_path_unaffected_by_stall_guard(self):
        """V1 看门狗只管流式：ainvoke 路径行为不变（透传）。"""
        inner = ScriptedModel([AIMessage(content="ok")])
        coordinator = ModelFallbackCoordinator(primary=inner, idle_timeout=0.1)
        ai = await coordinator.ainvoke([])
        assert ai.content == "ok"


class _SlowDripModel:
    """每 0.05s 滴一个 chunk、永不结束（模拟冒烟 10 分钟慢滴漏）。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        raise NotImplementedError

    async def astream(self, messages, **kwargs):
        while True:
            await asyncio.sleep(0.05)
            yield AIMessageChunk(content="x")


class TestTotalDeadlineGuard:
    """total 守卫：慢滴漏（chunk 间隔 < idle，永远不触发 idle）只有 total 能治。"""

    @pytest.mark.asyncio
    async def test_slow_drip_hits_total_deadline(self):
        model = _SlowDripModel()
        received = 0
        with pytest.raises(ModelStallError) as exc_info:
            async for chunk in stream_with_stall_guard(
                model.astream([]), idle_timeout=10.0, total_timeout=0.2,
            ):
                received += 1
        assert received > 2, "total 触发前慢滴漏 chunk 照常到达"
        assert exc_info.value.kind == "total"
        assert model.closed if hasattr(model, "closed") else True

    @pytest.mark.asyncio
    async def test_slow_drip_primary_switches_to_fallback(self):
        """冒烟场景的正主：慢滴漏 primary → total 断流 → fallback 完成。"""
        primary = _SlowDripModel()
        fallback = _ChunkyStreamModel([(0.01, "done")])
        coordinator = ModelFallbackCoordinator(
            primary=primary, fallback=fallback,
            idle_timeout=10.0, total_timeout=0.2,
        )

        pieces = [chunk.content async for chunk in coordinator.astream([])]

        assert "done" in "".join(pieces)
        transitions = coordinator.drain_transitions()
        assert len(transitions) == 1
        assert transitions[0].reason == "ModelStallError"

    @pytest.mark.asyncio
    async def test_total_disabled_allows_long_stream(self):
        """total=0 关闭 → 慢滴漏不受限（旧行为；测试里跑 5 个 chunk 即止）。"""
        model = _SlowDripModel()
        received = 0
        async for chunk in stream_with_stall_guard(
            model.astream([]), idle_timeout=0, total_timeout=0,
        ):
            received += 1
            if received >= 5:
                break
        assert received == 5


class TestGenuineTimeoutPassthrough:
    """看门狗不得劫持模型自己抛的 TimeoutError（如 request_timeout 到期）——
    那是真实错误语义（CLI 失败链日志断言 error_type=TimeoutError）。"""

    @pytest.mark.asyncio
    async def test_model_raised_timeouterror_passes_through(self):
        class _TimeoutModel:
            async def astream(self, messages, **kwargs):
                raise TimeoutError("模型请求超时")
                yield  # pragma: no cover — 使其成为 async generator

        with pytest.raises(TimeoutError, match="模型请求超时"):
            async for _chunk in stream_with_stall_guard(
                _TimeoutModel().astream([]), idle_timeout=1.0,
            ):
                pass
