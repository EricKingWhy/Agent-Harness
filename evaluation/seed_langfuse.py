"""推送 evaluation/datasets/*.jsonl → Langfuse Datasets（幂等，ADR-0018 D9）。

真相源在 repo（datasets/*.jsonl 版本化可 diff）；云端只是评测承载。
幂等策略：dataset 按 name 建一次；item 按 case name 对齐——已存在的跳过，
绝不重复建。Langfuse 未配置（key 空）→ 明确跳过，本地数据集不受影响。
手动入口：``uv run python -m evaluation.seed_langfuse``。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def push_dataset(
    dataset_path: str | Path,
    *,
    public_key: str,
    secret_key: str,
    base_url: str,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """把一个数据集推送到 Langfuse（幂等）。返回 {status, created, skipped[, reason]}。"""
    if not public_key or not secret_key:
        return {
            "status": "skipped",
            "reason": "LANGFUSE_PUBLIC_KEY/SECRET_KEY 未配置——云端推送跳过（本地数据集不受影响）",
            "created": 0, "skipped": 0,
        }
    from langfuse import Langfuse  # 云端操作是前台 CLI 路径，非旁路热路径

    factory = client_factory or (lambda **kwargs: Langfuse(**kwargs))
    client = factory(public_key=public_key, secret_key=secret_key, base_url=base_url)

    dataset_path = Path(dataset_path)
    dataset_name = dataset_path.stem
    cases = _load_cases(dataset_path)

    existing_names: set[str] = set()
    dataset_exists = True
    try:
        dataset = client.get_dataset(dataset_name)
        for item in (getattr(dataset, "items", None) or []):
            metadata = getattr(item, "metadata", None) or {}
            name = metadata.get("name") if isinstance(metadata, dict) else None
            if name:
                existing_names.add(str(name))
    except Exception:  # noqa: BLE001 - 404/网络差异统一按"不存在"处理再建
        dataset_exists = False

    created = 0
    skipped = 0
    if not dataset_exists:
        client.create_dataset(name=dataset_name)
    for case in cases:
        if case["name"] in existing_names:
            skipped += 1
            continue
        client.create_dataset_item(
            dataset_name=dataset_name,
            input={"task": case.get("task", "")},
            expected_output=case.get("expected", {}),
            metadata={
                "name": case["name"],
                "case_type": case.get("case_type", ""),
                "tags": case.get("tags", []),
                # deterministic 剧本随 item round-trip（experiment task 复原用）
                "script": case.get("script", []),
            },
        )
        created += 1
    return {"status": "ok", "created": created, "skipped": skipped,
            "dataset": dataset_name}


def main() -> int:
    """推送 datasets/ 下全部数据集；未配置时明确输出原因（退出码 0=正常跳过）。"""
    from agent_harness.config import Settings

    settings = Settings()
    datasets = sorted((_REPO_ROOT / "evaluation" / "datasets").glob("*.jsonl"))
    if not datasets:
        print("evaluation/datasets/ 下没有数据集。")
        return 0
    exit_code = 0
    for dataset in datasets:
        result = push_dataset(
            dataset,
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
        )
        print(f"[{result['status']}] {dataset.name}: "
              f"created={result.get('created', 0)} skipped={result.get('skipped', 0)}"
              f"{' — ' + result['reason'] if result.get('reason') else ''}")
        if result["status"] == "ok":
            exit_code = 0
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
