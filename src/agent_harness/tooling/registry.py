"""ToolRegistry：Tool 的路由目录。

为什么独立成 registry.py：
- Contract（contract.py）定义"Tool 是什么"；Registry 定义"当前注册了哪些 Tool"。
- 职责分离后，Registry 可独立测试，Executor（Task 2）也可独立替换。

Registry 的唯一职责：注册 / 查询 / 列出 / 导出模型定义。
【明确不负责】：Validation、Timeout、执行、重试、调度——全是 Executor 的活。

为什么不把 Retry/Timeout 塞进 Registry：
- Registry 是"配置时"对象（注册什么、查什么），运行策略是"运行时"对象。
- 耦合后，换 Executor 策略就得动 Registry，无法独立测试和替换。
"""

from __future__ import annotations

from agent_harness.tooling.contract import Tool


class ToolRegistry:
    """Tool 路由目录：name → Tool。

    设计约束：
    - 重复 name 在注册阶段直接抛错，绝不带着冲突继续运行（避免静默覆盖）。
    - get 找不到时抛 KeyError，不返回 None、不抛自定义异常类。
      理由：自定义 ToolNotFoundError 算"拆框架"，违反 Day04 Scope Lock；
      Executor（Task 2）负责把 KeyError 映射成 TOOL_NOT_FOUND ToolResult——
      这正是"Registry 只管查、Executor 只管执行域语义"的分工。
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        """注册一个 Tool。重复 name 直接 ValueError（注册阶段失败）。"""
        if tool.name in self._tools:
            raise ValueError(f"工具名 '{tool.name}' 已注册，拒绝覆盖")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        """按 name 取 Tool。找不到抛 KeyError(name)，由 Executor 映射成错误语义。"""
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def list(self) -> list[Tool]:
        """列出所有已注册 Tool（按注册顺序）。"""
        return list(self._tools.values())

    def filtered(self, names: frozenset[str] | set[str]) -> ToolRegistry:
        """派生一个只含 names 中已注册工具的【新】registry（原实例不动）。

        Multi-Agent 的 child 工具收窄机制（ADR-0015 决策 11）：构造期过滤、
        生成独立实例——child 拿到的 registry 物理上不含未授权工具，无逃逸面。
        names 中未注册的名字静默跳过（缺席 = optional capability 降级语义，
        越权校验是 AgentFactory 的职责，不在这一层）。
        """
        derived = ToolRegistry()
        for name, tool in self._tools.items():
            if name in names:
                derived.register(tool)
        return derived

    def export_model_definitions(self) -> list[dict]:
        """导出给模型/SDK 的工具菜单：name + description + parameters。

        形状即 LangChain bind_tools 消费的形状
        （{"name":..,"description":..,"parameters":..}），
        模型菜单与 Runtime Tool 来自同一份 Contract。

        为什么返回普通 dict 列表、不包成 Pydantic：
        - LangChain bind_tools 要的就是这个形状，包一层反而要再拆。
        - 薄层就好，避免抽象（Scope Lock：不拆 Adapter/Plugin 框架）。
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.args_schema.model_json_schema(),
            }
            for tool in self._tools.values()
        ]
