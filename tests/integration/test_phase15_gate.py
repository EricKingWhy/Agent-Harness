"""Phase 15 真实 Gate（#125，ADR-0018 D12）。

Gate 1（默认车道）：Langfuse 关闭时 Core 正常（不变量 #21）——生产装配形状
（每会话一 runtime）下事件流与 Phase 14 语义逐字节一致（trace_id=null）。
Gate 2（integration 车道，需密钥）：真云链路——真实 trace 上传 → flush →
回捞 → 对照官方 best-practices 逐项审计（模型名/usage/层级/命名/内容边界）。
Gate 3（默认车道）：P0 Golden Cases 全绿（deterministic，CI 可复现）。
Gate 4（默认车道）：seed/experiment 在未配置云时优雅降级。
Gate 5（integration 车道，需密钥）：真云 Dataset seed 幂等 + Experiment 上报。

跑法：uv run pytest tests/integration/test_phase15_gate.py -m integration -v
（Gate 1/3/4 在默认车道随全量跑。）
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from agent_harness.agent import AgentRuntime
from agent_harness.observability import LangfuseSink, flush_process_sink
from agent_harness.session import RUN_COMPLETED
from agent_harness.tooling import ToolExecutor, ToolRegistry
from evaluation.runner import run_dataset
from evaluation.seed_langfuse import push_dataset
from evaluation.support import AddTool
from tests.conftest import make_session
from tests.scripted_model import ScriptedModel

_REPO_ROOT = Path(__file__).resolve().parents[2]

# integration 车道在收集期即需判定密钥在场（skipif）：.env 此处显式加载。
# 键留在进程内，绝不打印/外泄。
from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")


def _has_langfuse_keys() -> bool:
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"),
    )


def _real_sink(tmp_path: Path, recorder_holder: dict) -> LangfuseSink:
    """真实 Langfuse 客户端（jp 云）；recorder_holder 捕获 trace id。"""
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
    from langfuse import Langfuse

    def factory(**kwargs):
        client = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            base_url=os.environ.get("LANGFUSE_BASE_URL") or None,
            environment="phase15-gate",
        )
        return client

    return LangfuseSink(
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        base_url=os.environ.get("LANGFUSE_BASE_URL", ""),
        client_factory=factory,
    )


# ── Gate 1（默认车道）：Langfuse 关闭时 Core 正常 ──


@pytest.mark.asyncio
async def test_gate1_core_normal_without_langfuse(tmp_path):
    sink = LangfuseSink(public_key="", secret_key="")
    registry = ToolRegistry()
    registry.register(AddTool())
    scripted = ScriptedModel([__import__(
        "langchain_core.messages", fromlist=["AIMessage"],
    ).AIMessage(content="你好")])
    session = make_session(tmp_path)
    runtime = AgentRuntime(scripted, registry, ToolExecutor(registry),
                           observability_sink=sink)
    result = await runtime.run(session, "hi")

    assert result.final_text == "你好"
    completed = next(e for e in session.events if e.type == RUN_COMPLETED)
    assert completed.data["trace_id"] is None
    assert sink.dropped == 0  # 缺席旁路零行为、零痕迹


# ── Gate 3（默认车道）：P0 Golden Cases 全绿 ──


def test_gate3_p0_golden_cases_all_green(tmp_path):
    results = run_dataset(
        _REPO_ROOT / "evaluation" / "datasets" / "p0_core.jsonl",
        session_root=tmp_path / "eval",
        write_report=False,
    )
    assert len(results) >= 3
    assert all(r.ok for r in results), [(r.name, r.metrics, r.error) for r in results]


# ── Gate 4（默认车道）：未配置云时 seed/experiment 优雅降级 ──


def test_gate4_cloud_ops_degrade_gracefully(tmp_path, monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    seed = push_dataset(
        _REPO_ROOT / "evaluation" / "datasets" / "p0_core.jsonl",
        public_key="", secret_key="", base_url="",
    )
    assert seed["status"] == "skipped"

    from evaluation.experiment import run_langfuse_experiment

    experiment = run_langfuse_experiment(
        "p0_core", public_key="", secret_key="", base_url="",
        client_factory=lambda **kw: (_ for _ in ()).throw(
            AssertionError("未配置不得触 SDK"),
        ),
    )
    assert experiment["status"] == "skipped"


# ── Gate 2/5（integration 车道）：真云上传 + 回捞 + 审计 + seed/experiment ──


@pytest.mark.integration
@pytest.mark.skipif(not _has_langfuse_keys(), reason="LANGFUSE keys 未配置（.env）")
@pytest.mark.asyncio
async def test_gate2_real_cloud_trace_upload_fetch_audit(tmp_path):
    """真实链路：埋点 → 上传 → 回捞 → 官方 best-practices 逐项审计。"""

    sink = _real_sink(tmp_path, {})
    registry = ToolRegistry()
    registry.register(AddTool())
    from langchain_core.messages import AIMessage

    scripted = ScriptedModel([
        AIMessage(
            content="",
            tool_calls=[{"name": "add", "args": {"first_number": 1, "second_number": 2},
                         "id": "call_gate", "type": "tool_call"}],
            response_metadata={"model_name": "gate-scripted-a"},
            usage_metadata={"input_tokens": 100, "output_tokens": 10,
                            "total_tokens": 110},
        ),
        AIMessage(
            content="1 + 2 = 3",
            response_metadata={"model_name": "gate-scripted-a"},
            usage_metadata={"input_tokens": 150, "output_tokens": 20,
                            "total_tokens": 170},
        ),
    ])
    session = make_session(tmp_path / "sess")
    runtime = AgentRuntime(scripted, registry, ToolExecutor(registry),
                           observability_sink=sink)
    result = await runtime.run(session, "请计算 1+2，使用 add 工具。")
    assert result.final_text == "1 + 2 = 3"

    completed = next(e for e in session.events if e.type == RUN_COMPLETED)
    trace_id = completed.data["trace_id"]
    assert trace_id, "Langfuse 开启时 trace_id 必须回填真实值"

    flush_process_sink()

    from langfuse import Langfuse

    client = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        base_url=os.environ.get("LANGFUSE_BASE_URL") or None,
    )
    # 回捞重试（后台批处理传播有延迟）：404 = trace 未落库；
    # trace 先于子观测落库 → 以 observations 到齐为就绪条件。
    trace = None
    from langfuse.api.commons.errors.not_found_error import NotFoundError

    for _attempt in range(16):  # 最长 ~48s
        try:
            candidate = client.api.trace.get(trace_id)
            if len(candidate.observations or []) >= 4:
                trace = candidate
                break
        except NotFoundError:
            pass
        await asyncio.sleep(3)
    assert trace is not None, f"48s 内未回捞到完整 trace {trace_id}"

    # ── 官方 best-practices 审计清单（D12：对照现查，本断言为项目内固化版）──
    assert trace.name == "agent-run"  # 描述性命名
    assert trace.session_id == session.session_id  # session 聚合（不发明新身份）
    assert trace.metadata["run_id"] == completed.run_id
    assert trace.metadata["agent_id"] == "default"
    assert trace.input == "请计算 1+2，使用 add 工具。"  # trace input = 用户消息
    generations = [o for o in trace.observations if o.type == "GENERATION"]
    tools = [o for o in trace.observations if o.type == "TOOL"]
    contexts = [o for o in trace.observations if o.name == "context-build"]
    assert len(generations) == 2, "两次模型调用 = 两个 generation"
    assert all(o.model for o in generations), "generation 必须带 model 名"
    assert all(o.usage_details and o.usage_details.get("total") > 0
               for o in generations), "usage 必须如实上报（自动 cost 的前提）"
    assert any(o.metadata.get("response_model") == "gate-scripted-a"
               for o in generations)
    assert len(tools) == 1 and tools[0].name == "add"
    assert tools[0].metadata["tool_call_id"] == "call_gate"
    assert tools[0].metadata["session_id"] == session.session_id  # ledger 对账键
    assert contexts, "context-build 观测在场"
    # trace output = 最终回答
    assert trace.output == "1 + 2 = 3"


@pytest.mark.integration
@pytest.mark.skipif(not _has_langfuse_keys(), reason="LANGFUSE keys 未配置（.env）")
def test_gate5_real_seed_idempotent_and_experiment(tmp_path):
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
    dataset_path = _REPO_ROOT / "evaluation" / "datasets" / "p0_core.jsonl"

    first = push_dataset(
        dataset_path,
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        base_url=os.environ.get("LANGFUSE_BASE_URL", ""),
    )
    assert first["status"] == "ok"
    second = push_dataset(
        dataset_path,
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        base_url=os.environ.get("LANGFUSE_BASE_URL", ""),
    )
    assert second["created"] == 0, "重复 seed 不得建重复 item（幂等）"
    assert second["skipped"] >= 3

    from evaluation.experiment import run_langfuse_experiment

    experiment = run_langfuse_experiment(
        "p0_core",
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        base_url=os.environ.get("LANGFUSE_BASE_URL", ""),
        experiment_name="phase15-gate",
        session_root=tmp_path / "exp",
    )
    assert experiment["status"] == "ok"
