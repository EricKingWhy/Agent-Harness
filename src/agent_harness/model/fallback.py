"""Model Fallback（ADR-0014 决策 14/15/16）：瞬时故障的两级模型转移。

不变量 #9：Model Fallback 与 Tool Retry 分离——本模块只关心模型调用故障，
绝不触碰工具重试语义（那是 ToolExecutor 的单一责任域）。

分层：
- is_transient_model_error：共享错误分类 helper（决策 15）——瞬时 =
  超时 / 5xx / 429 / 连接失败；认证错 / 参数错等非瞬时换一台模型也没用，
  直接失败不盲切（决策 1）。policy 复用不重写。
- FallbackPolicy：决策 seam（决策 14）。V1 契约只问「这个错误是否值得
  切换」；两级结构（primary → fallback、never 切回、只重试一次）由
  ModelFallbackCoordinator 持有。未来升级全链策略（role/wildcard 多级 +
  cooldown 切回）只换 policy 实现，Agent Loop 零改动。
- ModelFallbackCoordinator：执行调用序列（决策 16「决策在 policy，
  编排在模型层」）。Runtime 拥有 Session，因此切换事实以 FallbackTransition
  返回（drain 语义），由 Runtime 持久化为 model/fallback 事件——白盒透明。

脱敏：FallbackTransition.reason 只带异常类型名，不带异常消息——Provider
回显可能含敏感文本（与 model/failed 事件的脱敏不变量一致）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx
from langchain_core.messages import AnyMessage

from agent_harness.model.concurrency import ModelCallGate
from agent_harness.model.stall import ModelStallError, stream_with_stall_guard

# openai SDK 的瞬时错误类名（不硬 import openai：按类名识别，避免版本
# 差异与 LangChain 包装层变化破坏分类）。
_TRANSIENT_ERROR_NAMES = frozenset({
    "APITimeoutError",       # openai 请求超时
    "APIConnectionError",    # openai 连接失败
    "TimeoutError",          # 内建 / asyncio 超时（3.11+ 同一类）
    "ConnectionError",       # 内建 socket 连接失败
})


def is_transient_model_error(error: BaseException) -> bool:
    """判断模型调用错误是否瞬时（值得切 fallback 重试）。

    覆盖四层异常源：
    - 卡流看门狗：ModelStallError（超时形状，冒烟实测的 10 分钟缓速流）；
    - httpx 传输层：TimeoutException / TransportError（连接被拒、读失败等）；
    - httpx.HTTPStatusError：5xx / 429 瞬时，4xx 认证/参数错非瞬时；
    - openai SDK 风格：带 status_code 属性的按状态码判，APITimeoutError /
      APIConnectionError 按类名判（langchain-openai 的真实异常源）。
    """
    if isinstance(error, ModelStallError):
        return True
    # httpx.HTTPStatusError 与 TransportError 是兄弟分支（同出 HTTPError），
    # 先判状态错再判传输错，语义各自独立。
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status >= 500 or status == 429
    if isinstance(error, httpx.TransportError):
        # 含 TimeoutException（其子类）与 ConnectError / ReadError 等传输故障
        return True
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        return status_code >= 500 or status_code == 429
    return type(error).__name__ in _TRANSIENT_ERROR_NAMES


@dataclass(frozen=True)
class FallbackTransition:
    """一次成功的模型切换事实（Runtime 持久化为 model/fallback 事件）。

    reason 只带异常类型名不带消息——异常消息可能含 Provider 回显的敏感
    文本，与 model/failed 事件同一脱敏不变量。
    """

    from_model: str
    to_model: str
    reason: str


@runtime_checkable
class FallbackPolicy(Protocol):
    """fallback 决策 seam（ADR-0014 决策 14）。

    V1 只问「这个错误是否值得切换」；两级结构与 never 切回由 coordinator
    持有。未来升级 oh-my-pi 全链（role/wildcard 多级、cooldown 切回）时
    扩展为携带链状态的签名，Agent Loop 与本 Protocol 的消费方不变。
    """

    def should_fallback(self, error: BaseException) -> bool: ...


class TwoLevelFallbackPolicy:
    """默认策略：瞬时故障切换，非瞬时（认证/参数错）直接失败（决策 1/15）。"""

    def should_fallback(self, error: BaseException) -> bool:
        return is_transient_model_error(error)


class ModelFallbackCoordinator:
    """两级模型调用编排：primary 失败 → policy 放行 → 切 fallback 重试一次。

    - 决策在 FallbackPolicy（瞬时性判断）；结构在本类（两级、never 切回、
      只重试一次——fallback 再失败异常上抛，由 Runtime 统一失败兜底）。
    - 每实例绑定一次 run 的调用序列：切到 fallback 后 self.current 永久
      指向 fallback（never 切回，决策 14），后续调用不再碰 primary。
    - 并发安全：Runtime 每个 run 新建一个 coordinator（同 T1 的 guard
      姿势），切换状态不跨 run 共享。
    - transitions 是 drain 语义：Runtime 在每次模型调用完成后取走并持久化
      为 model/fallback 事件（Runtime 拥有 Session，模型层不持有会话）。
    """

    def __init__(
        self,
        *,
        primary: Any,
        fallback: Any | None = None,
        policy: FallbackPolicy | None = None,
        primary_name: str = "primary",
        fallback_name: str = "fallback",
        idle_timeout: float = 0.0,
        total_timeout: float = 0.0,
        gate: ModelCallGate | None = None,
    ) -> None:
        self._policy = policy or TwoLevelFallbackPolicy()
        self._fallback = fallback
        self._primary_name = primary_name
        self._fallback_name = fallback_name
        # 流式守卫（秒，逐项 ≤0 关闭）：idle = N 秒无新 chunk（死连接）；
        # total = 整条流必须 N 秒内完成（慢滴漏，冒烟 10 分钟场景）。
        # 每次流式尝试（含 fallback 重试）都被包住，超时抛 ModelStallError
        # （瞬时）→ fallback 接管。
        self._idle_timeout = idle_timeout
        self._total_timeout = total_timeout
        # 进程级模型并发闸（#89）：共享实例（assembly 创建、parent/child 传递
        # 同一引用）。闸包在 stall 看门狗【外面】——排队等槽位不计入 idle。
        self._gate = gate
        self.current = primary
        self._transitions: list[FallbackTransition] = []

    def _guarded_stream(self, model: Any, messages: list[AnyMessage]) -> AsyncIterator[Any]:
        """单次流式尝试（按需包双守卫 + 并发闸；fallback 重试同样受保护）。

        包裹顺序 = 闸(看门狗(原始流))：先拿到槽位，看门狗才开始计时。
        """
        stream = model.astream(messages)
        if (self._idle_timeout and self._idle_timeout > 0) or (
            self._total_timeout and self._total_timeout > 0
        ):
            stream = stream_with_stall_guard(
                stream, idle_timeout=self._idle_timeout,
                total_timeout=self._total_timeout,
            )
        if self._gate is not None:
            stream = self._gate.wrap(stream)
        return stream
        return stream

    def _slot(self) -> AbstractAsyncContextManager[None]:
        """取一个**新**的并发槽位——每次尝试都必须新取一个。

        `ModelCallGate.slot()` 是 `@asynccontextmanager` 产物，**一次性**：退出时
        contextlib 会 `del self.args`，复用同一个 CM 二次进入抛 `AttributeError`
        （2026-09-11 真实事故：非流式 run 回退重试必崩；回归锁见
        `tests/test_model_fallback.py::TestCoordinatorAinvoke::
        test_ainvoke_fallback_retry_reacquires_concurrency_slot`）。
        """
        return self._gate.slot() if self._gate is not None else nullcontext(None)

    async def ainvoke(self, messages: list[AnyMessage]) -> Any:
        """非流式调用：primary 瞬时失败 → 切 fallback 重试一次。

        V1 看门狗不覆盖 ainvoke（总时限会误杀合法长推理）——socket 级
        read-timeout 仍是底线，见 model/stall.py 模块 docstring。
        并发闸同样生效（非流式调用占一个槽位，两次尝试各占一次）。
        """
        try:
            async with self._slot():
                return await self.current.ainvoke(messages)
        except Exception as error:
            if not self._try_switch(error):
                raise
            async with self._slot():
                return await self.current.ainvoke(messages)

    async def astream(
        self, messages: list[AnyMessage]
    ) -> AsyncIterator[Any]:
        """流式调用：流中途瞬时失败（含卡流）→ 切 fallback 继续产出。

        已产出的 chunk 由消费者聚合（前缀 + fallback 续写）——SSE 客户端
        看到的是一段连续流；完整聚合结果由 model/completed 持久化。
        """
        try:
            async for chunk in self._guarded_stream(self.current, messages):
                yield chunk
        except Exception as error:
            if not self._try_switch(error):
                raise
            async for chunk in self._guarded_stream(self.current, messages):
                yield chunk

    def drain_transitions(self) -> list[FallbackTransition]:
        """取走自上次 drain 以来的切换事实（Runtime 逐调用持久化用）。"""
        out = self._transitions
        self._transitions = []
        return out

    def _try_switch(self, error: BaseException) -> bool:
        """错误值得切且还没切过 → 切换并记录事实；否则 False（上抛原异常）。"""
        if self._fallback is None or self.current is self._fallback:
            return False
        if not self._policy.should_fallback(error):
            return False
        self._transitions.append(FallbackTransition(
            from_model=self._primary_name,
            to_model=self._fallback_name,
            reason=type(error).__name__,
        ))
        self.current = self._fallback
        return True
