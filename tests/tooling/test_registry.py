"""Day4 Task1：Tool Contract / ToolResult / Registry 的最小行为测试。

零网络、零真实 API：用 AddTool（纯本地加法）和 FakeTool（脚本化失败结果）
证明抽象层语义。Executor/Validation/Retry 都还没出现，所以这里只测
Contract → Registry → 模型 Schema 导出 这一条主链。

Hands-on 落点（见下方 TODO 注释）：
1. 补全 AddArgs 两个字段 + AddTool.description
2. 跑 test_export_model_definitions 逐项核对导出
3. 临时改第二个工具名也叫 add，先预测再跑 test_duplicate_name_raises
4. 在 test_export_model_definitions 里加一条断言证明改坏字段名测试会变红
"""

from __future__ import annotations

import json
from typing import Annotated

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from agent_harness.tooling import (
    ErrorCode,
    Tool,
    ToolRegistry,
    ToolResult,
    ToolSideEffect,
)
from tests.scripted_model import ScriptedModel

# ============================================================================
# 示例工具 1：AddTool —— 证明 Contract 的"单一事实源"
# ============================================================================

class AddArgs(BaseModel):
    """add 工具的参数结构（Schema）。

    这一份结构会同时：
    - 被 Registry 导出成模型菜单的 parameters；
    - 被未来 Executor 用来校验模型回的参数。
    改这里，两边同步，不会漂移。
    """

    # —— TODO(你写) ①：定义两个数值参数 ——
    # 类型用 float（模型对整数的解析最稳）
    # 每个参数用 Field(..., description=...) 写清晰中文描述
    # description 会影响模型何时选这个工具、以及填参数的准确性
    # 操作：取消下面两行注释，把 ... 替换成清晰的中文 description
    # Annotated 式：类型在第一个参数，Field 约束作为元数据挂在类型上
    # （Pydantic v2 推荐写法，类型检查器看到的仍是纯 float）
    first_number: Annotated[
        float,
        Field(..., description="加法的第一个加数，任意整数或小数，例如 3.0", examples=[3.0, 4.0]),
    ]
    second_number: Annotated[
        float,
        Field(..., description="加法的第二个加数，任意整数或小数，例如 4.0"),
    ]


class AddTool(Tool):
    """add 工具：计算两个数的和。纯本地、零网络、READ_ONLY。"""

    @property
    def name(self) -> str:
        return "add"

    @property
    def description(self) -> str:
        return (
            "计算两个数的和（加法）。"
            "当用户需要把两个数值相加求和时使用本工具。"
            "参数：first_number 为第一个加数，second_number 为第二个加数，"
            "均为数值类型；返回两者之和。"
        )

    @property
    def args_schema(self) -> type[BaseModel]:
        return AddArgs

    @property
    def side_effect(self) -> ToolSideEffect:
        return ToolSideEffect.READ_ONLY

    async def execute(self, args: AddArgs) -> ToolResult:
        total = args.first_number + args.second_number
        return ToolResult.success(
            message=f"{args.first_number} + {args.second_number} = {total}",
            data={"sum": total},
        )


# ============================================================================
# 示例工具 2：FakeTool —— 脚本化失败结果，用来测 ToolResult 失败语义
# ============================================================================

class _FakeArgs(BaseModel):
    """FakeTool 的空参数 Schema（只为让 args_schema 返回一个合法类）。"""


class FakeTool(Tool):
    """返回脚本化失败 ToolResult 的假工具。

    用来测 ToolResult 的失败语义（error_code / retryable），不调真实函数。
    """

    def __init__(self, name: str, failure_result: ToolResult) -> None:
        self._name = name
        self._failure_result = failure_result

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "测试用假工具，总是返回预设的失败结果"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _FakeArgs

    async def execute(self, args: BaseModel) -> ToolResult:
        return self._failure_result


# ============================================================================
# 夹具
# ============================================================================

@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def add_tool() -> AddTool:
    return AddTool()


# ============================================================================
# 测试：Registry register / get / list
# ============================================================================

class TestRegistryBasic:
    def test_register_and_get(self, registry: ToolRegistry, add_tool: AddTool):
        """注册后能按 name 取回同一实例，list() 含它。"""
        registry.register(add_tool)

        got = registry.get("add")
        assert got is add_tool  # 同一实例
        assert got.name == "add"

        tools = registry.list()
        assert len(tools) == 1
        assert tools[0] is add_tool

    def test_get_unknown_raises_keyerror(self, registry: ToolRegistry):
        """查不存在的工具名抛 KeyError（由 Executor 映射成 TOOL_NOT_FOUND）。"""
        with pytest.raises(KeyError):
            registry.get("does_not_exist")

    def test_duplicate_name_raises_at_register(
        self, registry: ToolRegistry, add_tool: AddTool
    ):
        """重复 name 在注册阶段就抛 ValueError，不带着冲突继续运行。"""
        registry.register(add_tool)

        # 再注册一个同名工具 → 注册阶段直接失败
        # —— Hands-on ③：先预测结果，再跑这条确认 ——
        second_add = AddTool()  # 同名 add
        with pytest.raises(ValueError, match="已注册"):
            registry.register(second_add)

        # 确认 Registry 没被污染：仍然只有 1 个
        assert len(registry.list()) == 1


# ============================================================================
# 测试：export_model_definitions —— 单一事实源证据
# ============================================================================

class TestExportModelDefinitions:
    def test_shape_matches_bind_tools_contract(
        self, registry: ToolRegistry, add_tool: AddTool
    ):
        """导出的每个 dict 含 name/description/parameters 三键。"""
        registry.register(add_tool)
        defs = registry.export_model_definitions()

        assert len(defs) == 1
        d = defs[0]
        assert set(d.keys()) == {"name", "description", "parameters"}

        assert d["name"] == "add"
        assert "加" in d["description"]  # description 来自 Contract
        assert d["parameters"]["type"] == "object"  # JSON Schema 根

    def test_parameters_match_args_schema(
        self, registry: ToolRegistry, add_tool: AddTool
    ):
        """导出 parameters 的字段与 AddArgs 一致 → 单一事实源核心证据。"""
        registry.register(add_tool)
        d = registry.export_model_definitions()[0]
        props: dict = d["parameters"]["properties"]

        # —— Hands-on ④：这条断言证明"改坏参数名测试会变红" ——
        # 试着把 AddArgs 的 first_number 改名，这条会失败
        assert "first_number" in props
        assert "second_number" in props
        # required 字段也来自 AddArgs 的必填项
        assert set(d["parameters"]["required"]) == {"first_number", "second_number"}

    def test_can_feed_to_scripted_model_bind_tools(
        self, registry: ToolRegistry, add_tool: AddTool
    ):
        """导出的菜单能直接喂给 LangChain bind_tools（ScriptedModel 替身）。"""
        registry.register(add_tool)
        defs = registry.export_model_definitions()
        print(defs)
        model = ScriptedModel([AIMessage(content="ok")])
        bound = model.bind_tools(defs, strict=True)

        # 触发一次调用，确认 bind_tools 接受我们的导出形状
        # （ScriptedModel 的 bind_tools 会记住 tools，ainvoke 会记快照）
        assert bound is model  # ScriptedModel.bind_tools 返回 self
        assert model.bound_tools == defs


# ============================================================================
# 测试：ToolResult 序列化与不变量
# ============================================================================

class TestToolResultSuccess:
    def test_success_json_serializable(self):
        """成功结果能稳定 model_dump_json()，error_code=None、retryable=False。"""
        r = ToolResult.success(message="ok", data={"sum": 7.0})

        assert r.ok is True
        assert r.error_code is None
        assert r.retryable is False
        assert r.data == {"sum": 7.0}

        s = r.model_dump_json()
        parsed = json.loads(s)
        assert parsed["ok"] is True
        assert parsed["error_code"] is None
        assert parsed["retryable"] is False
        assert parsed["data"] == {"sum": 7.0}

    def test_success_rejects_error_code(self):
        """ok=True 时塞 error_code → 构造就抛（语义不可能错）。"""
        with pytest.raises(ValueError, match="error_code"):
            ToolResult(ok=True, message="ok", error_code=ErrorCode.TIMEOUT)


class TestToolResultFailure:
    def test_failure_json_serializable(self):
        """失败结果能稳定序列化，error_code/retryable 正确。"""
        r = ToolResult.failure(
            message="参数非法",
            error_code=ErrorCode.INVALID_ARGUMENT,
            retryable=False,
        )

        assert r.ok is False
        assert r.error_code == ErrorCode.INVALID_ARGUMENT
        assert r.retryable is False

        s = r.model_dump_json()
        print(s)
        parsed = json.loads(s)
        print(parsed)
        assert parsed["ok"] is False
        assert parsed["error_code"] == "INVALID_ARGUMENT"  # 枚举序列化成字符串
        assert parsed["retryable"] is False

    def test_failure_rejects_missing_error_code(self):
        """ok=False 但没设 error_code → 构造就抛。"""
        with pytest.raises(ValueError, match="error_code"):
            ToolResult(ok=False, message="失败", error_code=None)

    def test_failure_retryable_flag(self):
        """retryable 可独立设置（Task 3 的 Timeout 会用 retryable=True）。"""
        r = ToolResult.failure(
            message="超时",
            error_code=ErrorCode.TIMEOUT,
            retryable=True,
        )
        assert r.retryable is True


# ============================================================================
# 测试：AddTool execute 端到端
# ============================================================================

class TestAddToolExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_success(self, add_tool: AddTool):
        """AddTool.execute(合法 AddArgs) → success，data.sum 正确。"""
        args = AddArgs(first_number=3, second_number=4)
        r = await add_tool.execute(args)

        assert r.ok is True
        assert r.data == {"sum": 7.0}
        assert "7.0" in r.message or "7" in r.message
