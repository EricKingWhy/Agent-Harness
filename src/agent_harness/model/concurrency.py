"""进程级模型调用并发闸（Phase 13 T8, #89, ADR-0015）。

用户指出的双重约束：并发 child 同时打模型 API 会撞 TPM/QPM 限流（429 被
误判瞬时错误引发 fallback 抖动），多 runtime 并发也吃机器资源。一个进程级
信号量闸让「同一时刻在飞的模型调用 ≤ 上限」，超出的排队等待而非失败。

分层铁律：闸必须包在 stall 看门狗【外面】——排队等槽位的时间不该计入
卡流 idle 计时（先拿到槽位，看门狗才开始逐 chunk 计时）。组合顺序：
gate.wrap(stream_with_stall_guard(model.astream(...)))。

TPM 令牌桶限流器显式 DEFER：429 场景 V1 由「child 失败 → SubAgentResult
.status=failed → supervisor 决策重试/放弃」语义兜底（ADR-0015 决策 16）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class ModelCallGate:
    """模型调用并发闸：asyncio.Semaphore 的包装（支持 limit≤0 关闭）。

    进程内共享一个实例（assembly 创建、runtime 与所有 child factory 传递
    同一引用）——闸的语义是「全局在飞模型调用数」，不是每 runtime 一个。
    """

    def __init__(self, limit: int) -> None:
        # ≤0 = 关闭（调用方显式不加闸），行为与历史版本一致。
        self._sem: asyncio.Semaphore | None = (
            asyncio.Semaphore(limit) if limit and limit > 0 else None
        )
        self.limit = limit

    def wrap(self, agen: AsyncIterator[Any]) -> AsyncIterator[Any]:
        """包一层流式迭代：整个消费期间占用一个槽位（异常/取消安全释放）。"""
        if self._sem is None:
            return agen

        async def gated() -> AsyncIterator[Any]:
            await self._sem.acquire()
            try:
                async for chunk in agen:
                    yield chunk
            finally:
                self._sem.release()

        return gated()

    @asynccontextmanager
    async def slot(self):
        """非流式调用的槽位（async with 用法）。"""
        if self._sem is None:
            yield None
            return
        await self._sem.acquire()
        try:
            yield None
        finally:
            self._sem.release()
