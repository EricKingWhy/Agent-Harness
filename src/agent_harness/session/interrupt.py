"""崩溃中断检测（Phase Multiturn T8 / #138）。

进程重启后，事件流里「开了没关」的 run（`run/started` 之后没有
`run/completed` / `run/failed` / `run/interrupted`）就是被崩溃打断的 run。
本模块只做**纯投影**：检测不写事件；追加 `run/interrupted` 与 Ledger
reconcile 由 `recovery.scan` 编排（07 §9 恢复顺序的唯一入口仍是
RecoveryCoordinator）。

不变量 #12/#14：中断事实与「副作用是否发生」是两回事——这里只标记 run 中断，
工具调用的终态仍必须由 Ledger reconcile 判定（UNKNOWN 需人工裁决，不盲重跑）。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_harness.session.event import (
    RUN_STARTED,
    RUN_TERMINAL_TYPES,
    SessionEvent,
)


@dataclass(frozen=True)
class InterruptedRun:
    """一个被崩溃打断的 run 的投影。

    ``interrupted_seq`` = 该 run 最后一条事件的 seq（PRD §2.5 契约字段）；
    ``step_id`` = 最后一步的步号（前端显示「上次运行在第 N 步中断」，可能为 None）；
    ``run_id`` = 事件流里的 run 标识（可能为 None：run/started 之前的裸事件）；
    ``agent_id`` = 该 run 的 agent（回填到 run/interrupted 信封，与 run/started 一致）。
    """

    run_id: str | None
    interrupted_seq: int
    step_id: int | None
    agent_id: str | None = None


def detect_unterminated_runs(events: list[SessionEvent]) -> list[InterruptedRun]:
    """列出没有终态的 run（按出现顺序，最多每个 run 一项）。

    以 run_id 归组；没有 run_id 的事件归到当前开放 run（`run/started` 一定带
    run_id，所以这个兜底只影响同一 run 内事件缺 run_id 的异常写入）。
    """
    open_runs: dict[str, InterruptedRun] = {}
    anonymous_key = ""  # run_id 缺失事件的归组键（与真实 uuid 不会撞）

    for event in events:
        if event.type == RUN_STARTED:
            key = event.run_id or anonymous_key
            open_runs[key] = InterruptedRun(
                run_id=event.run_id,
                interrupted_seq=event.seq,
                step_id=event.step_id,
                agent_id=event.agent_id,
            )
            continue
        if event.type in RUN_TERMINAL_TYPES:
            # 信封带 run_id 就精确关闭；没带（手写/旧数据）关最近开启的那个 run。
            key = event.run_id or anonymous_key
            if key not in open_runs and open_runs:
                key = next(reversed(open_runs))
            open_runs.pop(key, None)
            continue
        # 普通事件：推进所属 run 的最后位置。
        key = event.run_id or anonymous_key
        current = open_runs.get(key)
        if current is not None:
            open_runs[key] = InterruptedRun(
                run_id=current.run_id,
                interrupted_seq=event.seq,
                step_id=event.step_id if event.step_id is not None else current.step_id,
                agent_id=current.agent_id,
            )
    return list(open_runs.values())
