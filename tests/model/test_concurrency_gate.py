"""进程级模型调用并发闸（Phase 13 T8, #89, ADR-0015）。

用户指出的双重约束：并发 child 同时打模型 API 会撞 TPM/QPM 限流（429 被
误判瞬时引发 fallback 抖动），多 runtime 并发也吃机器资源。契约：
- 同一时刻在飞的模型调用 ≤ 上限，其余【排队等待】而非失败；
- 排队等待不计入卡流 idle 计时（闸必须包在看门狗外面——先拿到槽位，
  看门狗才开始计时）；
- 异常/取消路径正确释放槽位（不泄漏）；
- limit ≤0 完全旁路（向后兼容）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from langchain_core.messages import AIMessageChunk

from agent_harness.model.concurrency import ModelCallGate
from agent_harness.model.stall import stream_with_stall_guard


class _ProbeModel:
    """astream 同时在飞计数探针：记录峰值并发。"""

    def __init__(self, chunk_delay: float = 0.02) -> None:
        self._delay = chunk_delay
        self.in_flight = 0
        self.peak = 0

    def bind_tools(self, tools, **kwargs):
        return self

    async def astream(self, messages, **kwargs) -> AsyncIterator[AIMessageChunk]:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self._delay)
            yield AIMessageChunk(content="x")
        finally:
            self.in_flight -= 1


async def _collect(agen: AsyncIterator) -> list:
    return [chunk async for chunk in agen]


class TestModelCallGate:
    @pytest.mark.asyncio
    async def test_concurrency_capped_and_no_loss(self):
        gate = ModelCallGate(limit=2)
        model = _ProbeModel()
        results = await asyncio.gather(*[
            _collect(gate.wrap(model.astream([]))) for _ in range(6)
        ])
        assert len(results) == 6
        assert all(len(r) == 1 for r in results), "排队不丢 chunk"
        assert model.peak <= 2, f"峰值并发 {model.peak} 超过上限 2"

    @pytest.mark.asyncio
    async def test_disabled_is_passthrough(self):
        gate = ModelCallGate(limit=0)
        model = _ProbeModel()
        await asyncio.gather(*[
            _collect(gate.wrap(model.astream([]))) for _ in range(8)
        ])
        assert model.peak == 8  # 无闸：不限制

    @pytest.mark.asyncio
    async def test_release_on_consumer_cancel(self):
        """消费者中途关闭流 → 槽位释放（后续调用不被饿死）。"""
        gate = ModelCallGate(limit=1)
        model = _ProbeModel(chunk_delay=0.05)

        agen = gate.wrap(model.astream([]))
        await agen.__anext__()  # 拿一个 chunk 后放弃
        await agen.aclose()

        # 槽位已释放：新流立即可跑
        chunks = await asyncio.wait_for(_collect(gate.wrap(model.astream([]))), timeout=2)
        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_waiting_does_not_consume_stall_idle(self):
        """闸必须包在看门狗外面：排队 0.3s 拿到槽位后，0.05s 间隔的正常流
        在 idle=0.2 下不触发 ModelStallError（idle 计时从拿到槽位才开始）。"""
        gate = ModelCallGate(limit=1)
        blocker = _ProbeModel(chunk_delay=0.3)

        async def occupy():
            await _collect(gate.wrap(blocker.astream([])))

        occupier = asyncio.create_task(occupy())
        await asyncio.sleep(0.05)  # 让占位者先进闸

        model = _ProbeModel(chunk_delay=0.05)
        chunks = [chunk.content async for chunk in gate.wrap(
            stream_with_stall_guard(model.astream([]), idle_timeout=0.2)
        )]
        assert chunks == ["x"], "排队后的正常流不应被看门狗误杀"
        await occupier

    @pytest.mark.asyncio
    async def test_ainvoke_slot_context(self):
        gate = ModelCallGate(limit=1)
        done: list[int] = []

        async def call(i: int) -> None:
            async with gate.slot():
                await asyncio.sleep(0.02)
                done.append(i)

        await asyncio.gather(call(1), call(2), call(3))
        assert sorted(done) == [1, 2, 3]


class TestGateStackingWithStallGuard:
    @pytest.mark.asyncio
    async def test_stall_guard_inside_gate_detects_real_stall(self):
        """组合语义：拿到槽位后卡流 → 看门狗正常触发（闸不吞 stall）。"""
        gate = ModelCallGate(limit=1)

        async def stalling_stream():
            yield AIMessageChunk(content="x")
            await asyncio.sleep(99)

        from agent_harness.model.stall import ModelStallError

        with pytest.raises(ModelStallError, match='no chunk for 0.1s'):
            async for _chunk in gate.wrap(
                stream_with_stall_guard(stalling_stream(), idle_timeout=0.1)
            ):
                pass
