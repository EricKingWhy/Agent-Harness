"""Phase 12 真实 Gate（T6, #81, ADR-0014 决策 19）。

三条 Gate（roadmap Phase 12）：
1. Tavily 真实联网：web_search 工具真实查询返回带 citation 的命中
2. Model Fallback 真实切换：primary 死端点（连接失败=瞬时）→ 切真实
   fallback provider 完成回答，model/fallback 事件落 JSONL
3. 同错熔断真实触发：真实模型反复同参数调用失败工具 → 软熔断（user
   纠正消息）→ 硬熔断 end_run(failed)

凭证零泄漏：key 只从 Settings（.env）读取，绝不打印/断言明文。
手动跑：uv run pytest tests/integration/test_phase12_web_gate.py -m integration -v
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from agent_harness.agent.runtime import AgentRuntime
from agent_harness.agent.types import STATUS_IDENTICAL_TOOL_FAILURE_LOOP
from agent_harness.config import Settings
from agent_harness.model.config import ModelConfig
from agent_harness.model.provider import create_chat_model
from agent_harness.session import MODEL_FALLBACK, TOOL_FAILURE_GUARD, USER_MESSAGE
from agent_harness.tooling import Tool, ToolExecutor, ToolRegistry, ToolResult
from agent_harness.websearch.tavily import TavilyWebSearchProvider
from agent_harness.websearch.tools import WebSearchTool
from tests.conftest import make_session

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
def settings() -> Settings:
    return Settings()


def _fallback_model_config(settings: Settings) -> ModelConfig:
    """从 .env 的 FALLBACK_MODEL_* 构造 fallback 配置（Gate 2/3 的真实 provider）。"""
    api_key = settings.fallback_model_api_key.get_secret_value()
    if (
        not settings.fallback_model_provider or not api_key
        or not settings.fallback_model_name
    ):
        pytest.skip("Real fallback model (FALLBACK_MODEL_*) is not configured")
    return ModelConfig(
        provider=settings.fallback_model_provider,
        model_name=settings.fallback_model_name,
        api_key=api_key,
        base_url=(settings.fallback_model_base_url
                  or "https://api.senseaudio.cn/v1"),
        temperature=0,
    )


# ── Gate 1：Tavily 真实联网 ──


@pytest.mark.asyncio
async def test_gate1_tavily_real_web_search(settings):
    """真实 Tavily 查询 → 命中带 web:<url> citation + 分数；空 key 提前 skip。"""
    api_key = settings.tavily_api_key.get_secret_value()
    if not api_key:
        pytest.skip("Real Tavily key is not configured")

    tool = WebSearchTool(TavilyWebSearchProvider(api_key))
    args = tool.args_schema(query="Python asyncio 官方文档", k=3)
    result = await tool.execute(args)

    assert result.ok, f"web_search 失败：{result.message}"
    import json

    output = json.loads(result.data["output"])
    hits = output["hits"]
    assert len(hits) >= 1, "真实联网查询应至少命中 1 条"
    first = hits[0]
    assert first["citation"].startswith("web:http")
    assert first["url"].startswith("http")
    assert first["content"], "命中必须带 snippet"
    assert isinstance(first["score"], float)


# ── Gate 2：Model Fallback 真实切换 ──


@pytest.mark.asyncio
async def test_gate2_model_fallback_real_switch(settings, tmp_path):
    """primary = 死端点（连接失败=瞬时）→ 切真实 fallback 完成回答。"""
    fallback_config = _fallback_model_config(settings)
    # primary 用真实 key + 不可达端点：连接失败是瞬时错误（决策 1），
    # 认证错（401）这类非瞬时错误绝不会被触发——端点根本连不上。
    primary_config = ModelConfig(
        provider=fallback_config.provider,
        model_name=fallback_config.model_name,
        api_key=fallback_config.get_secret_value(),
        base_url="http://127.0.0.1:1/v1",
        temperature=fallback_config.temperature,
    )
    primary = create_chat_model(primary_config)
    fallback = create_chat_model(fallback_config)

    registry = ToolRegistry()
    runtime = AgentRuntime(
        model=primary, registry=registry, executor=ToolExecutor(registry),
        max_steps=5,
        fallback_model=fallback,
        primary_model_name=primary_config.model_name,
        fallback_model_name=fallback_config.model_name,
    )
    session = make_session(tmp_path)

    result = await runtime.run(session, "用一句话回答：1+1等于几？")

    assert result.status == "completed", "fallback 接管后 run 必须完成"
    assert result.final_text.strip(), "必须有真实模型回答"
    fallback_events = [e for e in session._events if e.type == MODEL_FALLBACK]
    assert len(fallback_events) == 1
    data = fallback_events[0].data
    assert data["reason"] in {
        "APIConnectionError", "ConnectError", "APITimeoutError", "TimeoutError",
        "ConnectionError", "ConnectTimeout",
    }, f"切换原因应为瞬时连接类错误，实际：{data['reason']}"
    assert data["to_model"] == fallback_config.model_name


# ── Gate 3：同错熔断真实触发 ──


class _FailArgs(BaseModel):
    command: str = Field(default="probe", description="要执行的命令")


class _AlwaysFailTool(Tool):
    """总是业务失败的工具（ok=False，非异常）——真实模型的重试目标。"""

    @property
    def name(self) -> str:
        return "fail_probe"

    @property
    def description(self) -> str:
        return "总是失败的探测工具（用于熔断演练）。"

    @property
    def args_schema(self) -> type[BaseModel]:
        return _FailArgs

    async def execute(self, args: _FailArgs) -> ToolResult:
        return ToolResult.failure(
            message="命令执行失败：环境瞬时故障，请立即用完全相同的参数重试。",
            error_code="TOOL_EXECUTION_ERROR", retryable=True,
        )


@pytest.mark.asyncio
async def test_gate3_repeated_tool_failure_guard_real_trigger(settings, tmp_path):
    """真实模型反复同参调用失败工具 → 熔断触发 → run/failed。

    真实模型对「发起 8 个同参调用」的服从是概率性的（temperature=0 也不保证
    ）——这是 gate 与单元测试的本质差异：单元测试用 ScriptedModel 钉死确定
    语义（soft@3 → hard@6、指纹变化清零、单批塌缩到最严重信号）；gate 只
    证明真实模型行为能驱动真实熔断。因此最多独立尝试 3 次（各自全新 session
    ），熔断在任一次触发即通过；触发后按实际信号档位断言对应语义。
    """
    config = _fallback_model_config(settings)
    model = create_chat_model(config)

    prompt = (
        "请在你的下一条回复里，同时并行发起 8 个 fail_probe 工具调用，"
        "8 个调用的参数必须完全相同：command='probe'。不要在调用前输出任何"
        "解释文字，不要少于 8 个调用，不要修改参数。"
    )

    result = None
    guard_events: list = []
    session = None
    for attempt in range(3):
        registry = ToolRegistry()
        registry.register(_AlwaysFailTool())
        runtime = AgentRuntime(
            model=model, registry=registry, executor=ToolExecutor(registry),
            max_steps=20,
            primary_model_name=config.model_name,
        )
        session = make_session(tmp_path / f"attempt-{attempt}")
        result = await runtime.run(session, prompt)
        guard_events = [e for e in session._events if e.type == TOOL_FAILURE_GUARD]
        if guard_events:
            break

    assert result is not None and session is not None
    levels = [e.data["level"] for e in guard_events]
    assert levels, "3 次尝试内熔断都未触发（真实模型未产生同指纹连续失败）"

    # 单批并行同指纹失败 → 观察循环塌缩到最严重信号：硬触发时只发 hard 事件
    # （终结中的 run 不注入纠正消息）；跨轮次 soft→hard 顺序双事件由 T1 的
    # ScriptedModel 测试钉死。
    if "hard" in levels:
        hard = next(e for e in guard_events if e.data["level"] == "hard")
        assert hard.data["consecutive_failures"] == 6
        assert hard.data["tool_name"] == "fail_probe"
        # 硬熔断强制 end_run(failed)，绝不伪造最终回答。
        assert result.status == STATUS_IDENTICAL_TOOL_FAILURE_LOOP
    else:
        soft = next(e for e in guard_events if e.data["level"] == "soft")
        assert soft.data["consecutive_failures"] == 3
        assert soft.data["tool_name"] == "fail_probe"
        corrective = [
            e for e in session._events
            if e.type == USER_MESSAGE and "改变策略" in e.data.get("content", "")
        ]
        assert len(corrective) == 1
