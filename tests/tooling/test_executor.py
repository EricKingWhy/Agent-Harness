"""Day4 Task2/Task3：ToolExecutor 单次执行链 + Timeout/Retry 行为测试。

Task3 新增（详见文件末尾 Task3 部分）：
- SlowTool / FlakyTool / ForbiddenTool 制造三类失败，观察重试与不重试的差异；
- JSONL 测试：按 tool_call_id 从日志还原 attempt / duration_ms / error_code 链。

Hands-on 落点（见下方 TODO 注释）：

Validation-first 是本 Task 最锋利的一刀：参数非法 → tool.execute 根本不被调用
（execute 次数 = 0）。测试用【调用计数器】死死盯住这条边界。

零网络、零真实 API：复用 test_registry.py 的 AddTool 思路，
另造 CountingTool（计数器）和 FlakyTool（脚本化异常）证明执行域语义。

Hands-on 落点（见下方 TODO 注释）：
1. 先补 executor.py 里的 TODO ①（ValidationError → INVALID_ARGUMENT 映射）
2. 跑 test_invalid_argument_* 看 RED→GREEN
3. 填本文件 TODO ② 的断言：证明【参数错时 execute 次数 = 0】（核心 fail-fast 证据）
4. 临时把 AddArgs 的 first_number 类型改成 int，喂个字符串参数，确认仍走 INVALID_ARGUMENT
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Annotated

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from agent_harness.logging import setup_logging
from agent_harness.tooling import (
    ErrorCode,
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    ToolSideEffect,
)
from agent_harness.tooling.executor import MAX_ATTEMPTS, _ToolFailure
from tests.scripted_model import ScriptedModel

# ============================================================================
# 工具：CountingTool —— 用计数器盯住"execute 到底被调了几次"
# ============================================================================


class _CountArgs(BaseModel):
    value: Annotated[int, Field(..., description="要计入的值")]


class CountingTool(Tool):
    """带调用计数器的工具。

    测试 Validation-first 的关键：参数非法时 execute 次数必须为 0。
    没有计数器就没法证明"工具根本没跑"。
    """

    def __init__(self) -> None:
        self.call_count = 0

    @property
    def name(self) -> str:
        return "count"

    @property
    def description(self) -> str:
        return "计入一个整数值。用于演示执行计数。参数：value 为整数。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _CountArgs

    async def execute(self, args: _CountArgs) -> ToolResult:
        self.call_count += 1
        return ToolResult.success(message=f"计入 {args.value}", data={"value": args.value})


# ============================================================================
# 工具：ExplodingTool —— 工具内部抛异常，证明 TOOL_EXECUTION_ERROR 不冒泡
# ============================================================================


class _BoomArgs(BaseModel):
    pass


class ExplodingTool(Tool):
    """execute 内部总是抛 RuntimeError，用来测执行异常的兜底映射。"""

    @property
    def name(self) -> str:
        return "boom"

    @property
    def description(self) -> str:
        return "总是抛异常的测试工具。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _BoomArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        raise RuntimeError("故意爆炸")


# ============================================================================
# 夹具
# ============================================================================


@pytest.fixture
def registry_with_count() -> tuple[ToolRegistry, CountingTool]:
    """注册了 CountingTool 的 Registry + 工具实例（测试要读 call_count）。"""
    reg = ToolRegistry()
    counting = CountingTool()
    reg.register(counting)
    return reg, counting


@pytest.fixture
def executor_with_count(
    registry_with_count: tuple[ToolRegistry, CountingTool]
) -> tuple[ToolExecutor, CountingTool]:
    reg, counting = registry_with_count
    return ToolExecutor(reg), counting


# ============================================================================
# 测试：阶段 3 —— 合法 tool_call 成功透传
# ============================================================================


class TestExecuteSuccess:
    @pytest.mark.asyncio
    async def test_valid_call_returns_success(
        self, executor_with_count: tuple[ToolExecutor, CountingTool]
    ):
        """合法参数 → success，data 正确，execute 被调 1 次。"""
        executor, counting = executor_with_count
        tc = {"id": "call-1", "name": "count", "args": {"value": 42}}

        print("\n========== [阶段3 成功] 合法 tool_call ==========")
        print(f"输入 tool_call = {tc}")
        print("流程: Registry.get('count') ✓ → model_validate({value:42}) ✓ → execute() ✓")

        execution = await executor.execute(tc)

        print("\n--- 产出 ToolExecution ---")
        print(f"tool_call_id = {execution.tool_call_id}")
        print(f"result.ok    = {execution.result.ok}")
        print(f"result.data  = {execution.result.data}")
        print(f"result.model_dump_json() = {execution.result.model_dump_json()}")
        print(f"CountingTool.call_count  = {counting.call_count}  ← 工具被执行了 1 次")
        print("=" * 52)

        assert execution.tool_call_id == "call-1"
        assert execution.result.ok is True
        assert execution.result.data == {"value": 42}
        assert counting.call_count == 1

    @pytest.mark.asyncio
    async def test_tool_call_id_preserved(
        self, executor_with_count: tuple[ToolExecutor, CountingTool]
    ):
        """tool_call_id 原样透传——ToolMessage 配对协议的硬约束（Task 4/5 要用）。"""
        executor, _ = executor_with_count
        tc = {"id": "abc-123-xyz", "name": "count", "args": {"value": 1}}

        execution = await executor.execute(tc)

        assert execution.tool_call_id == "abc-123-xyz"


# ============================================================================
# 测试：阶段 1 —— 未知工具名 → TOOL_NOT_FOUND（execute 次数 0）
# ============================================================================


class TestToolNotFound:
    @pytest.mark.asyncio
    async def test_unknown_name_returns_tool_not_found(
        self, executor_with_count: tuple[ToolExecutor, CountingTool]
    ):
        """未知工具名 → TOOL_NOT_FOUND，retryable=False。"""
        executor, counting = executor_with_count
        tc = {"id": "call-x", "name": "does_not_exist", "args": {}}

        print("\n========== [阶段1 失败] 未知工具名 ==========")
        print(f"输入 tool_call = {tc}")
        print("流程: Registry.get('does_not_exist') ✗ 抛 KeyError → 映射 TOOL_NOT_FOUND")
        print("       （还没走到 validation，更没走到 execute）")

        execution = await executor.execute(tc)

        print("\n--- 产出 ToolExecution（失败结果，不是异常）---")
        print(f"tool_call_id            = {execution.tool_call_id}")
        print(f"result.ok               = {execution.result.ok}")
        print(f"result.error_code       = {execution.result.error_code}")
        print(f"result.retryable        = {execution.result.retryable}")
        print(f"result.message          = {execution.result.message}")
        print("result.model_dump_json()")
        print(f"  = {execution.result.model_dump_json()}")
        print(f"CountingTool.call_count = {counting.call_count}  ← 工具根本没被找到，自然没执行")
        print("=" * 52)

        assert execution.result.ok is False
        assert execution.result.error_code == ErrorCode.TOOL_NOT_FOUND
        assert execution.result.retryable is False
        assert counting.call_count == 0  # 没找到工具，execute 不可能被调

    @pytest.mark.asyncio
    async def test_no_exception_bubbles_up(
        self, executor_with_count: tuple[ToolExecutor, CountingTool]
    ):
        """Executor 对外永远返回结果，绝不抛异常（哪怕工具不存在）。"""
        executor, _ = executor_with_count
        tc = {"id": "call-x", "name": "ghost", "args": {}}

        # 不用 pytest.raises 包：如果抛了，测试直接红——正是我们想要的断言。
        execution = await executor.execute(tc)
        assert execution is not None


# ============================================================================
# 测试：阶段 2 —— 参数非法 → INVALID_ARGUMENT（execute 次数 0）
# 这一组是 Validation-first 的核心证据，也是 Hands-on 的落点。
# ============================================================================


class TestInvalidArgument:
    @pytest.mark.asyncio
    async def test_missing_required_field(
        self, executor_with_count: tuple[ToolExecutor, CountingTool]
    ):
        """缺必填字段 value → INVALID_ARGUMENT，retryable=False。"""
        executor, counting = executor_with_count
        tc = {"id": "call-v", "name": "count", "args": {}}  # 缺 value

        print("\n========== [阶段2 失败] 缺必填字段 ← Validation-first 核心 ==========")
        print(f"输入 tool_call = {tc}")
        print("流程: Registry.get('count') ✓ → model_validate({}) ✗ 抛 ValidationError")
        print("       → 映射 INVALID_ARGUMENT")
        print("       ←★ execute() 根本没被调用 ★")

        execution = await executor.execute(tc)

        print("\n--- 产出 ToolExecution（失败结果，模型可据此自纠错）---")
        print(f"tool_call_id            = {execution.tool_call_id}")
        print(f"result.ok               = {execution.result.ok}")
        print(f"result.error_code       = {execution.result.error_code}")
        print(f"result.retryable        = {execution.result.retryable}")
        print(f"result.message          = {execution.result.message}")
        print("result.model_dump_json()")
        print(f"  = {execution.result.model_dump_json()}")
        print(f"CountingTool.call_count = {counting.call_count}  ← 必须是 0！参数错→没执行")
        print("=" * 52)

        assert execution.result.ok is False
        assert execution.result.error_code == ErrorCode.INVALID_ARGUMENT
        assert execution.result.retryable is False
        # message 要能让模型自纠错：至少提到工具名或字段名
        assert "count" in execution.result.message or "value" in execution.result.message

        # Validation-first 最硬的证据：校验失败 → execute 次数必须为 0，工具根本没跑。
        assert counting.call_count == 0

    @pytest.mark.asyncio
    async def test_wrong_type_argument(
        self, executor_with_count: tuple[ToolExecutor, CountingTool]
    ):
        """类型错（value 传字符串给 int 字段）→ INVALID_ARGUMENT，execute 次数 0。"""
        executor, counting = executor_with_count
        tc = {"id": "call-t", "name": "count", "args": {"value": "不是整数"}}

        print("\n========== [阶段2 失败] 类型错 ← 同样走 INVALID_ARGUMENT ==========")
        print(f"输入 tool_call = {tc}")
        print("字段 value 期望 int，实际传了 str → Pydantic 类型校验失败")

        execution = await executor.execute(tc)

        print("\n--- 产出 ---")
        print(f"result.error_code       = {execution.result.error_code}")
        print(f"result.message          = {execution.result.message}")
        print(f"CountingTool.call_count = {counting.call_count}  ← 类型错也是 0")
        print("=" * 52)

        assert execution.result.ok is False
        assert execution.result.error_code == ErrorCode.INVALID_ARGUMENT
        assert counting.call_count == 0


# ============================================================================
# 测试：阶段 3 —— 工具内部抛异常 → TOOL_EXECUTION_ERROR（不冒泡）
# ============================================================================


class TestToolExecutionError:
    @pytest.mark.asyncio
    async def test_tool_raises_returns_execution_error(self):
        """execute 内部抛 RuntimeError → 映射 TOOL_EXECUTION_ERROR，不冒泡给上层。"""
        reg = ToolRegistry()
        reg.register(ExplodingTool())
        executor = ToolExecutor(reg)
        tc = {"id": "call-b", "name": "boom", "args": {}}

        print("\n========== [阶段3 失败] 工具内部抛异常 ==========")
        print(f"输入 tool_call = {tc}")
        print("流程: Registry.get('boom') ✓ → model_validate ✓ → execute() 抛 RuntimeError")
        print("       → Executor 宽捕获 → 映射 TOOL_EXECUTION_ERROR（不冒泡给上层）")

        execution = await executor.execute(tc)

        print("\n--- 产出（异常被吞并固化成 ErrorCode）---")
        print(f"result.ok               = {execution.result.ok}")
        print(f"result.error_code       = {execution.result.error_code}")
        print(f"result.retryable        = {execution.result.retryable}")
        print(f"result.message          = {execution.result.message}")
        print("result.model_dump_json()")
        print(f"  = {execution.result.model_dump_json()}")
        print("=" * 52)

        assert execution.result.ok is False
        assert execution.result.error_code == ErrorCode.TOOL_EXECUTION_ERROR
        assert execution.result.retryable is False
        # message 要暴露异常类型和内容，方便模型/人排查
        assert "RuntimeError" in execution.result.message or "故意爆炸" in execution.result.message


# ============================================================================
# 测试：ToolExecution 能序列化成 ToolMessage 的 content（Task 5 接入前的形状证据）
# ============================================================================


class TestToolExecutionSerialization:
    @pytest.mark.asyncio
    async def test_result_json_can_be_toolmessage_content(
        self, executor_with_count: tuple[ToolExecutor, CountingTool]
    ):
        """ToolResult.model_dump_json() 能直接当 ToolMessage content 回填给模型。"""
        executor, _ = executor_with_count
        tc = {"id": "call-1", "name": "count", "args": {"value": 7}}
        execution = await executor.execute(tc)

        # 这是 Task 5 AgentRuntime 会做的事：拿 result 的 JSON 当 ToolMessage content
        content = execution.result.model_dump_json()

        print("\n========== [序列化] ToolResult → ToolMessage content ==========")
        print("ToolExecution.result.model_dump_json():")
        print(f"  {content}")
        print("↑ 这串 JSON 就是将来回填给模型的 ToolMessage content（Task 5 接线点）")
        print("=" * 52)

        # model_dump_json() 输出紧凑 JSON（冒号后无空格）
        assert '"ok":true' in content
        assert '"value":7' in content


# ============================================================================
# 测试：Executor 不依赖真实模型 —— 用 ScriptedModel 证明执行链纯本地
# ============================================================================


class TestExecutorIsLocal:
    def test_registry_export_can_feed_scripted_model(
        self, registry_with_count: tuple[ToolRegistry, CountingTool]
    ):
        """Registry 导出的菜单能喂给 ScriptedModel——证明执行链与模型解耦。"""
        reg, _ = registry_with_count
        defs = reg.export_model_definitions()
        model = ScriptedModel([AIMessage(content="ok")])
        bound = model.bind_tools(defs, strict=True)

        print("\n========== [解耦证据] Registry 导出的模型菜单 ==========")
        print("这菜单就是将来 bind_tools 喂给模型的（同一个 args_schema 单一事实源）:")
        print(f"{defs}")
        print("=" * 52)

        assert bound is model
        assert model.bound_tools == defs


# ============================================================================
# Task 3 工具：慢工具 / 抖动工具 / 权限工具 -- 亲手制造三类失败
# ============================================================================


class _EmptyArgs(BaseModel):
    pass


class SlowTool(Tool):
    """慢工具：execute 睡 0.2s，但 timeout_seconds 只有 0.05s -> 必超时。

    观察 Timeout 边界的关键：每一轮 attempt 都【真的进入】execute
    （call_count 会涨），但到 0.05s 被 asyncio.timeout 掐断，永远到不了 return。
    超时是"掐断"，不是"没启动"。
    """

    def __init__(self) -> None:
        self.call_count = 0

    @property
    def name(self) -> str:
        return "slow"

    @property
    def description(self) -> str:
        return "执行需 0.2 秒的慢工具（超时上限 0.05 秒），用于演示 TIMEOUT。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EmptyArgs

    @property
    def timeout_seconds(self) -> float:
        return 0.05  # 覆写 Contract 默认 10s：测试要跑得快

    async def execute(self, args: BaseModel) -> ToolResult:
        self.call_count += 1
        await asyncio.sleep(0.2)
        return ToolResult.success(message="永远到不了这里：早被 timeout 掐断")


class FlakyTool(Tool):
    """抖动工具：前 fail_times 次抛 ConnectionError，之后成功。

    模拟真实世界的暂时性故障：网络抖一下，重试能自愈。
    fail_times 给很大（如 99）-> 永不恢复 -> 耗尽重试上限后返回失败。
    """

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.call_count = 0

    @property
    def name(self) -> str:
        return "flaky"

    @property
    def description(self) -> str:
        return f"前 {self.fail_times} 次执行抛网络错误，之后成功。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EmptyArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise ConnectionError(f"网络抖动（第 {self.call_count} 次失败）")
        return ToolResult.success(
            message="网络恢复了", data={"recovered_on_attempt": self.call_count}
        )


class ForbiddenTool(Tool):
    """权限工具：永远抛 PermissionError -> 确定性失败，重试也不会有权限。"""

    def __init__(self) -> None:
        self.call_count = 0

    @property
    def name(self) -> str:
        return "forbidden"

    @property
    def description(self) -> str:
        return "总是抛 PermissionError 的工具，用于演示确定性失败不重试。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EmptyArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        self.call_count += 1
        raise PermissionError("没有该资源的访问权限")


# ============================================================================
# Task 3 测试：Timeout 边界 -- 慢工具被掐断，每次 attempt 都真实发生
# ============================================================================


class TestTimeoutBoundary:
    @pytest.mark.asyncio
    async def test_slow_tool_times_out_and_retries(self):
        """慢工具 -> TIMEOUT + retryable=True，重试耗尽后 attempt = MAX_ATTEMPTS。"""
        reg = ToolRegistry()
        slow = SlowTool()
        reg.register(slow)
        executor = ToolExecutor(reg)
        tc = {"id": "call-slow", "name": "slow", "args": {}}

        print("\n========== [Task3 超时] 慢工具 vs 0.05s Timeout 边界 ==========")
        print(f"输入 tool_call = {tc}")
        print("流程: lookup ✓ -> validate ✓ -> attempt 1..3 每次都被 asyncio.timeout(0.05) 掐断")
        print(f"MAX_ATTEMPTS = {MAX_ATTEMPTS}")

        execution = await executor.execute(tc)

        print("\n--- 产出（超时被固化成 TIMEOUT，不是异常冒泡）---")
        print(f"result.ok           = {execution.result.ok}")
        print(f"result.error_code   = {execution.result.error_code}")
        print(f"result.retryable    = {execution.result.retryable}")
        print(f"result.message      = {execution.result.message}")
        print(f"result.metadata     = {execution.result.metadata}")
        print(f"SlowTool.call_count = {slow.call_count}")
        print("=" * 52)

        assert execution.result.ok is False
        assert execution.result.error_code == ErrorCode.TIMEOUT
        assert execution.result.retryable is True
        # 耗尽上限：最终结果的 metadata 记录了"停在第几次尝试"
        assert execution.result.metadata["attempt"] == MAX_ATTEMPTS
        assert execution.result.metadata["max_attempts"] == MAX_ATTEMPTS

        # 超时是"掐断"而不是"没启动"：每一轮 attempt 都真的调进了 execute
        # （call_count 在 execute 第一行就涨），只是被 timeout 掐断在 sleep 里。
        # TIMEOUT retryable=True -> 重试耗尽上限，共 MAX_ATTEMPTS(3) 轮 -> 计数 3。
        assert slow.call_count == MAX_ATTEMPTS


# ============================================================================
# Task 3 测试：暂时性错误 -- 重试能自愈；永不恢复则耗尽上限
# ============================================================================


class TestTransientRetry:
    @pytest.mark.asyncio
    async def test_flaky_recovers_within_budget(self):
        """前 2 次网络抖动、第 3 次成功 -> 重试自愈，最终 ok=True。"""
        reg = ToolRegistry()
        flaky = FlakyTool(fail_times=2)
        reg.register(flaky)
        executor = ToolExecutor(reg)
        tc = {"id": "call-flaky", "name": "flaky", "args": {}}

        print("\n========== [Task3 暂时性错误] 抖 2 次后自愈 ==========")
        print(f"输入 tool_call = {tc}")
        print("流程: attempt 1 ✗ ConnectionError -> 重试 -> attempt 2 ✗ -> 重试 -> attempt 3 ✓")

        execution = await executor.execute(tc)

        print("\n--- 产出（重试后成功）---")
        print(f"result.ok           = {execution.result.ok}")
        print(f"result.data         = {execution.result.data}")
        print(f"result.metadata     = {execution.result.metadata}")
        print(f"FlakyTool.call_count = {flaky.call_count}")
        print("=" * 52)

        assert execution.result.ok is True
        assert execution.result.data == {"recovered_on_attempt": 3}
        assert flaky.call_count == 3
        assert execution.result.metadata["attempt"] == 3

    @pytest.mark.asyncio
    async def test_transient_never_recovers_exhausts_attempts(self):
        """永不恢复的网络错误 -> TRANSIENT_ERROR + retryable=True，跑满上限后停。"""
        reg = ToolRegistry()
        flaky = FlakyTool(fail_times=99)  # 永不恢复
        reg.register(flaky)
        executor = ToolExecutor(reg)
        tc = {"id": "call-flaky", "name": "flaky", "args": {}}

        print("\n========== [Task3 暂时性错误] 永不恢复 -> 耗尽上限 ==========")
        print(f"输入 tool_call = {tc}")
        print(f"流程: attempt 1..{MAX_ATTEMPTS} 全部 ConnectionError -> 停手，不再无限重试")

        execution = await executor.execute(tc)

        print("\n--- 产出（跑满上限后的失败）---")
        print(f"result.ok           = {execution.result.ok}")
        print(f"result.error_code   = {execution.result.error_code}")
        print(f"result.retryable    = {execution.result.retryable}")
        print(f"result.metadata     = {execution.result.metadata}")
        print(f"FlakyTool.call_count = {flaky.call_count}  ← 重试有上限，不会无限打")
        print("=" * 52)

        assert execution.result.ok is False
        assert execution.result.error_code == ErrorCode.TRANSIENT_ERROR
        assert execution.result.retryable is True
        assert flaky.call_count == MAX_ATTEMPTS
        assert execution.result.metadata["attempt"] == MAX_ATTEMPTS


# ============================================================================
# Task 3 测试：确定性失败 -- 权限/普通异常只跑 1 次，不进入重试
# ============================================================================


class TestDeterministicNoRetry:
    @pytest.mark.asyncio
    async def test_permission_denied_runs_exactly_once(self):
        """PermissionError -> PERMISSION_DENIED + retryable=False，只跑 1 次。"""
        reg = ToolRegistry()
        forbidden = ForbiddenTool()
        reg.register(forbidden)
        executor = ToolExecutor(reg)
        tc = {"id": "call-denied", "name": "forbidden", "args": {}}

        print("\n========== [Task3 确定性失败] 权限拒绝不重试 ==========")
        print(f"输入 tool_call = {tc}")
        print("流程: attempt 1 ✗ PermissionError -> retryable=False -> 立即停，不重试")
        print("       （重试也不会突然有权限）")

        execution = await executor.execute(tc)

        print("\n--- 产出 ---")
        print(f"result.error_code      = {execution.result.error_code}")
        print(f"result.retryable       = {execution.result.retryable}")
        print(f"result.metadata        = {execution.result.metadata}")
        print(f"ForbiddenTool.call_count = {forbidden.call_count}  ← 必须是 1")
        print("=" * 52)

        assert execution.result.ok is False
        assert execution.result.error_code == ErrorCode.PERMISSION_DENIED
        assert execution.result.retryable is False
        assert forbidden.call_count == 1
        assert execution.result.metadata["attempt"] == 1

    @pytest.mark.asyncio
    async def test_generic_exception_still_runs_once(self):
        """普通异常（RuntimeError）-> TOOL_EXECUTION_ERROR：Task 2 语义不变，只跑 1 次。"""
        reg = ToolRegistry()
        reg.register(ExplodingTool())
        executor = ToolExecutor(reg)

        execution = await executor.execute({"id": "call-b2", "name": "boom", "args": {}})

        print("\n========== [Task3 确定性失败] 普通异常不重试（Task2 语义保持）==========")
        print(f"result.error_code = {execution.result.error_code}")
        print(f"result.metadata   = {execution.result.metadata}")
        print("=" * 52)

        assert execution.result.error_code == ErrorCode.TOOL_EXECUTION_ERROR
        assert execution.result.retryable is False
        assert execution.result.metadata["attempt"] == 1


# ============================================================================
# Task 3 测试：JSONL 可观察性 -- 按 tool_call_id 还原完整重试链
# 这就是 Day4 必做清单第 6 条的自动化版本：从 JSONL 定位一次 Tool 执行过程。
# ============================================================================


class TestRetryLogging:
    @pytest.mark.asyncio
    async def test_jsonl_records_every_attempt(self, tmp_path: Path):
        """慢工具跑完后，JSONL 里应有 3 条 tool_operation（attempt 1/2/3）+ 2 条 retry。"""
        log_path = setup_logging(workspace_dir=str(tmp_path / "workspace"))
        try:
            reg = ToolRegistry()
            reg.register(SlowTool())
            executor = ToolExecutor(reg)
            execution = await executor.execute(
                {"id": "call-jsonl", "name": "slow", "args": {}}
            )
        finally:
            # 测试收尾必须摘掉 root handler：
            # 否则后续所有测试的 execute() 都会往这个临时文件写日志。
            root = logging.getLogger()
            for handler in root.handlers:
                handler.close()
            root.handlers.clear()

        entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
        ]
        tool_ops = [e for e in entries if e["event_type(事件类型)"] == "tool_operation"]
        retries = [e for e in entries if e["event_type(事件类型)"] == "retry"]

        print("\n========== [Task3 JSONL] 按 tool_call_id 还原重试链 ==========")
        print(f"日志文件 = {log_path}")
        print(f"tool_operation 条数 = {len(tool_ops)}，retry 条数 = {len(retries)}")
        for e in tool_ops:
            print(
                f"  attempt={e['attempt(尝试次数)']} "
                f"error_code={e.get('error_code(错误码)')} "
                f"duration_ms={e['duration_ms(耗时毫秒)']} "
                f"timeout_ms={e.get('timeout_ms')} "
                f"tool_call_id={e['tool_call_id']}"
            )
        print("=" * 52)

        assert execution.result.error_code == ErrorCode.TIMEOUT
        assert len(tool_ops) == MAX_ATTEMPTS
        assert [e["attempt(尝试次数)"] for e in tool_ops] == [1, 2, 3]
        assert all(e["error_code(错误码)"] == "TIMEOUT" for e in tool_ops)
        assert all(e["tool_call_id"] == "call-jsonl" for e in tool_ops)
        # 每次超时都应被掐在超时上限附近（0.05s；放宽到 0.15s 防 CI 抖动）
        assert all(e["duration_ms(耗时毫秒)"] < 150 for e in tool_ops)
        # 两次"决定重试"事件：分别发生在 attempt 1 和 attempt 2 之后
        assert [e["attempt(尝试次数)"] for e in retries] == [1, 2]


# ============================================================================
# Task 4 工具：带 timing + side_effect 的确定性工具
# 用于证明【并发 vs 串行】的耗时差异，和【乱序完成 → 保序返回】。
# ============================================================================


class TimedReadTool(Tool):
    """睡 delay 秒后返回的 READ_ONLY 工具（默认 side_effect）。

    独立读操作可安全并发：3 个各睡 0.1s 的 read，并发跑总耗时 ≈ 0.1s。
    """

    def __init__(self, name: str, delay: float) -> None:
        self._name = name
        self._delay = delay

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"睡 {self._delay}s 的只读工具，用于演示并发耗时。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EmptyArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        await asyncio.sleep(self._delay)
        return ToolResult.success(
            message=f"{self._name} 完成（睡了 {self._delay}s）",
            data={"name": self._name, "delay": self._delay},
        )


class TimedMutatingTool(Tool):
    """睡 delay 秒后返回的 MUTATING 工具（覆写 side_effect）。

    含 MUTATING 的批次必须整批串行：副作用顺序确定、可复现、部分失败可归因。
    """

    def __init__(self, name: str, delay: float = 0.1) -> None:
        self._name = name
        self._delay = delay

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"睡 {self._delay}s 的写工具（MUTATING），用于演示含写批次整批串行。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EmptyArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.MUTATING  # 覆写默认 READ_ONLY

    async def execute(self, args: BaseModel) -> ToolResult:
        await asyncio.sleep(self._delay)
        return ToolResult.success(
            message=f"{self._name} 写入完成（睡了 {self._delay}s）",
            data={"name": self._name, "delay": self._delay},
        )


# ============================================================================
# Task 4 测试：并发 vs 串行 -- 用计时盯住"并发省时间"
# ============================================================================


class TestBatchConcurrency:
    @pytest.mark.asyncio
    async def test_all_read_only_runs_in_parallel(self):
        """3 个各睡 0.1s 的 READ_ONLY 并发 -> 总耗时 ≈ 0.1s，不是 0.3s。"""
        reg = ToolRegistry()
        reg.register(TimedReadTool("r1", 0.1))
        reg.register(TimedReadTool("r2", 0.1))
        reg.register(TimedReadTool("r3", 0.1))
        executor = ToolExecutor(reg)
        calls = [
            {"id": "c1", "name": "r1", "args": {}},
            {"id": "c2", "name": "r2", "args": {}},
            {"id": "c3", "name": "r3", "args": {}},
        ]

        t0 = perf_counter()
        results = await executor.execute_batch(calls)
        elapsed = perf_counter() - t0

        print("\n========== [Task4 并发] 3 个 READ_ONLY 各睡 0.1s ==========")
        print("调度模式：全 READ_ONLY → asyncio.gather 并发")
        print(f"实测总耗时 = {elapsed * 1000:.0f} ms")
        print("对照：串行会 ≈ 300ms，并发应 ≈ 100ms（给到 220ms 容忍调度开销）")
        print("--- 结果（按输入顺序，不是完成顺序）---")
        for r in results:
            print(f"  id={r.tool_call_id} ok={r.result.ok} data={r.result.data}")
        print("=" * 52)

        assert len(results) == 3
        assert all(r.result.ok for r in results)
        # 核心证据：并发耗时远小于串行总和（0.3s）。
        # 给 0.22s 上限：3×0.1s=0.3s 串行 vs 0.1s 并发，0.22s 卡在中间能区分两者。
        assert elapsed < 0.22

    @pytest.mark.asyncio
    async def test_mutating_forces_whole_batch_serial(self):
        """混入 1 个 MUTATING -> 整批串行 -> 总耗时 ≈ 0.3s（即使有 READ_ONLY）。"""
        reg = ToolRegistry()
        reg.register(TimedReadTool("r1", 0.1))
        reg.register(TimedReadTool("r2", 0.1))
        reg.register(TimedMutatingTool("w1", 0.1))
        executor = ToolExecutor(reg)
        calls = [
            {"id": "c1", "name": "r1", "args": {}},
            {"id": "c2", "name": "r2", "args": {}},
            {"id": "c3", "name": "w1", "args": {}},  # 含这一个 MUTATING → 整批串行
        ]

        t0 = perf_counter()
        results = await executor.execute_batch(calls)
        elapsed = perf_counter() - t0

        print("\n========== [Task4 串行] 含 1 个 MUTATING → 整批串行 ==========")
        print("调度模式：任一 MUTATING → 整批按原顺序串行（保守默认）")
        print(f"实测总耗时 = {elapsed * 1000:.0f} ms")
        print("对照：3×0.1s=300ms 串行；并发会跌到 ≈100ms（含写并发有副作用乱序雷）")
        print("--- 结果（按输入顺序）---")
        for r in results:
            print(f"  id={r.tool_call_id} ok={r.result.ok} data={r.result.data} message={r.result.message}")
        print("=" * 52)

        assert len(results) == 3
        assert all(r.result.ok for r in results)
        # 核心证据：整批串行，耗时接近 0.3s（给 0.25s 下限排除"误并发"）。
        assert elapsed > 0.25


# ============================================================================
# Task 4 测试：乱序完成 → 保序返回 -- gather 的顺序保持
# 故意让工具睡不同时长（先完成的是最后一个），验证结果仍是输入顺序。
# ============================================================================


class TestBatchOrderPreservation:
    @pytest.mark.asyncio
    async def test_out_of_order_completion_preserves_input_order(self):
        """工具乱序完成（最后那个最先睡完），结果仍按输入顺序 + tool_call_id 配对。"""
        reg = ToolRegistry()
        # r1 睡最久，r3 睡最少 -> 完成顺序是 r3, r2, r1（与输入顺序完全相反）
        reg.register(TimedReadTool("r1", 0.08))
        reg.register(TimedReadTool("r2", 0.04))
        reg.register(TimedReadTool("r3", 0.01))
        executor = ToolExecutor(reg)
        calls = [
            {"id": "c1", "name": "r1", "args": {}},
            {"id": "c2", "name": "r2", "args": {}},
            {"id": "c3", "name": "r3", "args": {}},
        ]

        results = await executor.execute_batch(calls)
        returned_ids = [r.tool_call_id for r in results]
        returned_names = [r.result.data["name"] for r in results]

        print("\n========== [Task4 保序] 乱序完成 → 保序返回 ==========")
        print("完成顺序（谁先睡完）：r3(0.01s) → r2(0.04s) → r1(0.08s)")
        print(f"返回顺序（应是输入顺序）：{returned_ids} / 工具名 {returned_names}")
        print("↑ gather 保证：返回顺序 = 喂入顺序，与完成顺序无关")
        print("↑ 这是 Task 5 回填 ToolMessage 的硬约束（tool_call_id 严格配对）")
        print("=" * 52)

        assert returned_ids == ["c1", "c2", "c3"]
        assert returned_names == ["r1", "r2", "r3"]

    @pytest.mark.asyncio
    async def test_empty_batch_returns_empty_list(self):
        """空批次 → 空 list（边界情况，execute_batch 不能炸）。"""
        reg = ToolRegistry()
        executor = ToolExecutor(reg)
        results = await executor.execute_batch([])
        assert results == []


# ============================================================================
# Round 8 加固：MUTATING 工具超时不得自动重试（未知副作用不盲重跑）
# ============================================================================


class _SlowMutatingTimeoutTool(Tool):
    """固定超时的 MUTATING 工具：每次 execute 都睡过上限。"""

    @property
    def name(self) -> str:
        return "slow_mutating"

    @property
    def description(self) -> str:
        return "必然超时的写工具。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _EmptyArgs

    @property
    def timeout_seconds(self) -> float:
        return 0.05

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.MUTATING

    async def execute(self, args: BaseModel) -> ToolResult:
        await asyncio.sleep(0.2)
        return ToolResult.success("done")


class _SlowReadTimeoutTool(_SlowMutatingTimeoutTool):
    """与上同类但 READ_ONLY：超时重跑无副作用风险，应保持 retryable=True。"""

    @property
    def name(self) -> str:
        return "slow_read"

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY


@pytest.mark.asyncio
async def test_mutating_tool_timeout_is_not_auto_retried():
    """MUTATING 工具超时 → retryable 必须为 False（不自动重试）。

    超时意味着第 1 次尝试的副作用状态未知（进程可能还在跑、写可能已落盘）——
    这与 Recovery 对 UNKNOWN 副作用要求人工 reconcile 是同一条语义（不变量
    #14）：恢复层都不盲重跑，执行层更不能在 run 内静默 double-apply。
    READ_ONLY 工具超时仍保持 retryable=True（重跑无副作用风险）。
    """
    registry = ToolRegistry()
    registry.register(_SlowMutatingTimeoutTool())
    executor = ToolExecutor(registry)

    execution = await executor.execute({"id": "c1", "name": "slow_mutating", "args": {}})
    assert execution.result.error_code == ErrorCode.TIMEOUT
    assert execution.result.retryable is False
    assert execution.result.metadata["attempt"] == 1  # 只尝试一次

    # 对照组：READ_ONLY 超时仍可重试（原有语义）。
    registry.register(_SlowReadTimeoutTool())
    read_exec = await executor.execute({"id": "c2", "name": "slow_read", "args": {}})
    assert read_exec.result.error_code == ErrorCode.TIMEOUT
    assert read_exec.result.retryable is True


@pytest.mark.asyncio
async def test_timeout_message_matches_the_retry_decision():
    """超时文案必须与实际 retryable 一致（OBS-009/014 的「文案矛盾」）。

    旧版对 MUTATING 也说「可稍后重试」，而 retryable=False——等于**教模型盲重跑
    副作用状态未知的命令**（违反不变量 #14）。实机观测到的「长命令超时 → 反复
    重试/退化」正被这句话推动。READ_ONLY 仍应鼓励重试（重跑无副作用风险）。

    这是纯文案契约，不改任何重试行为（行为由上面那个用例锁定）。
    """
    registry = ToolRegistry()
    registry.register(_SlowMutatingTimeoutTool())
    executor = ToolExecutor(registry)

    mutating = await executor.execute({"id": "c1", "name": "slow_mutating", "args": {}})
    assert mutating.result.retryable is False
    assert "可稍后重试" not in mutating.result.message, "不可重试却说可重试 = 误导模型盲重跑"
    assert "副作用状态未知" in mutating.result.message
    assert "不要直接重跑" in mutating.result.message

    registry.register(_SlowReadTimeoutTool())
    read = await executor.execute({"id": "c2", "name": "slow_read", "args": {}})
    assert read.result.retryable is True
    assert "可稍后重试" in read.result.message
    assert "副作用状态未知" not in read.result.message


# ============================================================================
# _ToolFailure：失败映射的唯一构造入口（架构深化候选 2）
# ============================================================================
#
# 为什么直接单测它：message ⇔ error_code ⇔ retryable 的一致性是 OBS-009/014 的
# 缺陷类（文案教模型盲重跑副作用状态未知的命令）。旧实现里三者在不同分支各自
# 拼装，只能靠「慢工具端到端」才观察得到矛盾；收成值对象后可直接表驱动，
# 不需要 sleep、不需要 Sandbox、不需要 event loop。


class TestToolFailureMapping:
    def test_timeout_shares_one_source_for_message_and_retryable(self):
        """超时的文案与 retryable 同源：可重试才允许出现「可稍后重试」。"""
        for tool, expected_retryable in (
            (_SlowMutatingTimeoutTool(), False),
            (_SlowReadTimeoutTool(), True),
        ):
            failure = _ToolFailure.from_timeout(tool, tool.name)

            assert failure.retryable is expected_retryable
            assert failure.error_code == ErrorCode.TIMEOUT
            assert ("可稍后重试" in failure.message) is expected_retryable
            assert ("不要直接重跑" in failure.message) is not expected_retryable

    def test_timeout_message_carries_the_actual_limit(self):
        """文案里的秒数取自工具的 timeout_seconds，不是写死的字面量。"""
        tool = _SlowMutatingTimeoutTool()

        failure = _ToolFailure.from_timeout(tool, tool.name)

        assert f"上限 {tool.timeout_seconds} 秒" in failure.message

    @pytest.mark.parametrize("error,expected_code,expected_retryable", [
        (PermissionError("denied"), ErrorCode.PERMISSION_DENIED, False),
        (ConnectionError("flaky"), ErrorCode.TRANSIENT_ERROR, True),
        (ValueError("boom"), ErrorCode.TOOL_EXECUTION_ERROR, False),
    ])
    def test_exception_classification_is_type_based(
        self, error, expected_code, expected_retryable
    ):
        """分类是确定性类型判断（不解析错误字符串）；未命中即内部错误、不重试。"""
        failure = _ToolFailure.from_exception(error, "t")

        assert failure.error_code == expected_code
        assert failure.retryable is expected_retryable
        assert type(error).__name__ in failure.message

    def test_subclass_of_classified_exception_is_matched(self):
        """isinstance 连子类一起认（与旧实现同语义，收进值对象后必须自证）。"""
        class _SubPermission(PermissionError):
            pass

        failure = _ToolFailure.from_exception(_SubPermission("x"), "t")

        assert failure.error_code == ErrorCode.PERMISSION_DENIED
        assert failure.retryable is False

    def test_result_is_a_faithful_projection(self):
        """to_result 只是投影：三字段逐一对应，不额外改写。"""
        failure = _ToolFailure.from_timeout(_SlowMutatingTimeoutTool(), "t")

        result = failure.to_result()

        assert result.ok is False
        assert (result.error_code, result.retryable, result.message) == (
            failure.error_code, failure.retryable, failure.message,
        )
