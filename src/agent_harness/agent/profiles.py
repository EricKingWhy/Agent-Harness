"""AgentProfile/AgentSpec：Multi-Agent 的核心域对象（ADR-0015 决策 2/9）。

Profile 是预定义的 agent 角色（核心域对象，不进插件）；Spec 是运行时
实例化描述——动态创建 = 实例化 AgentSpec，绝不生成代码（spec §2）。

字段设计参照 pi/oh-my-pi 的 AgentDefinition（PORT DESIGN：name/description/
systemPrompt/tools 必备形状 + per-agent 工具收窄与深度上限），裁剪到 V1：
- tool_scope 显式声明、无隐式默认——缺席的 optional capability 工具由
  AgentFactory 降级丢弃，存在的越权申请由 Factory 拒绝（防权限提升）；
- model_policy V1 只有 "inherit"（继承主模型链，fallback/看门狗自动生效）；
- max_depth V1 全线 1（child 无 delegate）；max_delegations 只对 supervisor
  角色有意义，默认挂在 main 上。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_harness.prompt import DEFAULT_REGISTRY


def _builtin_prompt(name: str) -> str:
    """内置 profile 的 system prompt **唯一来源 = 注册表**（ADR-0023 D1/D12）。

    只在这一处接线：parent 走 `assembly.py` 的 `profile_spec.system_prompt`，
    child 走 `factory.py` 的 `spec.system_prompt`——两条路径因此零改动即一致，
    不存在两个调用点漂移的可能。

    刻意**不**改成"按 `spec.name` 查注册表"：`AgentSpec.system_prompt` 必须继续
    是普通字段，否则自定义 spec（以及 `multiagent/provider.py` 传入的自定义
    profiles 字典）的 prompt 会被内置文案覆盖。
    """
    return DEFAULT_REGISTRY.assemble(f"profile:{name}").system_text


@dataclass(frozen=True)
class AgentSpec:
    """一个可实例化 agent 的完整描述（角色、边界、预算）。"""

    name: str
    description: str
    system_prompt: str
    tool_scope: frozenset[str] = field(default_factory=frozenset)
    max_steps: int = 20
    max_depth: int = 1
    model_policy: str = "inherit"
    max_delegations: int = 0

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("AgentSpec.name 不能为空")
        if self.max_steps < 1:
            raise ValueError(f"AgentSpec.max_steps 必须 ≥ 1：{self.max_steps}")
        if self.max_depth < 1:
            raise ValueError(f"AgentSpec.max_depth 必须 ≥ 1：{self.max_depth}")


#: coding 角色的工具集（spec §8：read/write/edit/apply_patch/bash/grep/glob，
#: 加 git_status/git_diff；默认不开放 web）。
_CODING_TOOLS = frozenset({
    "read", "write", "edit", "apply_patch", "bash", "grep", "glob",
    "git_status", "git_diff",
})

#: research/review 角色的只读工具集（spec §8：Knowledge/Web/MCP 只读，无
#: write/bash；本地 read/grep/glob 是 review 看共享 workspace 真实文件的最小需要）。
#: MCP 工具名运行时动态发现，V1 静态集合不含——capability 接线时按需扩展。
_RESEARCH_TOOLS = frozenset({
    "read", "grep", "glob",
    "retrieve_knowledge", "read_knowledge_source", "web_search",
})

#: supervisor（main）：亲自查证用全量 + delegate。max_steps 对齐单代理现状。
_MAIN_TOOLS = _CODING_TOOLS | _RESEARCH_TOOLS | {"delegate", "inspect_artifact"}

#: 三内置 profile（出厂设定，非用户自定义面——文件发现机制 DEFER）。
#: `system_prompt` 的正文在 `agent_harness.prompt.builtin`（改文案开那一个文件）。
BUILTIN_PROFILES: dict[str, AgentSpec] = {
    "main": AgentSpec(
        name="main",
        description="Supervisor：理解目标、拆解委派、必要时亲自查证与综合。",
        system_prompt=_builtin_prompt("main"),
        tool_scope=_MAIN_TOOLS,
        max_steps=20,
        max_depth=1,
        max_delegations=8,
    ),
    "coding": AgentSpec(
        name="coding",
        description="编码子代理：在共享 workspace 内读写代码并运行验证。",
        system_prompt=_builtin_prompt("coding"),
        tool_scope=_CODING_TOOLS,
        max_steps=10,
    ),
    "research_review": AgentSpec(
        name="research_review",
        description="调研/审查子代理：只读检索本地文件、知识库与网络证据。",
        system_prompt=_builtin_prompt("research_review"),
        tool_scope=_RESEARCH_TOOLS,
        max_steps=10,
    ),
}
