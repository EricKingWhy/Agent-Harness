"""Model stall watchdog（冒烟实测收尾）：流式调用卡流/慢滴漏治理。

冒烟实测（session 7afd328a）：上游瞬态劣化时 HTTP 200 头秒回、body 以
碎片缓速 10 分钟而不断开（平均 ~0.34s 一个 chunk）——httpx 的
request_timeout 是「单次 socket 读超时」，永不触发；Model Fallback 只对
「错误」生效，对「还在慢慢流」是盲区，用户看到的就是界面挂死。

两个守卫各治一种病理（都抛 ModelStallError，is_transient_model_error 判
瞬时，两级 fallback 据此接管）：
- idle（逐 chunk 间隔）：N 秒无【任何】新 chunk = 死连接/网关挂死；
- total（整体时限）：整条流必须在 N 秒内完成 = 慢滴漏（冒烟那场 chunk
  间隔只有 ~2s，idle 永远不触发，只有 total 能治）。

timeout ≤0 逐项关闭；关闭后行为与旧版一致。V1 明确不做 ainvoke 的总时
限（会误杀合法的长推理生成）——socket 级 300s read-timeout 仍是底线。

实现关键：__anext__ 必须跑在【独立 task】里。Python 3.12+ 的 wait_for
不再隔离协程——超时取消直接打进当前 task，aclose 会在取消展开期被调，
内层生成器休眠点的 CancelledError 会从 finally 逃逸吞掉 TimeoutError。
独立 task 让取消在内层完整展开（生成器 finally 照常执行），本层拿到
干净的 TimeoutError。finally 先收口未决 task 再 aclose 生成器，三条
收口路径（正常耗尽 / 消费者提前关闭 / 超时中断）都释放底层 HTTP 连接。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any


class ModelStallError(Exception):
    """流式模型调用超时（idle 或 total，按瞬时故障处理）。"""

    def __init__(self, seconds: float, kind: str = "idle") -> None:
        self.kind = kind
        if kind == "total":
            super().__init__(
                f"model stream exceeded total deadline of {seconds:.1f}s"
            )
        else:
            super().__init__(
                f"model stream stalled: no chunk for {seconds:.1f}s"
            )


async def stream_with_stall_guard(
    agen: AsyncIterator[Any],
    *,
    idle_timeout: float,
    total_timeout: float = 0.0,
) -> AsyncIterator[Any]:
    """双守卫流式迭代：idle（chunk 间隔）+ total（整体时限）。

    两项 ≤0 分别关闭；全部关闭时纯透传。finally 先收口未决 __anext__ task
    再 aclose 生成器——正常耗尽 / 消费者提前关闭 / 超时中断三条路径都释放
    底层 HTTP 连接。
    """
    guarded = (idle_timeout is not None and idle_timeout > 0) or (
        total_timeout is not None and total_timeout > 0
    )
    if not guarded:
        async for chunk in agen:
            yield chunk
        await agen.aclose()
        return

    deadline: float | None = (
        (time.perf_counter() + total_timeout)
        if total_timeout and total_timeout > 0 else None
    )
    anext_task: asyncio.Task | None = None
    try:
        while True:
            wait = idle_timeout if idle_timeout and idle_timeout > 0 else None
            is_total = False
            if deadline is not None:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise ModelStallError(total_timeout, kind="total")
                if wait is None or remaining < wait:
                    wait = remaining
                    is_total = True
            anext_task = asyncio.ensure_future(agen.__anext__())
            try:
                chunk = await asyncio.wait_for(anext_task, timeout=wait)
            except StopAsyncIteration:
                return
            except TimeoutError:
                # 只把「wait_for 超时取消」判为卡流；模型/SDK 自己抛的
                # TimeoutError（如 request_timeout 到期）必须原样上抛——
                # 两者同类不同态：前者 task 被 cancel，后者 task 携异常失败。
                if anext_task.cancelled():
                    if is_total:
                        raise ModelStallError(total_timeout, kind="total") from None
                    raise ModelStallError(idle_timeout) from None
                raise
            anext_task = None
            yield chunk
    finally:
        if anext_task is not None and not anext_task.done():
            anext_task.cancel()
            try:
                await anext_task
            except BaseException:  # noqa: BLE001, S110 — 取消展开期的任何结局都只算收尾
                pass
        await agen.aclose()
