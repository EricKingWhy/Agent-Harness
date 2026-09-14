"""T6 #122：evaluation/ 骨架——数据集加载、真实 Runtime 跑 case、报告、seed 幂等。"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.runner import load_dataset, run_case, run_dataset
from evaluation.seed_langfuse import push_dataset

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "evaluation" / "datasets" / "p0_core.jsonl"


def test_load_dataset_returns_typed_cases():
    cases = load_dataset(_DATASET)
    assert cases and cases[0].name == "tool_selection_add"
    assert cases[0].case_type == "tool_selection"
    assert cases[0].script, "deterministic case 必须带模型剧本"


def test_run_case_with_real_runtime_deterministic(tmp_path: Path):
    """默认路径 = ScriptedModel + 真实 AgentRuntime + 真实 tool registry。"""
    case = load_dataset(_DATASET)[0]
    result, events = run_case(case, session_root=tmp_path / "sess")

    assert result.ok, f"metrics={result.metrics} error={result.error}"
    assert result.metrics["tool_selected"] is True
    assert result.metrics["dangling_tool_calls"] == 0
    assert result.metrics["status"] == "completed"
    assert result.usage_total.get("total_tokens", 0) >= 0
    assert events, "事件流必须返回供 Langfuse Scores 复用"


def test_run_dataset_writes_local_report(tmp_path: Path):
    results = run_dataset(_DATASET, session_root=tmp_path / "sess")

    assert len(results) == 3 and all(r.ok for r in results)
    reports = sorted((_REPO_ROOT / "evaluation" / "reports").glob("p0_core-*.json"))
    assert reports, "本地报告恒产生（云关也能看）"
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert report["passed"] == 3 and report["total"] == 3
    reports[-1].unlink()  # 测试产物不留在 repo


class _FakeLangfuse:
    """记录式假客户端：get_dataset 第二次返回已有 items（幂等验证）。"""

    def __init__(self):
        self.datasets: dict[str, list] = {}
        self.created_items: list = []

    def get_dataset(self, name: str):
        if name not in self.datasets:
            raise RuntimeError(f"dataset {name} not found (404)")
        from types import SimpleNamespace

        return SimpleNamespace(items=[
            SimpleNamespace(metadata={"name": n}) for n in self.datasets[name]
        ])

    def create_dataset(self, name: str):
        self.datasets.setdefault(name, [])

    def create_dataset_item(self, *, dataset_name: str, input, expected_output, metadata):
        self.datasets.setdefault(dataset_name, [])
        self.datasets[dataset_name].append(metadata["name"])
        self.created_items.append(metadata["name"])


def test_seed_pushes_and_is_idempotent():
    client = _FakeLangfuse()
    factory = lambda **kwargs: client

    first = push_dataset(
        _DATASET, public_key="pk", secret_key="sk",
        base_url="https://example.invalid", client_factory=factory,
    )
    assert first == {"status": "ok", "created": 3, "skipped": 0,
                     "dataset": "p0_core"}

    second = push_dataset(
        _DATASET, public_key="pk", secret_key="sk",
        base_url="https://example.invalid", client_factory=factory,
    )
    assert second["created"] == 0 and second["skipped"] == 3, "重复推送不得建重复 item"
    assert len(client.created_items) == 3


def test_seed_skips_gracefully_without_keys():
    calls: list = []

    def _boom(**kwargs):
        calls.append(kwargs)
        raise AssertionError("未配置时不得触碰 SDK")

    result = push_dataset(
        _DATASET, public_key="", secret_key="",
        base_url="https://example.invalid", client_factory=_boom,
    )
    assert result["status"] == "skipped"
    assert "未配置" in result["reason"]
    assert not calls


def test_all_p0_cases_pass_end_to_end(tmp_path: Path):
    """P0 全量：tool_selection + recovery + kill_resume 三条 deterministic。"""
    from evaluation.runner import run_dataset

    results = run_dataset(_DATASET, session_root=tmp_path / "sess", write_report=False)
    assert len(results) == 3
    assert all(r.ok for r in results), [ (r.name, r.metrics, r.error) for r in results ]


def test_langfuse_experiment_upload_and_graceful_skip(tmp_path: Path):
    from types import SimpleNamespace

    from evaluation.experiment import run_langfuse_experiment

    # 未配置 → 跳过，不触 SDK
    skipped = run_langfuse_experiment(
        "p0_core", public_key="", secret_key="",
        base_url="https://example.invalid",
        client_factory=lambda **kw: (_ for _ in ()).throw(AssertionError("no SDK")),
    )
    assert skipped["status"] == "skipped"

    # 配置 → run_experiment 收到真实 task + deterministic evaluators
    recorded: dict = {}

    class _FakeExpClient:
        def get_dataset(self, name):
            return SimpleNamespace(items=[
                SimpleNamespace(
                    id="it-1",
                    metadata={"name": "tool_selection_add",
                              "case_type": "tool_selection", "tags": ["p0"],
                              "script": [
                                  {"content": "", "tool_calls": [
                                      {"name": "add", "args": {"first_number": 1,
                                                               "second_number": 2},
                                       "id": "call_e1"}]},
                                  {"content": "1 + 2 = 3"},
                              ]},
                    input={"task": "请计算 1+2 等于多少，使用 add 工具。"},
                    expected_output={"tools": ["add"]},
                ),
            ])

        def run_experiment(self, *, name, run_name, data, task, evaluators, max_concurrency):
            recorded.update(name=name, run_name=run_name, n_items=len(data),
                            task=task, evaluators=evaluators,
                            max_concurrency=max_concurrency)

    result = run_langfuse_experiment(
        "p0_core", public_key="pk", secret_key="sk",
        base_url="https://example.invalid",
        client_factory=lambda **kw: _FakeExpClient(),
        session_root=tmp_path / "exp",
    )
    assert result["status"] == "ok"
    assert recorded["n_items"] == 1 and recorded["max_concurrency"] == 1
    # 真跑一遍 task + evaluators：deterministic 评分器产出合法 Scores
    from evaluation.experiment import _case_from_item, _deterministic_evaluators

    fake_item = SimpleNamespace(
        id="it-1", metadata={"name": "tool_selection_add",
                             "case_type": "tool_selection", "tags": ["p0"],
                             "script": [
                                 {"content": "", "tool_calls": [
                                     {"name": "add", "args": {"first_number": 1,
                                                              "second_number": 2},
                                      "id": "call_e1"}]},
                                 {"content": "1 + 2 = 3"},
                             ]},
        input={"task": "请计算 1+2 等于多少，使用 add 工具。"},
        expected_output={"tools": ["add"]},
    )
    output = recorded["task"](fake_item)
    assert output["result"]["ok"] is True
    scores = [ev(input=None, output=output, expected_output=None)
              for ev in recorded["evaluators"]]
    values = {s["name"]: s["value"] for s in scores}
    assert values["p0_pass"] == 1
    assert values["dangling_tool_calls"] == 0
    assert _case_from_item(fake_item).name == "tool_selection_add"
    assert _deterministic_evaluators  # 引用完整性
