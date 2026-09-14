"""PermissionPolicy + ToolPermission 枚举 + 各 Tool 的 permission 声明测试。

验证 05_SANDBOX_CODING_TOOLS.md §6 的三层 Permission Policy 地基：
- Tool ABC 默认 permission = WORKSPACE_WRITE（安全偏高）。
- 9 个 Coding Tool 各自声明正确级别。
- permission 与 side_effect 正交（不同关注点）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.tooling import (
    PermissionPolicy,
    Tool,
    ToolPermission,
    ToolSideEffect,
)
from agent_harness.tools import (
    ApplyPatchTool,
    BashTool,
    EditTool,
    GitDiffTool,
    GitStatusTool,
    GlobTool,
    GrepTool,
    ReadTool,
    WriteTool,
)


@pytest.fixture
def sandbox(tmp_path: Path) -> LocalSubprocessSandbox:
    return LocalSubprocessSandbox(workspace_root=tmp_path)


class TestPermissionPolicyEnum:
    def test_three_levels(self):
        """PermissionPolicy 有三个级别。"""
        assert PermissionPolicy.READ_ONLY.value == "read-only"
        assert PermissionPolicy.WORKSPACE_WRITE.value == "workspace-write"
        assert PermissionPolicy.DANGER_FULL_ACCESS.value == "danger-full-access"

    def test_levels_are_ordered_by_risk(self):
        """三层按风险递增（靠字符串排序不保证，这里显式验证层级关系）。"""
        # READ_ONLY < WORKSPACE_WRITE < DANGER_FULL_ACCESS
        assert PermissionPolicy.READ_ONLY != PermissionPolicy.WORKSPACE_WRITE
        assert PermissionPolicy.WORKSPACE_WRITE != PermissionPolicy.DANGER_FULL_ACCESS


class TestToolPermissionEnum:
    def test_three_levels(self):
        """ToolPermission 有三个级别。"""
        assert ToolPermission.READ_ONLY.value == "read-only"
        assert ToolPermission.WORKSPACE_WRITE.value == "workspace-write"
        assert ToolPermission.DANGER.value == "danger"


class TestToolDefaultPermission:
    def test_tool_abc_default_is_workspace_write(self):
        """Tool ABC 默认 permission = WORKSPACE_WRITE（安全偏高，不默认 DANGER）。"""

        class _MinimalTool(Tool):
            @property
            def name(self):
                return "minimal"

            @property
            def description(self):
                return "minimal"

            @property
            def args_schema(self):
                from pydantic import BaseModel as _BM

                class _Args(_BM):
                    pass

                return _Args

            async def execute(self, args):
                pass

        assert _MinimalTool().permission == ToolPermission.WORKSPACE_WRITE


class TestCodingToolPermissions:
    """9 个 Coding Tool 的 permission 声明验证。"""

    def test_read_is_read_only(self, sandbox: LocalSubprocessSandbox):
        assert ReadTool(sandbox).permission == ToolPermission.READ_ONLY

    def test_grep_is_read_only(self, sandbox: LocalSubprocessSandbox):
        assert GrepTool(sandbox).permission == ToolPermission.READ_ONLY

    def test_glob_is_read_only(self, sandbox: LocalSubprocessSandbox):
        assert GlobTool(sandbox).permission == ToolPermission.READ_ONLY

    def test_git_status_is_read_only(self, sandbox: LocalSubprocessSandbox):
        assert GitStatusTool(sandbox).permission == ToolPermission.READ_ONLY

    def test_git_diff_is_read_only(self, sandbox: LocalSubprocessSandbox):
        assert GitDiffTool(sandbox).permission == ToolPermission.READ_ONLY

    def test_write_is_workspace_write(self, sandbox: LocalSubprocessSandbox):
        assert WriteTool(sandbox).permission == ToolPermission.WORKSPACE_WRITE

    def test_edit_is_workspace_write(self, sandbox: LocalSubprocessSandbox):
        assert EditTool(sandbox).permission == ToolPermission.WORKSPACE_WRITE

    def test_apply_patch_is_workspace_write(self, sandbox: LocalSubprocessSandbox):
        assert ApplyPatchTool(sandbox).permission == ToolPermission.WORKSPACE_WRITE

    def test_bash_is_danger(self, sandbox: LocalSubprocessSandbox):
        assert BashTool(sandbox).permission == ToolPermission.DANGER


class TestPermissionOrthogonalToSideEffect:
    """permission 和 side_effect 是正交关注点——验证它们不混淆。"""

    def test_bash_is_mutating_and_danger(self, sandbox: LocalSubprocessSandbox):
        """bash：side_effect=MUTATING（调度串行），permission=DANGER（需要审批）。"""
        tool = BashTool(sandbox)
        assert tool.side_effect == ToolSideEffect.MUTATING
        assert tool.permission == ToolPermission.DANGER

    def test_read_is_read_only_and_read_only(self, sandbox: LocalSubprocessSandbox):
        """read：side_effect=READ_ONLY（可并发），permission=READ_ONLY（不需审批）。"""
        tool = ReadTool(sandbox)
        assert tool.side_effect == ToolSideEffect.READ_ONLY
        assert tool.permission == ToolPermission.READ_ONLY

    def test_write_is_mutating_but_only_workspace_write(
        self, sandbox: LocalSubprocessSandbox
    ):
        """write：side_effect=MUTATING（调度串行），permission=WORKSPACE_WRITE（不需 DANGER 审批）。"""
        tool = WriteTool(sandbox)
        assert tool.side_effect == ToolSideEffect.MUTATING
        assert tool.permission == ToolPermission.WORKSPACE_WRITE
