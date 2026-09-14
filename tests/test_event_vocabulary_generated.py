"""事件词汇权威枚举守卫（#173 T5 / issue #178，路线 B）。

`docs/EVENT_VOCABULARY.md` 由 `scripts/gen_event_vocabulary.py` 从
`src/agent_harness/session/event.py` 生成。本测试独立复核两件事：

1. 产物与生成器当前输出**逐字节一致**——不一致说明有人改了 `event.py` 却没重新生成。
2. 把产物**重新解析回来**，与 `event.py` 的 `EVENT_TYPES` / `STREAM_ONLY_TYPES`
   双向比对：缺名 / 多名 / 分节归属错都红。

为什么第 2 条不能省：第 1 条只证明「产物 == 生成器输出」，一旦生成器自身漏渲染
（例如过滤条件写错），第 1 条照样绿。第 2 条把产物直接对上事实源，才是真兜底
（spec 旧事件表就是手工维护漂移到 21 个名字对不上才被发现的，见 #173）。
"""

from __future__ import annotations

import agent_harness.session.event as event_module
from scripts.gen_event_vocabulary import (
    OUTPUT_PATH,
    ROW_RE,
    format_row,
    generate_markdown,
    parse_vocabulary,
)


def _artifact_text() -> str:
    if not OUTPUT_PATH.exists():
        raise AssertionError(
            f"{OUTPUT_PATH} 不存在——运行 uv run python scripts/gen_event_vocabulary.py 生成"
        )
    return OUTPUT_PATH.read_text(encoding="utf-8")


def test_row_format_round_trips():
    """格式契约自洽：`format_row()` 写出来的行必须能被 `ROW_RE` 读回去。

    这条守的是**同一格式的两端**（写入端 f-string / 读取端正则）：只改一端时，
    下面的产物断言可能仍然绿（生成物与生成器一起变），但解析端会开始静默丢行——
    那正是"守卫看着在跑、其实瞎了"。"""
    row = format_row('TOOL_CALL', 'tool/call')
    match = ROW_RE.match(row)
    assert match is not None, f"format_row 的输出无法被 ROW_RE 解析：{row!r}"
    assert match.group("const") == 'TOOL_CALL'
    assert match.group("value") == 'tool/call'


def test_generated_event_vocabulary_artifact_is_current():
    """产物与生成器输出一致；漂移时提示重新生成命令。"""
    actual = _artifact_text()
    assert actual == generate_markdown(), (
        f"{OUTPUT_PATH} 与 src/agent_harness/session/event.py 漂移——"
        "运行 uv run python scripts/gen_event_vocabulary.py 重新生成"
    )


def test_artifact_names_match_event_module_both_directions():
    """产物里的名字与 event.py 注册表双向覆盖：缺名、多名、分节归错都红。"""
    durable, stream = parse_vocabulary(_artifact_text())

    missing = (event_module.EVENT_TYPES - durable) | (event_module.STREAM_ONLY_TYPES - stream)
    assert not missing, f"产物漏了 event.py 已注册的类型: {sorted(missing)}"

    extra = (durable - event_module.EVENT_TYPES) | (stream - event_module.STREAM_ONLY_TYPES)
    assert not extra, f"产物含 event.py 未注册的类型，或持久化/仅广播归属写错: {sorted(extra)}"


def test_artifact_declares_its_own_counts_and_stays_parsable():
    """AC3：格式稳定可解析——分节标题与合计行的数字必须等于实际行数。"""
    text = _artifact_text()
    durable, stream = parse_vocabulary(text)

    assert durable, "「持久化」一节解析为空——格式契约被破坏或事件全没了"
    assert stream, "「仅广播」一节解析为空——格式契约被破坏（仅广播类型不该消失）"
    assert f"## 持久化（{len(durable)}）" in text
    assert f"## 仅广播（{len(stream)}）" in text
    assert (
        f"合计 {len(durable) + len(stream)} 个类型：{len(durable)} 持久化 + {len(stream)} 仅广播" in text
    ), "合计行与实际行数不一致——重新生成即可"
