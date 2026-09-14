"""ToolCall 值对象（A2 深化）：模型 tool_call dict 的类型化归一。"""

from __future__ import annotations

import pytest

from agent_harness.tooling import ToolCall, ToolExecutor, ToolRegistry
from agent_harness.tooling.result import ErrorCode


class _Echo:
    pass


def test_normalize_from_langchain_dict_defaults_missing_keys():
    call = ToolCall.normalize({"id": "c1", "name": "add", "args": {"x": 1}})
    assert call == ToolCall(id="c1", name="add", args={"x": 1})

    sparse = ToolCall.normalize({})
    # 缺 id 时不再坍缩为空串——降级为唯一占位（gen_ 前缀），避免下游主键冲突。
    assert sparse.id.startswith("gen_") and sparse.name == "" and sparse.args == {}

    # args 为 None（部分模型会这么吐）→ 空字典，不是 None。
    assert ToolCall.normalize({"id": "c2", "name": "read", "args": None}).args == {}


def test_normalize_passes_toolcall_through():
    call = ToolCall(id="c1", name="add", args={"x": 1})
    assert ToolCall.normalize(call) is call


def test_normalize_all_mixed_shapes():
    calls = ToolCall.normalize_all([
        {"id": "c1", "name": "add", "args": {"x": 1}},
        ToolCall(id="c2", name="read", args={"path": "a.txt"}),
    ])
    assert [c.id for c in calls] == ["c1", "c2"]
    assert calls[1].args == {"path": "a.txt"}


def test_normalize_missing_id_yields_unique_nonempty_ids():
    """缺 id 时不能让多条调用都坍缩成空串——否则下游以 tool_call_id 为主键的
    Ledger 会互相覆盖、ToolMessage 配对会错位。必须降级为确定性且唯一的占位 id。
    """
    calls = ToolCall.normalize_all([
        {"name": "add", "args": {"x": 1}},
        {"name": "read", "args": {"path": "a"}},
    ])
    ids = [c.id for c in calls]
    assert all(ids), "缺 id 时必须降级为非空占位，不能是空串"
    assert len(set(ids)) == len(ids), "多条缺 id 调用必须各自唯一，避免下游主键冲突"


def test_normalize_preserves_explicit_empty_string_id():
    """模型显式给出 id='' 时与缺 id 同等对待，降级为唯一占位。"""
    a = ToolCall.normalize({"id": "", "name": "x", "args": {}})
    assert a.id != ""


@pytest.mark.asyncio
async def test_executor_accepts_toolcall_objects():
    """execute_batch 接受 ToolCall 值对象：缺参/未知工具的语义与 dict 输入一致。"""
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    unknown = await executor.execute(ToolCall(id="c1", name="ghost", args={}))
    assert unknown.result.error_code == ErrorCode.TOOL_NOT_FOUND

    bad_args = await executor.execute(ToolCall(id="c2", name="ghost", args={}))
    assert bad_args.result.error_code == ErrorCode.TOOL_NOT_FOUND


def test_normalize_all_dedupes_duplicate_nonempty_ids():
    """模型吐两条相同非空 id 的 tool_call 时必须去重（重复合成唯一占位）。

    重复 id 与缺 id 同样破坏下游：Ledger 主键冲突、_validate_tool_blocks 拒绝
    投影（session 越过阈值后永久 context_window_exceeded）。与缺 id 同一策略：
    保留首个、其余合成 gen_ 唯一占位。
    """
    calls = ToolCall.normalize_all([
        {"id": "c1", "name": "a", "args": {}},
        {"id": "c1", "name": "b", "args": {}},
        {"id": "c2", "name": "c", "args": {}},
    ])
    ids = [c.id for c in calls]
    assert ids[0] == "c1" and ids[2] == "c2"
    assert ids[1].startswith("gen_") and ids[1] != ids[0]
    assert len(set(ids)) == 3
