"""事件词汇单一来源守卫（Phase 9 技术债修复）。

背景：事件词汇曾在 src/agent_harness/session/event.py 与 web/src/types.ts
双处手工维护，因不同步出过 bug（tool/started vs tool/call）。

现在 web/src/generated/event-types.ts 由 scripts/gen_event_types.py 从
event.py 生成，本测试兜底防漂移：

1. 生成产物必须与脚本当前输出逐字节一致——不一致说明有人改了 event.py
   却没重新生成，测试失败并给出修复命令。
2. event.py 的词汇注册表必须自洽：每个 `xxx/yyy` 形态的模块常量都要
   入册 EVENT_TYPES ∪ STREAM_ONLY_TYPES，且集合里不能有孤儿值。
"""

from __future__ import annotations

from scripts.gen_event_types import OUTPUT_PATH, collect_vocabulary, generate_ts


def test_generated_event_types_artifact_is_current():
    """产物与生成器输出一致；漂移时提示重新生成命令。"""
    expected = generate_ts()
    if not OUTPUT_PATH.exists():
        raise AssertionError(
            f"{OUTPUT_PATH} 不存在——运行 uv run python scripts/gen_event_types.py 生成"
        )
    actual = OUTPUT_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        f"{OUTPUT_PATH} 与 src/agent_harness/session/event.py 漂移——"
        "运行 uv run python scripts/gen_event_types.py 重新生成"
    )


def test_event_module_constants_fully_registered():
    """模块常量与词汇注册表双向覆盖：无漏册常量、无孤儿值。"""
    pairs, persistent, stream_only = collect_vocabulary()
    values = {value for _, value in pairs}

    unregistered = values - (persistent | stream_only)
    assert not unregistered, (
        f"event.py 中的事件常量未入册 EVENT_TYPES/STREAM_ONLY_TYPES: {sorted(unregistered)}"
    )

    orphans = (persistent | stream_only) - values
    assert not orphans, (
        f"EVENT_TYPES/STREAM_ONLY_TYPES 含没有对应模块常量的孤儿值: {sorted(orphans)}"
    )
