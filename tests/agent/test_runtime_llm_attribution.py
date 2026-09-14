"""Runtime 主循环 llm_call 诊断日志的模型归因回归（Round 4 F3）。

spec 02 §7/§10 要求每个 step 在 Diagnostic Log 中可定位到具体 provider/model；
cli.py 已带 provider/model_id/duration_ms/token_usage，但 runtime 主循环此前
只打了 step / llm_input / llm_output，缺模型归因——一旦主 Loop 出问题，日志
无法回答"哪一轮、哪个模型"。这里钉死 runtime 与 cli 对齐的归因字段。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agent_harness.agent import AgentRuntime
from agent_harness.session import JsonlSessionStore, Session
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.scripted_model import ScriptedModel


@pytest.mark.asyncio
async def test_llm_call_log_carries_model_id_duration_and_usage(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """llm_call 日志必须带 model_id、duration_ms、token_usage——可定位到具体模型。"""
    store = JsonlSessionStore(root=tmp_path)
    session = Session.start(store)
    registry = ToolRegistry()
    # 构造带 usage 与 response_metadata.model_name 的响应，让 runtime 能抽到归因。
    model = ScriptedModel(
        [
            AIMessage(
                content="done",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                response_metadata={"model_name": "test-model-x"},
            ),
        ]
    )
    runtime = AgentRuntime(model, registry, ToolExecutor(registry))

    with caplog.at_level(logging.INFO, logger="agent_harness.agent"):
        await runtime.run(session, "hello")

    llm_call_records = [
        r for r in caplog.records
        if r.name == "agent_harness.agent" and r.getMessage().startswith("第 1 轮模型调用完成")
    ]
    assert len(llm_call_records) == 1
    record = llm_call_records[0]
    # 归因字段：runtime 把它们经 log_event 写进 record 的结构化字段。
    assert getattr(record, "model_id", None) == "test-model-x"
    assert getattr(record, "duration_ms", None) is not None
    usage = getattr(record, "token_usage", None)
    assert usage is not None and usage.get("total_tokens") == 15


@pytest.mark.asyncio
async def test_llm_call_log_without_response_metadata_still_logs_step(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """响应无 metadata 时 model_id / token_usage 可缺，但 llm_call 事件仍发出。"""
    store = JsonlSessionStore(root=tmp_path)
    session = Session.start(store)
    registry = ToolRegistry()
    model = ScriptedModel([AIMessage(content="ok")])
    runtime = AgentRuntime(model, registry, ToolExecutor(registry))

    with caplog.at_level(logging.INFO, logger="agent_harness.agent"):
        await runtime.run(session, "hi")

    llm_call_records = [
        r for r in caplog.records
        if r.name == "agent_harness.agent" and "模型调用完成" in r.getMessage()
    ]
    assert len(llm_call_records) == 1
    # duration_ms 始终可计算；model_id / token_usage 在无 metadata 时为缺省（不强断言）。
    assert getattr(llm_call_records[0], "duration_ms", None) is not None
