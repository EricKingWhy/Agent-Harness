"""AgentRuntime 端到端集成测试：真实 qwen 模型 + LocalSubprocessSandbox + read/write/bash。

测试缝 3（见 spec）：真实 LLM 驱动，验证 Agent 真能在 sandbox 里完成 Coding 闭环。
@skipif 无 API key 时跳过——默认套不烧 token、不挂。
手动跑：uv run pytest tests/agent/test_integration_coding.py -v --no-header -s
"""

from __future__ import annotations

import os
from pathlib import Path

# 阿里 MaaS 域名加入 NO_PROXY，绕过本地代理的 TLS 不兼容问题（直连）。
# 必须在 import openai/httpx 之前设好。
_MAAS_DOMAIN = "ws-z6pxn1u9u3hqds3j.cn-beijing.maas.aliyuncs.com"
_existing_no_proxy = os.environ.get("NO_PROXY", "")
if _MAAS_DOMAIN not in _existing_no_proxy:
    os.environ["NO_PROXY"] = f"{_existing_no_proxy},{_MAAS_DOMAIN},aliyuncs.com".lstrip(",")
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

import pytest

from agent_harness.agent import AgentRuntime
from agent_harness.agent.types import STATUS_COMPLETED
from agent_harness.config import Settings
from agent_harness.model.config import ModelConfig
from agent_harness.model.provider import create_chat_model
from agent_harness.sandbox import LocalSubprocessSandbox
from agent_harness.tooling import ToolExecutor, ToolRegistry
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
from tests.conftest import make_session

#: 从 .env 读 API key——存在才跑集成测试，否则 skipif。
_settings = Settings()
_HAS_API_KEY = bool(_settings.model_api_key)


def _make_runtime(workspace: Path) -> AgentRuntime:
    """构造完整 AgentRuntime：真实模型 + LocalSandbox + 全部 9 个 Coding Tools。"""
    config = ModelConfig.from_settings(_settings)
    model = create_chat_model(config)

    sandbox = LocalSubprocessSandbox(workspace_root=workspace)
    registry = ToolRegistry()
    registry.register(ReadTool(sandbox))
    registry.register(WriteTool(sandbox))
    registry.register(BashTool(sandbox))
    registry.register(EditTool(sandbox))
    registry.register(ApplyPatchTool(sandbox))
    registry.register(GlobTool(sandbox))
    registry.register(GrepTool(sandbox))
    registry.register(GitStatusTool(sandbox))
    registry.register(GitDiffTool(sandbox))

    return AgentRuntime(
        model=model,
        registry=registry,
        executor=ToolExecutor(registry),
        max_steps=10,
    )


@pytest.mark.skipif(not _HAS_API_KEY, reason="需要 .env 里配置 MODEL_API_KEY 才跑集成测试")
@pytest.mark.integration
@pytest.mark.asyncio
class TestAgentCodingIntegration:
    """真实 LLM 驱动的端到端：Agent 在 sandbox 里写文件、跑命令、读结果、给回答。"""

    async def test_agent_writes_file_and_reads_it(self, tmp_path: Path):
        """Agent 收到指令 → 用 write 写文件 → 用 read 读回来 → 给最终回答。"""
        runtime = _make_runtime(tmp_path)

        result = await runtime.run(
            make_session(tmp_path),
            "请在 workspace 里创建一个文件 hello.txt，内容写 'Hello from Agent'，"
            "然后读取它确认内容，最后告诉我你写了什么。"
        )

        assert result.status == STATUS_COMPLETED
        assert result.steps <= 10
        # Agent 真的在 workspace 里写了文件
        assert (tmp_path / "hello.txt").exists()
        content = (tmp_path / "hello.txt").read_text(encoding="utf-8")
        assert "Hello from Agent" in content

    async def test_agent_runs_bash_and_reports_exit_code(self, tmp_path: Path):
        """Agent 收到指令 → 用 bash 跑命令 → 读 stdout → 给最终回答。"""
        runtime = _make_runtime(tmp_path)

        result = await runtime.run(
            make_session(tmp_path),
            "请在 workspace 里用 bash 执行 'echo 42'，然后告诉我输出结果是什么数字。"
        )

        assert result.status == STATUS_COMPLETED
        # 最终回答里应该提到 42
        assert "42" in result.final_text

    async def test_agent_writes_then_runs_pytest(self, tmp_path: Path):
        """完整闭环：写一个会失败的 pytest → 跑 pytest 看到 exit_code=1 → 读结果 → 给回答。

        这是 SourcePlan 定义的核心能力：read → write → bash → 读失败 → 给回答。
        """
        runtime = _make_runtime(tmp_path)

        result = await runtime.run(
            make_session(tmp_path),
            "请在 workspace 里写一个 pytest 测试文件 test_sample.py，"
            "里面有一个 assert 1 == 2 的测试（故意会失败的）。"
            "然后用 bash 跑 'pip install pytest -q 2>nul & pytest -q test_sample.py'，"
            "跑完告诉我 pytest 的 exit code 是多少、测试有没有通过。"
        )

        assert result.status == STATUS_COMPLETED
        # Agent 应该提到测试失败或 exit code 非零
        final_lower = result.final_text.lower()
        assert any(
            kw in final_lower
            for kw in ["fail", "失败", "exit", "未通过", "1 == 2", "assert"]
        )
