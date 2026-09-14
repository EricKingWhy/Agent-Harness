"""GlobTool 单元测试：glob 模式文件匹配 + 截断。

测试缝 2（见 spec）：用 LocalSubprocessSandbox 做后端，构造 tool_call dict 喂给
ToolExecutor.execute()，断言 ToolResult 形状。复用 test_coding_tools.py 的风格。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.tooling import (
    ErrorCode,
    ToolExecutor,
    ToolRegistry,
    ToolSideEffect,
)
from agent_harness.tools import GlobTool


@pytest.fixture
def sandbox(tmp_path: Path) -> LocalSubprocessSandbox:
    return LocalSubprocessSandbox(workspace_root=tmp_path)


@pytest.fixture
def registry(sandbox: LocalSubprocessSandbox) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(GlobTool(sandbox))
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registry)


def _tool_call(args: dict, call_id: str = "test_call") -> dict:
    return {"id": call_id, "name": "glob", "args": args}


class TestGlobSideEffect:
    def test_side_effect_is_read_only(self, sandbox: LocalSubprocessSandbox):
        assert GlobTool(sandbox).side_effect == ToolSideEffect.READ_ONLY


class TestGlobHappyPath:
    @pytest.mark.asyncio
    async def test_extension_filter(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """*.py 匹配返回 .py 文件。"""
        sandbox.write_text("a.py", "x")
        sandbox.write_text("b.txt", "y")
        sandbox.write_text("c.py", "z")

        result = await executor.execute(
            _tool_call({"pattern": "*.py"})
        )

        assert result.result.ok is True
        assert "a.py" in result.result.data["paths"]
        assert "c.py" in result.result.data["paths"]
        assert all(not p.endswith(".txt") for p in result.result.data["paths"])

    @pytest.mark.asyncio
    async def test_double_star_recursive(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """**/*.py 匹配嵌套子目录。"""
        sandbox.write_text("top.py", "x")
        sandbox.write_text("pkg/mod.py", "y")
        sandbox.write_text("pkg/sub/deep.py", "z")

        result = await executor.execute(
            _tool_call({"pattern": "**/*.py"})
        )

        assert result.result.ok is True
        paths = result.result.data["paths"]
        assert "top.py" in paths
        assert "pkg/mod.py" in paths
        assert "pkg/sub/deep.py" in paths

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """无匹配 → 空列表，count=0，truncated=False。"""
        sandbox.write_text("a.py", "x")

        result = await executor.execute(
            _tool_call({"pattern": "*.rb"})
        )

        assert result.result.ok is True
        assert result.result.data["paths"] == []
        assert result.result.data["count"] == 0
        assert result.result.data["truncated"] is False


class TestGlobTruncation:
    @pytest.mark.asyncio
    async def test_max_results_truncation(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """匹配数 > max_results → 截断，truncated=True，count==max_results。"""
        for i in range(15):
            sandbox.write_text(f"f{i:02d}.py", "x")

        result = await executor.execute(
            _tool_call({"pattern": "*.py", "max_results": 10})
        )

        assert result.result.ok is True
        assert result.result.data["count"] == 10
        assert result.result.data["truncated"] is True


class TestGlobErrors:
    @pytest.mark.asyncio
    async def test_wrong_arg_type(self, executor: ToolExecutor):
        """参数类型错 → INVALID_ARGUMENT。"""
        result = await executor.execute(
            _tool_call({"pattern": 123})
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.INVALID_ARGUMENT

    @pytest.mark.asyncio
    async def test_bad_max_results(self, executor: ToolExecutor):
        """max_results < 1 → schema ge=1 拦截 → INVALID_ARGUMENT。"""
        result = await executor.execute(
            _tool_call({"pattern": "*.py", "max_results": 0})
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.INVALID_ARGUMENT
