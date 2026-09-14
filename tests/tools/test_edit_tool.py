"""EditTool 单元测试：精确字符串替换 0/1/>1 三态 + replace_all。

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
from agent_harness.tools import EditTool


@pytest.fixture
def sandbox(tmp_path: Path) -> LocalSubprocessSandbox:
    return LocalSubprocessSandbox(workspace_root=tmp_path)


@pytest.fixture
def registry(sandbox: LocalSubprocessSandbox) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EditTool(sandbox))
    return reg


@pytest.fixture
def executor(registry: ToolRegistry) -> ToolExecutor:
    return ToolExecutor(registry)


def _tool_call(args: dict, call_id: str = "test_call") -> dict:
    return {"id": call_id, "name": "edit", "args": args}


class TestEditSideEffect:
    def test_side_effect_is_mutating(self, sandbox: LocalSubprocessSandbox):
        assert EditTool(sandbox).side_effect == ToolSideEffect.MUTATING


class TestEditHappyPath:
    @pytest.mark.asyncio
    async def test_single_match_success(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """1 处匹配 → 成功，文件内容确实被替换。"""
        sandbox.write_text("f.py", "def foo():\n    return 1\n")

        result = await executor.execute(
            _tool_call({"path": "f.py", "old_string": "return 1", "new_string": "return 2"})
        )

        assert result.result.ok is True
        assert result.result.data["replacements"] == 1
        assert sandbox.read_text("f.py") == "def foo():\n    return 2\n"

    @pytest.mark.asyncio
    async def test_multiline_old_string(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """多行 old_string 也能精确匹配替换。"""
        sandbox.write_text("f.py", "def foo():\n    return 1\n")

        result = await executor.execute(
            _tool_call({
                "path": "f.py",
                "old_string": "def foo():\n    return 1\n",
                "new_string": "def bar():\n    return 2\n",
            })
        )

        assert result.result.ok is True
        assert sandbox.read_text("f.py") == "def bar():\n    return 2\n"


class TestEditThreeStates:
    @pytest.mark.asyncio
    async def test_zero_match_fails(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """0 匹配 → failure(TOOL_EXECUTION_ERROR)，文件不变。"""
        sandbox.write_text("f.py", "content")

        result = await executor.execute(
            _tool_call({"path": "f.py", "old_string": "nonexistent", "new_string": "x"})
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.TOOL_EXECUTION_ERROR
        assert sandbox.read_text("f.py") == "content"

    @pytest.mark.asyncio
    async def test_multiple_match_fails(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """>1 匹配且 replace_all=False → failure(AMBIGUOUS)，文件不变。"""
        sandbox.write_text("f.py", "x x x")

        result = await executor.execute(
            _tool_call({"path": "f.py", "old_string": "x", "new_string": "y"})
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.TOOL_EXECUTION_ERROR
        assert "3" in result.result.message
        assert sandbox.read_text("f.py") == "x x x"


class TestEditReplaceAll:
    @pytest.mark.asyncio
    async def test_replace_all_succeeds(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """replace_all=True + 多匹配 → 全替换成功。"""
        sandbox.write_text("f.py", "x x x")

        result = await executor.execute(
            _tool_call({
                "path": "f.py",
                "old_string": "x",
                "new_string": "y",
                "replace_all": True,
            })
        )

        assert result.result.ok is True
        assert result.result.data["replacements"] == 3
        assert sandbox.read_text("f.py") == "y y y"

    @pytest.mark.asyncio
    async def test_replace_all_zero_match_still_fails(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """replace_all=True + 0 匹配 → 仍然失败。"""
        sandbox.write_text("f.py", "content")

        result = await executor.execute(
            _tool_call({
                "path": "f.py",
                "old_string": "nope",
                "new_string": "x",
                "replace_all": True,
            })
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.TOOL_EXECUTION_ERROR


class TestEditErrors:
    @pytest.mark.asyncio
    async def test_empty_old_string_rejected(self, executor: ToolExecutor):
        """空 old_string → schema min_length=1 拦截 → INVALID_ARGUMENT。"""
        result = await executor.execute(
            _tool_call({"path": "f.py", "old_string": "", "new_string": "x"})
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.INVALID_ARGUMENT

    @pytest.mark.asyncio
    async def test_path_escape_denied(self, executor: ToolExecutor):
        """路径越界 → PERMISSION_DENIED。"""
        result = await executor.execute(
            _tool_call({
                "path": "../../etc/passwd",
                "old_string": "x",
                "new_string": "y",
            })
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_nonexistent_file_fails(
        self, executor: ToolExecutor, sandbox: LocalSubprocessSandbox
    ):
        """文件不存在 → TOOL_EXECUTION_ERROR。"""
        result = await executor.execute(
            _tool_call({"path": "ghost.py", "old_string": "x", "new_string": "y"})
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.TOOL_EXECUTION_ERROR

    @pytest.mark.asyncio
    async def test_wrong_arg_type(self, executor: ToolExecutor):
        """参数类型错（path 非 str）→ INVALID_ARGUMENT。"""
        result = await executor.execute(
            _tool_call({"path": 123, "old_string": "x", "new_string": "y"})
        )

        assert result.result.ok is False
        assert result.result.error_code == ErrorCode.INVALID_ARGUMENT
