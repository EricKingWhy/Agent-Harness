"""Langfuse 旁路 sink（ADR-0018）。

三层观测的第三层接入点：把 Langfuse 做成纯旁路——
- 未配置（key 空）= 完全缺席零开销（懒加载，连 ``langfuse`` 包都不 import）；
- 初始化失败 = 本进程永久禁用 + JSONL system_log 诊断行，主流程零感知；
- 任何 SDK 异常被单一异常边界吞掉，绝不传染主流程（不变量 #21）；
  用户 with 体自身的异常照常传播——旁路只吞 SDK 故障，不改变业务语义；
- 端点持续不可达 → 熔断（暂停外发），丢弃计数只进 JSONL 诊断行
  （Event ≠ 诊断日志，SessionEvent 流保持纯净业务事实）。

热路径约束（ADR-0018 D3 性能红线）：经由本模块的调用只允许内存操作，
零同步网络、零 await、零磁盘写；真正发送全部走 SDK 后台批处理。

实现注记：异常边界不能用 @contextmanager 生成器——contextlib 对"捕获
注入异常后不再 yield"的生成器会把异常重新抛给调用方；观测用显式 CM 类，
flush/shutdown 用普通 try/except。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from types import TracebackType
from typing import Any

from agent_harness.logging import log_event

_LOGGER = logging.getLogger("agent_harness.observability")


def _default_client_factory(
    *,
    public_key: str,
    secret_key: str,
    base_url: str,
    environment: str = "",
    release: str = "",
) -> Any:
    # 懒加载：只有配置了 key 才会执行到这里（D2）。必须在 load_dotenv 之后
    # 调用（assembly/CLI 入口保证），否则 SDK 读不到环境变量。
    from langfuse import Langfuse

    kwargs: dict[str, Any] = {
        "public_key": public_key or None,
        "secret_key": secret_key or None,
        "base_url": base_url or None,
    }
    # D7 DEFER 批：environment/release 是 Langfuse 一等字段；空值不塞（SDK 自决），
    # 非空才透传——避免把空串当显式设置覆盖云端项目配置。
    if environment:
        kwargs["environment"] = environment
    if release:
        kwargs["release"] = release
    return Langfuse(**kwargs)


class LangfuseSink:
    """Langfuse 客户端的故障隔离包装：公开方法不向调用方抛 SDK 异常。"""

    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        base_url: str = "",
        trace_content: str = "full",
        tracing_environment: str = "development",
        release: str = "",
        client_factory: Callable[..., Any] | None = None,
        breaker_threshold: int = 5,
        breaker_cooldown_seconds: float = 60.0,
        flush_timeout_seconds: float = 5.0,
    ) -> None:
        self._logger = _LOGGER
        self._client: Any = None
        # 内容边界（ADR-0018 D6）：full=完整输入输出；redacted=只传 metadata+截断。
        # 非法值按 full 处理（宁多不少地保守降级到完整侧会泄漏——这里反向：
        # 未知值归 full 是用户显式默认，redaction 由 tracer 侧再次校验）。
        self.trace_content = trace_content if trace_content in ("full", "redacted") else "full"
        self._breaker_threshold = breaker_threshold
        self._breaker_cooldown = breaker_cooldown_seconds
        self._flush_timeout = flush_timeout_seconds
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0
        self._dropped = 0

        if not public_key or not secret_key:
            return  # 未配置：完全缺席（D2），连工厂都不碰
        factory = client_factory or _default_client_factory
        try:
            self._client = factory(
                public_key=public_key, secret_key=secret_key, base_url=base_url,
                environment=tracing_environment, release=release,
            )
        except Exception as exc:  # noqa: BLE001 - D3 异常边界：初始化失败必须隔离
            self._client = None  # 永久禁用：本进程不再尝试
            log_event(
                self._logger,
                "system_log",
                "Langfuse sink 初始化失败，本进程永久禁用旁路",
                level="warn",
                component="langfuse_sink",
                outcome="init_failed_permanently_disabled",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def dropped(self) -> int:
        """熔断开启以来被丢弃的旁路写入数（诊断用）。"""
        return self._dropped

    def start_as_current_observation(
        self, *, name: str, as_type: str = "span", **fields: Any
    ) -> Any:
        """开一个 Langfuse 观测（span/generation/agent/...），嵌套由 SDK
        current-context 维护。返回值是上下文管理器，``as`` 得到的观测在
        缺席/熔断丢弃/进入失败时为 None——调用方据此跳过后续 update。"""
        client = self._client
        if client is None:
            return nullcontext(None)
        if self._breaker_open():
            self._register_drop("start_observation")
            return nullcontext(None)
        return _ObservationContext(
            self, client, {"name": name, "as_type": as_type, **fields}
        )

    def start_observation(self, *, name: str, as_type: str = "span", **fields: Any) -> Any:
        """非 current 形式：直接返回观测句柄（显式树控制用，RunTracer 的
        trace 根由此创建）。缺席/熔断丢弃/SDK 异常 → None。"""
        client = self._client
        if client is None:
            return None
        if self._breaker_open():
            self._register_drop("start_observation")
            return None
        try:
            span = client.start_observation(name=name, as_type=as_type, **fields)
            self._consecutive_failures = 0
            return span
        except Exception as exc:  # noqa: BLE001 - D3 异常边界
            self._register_failure("start_observation", exc)
            return None

    def trace_attributes(self, **kwargs: Any) -> Any:
        """trace 级属性传播（session_id / tags / trace_name 等，ADR-0018 D5）。

        返回上下文管理器：在该上下文内创建的观测都会带上这些 trace 级属性。
        缺席/SDK 异常 → nullcontext（调用方无需判空）。"""
        if self._client is None:
            return nullcontext(None)
        try:
            from langfuse import propagate_attributes

            return propagate_attributes(**kwargs)
        except Exception:  # noqa: BLE001 - D3 异常边界
            return nullcontext(None)

    def get_trace_url(self, *, trace_id: str | None) -> str | None:
        """官方 SDK 的 trace 可点击 URL 薄封装（trace_url 契约；ADR-0018 D7 延伸）。

        - 不手拼 URL——host / project_id 由 SDK 解析（§6 Reuse First）；
        - 未配置 / 熔断开启 / SDK 异常 → None（与 trace_id 同一降级模式）；
        - 仅内存合成（host+project 来自配置），不走外部网络，热路径安全。
        """
        client = self._client
        if client is None:
            return None
        if self._breaker_open():
            self._register_drop("get_trace_url")
            return None
        try:
            url = client.get_trace_url(trace_id=trace_id)
            self._consecutive_failures = 0
            return url if isinstance(url, str) else None
        except Exception as exc:  # noqa: BLE001 - D3 异常边界
            self._register_failure("get_trace_url", exc)
            return None

    def report_failure(self, operation: str, exc: Exception) -> None:
        """观测句柄上的后续操作（update/end/子观测）失败时由 tracer 回注——
        计数进同一熔断账本，但绝不向调用方抛出。"""
        self._register_failure(operation, exc)

    def flush(self, timeout: float | None = None) -> None:
        """尽力把后台队列发送完；有超时上限，退出节奏不被旁路拖死（D3）。"""
        client = self._client
        if client is None:
            return
        if self._breaker_open():
            self._register_drop("flush")
            return
        try:
            self._call_with_deadline(client.flush, timeout)
            self._consecutive_failures = 0
        except Exception as exc:  # noqa: BLE001 - D3 异常边界
            self._register_failure("flush", exc)

    def shutdown(self, timeout: float | None = None) -> None:
        """进程收尾：停止后台处理器并发送剩余队列（语义同 flush 的有界性）。"""
        client = self._client
        if client is None:
            return
        if self._breaker_open():
            self._register_drop("shutdown")
            return
        try:
            self._call_with_deadline(client.shutdown, timeout)
            self._consecutive_failures = 0
        except Exception as exc:  # noqa: BLE001 - D3 异常边界
            self._register_failure("shutdown", exc)

    # —— 内部 ——

    def _breaker_open(self) -> bool:
        return time.monotonic() < self._breaker_open_until

    def _register_drop(self, operation: str) -> None:
        self._dropped += 1
        if self._dropped == 1 or self._dropped % 50 == 0:
            log_event(
                self._logger,
                "system_log",
                "Langfuse 旁路熔断中，写入被丢弃",
                level="warn",
                component="langfuse_sink",
                outcome="dropped",
                operation=operation,
                drop_count=self._dropped,
            )

    def _register_failure(self, operation: str, exc: Exception) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._breaker_threshold:
            self._breaker_open_until = time.monotonic() + self._breaker_cooldown
            self._dropped = 0
            log_event(
                self._logger,
                "system_log",
                "Langfuse 连续失败达阈值，旁路熔断开启",
                level="warn",
                component="langfuse_sink",
                outcome="breaker_opened",
                operation=operation,
                consecutive_failures=self._consecutive_failures,
                cooldown_seconds=self._breaker_cooldown,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        else:
            log_event(
                self._logger,
                "system_log",
                "Langfuse 旁路调用异常（已吞，不计入业务）",
                level="debug",
                component="langfuse_sink",
                outcome="swallowed",
                operation=operation,
                consecutive_failures=self._consecutive_failures,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def _call_with_deadline(self, fn: Callable[[], None], timeout: float | None) -> None:
        # SDK flush/shutdown 是同步 join，没有超时参数——放进 daemon 线程，
        # 主线程限时等待；SDK 内部的异常转回调用线程统一计数。
        deadline = self._flush_timeout if timeout is None else timeout
        error: list[BaseException] = []

        def _runner() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 - 线程内兜底
                error.append(exc)

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        worker.join(deadline)
        if error:
            raise error[0]  # 交给调用方 _register_failure 吞掉并计数


class _ObservationContext:
    """观测的故障隔离上下文管理器。

    - ``__enter__`` 故障 → 吞掉并计数，观测降级为 None；
    - 用户 with 体异常 → 照常传播（旁路不改业务语义）；
    - ``__exit__``（SDK 收尾）故障 → 吞掉并计数，且不抑制用户异常。
    """

    def __init__(self, sink: LangfuseSink, client: Any, fields: dict[str, Any]) -> None:
        self._sink = sink
        self._client = client
        self._fields = fields
        self._cm: Any = None

    def __enter__(self) -> Any:
        try:
            self._cm = self._client.start_as_current_observation(**self._fields)
            return self._cm.__enter__()
        except Exception as exc:  # noqa: BLE001 - D3 异常边界：进入失败必须隔离
            self._cm = None
            self._sink._register_failure("start_observation", exc)
            return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if self._cm is None:
            return False  # 未成功进入：不抑制任何东西
        try:
            return bool(self._cm.__exit__(exc_type, exc, tb))
        except Exception as sdk_exc:  # noqa: BLE001 - D3 异常边界：SDK 收尾故障隔离
            self._sink._register_failure("observation_exit", sdk_exc)
            return False
