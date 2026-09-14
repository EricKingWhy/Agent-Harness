"""T5 #121：flush 生命周期——CLI 退出 + web graceful shutdown（ADR-0018 D3）。

旁路数据不丢尾：任何退出路径都尽力发送剩余 span；有超时上限，退出节奏
不被拖死；未配置/未装配 = 零开销 no-op。
"""

from __future__ import annotations

import sys

import agent_harness.observability as observability_module
from agent_harness.observability import LangfuseSink, flush_process_sink
from tests.observability.test_tracer import FakeRecorder


class _RecordingSink(LangfuseSink):
    def __init__(self, *, enabled: bool = True):
        super().__init__(
            public_key="pk" if enabled else "",
            secret_key="sk" if enabled else "",
            base_url="https://example.invalid",
            client_factory=(lambda **kwargs: FakeRecorder().client())
            if enabled else None,
        )
        self.flush_calls = 0

    def flush(self, timeout: float | None = None) -> None:
        self.flush_calls += 1


def test_flush_process_sink_semantics():
    # 未装配：no-op 不抛
    observability_module._process_sink = None
    flush_process_sink()

    # disabled 装配：no-op
    disabled = _RecordingSink(enabled=False)
    observability_module._process_sink = disabled
    flush_process_sink()
    assert disabled.flush_calls == 0

    # enabled 装配：flush 恰好一次
    enabled = _RecordingSink(enabled=True)
    observability_module._process_sink = enabled
    flush_process_sink()
    assert enabled.flush_calls == 1

    observability_module._process_sink = None


def test_cli_main_flushes_on_normal_exit(monkeypatch):
    fake = _RecordingSink(enabled=True)
    observability_module._process_sink = fake
    monkeypatch.setattr(sys, "argv", ["agent-harness", "sessions", "--help"])

    from agent_harness.cli import main

    try:
        main()  # --help 触发 SystemExit：finally 仍必须 flush
    except SystemExit:
        pass
    assert fake.flush_calls == 1
    observability_module._process_sink = None


def test_web_lifespan_flushes_on_shutdown():
    fake = _RecordingSink(enabled=True)
    observability_module._process_sink = fake

    from fastapi.testclient import TestClient

    from agent_harness.web.app import create_app

    app = create_app()
    with TestClient(app):  # 进入+退出 lifespan（startup+shutdown）
        pass
    assert fake.flush_calls == 1
    observability_module._process_sink = None
