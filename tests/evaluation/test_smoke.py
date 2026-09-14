"""T8 #124：regression metadata（spec 12 §8）+ smoke 结构性断言 + 手动入口。

真实模型链的实际调用不进默认 pytest（烧 token、依赖上游稳定性）——
本文件只测 metadata 收集、结构性断言纯函数与注入 fake runtime 的 smoke 管线。
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.smoke import (
    dataset_version,
    regression_metadata,
    run_real_model_smoke,
    smoke_structural_ok,
)
from tests.scripted_model import ScriptedModel

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "evaluation" / "datasets" / "p0_core.jsonl"


def test_regression_metadata_fields_are_honest():
    metadata = regression_metadata(dataset_path=_DATASET)
    assert metadata["app_version"]  # 包版本真实存在
    assert metadata["git_commit"], "git worktree 内必须取到短哈希"
    assert metadata["model_provider"]
    assert metadata["eval_dataset_version"] == dataset_version(_DATASET)
    assert len(metadata["eval_dataset_version"]) == 12
    assert "timestamp" in metadata
    # 无版本化来源的键如实省略（零伪造）
    assert "knowledge_version" not in metadata
    assert "memory_provider" not in metadata


def test_dataset_version_is_content_hash(tmp_path: Path):
    f1 = tmp_path / "d.jsonl"
    f1.write_text("a", encoding="utf-8")
    f2 = tmp_path / "d2.jsonl"
    f2.write_text("a", encoding="utf-8")
    f3 = tmp_path / "d3.jsonl"
    f3.write_text("b", encoding="utf-8")
    assert dataset_version(f1) == dataset_version(f2)
    assert dataset_version(f1) != dataset_version(f3)


def test_smoke_structural_ok_semantics():
    class _E:
        def __init__(self, type, data):
            self.type = type
            self.data = data

    good = [
        _E("run/completed", {"usage_total": {"total_tokens": 10},
                             "trace_id": "tr-1"}),
    ]
    metrics = smoke_structural_ok(good)
    assert metrics["ok"] and metrics["trace_id_present"]

    no_usage = smoke_structural_ok([_E("run/completed", {})])
    assert not no_usage["ok"]  # usage 缺失 = 结构不完整（绝不伪造 0）

    dangling = smoke_structural_ok([
        _E("tool/call", {"tool_call_id": "c1"}),
        _E("run/completed", {"usage_total": {"total_tokens": 1}}),
    ])
    assert not dangling["ok"]

    require_trace = smoke_structural_ok(
        [_E("run/completed", {"usage_total": {"total_tokens": 1}})],
        require_trace=True,
    )
    assert not require_trace["ok"]  # Langfuse 开启时 trace 必须在场


def test_smoke_pipeline_with_injected_fake_runtime(tmp_path: Path, monkeypatch):
    """管线验证（真实模型调用不在 pytest 车道）：注入 ScriptedModel runtime。"""
    from agent_harness.agent import AgentRuntime
    from agent_harness.tooling import ToolExecutor, ToolRegistry
    from evaluation.support import AddTool

    settings_stub = type("S", (), {
        "model_provider": "deepseek", "model_name": "scripted",
        "fallback_model_provider": "", "fallback_model_name": "",
        "langfuse_public_key": "", "langfuse_secret_key": "",
        "langfuse_base_url": "", "langfuse_trace_content": "full",
        "langfuse_tracing_environment": "development", "langfuse_release": "",
    })()

    def factory(_task: str) -> AgentRuntime:
        registry = ToolRegistry()
        registry.register(AddTool())
        model = ScriptedModel([
            __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(
                content="3",
                usage_metadata={"input_tokens": 5, "output_tokens": 2,
                                "total_tokens": 7},
            ),
        ])
        return AgentRuntime(model, registry, ToolExecutor(registry))

    result = run_real_model_smoke(
        "请计算 1+1。", settings=settings_stub,
        session_root=tmp_path / "sess", runtime_factory=factory,
    )
    assert result.ok, (result.metrics, result.error)
    assert result.usage_total.get("total_tokens") == 7
    reports = sorted((_REPO_ROOT / "evaluation" / "reports").glob("smoke-real-*.json"))
    assert reports
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["smoke"] == "real-model"
    assert payload["regression_metadata"]["model_name"] == "scripted"
    reports[-1].unlink()


def test_smoke_builds_runtime_with_fallback_config(tmp_path: Path, monkeypatch):
    """fallback 配置在场时真实构建路径不崩（回归：ModelConfig 字段名错配）。

    手动车道入口曾因 ModelConfig 字段名错配（name vs model_name、缺 temperature、
    api_key 传 SecretStr）在首次真实运行时崩——现有 factory 注入测试绕过了这段。
    此处 monkeypatch create_chat_model 返回 ScriptedModel（不烧 token），强制
    走完 fallback 构建分支，验证字段正确解析。
    """
    from langchain_core.messages import AIMessage
    from pydantic import SecretStr

    import agent_harness.model.provider as provider_mod

    settings_stub = type("S", (), {
        "model_provider": "deepseek", "model_name": "primary-model",
        "model_api_key": SecretStr("sk-primary"),
        "model_base_url": "https://primary.example.com",
        "temperature": 0.2,
        "fallback_model_provider": "zhipu", "fallback_model_name": "fallback-model",
        "fallback_model_api_key": SecretStr("sk-fallback"),
        "fallback_model_base_url": "https://fallback.example.com",
        "langfuse_public_key": SecretStr(""), "langfuse_secret_key": SecretStr(""),
        "langfuse_base_url": "", "langfuse_trace_content": "full",
        "langfuse_tracing_environment": "development", "langfuse_release": "",
    })()

    def fake_create(config):
        return ScriptedModel([AIMessage(content="ok", usage_metadata={
            "input_tokens": 1, "output_tokens": 1, "total_tokens": 2})])

    monkeypatch.setattr(provider_mod, "create_chat_model", fake_create)

    result = run_real_model_smoke(
        "计算 1+1。", settings=settings_stub,
        session_root=tmp_path / "sess",
    )
    assert result.ok, (result.metrics, result.error)
    reports = sorted((_REPO_ROOT / "evaluation" / "reports").glob("smoke-real-*.json"))
    if reports:
        reports[-1].unlink()
