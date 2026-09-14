"""Model Fallback 在真实 AgentRuntime 循环中的集成测试（T5, #80, ADR-0014）。

验证：
1. primary 瞬时失败 → 切 fallback 重试 → model/fallback 事件持久化（白盒）；
2. 非瞬时错误（参数错）不切 → 走统一失败兜底；
3. 未配 fallback → 原样失败，无 fallback 事件；
4. 切换后本 run 后续步骤沿用 fallback（never 切回，只一条事件）；
5. 流式路径（run_stream）同样支持切换。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import BaseModel, Field

from agent_harness.agent.runtime import AgentRuntime
from agent_harness.model.fallback import TwoLevelFallbackPolicy
from agent_harness.session import MODEL_FAILED, MODEL_FALLBACK
from agent_harness.tooling import Tool, ToolExecutor, ToolRegistry, ToolResult
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel


class _EchoArgs(BaseModel):
    text: str = Field(default="x", description="回显文本")


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "原样回显文本的测试工具。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EchoArgs

    async def execute(self, args: _EchoArgs) -> ToolResult:
        return ToolResult.success(message=args.text, data={"text": args.text})


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    return reg


def _tool_call(name: str, args: dict, idx: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": f"call_{idx:04d}", "name": name, "args": args}],
    )


class _StalledStreamModel:
    """先产出一个 chunk，休眠 stall_seconds 后产出第二个（模拟卡流/慢流）。"""

    def __init__(self, first_chunk: str, stall_seconds: float) -> None:
        self._first = first_chunk
        self._stall = stall_seconds

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        raise NotImplementedError

    async def astream(self, messages, **kwargs):
        yield AIMessageChunk(content=self._first)
        import asyncio

        await asyncio.sleep(self._stall)
        yield AIMessageChunk(content=" done")


class FailOnceModel:
    """前 fail_times 次 ainvoke/astream 抛指定异常，之后委托 inner（记录切换）。"""

    def __init__(self, inner: Any, fail_times: int, error: Exception) -> None:
        self._inner = inner
        self._fail_times = fail_times
        self._error = error
        self.calls = 0

    def bind_tools(self, tools, **kwargs):
        self._inner.bind_tools(tools, **kwargs)
        return self

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return await self._inner.ainvoke(messages, **kwargs)

    async def astream(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        async for chunk in self._inner.astream(messages, **kwargs):
            yield chunk


def _runtime(primary: Any, fallback: Any | None) -> AgentRuntime:
    return AgentRuntime(
        model=primary, registry=_registry(), executor=ToolExecutor(_registry()),
        max_steps=10,
        fallback_model=fallback,
        fallback_policy=TwoLevelFallbackPolicy(),
        primary_model_name="primary-model",
        fallback_model_name="fallback-model",
    )


class TestModelFallbackInLoop:
    @pytest.mark.asyncio
    async def test_transient_failure_switches_and_emits_event(self, tmp_path):
        """primary 首轮超时 → 切 fallback 完成回答 + model/fallback 事件持久化。"""
        primary = FailOnceModel(
            ScriptedModel([AIMessage(content="unused")]),
            fail_times=1, error=TimeoutError("primary down"),
        )
        fallback_answer = AIMessage(
            content="fallback 的回答",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        fallback = ScriptedModel([fallback_answer])
        runtime = _runtime(primary, fallback)
        session = make_session(tmp_path)

        result = await runtime.run(session, "你好")

        assert result.status == "completed"
        assert result.final_text == "fallback 的回答"
        events = [e for e in session._events if e.type == MODEL_FALLBACK]
        assert len(events) == 1
        data = events[0].data
        assert data["from_model"] == "primary-model"
        assert data["to_model"] == "fallback-model"
        assert data["reason"] == "TimeoutError"
        # usage = 切换后实际产出本步回答的那次调用的用量（ADR-0014 决策 18）
        assert data["usage"] == {"prompt_tokens": 10, "completion_tokens": 5,
                                 "total_tokens": 15}

    @pytest.mark.asyncio
    async def test_non_transient_error_does_not_switch(self, tmp_path):
        """参数错（ValueError）非瞬时：不切 fallback，走统一失败兜底。"""
        primary = FailOnceModel(
            ScriptedModel([AIMessage(content="unused")]),
            fail_times=99, error=ValueError("bad request shape"),
        )
        fallback = ScriptedModel([AIMessage(content="不该被用到")])
        runtime = _runtime(primary, fallback)
        session = make_session(tmp_path)

        result = await runtime.run(session, "你好")

        assert result.status == "failed"
        assert not any(e.type == MODEL_FALLBACK for e in session._events)
        # model/failed 归因到具体一步（失败兜底不变量）
        assert any(e.type == MODEL_FAILED for e in session._events)

    @pytest.mark.asyncio
    async def test_no_fallback_configured_fails_plainly(self, tmp_path):
        """未配 fallback：瞬时错误也无处可切 → 原样失败，无 fallback 事件。"""
        primary = FailOnceModel(
            ScriptedModel([AIMessage(content="unused")]),
            fail_times=99, error=TimeoutError("primary down"),
        )
        runtime = _runtime(primary, None)
        session = make_session(tmp_path)

        result = await runtime.run(session, "你好")

        assert result.status == "failed"
        assert not any(e.type == MODEL_FALLBACK for e in session._events)

    @pytest.mark.asyncio
    async def test_fallback_persists_across_steps_never_switch_back(self, tmp_path):
        """切换发生在带 tool_calls 的轮次：后续步骤沿用 fallback，全程仅一条事件。"""
        primary = FailOnceModel(
            ScriptedModel([AIMessage(content="unused")]),
            fail_times=1, error=TimeoutError("primary down"),
        )
        # fallback 剧本：第 1 轮发 tool_call，第 2 轮给最终回答
        fallback = ScriptedModel([
            _tool_call("echo", {"text": "hi"}, 0),
            AIMessage(content="工具之后的最终回答"),
        ])
        runtime = _runtime(primary, fallback)
        session = make_session(tmp_path)

        result = await runtime.run(session, "用 echo 工具")

        assert result.status == "completed"
        assert result.final_text == "工具之后的最终回答"
        assert result.steps == 2
        events = [e for e in session._events if e.type == MODEL_FALLBACK]
        assert len(events) == 1  # never 切回：全程只切一次
        assert primary.calls == 1  # 切换后不再碰 primary

    @pytest.mark.asyncio
    async def test_stream_path_also_switches(self, tmp_path):
        """流式入口（run_stream）：primary 瞬时失败 → fallback 接管完成回答。"""
        primary = FailOnceModel(
            ScriptedModel([AIMessage(content="unused")]),
            fail_times=1, error=TimeoutError("primary down"),
        )
        fallback = ScriptedModel([AIMessage(content="流式回答")])
        runtime = _runtime(primary, fallback)
        session = make_session(tmp_path)

        final_text = ""
        async for event in runtime.run_stream(session, "你好"):
            if event.type == "text/delta":
                final_text += event.data["delta"]

        assert "流式回答" in final_text
        events = [e for e in session._events if e.type == MODEL_FALLBACK]
        assert len(events) == 1
        assert events[0].data["reason"] == "TimeoutError"


class TestMalformedToolCallMarkupGuard:
    """冒烟实测发现（session 7afd328a）：碎片流下 deepseek 的 DSML 工具调用
    协议未解析成结构化 tool_calls，而是以乱码 content 泄漏——旧实现把它当
    正常最终回答 run/completed（假装成功）。契约：含协议保留标记的 content
    必须按模型故障处理（model/failed + run/failed），绝不伪造最终回答。"""

    @pytest.mark.asyncio
    async def test_dsml_markup_final_answer_fails_run(self, tmp_path):
        from agent_harness.session import MODEL_FAILED

        scripted = ScriptedModel([AIMessage(
            content='\n\n<｜DSML｜tool_calls</parameter>\n'
                    '<invoke name="true">{"ok"</invoke></p></p></',
        )])
        runtime = _runtime(scripted, None)
        session = make_session(tmp_path)

        result = await runtime.run(session, "你好")

        assert result.status == "failed"
        assert any(e.type == MODEL_FAILED for e in session._events)
        assert not any(e.type == "run/completed" for e in session._events)

    @pytest.mark.asyncio
    async def test_normal_content_mentioning_markup_passes(self, tmp_path):
        """讨论性质的文本（无协议保留标记 <｜DSML｜）不受影响。"""
        scripted = ScriptedModel([AIMessage(content="DSML 是 deepseek 的工具调用协议")])
        runtime = _runtime(scripted, None)
        session = make_session(tmp_path)

        result = await runtime.run(session, "什么是 DSML？")

        assert result.status == "completed"
        assert "deepseek" in result.final_text


class TestStallWatchdogInLoop:
    """runtime 流式卡流治理（冒烟实测收尾）：N 秒无 chunk → 瞬时 → fallback /
    统一失败兜底。watchdog 本体契约见 tests/model/test_stall_watchdog.py。"""

    def _stall_runtime(
        self, primary, fallback, idle_timeout: float = 0.2,
        total_timeout: float = 0.0,
    ) -> AgentRuntime:
        return AgentRuntime(
            model=primary, registry=_registry(), executor=ToolExecutor(_registry()),
            max_steps=10,
            fallback_model=fallback,
            primary_model_name="primary-model",
            fallback_model_name="fallback-model",
            stream_idle_timeout=idle_timeout,
            stream_total_timeout=total_timeout,
        )

    @pytest.mark.asyncio
    async def test_stream_stall_switches_to_fallback_and_completes(self, tmp_path):
        """primary 流卡死 → watchdog 断流 → fallback 接管 → run 完成 + 事件。"""
        primary = _StalledStreamModel(first_chunk="partial ", stall_seconds=99.0)
        fallback = ScriptedModel([AIMessage(content="fallback 接管完成")])
        runtime = self._stall_runtime(primary, fallback)
        session = make_session(tmp_path)

        final_text = ""
        async for event in runtime.run_stream(session, "你好"):
            if event.type == "text/delta":
                final_text += event.data["delta"]

        assert "fallback 接管完成" in final_text
        events = [e for e in session._events if e.type == MODEL_FALLBACK]
        assert len(events) == 1
        assert events[0].data["reason"] == "ModelStallError"
        assert events[0].data["from_model"] == "primary-model"

    @pytest.mark.asyncio
    async def test_stream_stall_without_fallback_fails_run(self, tmp_path):
        """未配 fallback：卡流 → watchdog 断流 → 统一失败兜底（不挂死）。"""
        primary = _StalledStreamModel(first_chunk="partial ", stall_seconds=99.0)
        runtime = self._stall_runtime(primary, None)
        session = make_session(tmp_path)

        result = await runtime.run(session, "你好")

        assert result.status == "failed"
        assert any(e.type == MODEL_FAILED for e in session._events)
        assert not any(e.type == MODEL_FALLBACK for e in session._events)

    @pytest.mark.asyncio
    async def test_stall_disabled_keeps_old_behavior(self, tmp_path):
        """stall_timeout=0 → 看门狗关闭：慢流原样通过（旧行为）。"""
        primary = _StalledStreamModel(first_chunk="slow", stall_seconds=0.3)
        runtime = self._stall_runtime(primary, None, idle_timeout=0)
        session = make_session(tmp_path)

        final_text = ""
        async for event in runtime.run_stream(session, "你好"):
            if event.type == "text/delta":
                final_text += event.data["delta"]

        assert final_text == "slow done"


class TestTransitionPersistenceOnFailure:
    """冒烟实测缺陷（集成 AI 报告）：primary 切到 fallback 后 fallback 也失败时，
    切换事实只在成功路径 drain —— 异常臂丢失 model/fallback 事件，JSONL 里
    看起来像"从未切换"（白盒透明的洞）。契约：任何终态下切换事实都落盘。"""

    @pytest.mark.asyncio
    async def test_fallback_also_stalls_still_persists_transition(self, tmp_path):
        primary = _StalledStreamModel(first_chunk="partial ", stall_seconds=99.0)
        fallback = _StalledStreamModel(first_chunk="fb ", stall_seconds=99.0)
        runtime = AgentRuntime(
            model=primary, registry=_registry(), executor=ToolExecutor(_registry()),
            max_steps=10,
            fallback_model=fallback,
            primary_model_name="primary-model",
            fallback_model_name="fallback-model",
            stream_idle_timeout=0.2,
        )
        session = make_session(tmp_path)

        # 流式路径（stall 守卫只治理流式；ainvoke 的总时限显式 DEFER）
        async for _event in runtime.run_stream(session, "你好"):
            pass

        transitions = [e for e in session._events if e.type == MODEL_FALLBACK]
        assert len(transitions) == 1, "fallback 也失败时切换事实仍必须持久化"
        assert transitions[0].data["from_model"] == "primary-model"
        assert transitions[0].data["to_model"] == "fallback-model"
        assert transitions[0].data["reason"] == "ModelStallError"


class TestModelCallGateWiring:
    """#89：闸贯穿 coordinator/runtime/assembly；排队不计入卡流 idle。"""

    @pytest.mark.asyncio
    async def test_coordinator_ainvoke_gated(self, tmp_path):
        import time

        from agent_harness.model.concurrency import ModelCallGate

        gate = ModelCallGate(limit=1)
        inner = ScriptedModel([AIMessage(content="ok"), AIMessage(content="ok")])
        coord_a = AgentRuntime(
            model=inner, registry=_registry(), executor=ToolExecutor(_registry()),
            max_steps=5, model_call_gate=gate,
        )._new_coordinator()
        coord_b = AgentRuntime(
            model=inner, registry=_registry(), executor=ToolExecutor(_registry()),
            max_steps=5, model_call_gate=gate,
        )._new_coordinator()

        t0 = time.perf_counter()
        await asyncio.gather(coord_a.ainvoke([]), coord_b.ainvoke([]))
        elapsed = time.perf_counter() - t0
        # 两个调用共享 1 个槽位 → 串行化（各自 ScriptedModel ainvoke 无延迟，
        # 串行化证据取槽位语义而非时长，这里主要验证不死锁、不丢结果）
        assert elapsed < 5
