"""一次性迁移：把历史 session 的 step_id 重编号为 session 级唯一。

## 为什么需要

TICKET_STEP_ID_COLLISION_MULTI_TURN：修复前后端 `step_id` 是 per-run 局部
计数，每个 run 都从 1 开始；前端把 `step_id` 当 session 级 turn 标识
（`projection.resolveStep` → `withTurnAt`），于是第二轮起的事件折叠进首轮
turn——首轮回答被清空、次轮回答错位。修复后新事件已是 session 级唯一，
但**修复前落盘的旧 session 仍是旧编号**，回放仍会错位。

本脚本把旧事件流按「run 边界 + 每轮局部位号」重编号为 session 级唯一，
与修复后 runtime 的编号规则（`step_base = max(已有最大 step_id, 真实用户轮数)`）
逐值一致，因此：

- 迁移后旧会话回放正常（前端零改动）；
- 旧会话继续续聊也正确（runtime 的 step_base 基于已修正数据计算）；
- 对新数据是 **no-op**（幂等），可安全地对整个 store 跑。

## 规则（与服务端同一口径）

```
allocated = 0            已分配 turn 数（= 前端 turns.length）
遇到 run/started：       anchor = allocated（该 run 的 user 消息已计入）
遇到 user/message：      非注入的才 allocated += 1（注入的纠正消息不新开轮）
遇到带 step_id 的事件：  new = anchor + (raw - 本 run 首个 raw)
                        allocated = max(allocated, new)
```

## 只改 step_id

逐行处理：只有值真的变化的那一行才重新序列化（用 JsonlSessionStore 的
同一格式 `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`），
其余行**原样保留**——seq / type / data / 行序 / 键序均不动，损坏行也不碰。

## 用法

```bash
# 1) 先看（默认 dry-run，不写任何文件）
python scripts/migrate_legacy_step_id.py --root D:/intelligence-agent/.agent/workspace/sessions

# 2) 确认后应用（自动备份原文；退出码 0=已应用/无待迁移，2=dry-run 有待迁移）
python scripts/migrate_legacy_step_id.py --root <dir> --apply
```

**应用前请停止服务**（Web/CLI）：写入期间若有 append，脚本会因内容哈希
变化而拒绝执行，不会覆盖正在写入的会话。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

RUN_STARTED = "run/started"
USER_MESSAGE = "user/message"
EVENTS_FILENAME = "events.jsonl"


@dataclass
class RunInfo:
    """一个 run 的重编号记录。"""

    index: int
    run_id: str | None
    anchor: int
    renames: dict[int, int] = field(default_factory=dict)

    @property
    def raw_steps(self) -> list[int]:
        return sorted(self.renames)


@dataclass
class SessionPlan:
    """一个 session 的只读迁移方案（dry-run 与 apply 共用）。"""

    session_id: str
    path: Path
    content_sha256: str
    raw_lines: list[str]
    parsed: list[tuple[int, dict]]  # (行下标, 事件对象)
    new_ids: list[int | None]  # 与 parsed 等长
    runs: list[RunInfo]
    unassigned: int  # run 边界之外带 step_id 的事件数（不迁移，如实计数）

    @property
    def event_count(self) -> int:
        return len(self.parsed)

    @property
    def changes(self) -> list[tuple[int, dict, int]]:
        """(行下标, 事件对象, 新 step_id)——仅列出真的变化的行。"""
        out = []
        for (line_idx, event), new_id in zip(self.parsed, self.new_ids):
            if new_id is not None and new_id != event.get("step_id"):
                out.append((line_idx, event, new_id))
        return out

    @property
    def changed(self) -> int:
        return len(self.changes)

    def render(self) -> str:
        """迁移后的整文件文本（未变化的行逐字节保留原文）。

        重新序列化沿用 `JsonlSessionStore.append_event` 的同一口径
        （`ensure_ascii=False, separators=(",", ":")`）——改 store 的格式必须同步这里，
        否则迁移行会与库写入格式不一致。
        """
        lines = list(self.raw_lines)
        for line_idx, event, new_id in self.changes:
            lines[line_idx] = json.dumps(
                {**event, "step_id": new_id},
                ensure_ascii=False, separators=(",", ":"),
            )
        return "\n".join(lines) + "\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_step_ids(
    events: list[dict],
) -> tuple[list[int | None], list[RunInfo], int]:
    """按 run 边界重编号，返回 (新 step_id 列表, 每轮记录, run 外事件数)。

    ``new step_id`` 与 ``events`` 等长：``None`` 表示该事件本来就没有 step_id。
    """
    new_ids: list[int | None] = [e.get("step_id") for e in events]
    allocated = 0  # 已分配 turn 数（= 前端 turns.length）
    anchor = 0  # 当前 run 的步号锚点（该 run user 消息占用的 turn 键）
    first_raw: int | None = None  # 当前 run 首个 raw step（局部化基准）
    runs: list[RunInfo] = []
    current: RunInfo | None = None
    unassigned = 0

    for i, event in enumerate(events):
        etype = event.get("type")
        raw = event.get("step_id")

        if etype == RUN_STARTED:
            anchor = allocated
            first_raw = None
            current = RunInfo(index=len(runs) + 1, run_id=event.get("run_id"),
                              anchor=anchor)
            runs.append(current)
            continue

        if etype == USER_MESSAGE and not (event.get("data") or {}).get("injected_by"):
            allocated += 1

        if raw is None or not isinstance(raw, int):
            continue

        if current is None:
            # run 边界之外的事件：无锚点可依，保守不动（如实计数报警）。
            unassigned += 1
            continue

        if first_raw is None:
            first_raw = raw
        new_id = anchor + (raw - first_raw)
        new_ids[i] = new_id
        if new_id != raw:
            current.renames[raw] = new_id
        allocated = max(allocated, new_id)

    return new_ids, runs, unassigned


def is_collision_free(events: list[dict]) -> bool:
    """给定事件流的 step_id 是否**本身**已 session 级单调（run 之间不重叠）。

    直接读原始值、不做归一化——因此旧数据（每轮从 1 重数）返回 False
    （= 需要迁移），迁移后的数据返回 True。前端 `withTurnAt` 按唯一 step
    定位 turn 的前提就是它。
    """
    seen_max = 0
    run_ids: list[int] = []
    for event in events:
        if event.get("type") == RUN_STARTED:
            if run_ids and min(run_ids) <= seen_max:
                return False
            if run_ids:
                seen_max = max(seen_max, max(run_ids))
            run_ids = []
            continue
        raw = event.get("step_id")
        if raw is None:
            # data.step 是 model/started（stream-only）的前端首选键，一并纳入判定。
            raw = (event.get("data") or {}).get("step")
        if isinstance(raw, int):
            run_ids.append(raw)
    return not (run_ids and min(run_ids) <= seen_max)


def parse_event_lines(raw_lines: list[str]) -> list[tuple[int, dict]]:
    """解析出行下标 → 事件对象（空行/损坏行/非事件行跳过，与 store 容错一致）。"""
    parsed: list[tuple[int, dict]] = []
    for line_idx, line in enumerate(raw_lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "seq" in obj:
            parsed.append((line_idx, obj))
    return parsed


def count_pending(events: list[dict]) -> int:
    """给定事件流，返回仍需改写的行数（0 = 已是 session 级唯一编号）。"""
    ids, _, _ = normalize_step_ids(events)
    return sum(
        1 for event, new_id in zip(events, ids)
        if new_id is not None and new_id != event.get("step_id")
    )


def plan_session(path: Path) -> SessionPlan:
    """只读地规划一个 events.jsonl（不写盘）。"""
    content = path.read_text(encoding="utf-8")
    raw_lines = content.splitlines()
    parsed = parse_event_lines(raw_lines)

    new_ids, runs, unassigned = normalize_step_ids([obj for _, obj in parsed])
    return SessionPlan(
        session_id=path.parent.name,
        path=path,
        content_sha256=_sha256(content),
        raw_lines=raw_lines,
        parsed=parsed,
        new_ids=new_ids,
        runs=runs,
        unassigned=unassigned,
    )


def apply_session(plan: SessionPlan, *, backup_dir: Path) -> Path:
    """备份原文后原子写回迁移结果；返回备份文件路径。

    写入前复核内容哈希：规划之后文件被 append（服务在跑）则拒绝执行——
    绝不覆盖正在写入的会话。
    """
    current = plan.path.read_text(encoding="utf-8")
    if _sha256(current) != plan.content_sha256:
        raise RuntimeError(
            f"{plan.path} 在规划后被改动（会话可能仍在写入）；"
            "请停止服务后重跑"
        )
    if plan.changed == 0:
        return Path()

    backup_path = backup_dir / plan.session_id / EVENTS_FILENAME
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plan.path, backup_path)

    tmp_path = plan.path.with_suffix(".jsonl.migrating")
    tmp_path.write_text(plan.render(), encoding="utf-8")
    tmp_path.replace(plan.path)
    return backup_path


def _iter_event_files(root: Path):
    if root.is_file() and root.name == EVENTS_FILENAME:
        yield root
        return
    yield from sorted(root.glob(f"*/{EVENTS_FILENAME}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把历史 session 的 step_id 重编号为 session 级唯一（幂等）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("## 用法", 1)[-1],
    )
    parser.add_argument("--root", action="append", required=True, type=Path,
                        help="session store 根目录（可重复；也可直接给 events.jsonl）")
    parser.add_argument("--apply", action="store_true",
                        help="真正写入（默认只 dry-run 出报告）")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="备份目录（默认 <root>/../step-id-backup-<UTC 时间戳>）")
    parser.add_argument("--quiet", action="store_true", help="只打印汇总")
    args = parser.parse_args(argv)

    roots = [p for p in args.root]
    missing = [str(p) for p in roots if not p.exists()]
    if missing:
        print(f"[错误] 路径不存在：{', '.join(missing)}", file=sys.stderr)
        return 1

    plans: list[SessionPlan] = []
    for root in roots:
        for events_path in _iter_event_files(root):
            plans.append(plan_session(events_path))

    pending = [p for p in plans if p.changed]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_dir = args.backup_dir or (roots[0].parent / f"step-id-backup-{stamp}")

    print(f"扫描 {len(plans)} 个 session，需要迁移 {len(pending)} 个"
          f"（{'APPLY' if args.apply else 'DRY-RUN'}）")
    for plan in pending:
        tags = ""
        if plan.unassigned:
            tags = f"  ⚠ run 外带 step_id 事件 {plan.unassigned} 条（未迁移）"
        print(f"\n  {plan.session_id}：{plan.event_count} 事件 / {plan.changed} 行改写{tags}")
        for run in plan.runs:
            if run.renames:
                mapping = ", ".join(f"{raw}→{new}" for raw, new in sorted(run.renames.items()))
                print(f"    run#{run.index} anchor={run.anchor}  {mapping}")

    # 迁移后不变量自校验（预演阶段先算，不写盘）：① 步号不再重叠；② 幂等
    for plan in pending:
        rendered = plan.render()
        migrated = [obj for _, obj in parse_event_lines(rendered.splitlines())]
        if not is_collision_free(migrated):
            print(f"\n[错误] {plan.session_id} 迁移后仍存在步号重叠，已中止（未写任何文件）",
                  file=sys.stderr)
            return 1
        again = count_pending(migrated)
        if again != 0:
            print(f"\n[错误] {plan.session_id} 迁移不幂等（二次规划仍有 {again} 行改动），"
                  "已中止（未写任何文件）", file=sys.stderr)
            return 1

    if not args.apply:
        if pending:
            print(f"\n以上为预演。加 --apply 执行（备份写入 {backup_dir}）")
            return 2
        print("\n无待迁移 session（全部已是 session 级唯一编号）。")
        return 0

    applied = 0
    for plan in pending:
        backup = apply_session(plan, backup_dir=backup_dir)
        if backup == Path():
            continue
        applied += 1
        print(f"\n  ✅ {plan.session_id}：{plan.changed} 行改写，备份 → {backup}")
    print(f"\n完成：{applied} 个 session 已迁移，备份目录 {backup_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
