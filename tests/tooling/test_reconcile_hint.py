"""ReconcileHint contract tests（#30）。

ReconcileHint 是 Tool 对"我怎么验证自己是否成功执行"的封装（CONTEXT.md）：
- Tool ABC 默认 unverifiable——安全默认即 NEED_RECONCILE；
- 可验证工具（read/write/edit/glob/grep/git_status/git_diff）覆写为 verifiable
  并给出建议验证动作；
- bash 保持默认（spec 07 §7：bash 的副作用彼此不同，不允许统一假装可验证）。

hint 只是给 ReconcileCallback 的建议数据：协调器永不自动验证、永不自动重跑。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from agent_harness.sandbox.local import LocalSubprocessSandbox
from agent_harness.tooling import Tool
from agent_harness.tools import (
    BashTool,
    EditTool,
    GitDiffTool,
    GitStatusTool,
    GlobTool,
    GrepTool,
    ReadTool,
    WriteTool,
)


class _MinimalTool(Tool):
    """不覆写任何可选元数据的最小 Tool——验证 ABC 安全默认值。"""

    @property
    def name(self) -> str:
        return "minimal"

    @property
    def description(self) -> str:
        return "minimal tool"

    @property
    def args_schema(self) -> type[BaseModel]:
        class _Args(BaseModel):
            pass

        return _Args

    async def execute(self, args: BaseModel):  # pragma: no cover - 不应被调用
        raise AssertionError("minimal tool 不应被执行")


def test_tool_default_reconcile_hint_is_unverifiable() -> None:
    hint = _MinimalTool().reconcile_hint

    assert hint.verifiable is False
    assert hint.suggested_action is None


@pytest.mark.parametrize(
    "tool_cls",
    [ReadTool, WriteTool, EditTool, GlobTool, GrepTool, GitStatusTool, GitDiffTool],
)
def test_verifiable_tools_declare_verifiable_hint(
    tool_cls: type, tmp_path: Path
) -> None:
    tool = tool_cls(LocalSubprocessSandbox(workspace_root=tmp_path))

    hint = tool.reconcile_hint

    assert hint.verifiable is True
    assert hint.suggested_action  # 建议验证动作非空，供 ReconcileCallback 参考


def test_bash_keeps_unverifiable_default(tmp_path: Path) -> None:
    tool = BashTool(LocalSubprocessSandbox(workspace_root=tmp_path))

    hint = tool.reconcile_hint

    assert hint.verifiable is False
    assert hint.suggested_action is None
