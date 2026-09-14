"""Phase 9 CLI Renderer：AgentEvent 流 → 终端文本；会话持久化；失败退出码。

渲染约定借鉴 pi-mono / oh-my-pi（均 MIT，见 cli.py 模块 docstring 署名）：
状态行语法、参数折叠、结果尾部预览、时长徽章、用量页脚；V1 采用 ascii 符号
（oh-my-pi 的 ascii preset 路线——Windows GBK 控制台编码 ✔/⏳ 会崩）。
渲染器是事件流的纯函数：完整事实源是 Session JSONL，终端只挑人要看的。
"""

import json

import pytest
from langchain_core.messages import AIMessage

from agent_harness.agent import AgentEvent
from agent_harness.cli import StreamRenderer, run
from agent_harness.session import (
    MODEL_COMPLETED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    SESSION_STARTED,
    TEXT_DELTA,
    TOOL_CALL,
    TOOL_RESULT,
    USER_MESSAGE,
    JsonlSessionStore,
)
from tests.scripted_model import ScriptedModel


def _event(event_type: str, data: dict) -> AgentEvent:
    return AgentEvent(type=event_type, data=data, run_id="r1", step_id=1)


class TestStreamRenderer:
    def test_deltas_stream_verbatim_without_newlines(self):
        out: list[str] = []
        renderer = StreamRenderer(out.append)
        renderer.handle(_event(TEXT_DELTA, {"delta": "你"}))
        renderer.handle(_event(TEXT_DELTA, {"delta": "好"}))
        assert out == ["你", "好"], "delta 是流式正文，逐段原样续写"

    def test_tool_call_closes_delta_and_collapses_args(self):
        out: list[str] = []
        renderer = StreamRenderer(out.append)
        renderer.handle(_event(TEXT_DELTA, {"delta": "正在查"}))
        renderer.handle(_event(TOOL_CALL, {
            "tool_call_id": "c1", "tool_name": "bash",
            "args": {"command": "ls -la", "timeout": 5}}))
        assert "".join(out) == '正在查\n\n[tool] bash command="ls -la" timeout=5\n'

    def test_tool_result_shows_status_duration_and_preview(self):
        out: list[str] = []
        renderer = StreamRenderer(out.append)
        renderer.handle(_event(TOOL_RESULT, {
            "tool_call_id": "c1",
            "content": json.dumps({
                "ok": True, "message": "a\nb\nc\nd",
                "metadata": {"duration_ms": 1234}})}))
        assert out == ["  [ok] (1.2s)\n", "  a\n", "  b\n", "  c\n",
                       "  ... +1 more lines\n"]

    def test_tool_failure_marked_without_duration(self):
        out: list[str] = []
        renderer = StreamRenderer(out.append)
        renderer.handle(_event(TOOL_RESULT, {
            "tool_call_id": "c1",
            "content": json.dumps({"ok": False, "message": "boom"})}))
        assert out == ["  [fail]\n", "  boom\n"]

    def test_run_completed_prints_usage_footer(self):
        out: list[str] = []
        renderer = StreamRenderer(out.append)
        renderer.handle(_event(RUN_COMPLETED, {
            "final_text": "完成",
            "usage_total": {"prompt_tokens": 1200, "completion_tokens": 345}}))
        assert out == ["\n", "tokens: in 1.2k, out 345\n"]

    def test_run_completed_without_usage_prints_blank_line_only(self):
        out: list[str] = []
        StreamRenderer(out.append).handle(
            _event(RUN_COMPLETED, {"final_text": "done"}))
        assert out == ["\n"]

    def test_run_failed_shows_reason(self):
        out: list[str] = []
        StreamRenderer(out.append).handle(
            _event(RUN_FAILED, {"reason": "cancelled"}))
        assert out == ["\n[run failed] (cancelled)\n"]

    def test_persistence_only_events_are_silent(self):
        """model/completed、user/message 等持久化镜像不渲染——事实在 JSONL，
        重复打印只会把终端变成第二份日志（与不变量 #5/#6 同一哲学）。"""
        out: list[str] = []
        renderer = StreamRenderer(out.append)
        for event_type, data in ((USER_MESSAGE, {"content": "hi"}),
                                 (MODEL_COMPLETED, {"content": "你好"})):
            renderer.handle(_event(event_type, data))
        assert out == []


@pytest.mark.asyncio
async def test_cli_run_streams_persists_session_and_returns_final_text(
    tmp_path, monkeypatch
):
    from agent_harness.config import Settings

    monkeypatch.setattr(
        "agent_harness.cli.Settings",
        lambda: Settings(model_api_key="sk-test", workspace_dir=str(tmp_path),
                         _env_file=None),
    )
    monkeypatch.setattr(
        "agent_harness.assembly.create_chat_model",
        lambda config, **kw: ScriptedModel([AIMessage(content="你好世界")], chunk_size=2),
    )
    out: list[str] = []
    final = await run("打个招呼", write=out.append)

    assert final == "你好世界"
    streamed = "".join(out)
    assert "你好" in streamed and "世界" in streamed, "回答经 delta 流式可见"

    # 会话持久化：完整事件链落在 JSONL（CLI 不再是无事实源的裸 ainvoke）
    store = JsonlSessionStore(root=tmp_path / "sessions")
    (session_id,) = store.list_session_ids()
    types = [event.type for event in store.read_events(session_id)]
    assert types == [SESSION_STARTED, USER_MESSAGE, RUN_STARTED,
                     TEXT_DELTA, MODEL_COMPLETED, RUN_COMPLETED]


@pytest.mark.asyncio
async def test_cli_run_failed_returns_empty_final_text(tmp_path, monkeypatch):
    """失败的 run 不抛异常（runtime 契约：失败事实由终结事件承载）——
    返回空 final_text 供 main() 转 SystemExit(1)，渲染层已告知原因。"""
    from agent_harness.config import Settings

    class ExplodingModel:
        def bind_tools(self, tools, **kwargs):
            return self

        async def astream(self, messages, **kwargs):
            raise TimeoutError("模型请求超时")
            yield AIMessage(content="")  # pragma: no cover — 声明 async generator 用

    monkeypatch.setattr(
        "agent_harness.cli.Settings",
        lambda: Settings(model_api_key="sk-test", workspace_dir=str(tmp_path),
                         _env_file=None),
    )
    monkeypatch.setattr(
        "agent_harness.assembly.create_chat_model", lambda config, **kw: ExplodingModel(),
    )
    out: list[str] = []
    final = await run("触发失败", write=out.append)
    assert final == ""
    assert "[run failed]" in "".join(out)
