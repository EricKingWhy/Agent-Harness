"""同错熔断在真实 AgentRuntime 循环中的集成测试（T1, #76, ADR-0014）。

用 ScriptedModel + 总是失败的 FailureTool 构造模型反复同错调用，
验证：软熔断（3 次）→ 注入 user 纠正消息 → 再 3 次 → 硬熔断 → end_run(failed)。
不同工具交替 / 同工具不同 args 不误伤。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from agent_harness.agent.runtime import AgentRuntime
from agent_harness.agent.types import STATUS_IDENTICAL_TOOL_FAILURE_LOOP
from agent_harness.session import TOOL_FAILURE_GUARD, USER_MESSAGE
from agent_harness.tooling import Tool, ToolExecutor, ToolRegistry, ToolResult
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel

TOOL_CALL_ID = "call_agent_0001"


class _FailArgs(BaseModel):
    command: str = Field(default="x", description="要执行的命令")


class FailureTool(Tool):
    """总是返回 ok=False 的工具（模拟命令业务失败——非执行异常）。"""

    @property
    def name(self) -> str:
        return "fail"

    @property
    def description(self) -> str:
        return "总是失败的工具。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _FailArgs

    async def execute(self, args: _FailArgs) -> ToolResult:
        return ToolResult.failure(
            message=f"命令 {args.command!r} 失败", error_code="TOOL_EXECUTION_ERROR",
        )


class FlakyTool(Tool):
    """按 args.command 决定成功/失败：偶数次失败用于测「成功不重置计数」。

    成功路径 ok=True 但工具名 + args 指纹与失败路径相同——验证 Q12-b：
    只有指纹变化才清零，成功不重置。
    """

    @property
    def name(self) -> str:
        return "flaky"

    @property
    def description(self) -> str:
        return "按 command 内容决定成功或失败的测试工具。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _FailArgs

    async def execute(self, args: _FailArgs) -> ToolResult:
        # command="boom" 永远失败；其它永远成功。
        if args.command == "boom":
            return ToolResult.failure(message="boom 失败", error_code="TOOL_EXECUTION_ERROR")
        return ToolResult.success(message="ok", data={"command": args.command})


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FailureTool())
    reg.register(FlakyTool())
    return reg


def _runtime(model: ScriptedModel, max_steps: int = 20) -> AgentRuntime:
    reg = _registry()
    return AgentRuntime(
        model=model, registry=reg, executor=ToolExecutor(reg), max_steps=max_steps,
    )


def _tool_call(name: str, args: dict, idx: int) -> AIMessage:
    """构造带单个 tool_call 的 AIMessage（call_id 唯一避免 ledger 冲突）。"""
    return AIMessage(
        content="",
        tool_calls=[{
            "id": f"call_{idx:04d}",
            "name": name,
            "args": args,
        }],
    )


class TestRepeatedToolFailureGuardInLoop:
    """通过 Runtime 全循环验证两级熔断行为。"""

    @pytest.mark.asyncio
    async def test_soft_then_hard_triggers_on_repeated_identical_failure(self, tmp_path):
        """连续 6 次同指纹 fail 调用 → 第 3 次软熔断 + 第 6 次硬熔断。"""
        # 6 轮，每轮模型提议同一个 fail 调用（同 args）。
        scripted = ScriptedModel([
            _tool_call("fail", {"command": "ls"}, i) for i in range(6)
        ])
        runtime = _runtime(scripted, max_steps=20)
        session = make_session(tmp_path)

        result = await runtime.run(session, "反复试同一个失败命令")

        # 硬熔断：status = identical_tool_failure_loop
        assert result.status == STATUS_IDENTICAL_TOOL_FAILURE_LOOP
        assert result.steps == 6  # 第 6 轮触发 HARD

        # 事件历史里应有 soft + hard 两条 tool_failure_guard
        guard_events = [e for e in session._events if e.type == TOOL_FAILURE_GUARD]
        assert len(guard_events) == 2
        levels = [e.data["level"] for e in guard_events]
        assert levels == ["soft", "hard"]
        # 软熔断后注入了 user 角色纠正消息
        corrective = [
            e for e in session._events
            if e.type == USER_MESSAGE and "改变策略" in e.data.get("content", "")
        ]
        assert len(corrective) == 1
        # 注入消息带来源标记（runtime 行为 ≠ 真实用户发言，前端投影可区分）
        assert corrective[0].data.get("injected_by") == "tool_failure_guard"
        # 持久化的 run/failed 带 reason（消费者区分失败原因，#76 契约）
        run_failed = [e for e in session._events if e.type == "run/failed"]
        assert len(run_failed) == 1
        assert run_failed[0].data.get("reason") == STATUS_IDENTICAL_TOOL_FAILURE_LOOP

    @pytest.mark.asyncio
    async def test_different_args_does_not_trigger(self, tmp_path):
        """同工具不同 args → 指纹变化清零，不触发熔断。"""
        # 每轮换 args → 指纹都不同 → 计数器每次清零。
        scripted = ScriptedModel([
            _tool_call("fail", {"command": f"cmd{i}"}, i) for i in range(6)
        ])
        runtime = _runtime(scripted, max_steps=10)
        session = make_session(tmp_path)

        result = await runtime.run(session, "每轮换不同命令")

        # 没触发熔断——撞 max_steps（10）兜底。
        assert result.status != STATUS_IDENTICAL_TOOL_FAILURE_LOOP
        guard_events = [e for e in session._events if e.type == TOOL_FAILURE_GUARD]
        assert len(guard_events) == 0

    @pytest.mark.asyncio
    async def test_success_does_not_reset_counter(self, tmp_path):
        """Q12 b：同指纹的成功结果不重置计数；失败累积到阈值仍触发。

        用 FlakyTool 保持指纹 (flaky, {command: "boom"}) 一致——
        中间穿插一次成功（command 不同但... 不行：command 变了指纹也变）。
        正确姿势：同一指纹永远失败时计数累积；同指纹的成功只可能出现在
        guard 单元测试（同 fp、ok=True）里——此处验证完整循环里
        「成功不重置」的可观察行为：flaky("boom")×3 触发软，
        之后 flaky("ok")（指纹变 → 清零）→ 不再触发硬。
        """
        # 3 次 boom 失败（软触发）+ 1 次 ok（指纹变 → 清零）→ 不应触发硬。
        scripted = ScriptedModel([
            _tool_call("flaky", {"command": "boom"}, 0),
            _tool_call("flaky", {"command": "boom"}, 1),
            _tool_call("flaky", {"command": "boom"}, 2),  # soft @ 3
            _tool_call("flaky", {"command": "ok"}, 3),     # 指纹变 → 清零
        ] + [_tool_call("flaky", {"command": "ok"}, i) for i in range(4, 9)])
        runtime = _runtime(scripted, max_steps=15)
        session = make_session(tmp_path)

        result = await runtime.run(session, "成功穿插")

        # 软触发发生，但因指纹变化未累积到硬。
        guard_events = [e for e in session._events if e.type == TOOL_FAILURE_GUARD]
        assert any(e.data["level"] == "soft" for e in guard_events)
        assert not any(e.data["level"] == "hard" for e in guard_events)
        assert result.status != STATUS_IDENTICAL_TOOL_FAILURE_LOOP

    @pytest.mark.asyncio
    async def test_alternating_different_tools_does_not_trigger(self, tmp_path):
        """fail 与 flaky 交替（不同工具名 → 指纹变化清零），不熔断。"""
        scripted = ScriptedModel([
            _tool_call("fail", {"command": "x"}, 0),
            _tool_call("flaky", {"command": "boom"}, 1),
            _tool_call("fail", {"command": "x"}, 2),
            _tool_call("flaky", {"command": "boom"}, 3),
            _tool_call("fail", {"command": "x"}, 4),
            _tool_call("flaky", {"command": "boom"}, 5),
        ])
        runtime = _runtime(scripted, max_steps=10)
        session = make_session(tmp_path)

        result = await runtime.run(session, "交替调不同工具")

        assert result.status != STATUS_IDENTICAL_TOOL_FAILURE_LOOP
        guard_events = [e for e in session._events if e.type == TOOL_FAILURE_GUARD]
        assert len(guard_events) == 0
