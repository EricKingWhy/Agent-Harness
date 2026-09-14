"""AgentRuntime 失败路径回归：异常终结、并发结果隔离、非 str content 落盘。

三个面：
- 模型调用抛错（API 中断）：run / run_stream 必须以 run/failed 终结——JSONL 不能
  停在悬空的 run/started 上，SSE 消费者必须收到终止帧，run() 返回 failed 结果
  而不是把异常抛给调用方。
- 非 str content（Anthropic 风格块列表）：落盘前抽纯文本，绝不把 Python repr
  写进 model/completed 再被 derive_messages 回灌给模型。
- 并发 run()：最终结果经每次调用的独立载体回传，不经实例字段跨 run 串台。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from agent_harness.agent import AgentRuntime
from agent_harness.agent.types import STATUS_FAILED
from agent_harness.session import (
    MODEL_COMPLETED,
    MODEL_FAILED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    TEXT_DELTA,
    TOOL_CALL,
    TOOL_RESULT,
    JsonlSessionStore,
)
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel

TOOL_CALL_ID = "call_failure_001"


# ---- 失败注入替身：异常来自模型调用本身（不是工具），剧本可控可重现 ----


class ExplodingModel:
    """ainvoke / astream 一律抛 RuntimeError：模拟 API 中断（供应商宕机）。"""

    async def ainvoke(self, messages: list, **kwargs) -> AIMessage:
        raise RuntimeError("模拟 API 中断")

    async def astream(self, messages: list, **kwargs):
        raise RuntimeError("模拟 API 中断")
        yield AIMessageChunk(content="")  # 不可达：仅为把函数声明成 async generator


class ToolCallThenExplodeModel:
    """第 1 轮正常提议工具，第 2 轮 ainvoke 抛错：模拟多轮循环中途 API 中断。"""

    def __init__(self, tool_call: dict) -> None:
        self._tool_call = tool_call
        self._calls = 0

    async def ainvoke(self, messages: list, **kwargs) -> AIMessage:
        self._calls += 1
        if self._calls == 1:
            return AIMessage(content="", tool_calls=[self._tool_call])
        raise RuntimeError("第二轮模型调用中断")


class ListContentModel:
    """ainvoke / astream 都吐 Anthropic 风格块列表：验证落盘前抽纯文本，不落 repr。"""

    async def ainvoke(self, messages: list, **kwargs) -> AIMessage:
        return AIMessage(content=[
            {"type": "text", "text": "你好"},
            {"type": "text", "text": "世界"},
        ])

    async def astream(self, messages: list, **kwargs):
        yield AIMessageChunk(content=[{"type": "text", "text": "你好"}])
        yield AIMessageChunk(content=[{"type": "text", "text": "世界"}])


def _runtime(model: Any, registry: ToolRegistry | None = None) -> AgentRuntime:
    """构造最小 Runtime：不传 registry 时用空 Registry（模型替身无需 bind_tools）。"""
    reg = registry or ToolRegistry()
    return AgentRuntime(model=model, registry=reg, executor=ToolExecutor(reg))


# ---------- FIX 1：模型调用异常必须以 run/failed 终结，不能悬挂 ----------


class TestModelExceptionTerminalEvents:
    """模型 ainvoke / astream 抛错：补终结事件 + 正常收流 + 返回 failed 结果。"""

    @pytest.mark.asyncio
    async def test_run_returns_failed_result_and_persists_run_failed(self, tmp_path):
        """ainvoke 抛错 -> run() 正常返回 failed（不向上抛）+ JSONL 以 run/failed 终结。"""
        session = make_session(tmp_path)
        runtime = _runtime(ExplodingModel())

        result = await runtime.run(session, "你好")

        # run() 不把异常抛给调用方；终结状态如实是 failed，final_text 绝不伪造
        assert result.status == "failed"
        assert result.final_text == ""
        # 从 store 重读（不只看内存缓存）：JSONL 的最后一条必须是 run/failed
        persisted = JsonlSessionStore(root=tmp_path).read_events(session.session_id)
        assert persisted[-1].type == RUN_FAILED
        run_started = next(e for e in persisted if e.type == RUN_STARTED)
        assert persisted[-1].run_id == run_started.run_id
        assert "final_text" not in persisted[-1].data
        # 故障归因：模型调用阶段炸的 -> model/failed 也要落盘（该类型此前从未发过）
        assert [e.type for e in persisted[-2:]] == [MODEL_FAILED, RUN_FAILED]

    @pytest.mark.asyncio
    async def test_run_stream_completes_with_terminal_failure_frame(self, tmp_path):
        """astream 中途抛错 -> 迭代器正常收尾，最后一帧是 run/failed（SSE 不断流）。"""
        session = make_session(tmp_path)
        runtime = _runtime(ExplodingModel())

        frames = [frame async for frame in runtime.run_stream(session, "你好")]

        # 迭代器正常耗尽（异常不向上抛），终结帧来自持久化事件（有 seq）
        assert frames[-1].type == RUN_FAILED
        assert frames[-1].is_durable
        assert MODEL_FAILED in [f.type for f in frames]

    @pytest.mark.asyncio
    async def test_persisted_tool_backfill_intact_after_midloop_failure(self, tmp_path):
        """工具回填已落盘后第 2 轮模型炸 -> 回填事件恰好一次、无重复补写。"""
        session = make_session(tmp_path)
        model = ToolCallThenExplodeModel({
            "name": "multiply",
            "args": {"first_number": 3, "second_number": 4},
            "id": TOOL_CALL_ID,
            "type": "tool_call",
        })
        runtime = _runtime(model)  # multiply 未注册 -> Executor 回填错误而不是抛

        result = await runtime.run(session, "计算 3 乘 4")

        assert result.status == "failed"
        events = session.events
        # 第 1 轮的 tool/call + tool/result 已持久化，且各恰好一份（兜底不得重复补写）
        assert [e.data["tool_call_id"] for e in events if e.type == TOOL_CALL] == [TOOL_CALL_ID]
        assert [e.data["tool_call_id"] for e in events if e.type == TOOL_RESULT] == [TOOL_CALL_ID]
        # 第 1 轮 model/completed 也还在：历史完整可重放
        assert any(e.type == MODEL_COMPLETED for e in events)
        # 收尾：model/failed + run/failed
        assert [e.type for e in events[-2:]] == [MODEL_FAILED, RUN_FAILED]


# ---------- FIX 3：非 str content（Anthropic 风格块）落盘前抽纯文本 ----------


class TestNonStrContentExtracted:
    """list 型 content 绝不能以 Python repr 形态进 JSONL / final_text / delta。"""

    @pytest.mark.asyncio
    async def test_ainvoke_list_content_persisted_as_plain_text(self, tmp_path):
        """ainvoke 返回块列表 -> model/completed.content 是拼接文本，不是 repr。"""
        session = make_session(tmp_path)
        runtime = _runtime(ListContentModel())

        result = await runtime.run(session, "打个招呼")

        # final_text 来自模型 content，抽纯文本而非 str(list) 的 repr
        assert result.status == "completed"
        assert result.final_text == "你好世界"
        completed = next(e for e in session.events if e.type == MODEL_COMPLETED)
        assert completed.data["content"] == "你好世界"
        # 全部持久化事件里不允许出现 repr 痕迹（derive_messages 会把它回灌给模型）
        for event in session.events:
            assert "['" not in str(event.data.get("content", ""))

    @pytest.mark.asyncio
    async def test_astream_list_content_deltas_and_persistence(self, tmp_path):
        """astream 逐 chunk 吐块列表 -> delta 是纯文本，聚合落盘同样是纯文本。"""
        session = make_session(tmp_path)
        runtime = _runtime(ListContentModel())

        frames = [frame async for frame in runtime.run_stream(session, "打个招呼")]

        deltas = [f.data["delta"] for f in frames if f.type == TEXT_DELTA]
        # ADR-0016 §3.3：30ms 窗口内快速 chunk 合帧——拼接不变，行数不逐 token
        assert "".join(deltas) == "你好世界"
        assert all(f.seq is not None for f in frames if f.type == TEXT_DELTA)
        completed = next(e for e in session.events if e.type == MODEL_COMPLETED)
        assert completed.data["content"] == "你好世界"
        for frame in frames:
            assert "['" not in str(frame.data.get("delta", ""))


# ---------- FIX 2：并发 run() 的结果隔离（结果不经实例字段跨 run 串台） ----------


class CounterModel:
    """ainvoke 返回 answer-{n}；sleep(0) 让出事件循环，保证两个 run 真正并发交错。"""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages: list, **kwargs) -> AIMessage:
        await asyncio.sleep(0)
        self.calls += 1
        return AIMessage(content=f"answer-{self.calls}")


class TestConcurrentRunResultIsolation:
    @pytest.mark.asyncio
    async def test_two_concurrent_runs_each_get_own_result(self, tmp_path):
        """同一 Runtime 并发两个 run -> 各拿自己那次调用的回答，不做"最后完成者"串台。"""
        runtime = _runtime(CounterModel())

        r1, r2 = await asyncio.gather(
            runtime.run(make_session(tmp_path), "问题一"),
            runtime.run(make_session(tmp_path), "问题二"),
        )

        assert r1.status == "completed"
        assert r2.status == "completed"
        # 结果必须经每次调用独立的载体回传：两份回答各归各的 run，
        # 而不是共享实例字段上"谁后写谁生效"的那一份。
        assert r1.final_text != r2.final_text
        assert {r1.final_text, r2.final_text} == {"answer-1", "answer-2"}


@pytest.mark.asyncio
async def test_model_failed_event_redacts_exception_message(tmp_path):
    """model/failed 事件只带异常类型名，不带原始消息——Provider 异常文本可能
    含回显的凭证（脱敏不变量与 memory/writeback 一致）；完整消息只进日志。"""
    class ExplodingModel:
        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages, **kwargs):
            raise RuntimeError("api-key sk-secret-123 invalid")

    from tests.conftest import make_session

    runtime = AgentRuntime(ExplodingModel(), ToolRegistry(), ToolExecutor(ToolRegistry()))
    session = make_session(tmp_path)
    result = await runtime.run(session, "hello")
    assert result.status == STATUS_FAILED
    model_failed = next(e for e in session.events if e.type == "model/failed")
    assert model_failed.data["message"] == "model call failed: RuntimeError"
    assert "sk-secret-123" not in str(model_failed.data)


# ---- provider 内容审查拒绝（data_inspection_failed）→ 可读失败消息 ----


#: 2026-09-11 真实案例：阿里云百炼专有端点对含检索网页文本的二次调用返回
#: 400，错误码只出现在响应体文本里（openai SDK 对 SSE 形状错误解析不出结构
#: 化 body）。原样保留形状作分类器输入。
ALIYUN_INSPECTION_PAYLOAD = (
    'data: {"error":{"code":"data_inspection_failed","param":null,'
    '"message":"Input text data may contain inappropriate content.",'
    '"type":"data_inspection_failed"},"id":"chatcmpl-88bc0696"}'
)


class ModerationRejectModel:
    """ainvoke / astream 抛携带 data_inspection_failed 载荷的错误。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        raise RuntimeError(ALIYUN_INSPECTION_PAYLOAD)

    async def astream(self, messages, **kwargs):
        raise RuntimeError(ALIYUN_INSPECTION_PAYLOAD)
        yield AIMessageChunk(content="")  # 不可达：声明 async generator 用


READABLE = "provider 内容审查拒绝输入（可能因检索到的网页文本）"


class TestProviderContentModerationClassification:
    """错误文本含 data_inspection_failed → 失败事件升级为已分类可读消息。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_stream", [True, False])
    async def test_moderation_rejection_upgrades_terminal_events(
        self,
        tmp_path,
        use_stream,
    ):
        """model/failed.message 是固定可读文案；run/failed 落
        reason=provider_content_moderation + 同文案 message（与上下文超限
        路径的 reason+message 形状一致）。run()/run_stream() 两条路径同享。"""
        session = make_session(tmp_path)
        runtime = _runtime(ModerationRejectModel())

        if use_stream:
            frames = [f async for f in runtime.run_stream(session, "写论文")]
            assert any(f.type == MODEL_FAILED for f in frames), (
                "流路径 model/failed 也必须镜像给 SSE 消费者"
            )
        else:
            result = await runtime.run(session, "写论文")
            assert result.status == STATUS_FAILED

        # 两条路径都以持久化事件为准断言（SSE 帧来自持久化事件镜像）
        model_failed = next(e for e in session.events if e.type == MODEL_FAILED)
        assert model_failed.data["message"] == READABLE
        failed = next(e for e in session.events if e.type == RUN_FAILED)
        assert failed.data["reason"] == "provider_content_moderation"
        assert failed.data["message"] == READABLE

    @pytest.mark.asyncio
    async def test_moderation_rejection_model_failed_message_readable(self, tmp_path):
        """model/failed 的 message 用固定可读文案，且绝不携带 provider 回显
        原文（脱敏不变量——载荷文本可能含敏感内容，只进结构化日志）。"""
        session = make_session(tmp_path)
        runtime = _runtime(ModerationRejectModel())

        await runtime.run(session, "写论文")

        model_failed = next(e for e in session.events if e.type == MODEL_FAILED)
        assert model_failed.data["message"] == READABLE
        for event in session.events:
            assert "inappropriate" not in str(event.data), (
                "provider 回显原文不得进任何持久化事件"
            )
            assert "chatcmpl-88bc0696" not in str(event.data)

    @pytest.mark.asyncio
    async def test_unclassified_failure_keeps_type_only_terminal(self, tmp_path):
        """未分类错误保持原行为：model/failed 只带类型名，run/failed 不落
        reason / message 键（合同：缺省 = 模型/执行器异常）。"""
        session = make_session(tmp_path)
        runtime = _runtime(ExplodingModel())

        result = await runtime.run(session, "你好")

        assert result.status == STATUS_FAILED
        model_failed = next(e for e in session.events if e.type == MODEL_FAILED)
        assert model_failed.data["message"] == "model call failed: RuntimeError"
        run_failed = next(e for e in session.events if e.type == RUN_FAILED)
        assert "reason" not in run_failed.data
        assert "message" not in run_failed.data

    @pytest.mark.asyncio
    async def test_tool_phase_error_with_marker_not_misclassified(self, tmp_path):
        """分类只在模型调用在途时进行：工具/执行器阶段异常的错误文本即使恰好
        含 data_inspection_failed（如抓取到引用该错误码的文档），也不得误标——
        model_call_open 在模型完整返回后已复位（runtime.py「调用完整返回，
        后续异常不再归因 model」）。"""
        session = make_session(tmp_path)
        model = ToolCallThenExplodeModel({
            "name": "multiply",
            "args": {"first_number": 3, "second_number": 4},
            "id": TOOL_CALL_ID,
            "type": "tool_call",
        })
        # 篡改：tool/call 写盘时抛含错误码的异常（模拟工具阶段异常抵达顶层兜底）
        original_append = session.append
        marker_error = RuntimeError('data: {"error":{"code":"data_inspection_failed"}}')

        def sabotaged_append(event_type, data, **kwargs):
            if event_type == TOOL_CALL:
                raise marker_error
            return original_append(event_type, data, **kwargs)

        session.append = sabotaged_append
        runtime = _runtime(model)

        result = await runtime.run(session, "计算 3 乘 4")

        assert result.status == STATUS_FAILED
        run_failed = next(e for e in session.events if e.type == RUN_FAILED)
        assert "reason" not in run_failed.data, "工具阶段异常不得误标内容审查"
        assert "message" not in run_failed.data
        # 模型已完整返回（归因窗口已关）：不补 model/failed
        assert not [e for e in session.events if e.type == MODEL_FAILED]


@pytest.mark.asyncio
async def test_stream_close_persists_terminal_event(tmp_path):
    """消费方中途关闭 run_stream 生成器（客户端断连的运行时等价物）时，
    _drive 必须补 run/failed 终结事件再退出——JSONL 绝不能停在悬空的
    run/started 上（该 run 在历史里永远没有结局）。

    GeneratorExit / CancelledError 是 BaseException，顶层 except Exception
    兜不到；取消臂只做持久化收尾（不 yield——生成器关闭中禁止再产出），
    然后继续向上传播取消。
    """
    session = make_session(tmp_path)
    runtime = AgentRuntime(
        model=ScriptedModel([AIMessage(content="第一轮就完成的答案")]),
        registry=ToolRegistry(),
        executor=ToolExecutor(ToolRegistry()),
    )
    agen = runtime.run_stream(session, "hi")
    async for _event in agen:
        if _event.type == RUN_STARTED:
            break  # 悬空点：run/started 已持久化 + 已 yield，消费者在这里断开
    await agen.aclose()

    event_types = [e.type for e in session.events]
    assert event_types[-1] == RUN_FAILED, f"悬空 run/started 未被终结：{event_types}"
    failed = session.events[-1]
    assert failed.data.get("reason") == "cancelled"


@pytest.mark.asyncio
async def test_stream_close_after_completion_does_not_double_terminate(tmp_path):
    """取消落在 run/completed 已持久化之后的窗口（终结帧 yield / 收尾 checkpoint
    await）时，不得给同一 run 再补 run/failed——双终结事件 = 历史不可对账。"""
    session = make_session(tmp_path)
    runtime = AgentRuntime(
        model=ScriptedModel([AIMessage(content="最终回答")]),
        registry=ToolRegistry(),
        executor=ToolExecutor(ToolRegistry()),
    )
    agen = runtime.run_stream(session, "hi")
    async for _event in agen:
        if _event.type == RUN_COMPLETED:
            break  # 终结帧已拿到；生成器挂在终结帧 yield / 收尾 checkpoint 窗口
    await agen.aclose()

    terminals = [e.type for e in session.events if e.type in (RUN_COMPLETED, RUN_FAILED)]
    assert terminals == [RUN_COMPLETED], f"出现双终结：{terminals}"


# ---- A 组（R6-2）：零 chunk 流不得伪装成成功完成 ----


class EmptyStreamModel:
    """ainvoke/astream 吐出零 chunk（内容过滤/上游静默失败的模拟）。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        return AIMessage(content="")

    async def astream(self, messages, **kwargs):
        return
        yield AIMessageChunk(content="")  # 不可达：声明 async generator 用


@pytest.mark.asyncio
@pytest.mark.parametrize("use_stream", [True, False])
async def test_empty_model_response_fails_the_run(tmp_path, use_stream):
    """聚合后 content 与 tool_calls 双空 = 模型没有产出任何决策：
    按 model/failed + run/failed 终结，而不是 completed + final_text=""。

    SSE 客户端必须能区分"模型答了空话"与"上游失败"——静默空成功是最危险的
    错误结果形态（R6-2，用户拍板）。"""
    session = make_session(tmp_path)
    runtime = AgentRuntime(EmptyStreamModel(), ToolRegistry(), ToolExecutor(ToolRegistry()))
    result = await runtime.run(session, "hi")
    assert result.status == STATUS_FAILED
    types = [e.type for e in session.events]
    assert types[-1] == RUN_FAILED
    assert "model/failed" in types
    completed = [e for e in session.events if e.type == "model/completed"]
    assert not completed, "空响应不应持久化为 model/completed"


# ---------- 批次 B / 候选 2：消费方抛异常不得产生双终结 ----------


@pytest.mark.asyncio
async def test_consumer_throw_after_completed_does_not_double_terminal(tmp_path):
    """消费方在 run/completed 的 yield 点向生成器抛异常（SSE 中转层故障的
    抽象）：异常臂不得对已终结的 run 再补 run/failed——"一个 run 至多一条
    终态事件"是不变量（双终结 = 历史不可对账）。此前该检查只在取消臂有、
    异常臂没有，属漏网的双终结窗口。"""
    from tests.conftest import make_session

    session = make_session(tmp_path)
    runtime = _runtime(ScriptedModel(responses=[AIMessage(content="done")]))
    terminals: list[str] = []

    gen = runtime.run_stream(session, "hi")
    async for event in gen:
        if event.type in (RUN_COMPLETED, RUN_FAILED):
            terminals.append(event.type)
        if event.type == RUN_COMPLETED:
            with pytest.raises(RuntimeError):
                await gen.athrow(RuntimeError("consumer exploded mid-stream"))
            break

    persisted = [e.type for e in session.events]
    assert terminals == ["run/completed"], f"消费方应已收到 run/completed：{terminals}"
    assert persisted.count("run/completed") == 1
    assert persisted.count("run/failed") == 0, (
        f"已终结的 run 不得补第二条终态事件，实际事件链：{persisted}"
    )
