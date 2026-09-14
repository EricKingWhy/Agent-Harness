"""AgentRuntime + AgentFactory 的 system_prompt 透传（ADR-0020a）。

覆盖两条契约：
  B1：AgentRuntime(system_prompt="X") → 内部 ContextBuilder.system_prompt == "X"；
  B2：AgentFactory.create(spec) → child runtime 的 ContextBuilder.system_prompt
      == spec.system_prompt（child 与 parent 路径一致，ADR-0020a 决策 2.3）。

Scope：只验透传接线（system_prompt 到达 ContextBuilder），不验 build() 注入
（切片 A 已覆盖）。ContextBuilder.system_prompt 是公开属性（切片 A 已验）。
"""

from __future__ import annotations

from agent_harness.agent.factory import AgentFactory
from agent_harness.agent.profiles import AgentSpec
from agent_harness.agent.runtime import AgentRuntime
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.scripted_model import ScriptedModel


def _registry_with_read(tmp_path) -> ToolRegistry:
    """最小 registry：一个 read 工具（factory.create 需要非空 source）。"""
    from agent_harness.sandbox import LocalSubprocessSandbox
    from agent_harness.tools import ReadTool

    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path)
    reg = ToolRegistry()
    reg.register(ReadTool(sandbox))
    return reg


def test_agent_runtime_passes_system_prompt_to_context_builder(tmp_path):
    """B1：AgentRuntime(system_prompt="X") → _context_builder.system_prompt == "X"。"""
    runtime = AgentRuntime(
        model=ScriptedModel([]),
        registry=ToolRegistry(),
        executor=ToolExecutor(ToolRegistry()),
        system_prompt="你是 coding agent。",
    )
    assert runtime._context_builder.system_prompt == "你是 coding agent。"


def test_agent_runtime_no_system_prompt_by_default(tmp_path):
    """不传 system_prompt → ContextBuilder.system_prompt 是 None（向后兼容）。"""
    runtime = AgentRuntime(
        model=ScriptedModel([]),
        registry=ToolRegistry(),
        executor=ToolExecutor(ToolRegistry()),
    )
    assert runtime._context_builder.system_prompt is None


def test_agent_factory_create_passes_system_prompt(tmp_path):
    """B2：AgentFactory.create(spec) → child runtime 的 system_prompt == spec.system_prompt。"""
    source = _registry_with_read(tmp_path)
    factory = AgentFactory(model=ScriptedModel([]))
    spec = AgentSpec(
        name="coding",
        description="编码子代理",
        system_prompt="你是编码 agent，在给定 workspace 内完成 scoped task。",
        tool_scope=frozenset({"read"}),
    )

    child = factory.create(spec, source_registry=source)

    assert child._context_builder.system_prompt == spec.system_prompt
