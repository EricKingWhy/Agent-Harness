"""工具 diff 字段回归测试（Phase 9 / Web UI）。

EditTool / ApplyPatchTool / WriteTool 成功后，ToolResult.data 必须含
before / after / truncated 三个字段，供前端 diff 视图渲染（Q12=B 决策）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.tooling import ToolExecutor, ToolRegistry
from agent_harness.tools import ApplyPatchTool, EditTool, WriteTool


@pytest.fixture
def sandbox(tmp_path: Path) -> LocalSubprocessSandbox:
    return LocalSubprocessSandbox(workspace_root=tmp_path)


@pytest.fixture
def executor(sandbox: LocalSubprocessSandbox) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(EditTool(sandbox))
    registry.register(ApplyPatchTool(sandbox))
    registry.register(WriteTool(sandbox))
    return ToolExecutor(registry)


def _result_data(executor: ToolExecutor, tool_name: str, args: dict) -> dict:
    """跑一次 tool_call，返回 ToolResult 的 data dict。"""
    import asyncio

    async def _run():
        ai = AIMessage(content="", tool_calls=[{"id": "tc1", "name": tool_name, "args": args}])
        execs = await executor.execute_batch(ai.tool_calls)
        return execs[0].result

    result = asyncio.run(_run())
    assert result.ok, f"{tool_name} 应该成功：{result.message}"
    return result.data


class TestEditDiffData:
    def test_edit_returns_before_after(self, executor, sandbox):
        sandbox.write_text("f.txt", "hello world")
        data = _result_data(executor, "edit", {
            "path": "f.txt", "old_string": "world", "new_string": "agent",
        })
        assert data["before"] == "hello world"
        assert data["after"] == "hello agent"
        assert data["truncated"] is False


class TestWriteDiffData:
    def test_write_new_file_empty_before(self, executor, sandbox):
        data = _result_data(executor, "write", {
            "path": "new.txt", "content": "fresh content",
        })
        assert data["before"] == ""  # 新文件
        assert data["after"] == "fresh content"
        assert data["truncated"] is False

    def test_write_overwrite_keeps_old_before(self, executor, sandbox):
        sandbox.write_text("old.txt", "original")
        data = _result_data(executor, "write", {
            "path": "old.txt", "content": "replaced",
        })
        assert data["before"] == "original"
        assert data["after"] == "replaced"


class TestApplyPatchDiffData:
    def test_apply_patch_returns_before_after(self, executor, sandbox):
        sandbox.write_text("p.txt", "line1\nline2\nline3")
        data = _result_data(executor, "apply_patch", {
            "path": "p.txt",
            "hunks": [{"old_string": "line2", "new_string": "LINE TWO"}],
        })
        assert data["before"] == "line1\nline2\nline3"
        assert data["after"] == "line1\nLINE TWO\nline3"
        assert data["truncated"] is False


class TestDiffTruncation:
    def test_large_file_truncated(self, executor, sandbox):
        # 生成 > 50KB 的内容触发截断
        big = "x" * 60_000
        sandbox.write_text("big.txt", big)
        new_big = "y" * 60_000
        data = _result_data(executor, "write", {
            "path": "big.txt", "content": new_big,
        })
        assert data["truncated"] is True
        assert len(data["before"]) <= 6_000  # 截断后远小于原
        assert len(data["after"]) <= 6_000
