"""T1 #117：LangfuseSink 旁路装配语义（ADR-0018 D2/D3）。

旁路红线：
- 未配置（key 空）= 完全缺席，连 langfuse 包都不许 import（懒加载）；
- 初始化失败 = 本进程永久禁用 + JSONL system_log 诊断行，主流程零感知；
- 单一异常边界：sink 内任何 SDK 异常被吞，绝不传染主流程；
- 熔断：连续失败达阈值后停止外发，期间写入计数丢弃并留诊断痕迹；
- flush 有超时上限，退出节奏不被旁路拖死。
"""

from __future__ import annotations

import logging
import time

from agent_harness.observability import LangfuseSink


def _sink(client_factory=None, *, public_key: str = "pk-test", secret_key: str = "sk-test", **kwargs):
    return LangfuseSink(
        public_key=public_key,
        secret_key=secret_key,
        base_url="https://example.invalid",
        client_factory=client_factory,
        **kwargs,
    )


class _NeverFactory:
    """任何对 SDK 工厂的调用都是测试失败。"""

    def __call__(self, **kwargs):
        raise AssertionError("不得触碰 SDK 工厂")


def test_no_keys_disabled_and_never_touches_sdk():
    sink = _sink(client_factory=_NeverFactory(), public_key="", secret_key="")

    assert sink.enabled is False
    # 缺席态下所有操作都是安全 no-op
    with sink.start_as_current_observation(name="x"):
        pass
    sink.flush(timeout=0.1)
    assert sink.dropped == 0


def test_init_failure_permanently_disables_with_diagnostic(caplog):
    def _boom(**kwargs):
        raise RuntimeError("sdk exploded on init")

    with caplog.at_level(logging.WARNING, logger="agent_harness.observability"):
        sink = _sink(client_factory=_boom)

    assert sink.enabled is False
    assert any("初始化失败" in r.message for r in caplog.records)
    # 永久禁用：后续操作保持 no-op，不再触碰工厂
    with (
        caplog.at_level(logging.WARNING, logger="agent_harness.observability"),
        sink.start_as_current_observation(name="x"),
    ):
        pass
    sink.flush(timeout=0.1)
    assert not any("熔断" in r.message for r in caplog.records)


def test_exception_boundary_swallows_sdk_errors():
    class _BadClient:
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("sdk blew up mid-call")

        def flush(self):
            raise RuntimeError("flush blew up")

    sink = _sink(client_factory=lambda **kwargs: _BadClient())

    with sink.start_as_current_observation(name="x"):
        pass  # __enter__/__exit__ 全程被边界吞掉
    sink.flush(timeout=1)  # 同样不抛


def test_breaker_opens_after_consecutive_failures_and_counts_drops(caplog):
    class _DownClient:
        def __init__(self):
            self.calls = 0

        def start_as_current_observation(self, **kwargs):
            self.calls += 1
            raise RuntimeError("endpoint down")

    client = _DownClient()
    sink = _sink(client_factory=lambda **kwargs: client)

    with caplog.at_level(logging.INFO, logger="agent_harness.observability"):
        for _ in range(5):  # 达到熔断阈值（5）
            with sink.start_as_current_observation(name="x"):
                pass
        assert client.calls == 5
        for _ in range(10):  # 熔断开启：写入被丢弃，不再触达 SDK
            with sink.start_as_current_observation(name="y"):
                pass

    assert client.calls == 5
    assert sink.dropped == 10
    assert any("熔断" in r.message for r in caplog.records)


def test_breaker_half_open_recovers_on_success():
    class _FlakyClient:
        def __init__(self):
            self.calls = 0

        def start_as_current_observation(self, **kwargs):
            self.calls += 1
            if self.calls <= 5:
                raise RuntimeError("still down")
            return _null_span_cm()

        def flush(self):
            pass

    client = _FlakyClient()
    sink = _sink(
        client_factory=lambda **kwargs: client, breaker_cooldown_seconds=0.05
    )

    for _ in range(6):  # 前 5 次失败 → 熔断开启；第 6 次在熔断期被丢弃
        with sink.start_as_current_observation(name="x"):
            pass
    assert client.calls == 5
    assert sink.dropped == 1

    time.sleep(0.1)  # 短冷却（注入值）过期 → 半开探测
    with sink.start_as_current_observation(name="y"):
        pass  # 探测成功 → 熔断恢复
    for _ in range(10):
        with sink.start_as_current_observation(name="z"):
            pass  # 恢复后全部触达 SDK
    assert client.calls == 16
    assert sink.dropped == 1


def test_flush_timeout_is_bounded():
    class _SlowClient:
        def flush(self):
            time.sleep(2)

    sink = _sink(client_factory=lambda **kwargs: _SlowClient())
    started = time.monotonic()
    sink.flush(timeout=0.3)
    assert time.monotonic() - started < 1.5


# ── get_trace_url（trace_url 契约：官方 SDK 薄封装，故障隔离同款） ──


def test_get_trace_url_returns_official_url_when_enabled():
    """启用时透传官方 client.get_trace_url(trace_id=…) 的结果（不手拼 URL）。"""

    class _UrlClient:
        def get_trace_url(self, *, trace_id):
            return f"https://lf.example.invalid/project/proj/traces/{trace_id}"

    sink = _sink(client_factory=lambda **kwargs: _UrlClient())

    url = sink.get_trace_url(trace_id="tr-123")
    assert url == "https://lf.example.invalid/project/proj/traces/tr-123"


def test_get_trace_url_returns_none_when_disabled():
    """未配置（key 空）= 完全缺席：恒 None（同 trace_id 降级模式）。"""
    sink = _sink(client_factory=_NeverFactory(), public_key="", secret_key="")
    assert sink.get_trace_url(trace_id="tr-x") is None


def test_get_trace_url_returns_none_when_breaker_open():
    """熔断开启时 trace_url 也被丢弃（与 start_observation 同款）；不触达 SDK。"""

    class _CountingClient:
        def __init__(self):
            self.calls = 0

        def start_as_current_observation(self, **kwargs):
            self.calls += 1
            raise RuntimeError("down")

        def get_trace_url(self, *, trace_id):
            raise AssertionError("熔断期不得触达 SDK")

    client = _CountingClient()
    sink = _sink(client_factory=lambda **kwargs: client)
    for _ in range(5):
        with sink.start_as_current_observation(name="x"):
            pass
    assert client.calls == 5
    # 熔断已开
    assert sink.get_trace_url(trace_id="tr-y") is None


def test_get_trace_url_swallows_sdk_exception_and_returns_none():
    """SDK 抛异常 → 单一异常边界吞掉并计数，调用方拿到 None（D3 不变）。"""

    class _ExplodingUrlClient:
        def get_trace_url(self, *, trace_id):
            raise RuntimeError("sdk blew up building url")

    sink = _sink(client_factory=lambda **kwargs: _ExplodingUrlClient())
    assert sink.get_trace_url(trace_id="tr-z") is None


def test_get_trace_url_accepts_none_trace_id_returns_none():
    """trace_id=None 是合法入参（SDK 也接受），结果视 SDK 而定；
    我们不假设——直接透传 SDK 返回值。这里的 FakeClient 返回 None。"""

    class _NullUrlClient:
        def get_trace_url(self, *, trace_id):
            return None if trace_id is None else f"https://x/{trace_id}"

    sink = _sink(client_factory=lambda **kwargs: _NullUrlClient())
    assert sink.get_trace_url(trace_id=None) is None
    assert sink.get_trace_url(trace_id="abc") == "https://x/abc"


def test_init_passes_environment_and_release_to_factory():
    """Gap 1+2（D7 DEFER 批）：environment/release 是 Langfuse 一等字段，
    必须透传到 SDK init——否则 trace 落入 default 环境、release 永远 null。"""

    captured: dict = {}

    def _capturing_factory(**kwargs):
        captured.update(kwargs)

        class _Client: ...
        return _Client()

    _sink(
        client_factory=_capturing_factory,
        tracing_environment="development",
        release="v1.2.3",
    )
    assert captured.get("environment") == "development"
    assert captured.get("release") == "v1.2.3"


def test_init_defaults_environment_development_empty_release_omitted():
    """environment 缺省 development（避免落入 default）；release 空串不塞给 SDK。"""

    captured: dict = {}

    def _capturing_factory(**kwargs):
        captured.update(kwargs)

        class _Client: ...
        return _Client()

    _sink(client_factory=_capturing_factory)  # 不传新参数
    assert captured.get("environment") == "development"
    assert not captured.get("release")  # 空=不塞（SDK 自决）


def _null_span_cm():
    import contextlib

    return contextlib.nullcontext(object())
