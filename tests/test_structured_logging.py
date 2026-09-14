"""JSONL 结构化日志与最小 Agent 执行链路测试。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from agent_harness import cli
from agent_harness.config import Settings
from agent_harness.logging import LogContext, log_context, log_event, setup_logging


def read_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines
    return [json.loads(line) for line in lines]


def test_third_party_message_is_system_log_in_shanghai_time(tmp_path: Path):
    log_path = setup_logging(workspace_dir=str(tmp_path / "workspace"))

    logging.getLogger("third_party").warning("一段会变化的第三方消息")

    [entry] = read_jsonl(log_path)
    assert entry["event_type(事件类型)"] == "system_log"
    assert entry["message(消息)"] == "一段会变化的第三方消息"
    assert entry["level(级别)"] == "warn"
    assert entry["schema_version(协议版本)"] == "1.0"
    assert datetime.fromisoformat(entry["timestamp(时间戳)"]).utcoffset().total_seconds() == 8 * 3600


def test_tool_event_keeps_operation_fields_and_omits_none(tmp_path: Path):
    log_path = setup_logging(workspace_dir=str(tmp_path / "workspace"))
    context = LogContext.create()

    with log_context(context):
        log_event(
            logging.getLogger("test_agent"),
            "tool_operation",
            "读取文件完成",
            tool_call_id="call_123",
            operation_id="op_123",
            idempotency_key="read:file.txt",
            tool_name="read_file",
            tool_input={"path": "file.txt"},
            tool_output="内容",
            read_only=True,
            execution_mode="parallel",
            attempt=1,
            max_attempts=1,
            timeout_ms=1000,
            duration_ms=2.5,
            output_truncated=False,
            checkpoint_id=None,
            outcome="success",
        )

    [entry] = read_jsonl(log_path)
    assert entry["event_type(事件类型)"] == "tool_operation"
    assert entry["outcome(结果)"] == "success"
    assert entry["attempt(尝试次数)"] == 1
    assert entry["execution_mode(执行模式)"] == "parallel"
    assert "checkpoint_id" not in entry
    assert entry["trace_id(追踪ID)"] == context.trace_id
    assert all(value is not None for value in entry.values())


@pytest.mark.asyncio
async def test_minimal_agent_success_chain(monkeypatch, tmp_path: Path):
    """CLI（run_stream 路径）的结构化日志链：runtime 的 _log 统一产出
    agent_start → llm_call → agent_decision → task_completed，CLI 只负责
    setup_logging，不再手搓链路。单值 trace_id/task_id 贯穿全链。"""
    from langchain_core.messages import AIMessageChunk

    class FakeModel:
        def bind_tools(self, tools, **kwargs):
            return self

        async def astream(self, messages, **kwargs):
            # 用户消息是**最后**一条：T7 起 meta_user 运行时快照会插在它之前
            # （ADR-0023 D8）。断言最后一条既保住"用户输入到达模型"的原意，
            # 又顺带钉住快照的位置契约。
            assert messages[-1].content == "只回复 ok"
            yield AIMessageChunk(
                content="ok",
                id="lc_run--internal-id",
                response_metadata={
                    "finish_reason": "stop",
                    "id": "provider-response-123",
                },
                usage_metadata={
                    "input_tokens": 4,
                    "output_tokens": 1,
                    "total_tokens": 5,
                    "input_token_details": {"cache_read": 2},
                    "output_token_details": {"reasoning": 0},
                },
            )

    settings = Settings(
        model_api_key="sk-test",
        workspace_dir=str(tmp_path / "workspace"),
        _env_file=None,
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr("agent_harness.assembly.create_chat_model",
                      lambda config, **kw: FakeModel())

    result = await cli.run("只回复 ok", write=lambda _text: None)

    assert result == "ok"
    entries = read_jsonl(tmp_path / "logs" / "agent.jsonl")
    assert [entry["event_type(事件类型)"] for entry in entries] == [
        "agent_start",
        "llm_call",
        "agent_decision",
        "task_completed",
    ]
    assert len({entry["trace_id(追踪ID)"] for entry in entries}) == 1
    assert len({entry["task_id(任务ID)"] for entry in entries}) == 1

    llm_entry = entries[1]
    assert llm_entry["llm_input(模型输入)"] == "只回复 ok"
    assert llm_entry["llm_output(模型输出)"] == "ok"
    assert llm_entry["token_usage(Token用量)"] == {
        "prompt_tokens": 4,
        "completion_tokens": 1,
        "total_tokens": 5,
    }
    assert llm_entry["outcome(结果)"] == "success"
    assert "duration_ms(耗时毫秒)" in llm_entry
    assert entries[2]["decision(决策)"] == "finish"
    assert entries[-1]["outcome(结果)"] == "success"


@pytest.mark.asyncio
async def test_minimal_agent_failure_chain(monkeypatch, tmp_path: Path):
    """模型调用失败：runtime 补 model/failed + run/failed 终结事件，日志链
    干净收尾（task_failed outcome=error）；cli.run 不抛异常（失败由终结事件
    承载，返回空 final_text 供 main() 转 SystemExit(1)）。

    OBS-008：durable 的 model/failed 只带类型名（脱敏），因此**调用栈必须落在
    结构化日志里**——否则排障只剩「model call failed: TimeoutError」一个类型名，
    看不到具体是哪一帧/哪个 SDK 调用挂的。断言 stack_trace 存在且含真实调用栈。
    """
    from langchain_core.messages import AIMessageChunk

    class FailingModel:
        def bind_tools(self, tools, **kwargs):
            return self

        async def astream(self, messages, **kwargs):
            raise TimeoutError("模型请求超时")
            yield AIMessageChunk(content="")  # pragma: no cover

    settings = Settings(
        model_api_key="sk-test",
        workspace_dir=str(tmp_path / "workspace"),
        _env_file=None,
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr("agent_harness.assembly.create_chat_model",
                      lambda config, **kw: FailingModel())

    result = await cli.run("触发失败", write=lambda _text: None)
    assert result == ""

    entries = read_jsonl(tmp_path / "logs" / "agent.jsonl")
    assert [entry["event_type(事件类型)"] for entry in entries] == [
        "agent_start",
        "task_failed",
    ]
    task_failed = entries[-1]
    assert task_failed["outcome(结果)"] == "error"
    assert task_failed["error_type(错误类型)"] == "TimeoutError"
    # OBS-008：调用栈必须落盘（此前只有类型名，traceback 被吞）。
    stack_trace = task_failed.get("stack_trace(调用栈)")
    assert stack_trace, "模型调用失败的调用栈必须写进结构化日志（OBS-008）"
    assert "Traceback (most recent call last)" in stack_trace
    assert "TimeoutError" in stack_trace
    assert len({entry["trace_id(追踪ID)"] for entry in entries}) == 1


# ── B 组加固：formatter 对未知 event_type 显式告警（R4-6）──


def test_formatter_warns_on_unknown_event_type(caplog):
    """绕过 log_event 直接写 extra 的拼错 event_type：仍归一成 system_log，
    但必须发一条 warning（此前静默改写——诊断协议被旁路时无任何痕迹）。"""
    import json
    import logging as std_logging

    from agent_harness.logging import JsonlFormatter

    formatter = JsonlFormatter()
    record = std_logging.LogRecord(
        "agent_harness.test", std_logging.INFO, __file__, 1,
        "msg", None, None,
    )
    record.event_type = "llm_cal"  # 拼错：不在 EVENT_TYPES 白名单
    formatted = formatter.format(record)
    assert json.loads(formatted)["event_type(事件类型)"] == "system_log"
    warnings = [r for r in caplog.records if r.levelno == std_logging.WARNING
                and "llm_cal" in r.getMessage()]
    assert warnings, "未知 event_type 必须产生告警"
