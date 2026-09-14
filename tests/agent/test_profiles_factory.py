"""AgentProfile/AgentSpec 域对象 + AgentFactory（Phase 13 T1, #82, ADR-0015）。

设计参照 pi/oh-my-pi 的 AgentDefinition（PORT DESIGN：name/description/
systemPrompt/tools 必备形状 + per-agent 工具收窄），落成 Python 域对象。
profile 是核心域对象（ADR-0015 决策 2/9），编排能力（delegate）才是插件。

契约：
- 三内置 profile 常量：tool_scope 显式声明、无隐式默认（决策 9）；
- AgentFactory.create：越权拒绝（防提升）、缺席工具降级丢弃、构造期过滤出
  **新 registry 实例**（原全量不被污染）、模型链继承（fallback/看门狗）；
- Gate「动态创建第四个 Agent 而不改 Core」在本文件以动态 AgentSpec 达成。
"""

from __future__ import annotations

import logging

import pytest

from agent_harness.agent.factory import AgentFactory
from agent_harness.agent.profiles import BUILTIN_PROFILES, AgentSpec
from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.tooling import ToolExecutor, ToolRegistry
from tests.scripted_model import ScriptedModel


def _full_registry(tmp_path) -> ToolRegistry:
    """模拟装配后的全量 registry（coding 工具；工具从不执行，sandbox 仅构造）。"""
    from agent_harness.tools import (
        BashTool,
        EditTool,
        GlobTool,
        GrepTool,
        ReadTool,
        WriteTool,
    )

    sandbox = LocalSubprocessSandbox(workspace_root=tmp_path)
    reg = ToolRegistry()
    for tool in (ReadTool(sandbox), WriteTool(sandbox), BashTool(sandbox),
                 EditTool(sandbox), GlobTool(sandbox), GrepTool(sandbox)):
        reg.register(tool)
    return reg


class TestBuiltinProfiles:
    def test_three_builtin_profiles_exist(self):
        assert set(BUILTIN_PROFILES) == {"main", "coding", "research_review"}

    def test_main_is_supervisor_with_union_scope(self):
        main = BUILTIN_PROFILES["main"]
        assert "delegate" in main.tool_scope
        assert {"read", "write", "bash", "retrieve_knowledge",
                "web_search"} <= main.tool_scope
        assert main.max_steps == 20
        assert main.max_delegations == 8

    def test_coding_scope_has_no_web(self):
        coding = BUILTIN_PROFILES["coding"]
        assert {"read", "write", "edit", "apply_patch", "bash", "grep",
                "glob", "git_status", "git_diff"} == coding.tool_scope
        assert "web_search" not in coding.tool_scope
        assert "delegate" not in coding.tool_scope  # depth=1：child 无 delegate
        assert coding.max_steps == 10

    def test_research_review_is_read_only(self):
        research = BUILTIN_PROFILES["research_review"]
        assert {"read", "grep", "glob", "retrieve_knowledge",
                "read_knowledge_source", "web_search"} == research.tool_scope
        assert not (research.tool_scope & {"write", "edit", "bash",
                                           "apply_patch"})
        assert research.max_steps == 10

    def test_spec_rejects_invalid_shape(self):
        with pytest.raises(ValueError, match="name"):
            AgentSpec(name="", description="d", system_prompt="s",
                      tool_scope=frozenset({"read"}))
        with pytest.raises(ValueError, match="max_steps"):
            AgentSpec(name="x", description="d", system_prompt="s",
                      tool_scope=frozenset({"read"}), max_steps=0)


class TestAgentFactoryFiltering:
    def test_filtered_registry_is_new_instance_and_unpolluted(self, tmp_path):
        source = _full_registry(tmp_path)
        factory = AgentFactory(model=ScriptedModel([]),
                               primary_model_name="main-model")
        spec = AgentSpec(name="child", description="d", system_prompt="s",
                         tool_scope=frozenset({"read", "bash"}))

        runtime = factory.create(spec, source_registry=source)

        assert {x.name for x in runtime.registry.list()} == {"read", "bash"}
        assert {x.name for x in source.list()} == {"read", "write", "bash", "edit",
                                      "glob", "grep"}, "全量 registry 不被污染"
        assert runtime.registry is not source

    def test_escalation_rejected_when_grantable_narrower(self, tmp_path):
        """spec 要的 tool 存在于全量 registry 但不在可授予集合 → 拒绝（防提升）。"""
        source = _full_registry(tmp_path)
        factory = AgentFactory(model=ScriptedModel([]))
        spec = AgentSpec(name="child", description="d", system_prompt="s",
                         tool_scope=frozenset({"read", "bash"}))

        with pytest.raises(ValueError, match="bash"):
            factory.create(spec, source_registry=source,
                           grantable=frozenset({"read"}))

    def test_absent_tools_degrade_dropped_with_warning(self, tmp_path, caplog):
        """optional capability 的工具缺席（如 websearch 未配）→ 降级丢弃，不炸。"""
        source = _full_registry(tmp_path)  # 没有 web_search
        factory = AgentFactory(model=ScriptedModel([]))
        spec = AgentSpec(name="child", description="d", system_prompt="s",
                         tool_scope=frozenset({"read", "web_search"}))

        with caplog.at_level(logging.WARNING, logger="agent_harness.agent.factory"):
            runtime = factory.create(spec, source_registry=source)

        assert {x.name for x in runtime.registry.list()} == {"read"}
        assert any("web_search" in rec.message for rec in caplog.records)

    def test_default_grantable_is_source_registry(self, tmp_path):
        """不传 grantable = 可授予全集（built-in profile 从全量 registry 起步）。"""
        source = _full_registry(tmp_path)
        factory = AgentFactory(model=ScriptedModel([]))
        spec = AgentSpec(name="child", description="d", system_prompt="s",
                         tool_scope=frozenset({"read", "write"}))

        runtime = factory.create(spec, source_registry=source)
        assert {x.name for x in runtime.registry.list()} == {"read", "write"}


class TestAgentFactoryInheritance:
    def test_model_chain_and_limits_inherited(self, tmp_path):
        model = ScriptedModel([])
        fallback = ScriptedModel([])
        factory = AgentFactory(
            model=model, fallback_model=fallback,
            primary_model_name="main-model", fallback_model_name="fb-model",
            stream_idle_timeout=30.0, stream_total_timeout=120.0,
        )
        spec = AgentSpec(name="child", description="d", system_prompt="s",
                         tool_scope=frozenset({"read"}), max_steps=7)

        runtime = factory.create(spec, source_registry=_full_registry(tmp_path))

        assert runtime.model is model
        assert runtime._fallback_model is fallback
        assert runtime.max_steps == 7
        assert runtime._stream_idle_timeout == 30.0
        assert runtime._stream_total_timeout == 120.0
        assert runtime._primary_model_name == "main-model"
        assert runtime._fallback_model_name == "fb-model"

    def test_executor_factory_seam_receives_child_registry(self, tmp_path):
        captured: list[ToolRegistry] = []

        def executor_factory(registry: ToolRegistry) -> ToolExecutor:
            captured.append(registry)
            return ToolExecutor(registry)

        factory = AgentFactory(model=ScriptedModel([]),
                               executor_factory=executor_factory)
        spec = AgentSpec(name="child", description="d", system_prompt="s",
                         tool_scope=frozenset({"read"}))

        runtime = factory.create(spec, source_registry=_full_registry(tmp_path))

        assert captured == [runtime.registry]


class TestGateFourthAgent:
    def test_dynamic_fourth_agent_without_core_change(self, tmp_path):
        """Gate：动态创建第四个 Agent——构造全新 AgentSpec 走 factory，零 Core 改动。"""
        assert "analyst" not in BUILTIN_PROFILES
        spec = AgentSpec(
            name="analyst", description="数据分析临时角色",
            system_prompt="你是数据分析专家。",
            tool_scope=frozenset({"read", "grep"}),
            max_steps=5,
        )
        factory = AgentFactory(model=ScriptedModel([]),
                               primary_model_name="main-model")
        runtime = factory.create(spec, source_registry=_full_registry(tmp_path))

        assert {x.name for x in runtime.registry.list()} == {"read", "grep"}
        assert runtime.max_steps == 5
