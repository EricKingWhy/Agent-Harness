"""JsonlSessionStore：SessionEvent 的薄 IO 层（JSONL append-only）。

只负责三件事：
    1. read_events(session_id) — 读取一个 Session 的全部有效事件
    2. append_event(session_id, event) — 向一个 Session 追加一条事件
    3. 守卫 seq 单调性（BUG-011）——重复 / 回退 seq 拒写（``SeqConflict``）

seq **分配**仍是 Session 聚合根的职责（``_next_seq``）；本层负责把每会话的
「读已落盘最大 seq → 判定 → 写」串成临界区，并拒写违反单调性的 seq
（写者跨线程：事件循环的 ``Session.append`` 与恢复扫描的工作线程都会进来）。
保证范围是**同一进程内**——跨进程没有文件锁，见 ``__init__`` 的边界说明。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agent_harness.session.errors import SeqConflict
from agent_harness.session.event import (
    RUN_TERMINAL_TYPES,
    SESSION_STARTED,
    USER_MESSAGE,
    SessionEvent,
)
from agent_harness.session.header import StartedHeader

logger = logging.getLogger("agent_harness.session.store")

#: read_session_summary 头部扫描的解析上限：first_user_message 几乎总在
#: 会话最初几条事件里；超过此数仍未找到则放弃（返回 None，前端有
#: events 扫描降级路径）。只约束"解析几条"，不约束行计数（O(1)/行）。
_SUMMARY_HEAD_PARSE_LIMIT = 200


@dataclass(frozen=True)
class WorkspaceRef:
    """会话摘要里的**项目引用**（WS-3 / #153 AC1–AC2）：id 做请求/重命名，title 做显示。

    放在 session 层而不是 `agent_harness.workspace`：依赖方向是 session ← workspace
    （`workspace/models.py` 本来就 import 本层），反向 import 会成环。本类只是**值对象**
    ——它就是"会话摘要里那一格"的形状，不含任何项目领域行为（那些在 `WorkspaceIndex`）。
    """

    id: str
    title: str


@dataclass(frozen=True)
class SessionSummaryStats:
    """read_session_summary 的产出：列表页所需的最小字段集。

    `session_id` 是这一行的身份，与统计字段同属列表页所需——它在这里自洽后，
    `service.list_sessions` 可原样返回本 dataclass：列表行的字段因此只有一个带类型的
    定义点，新增字段漏改会被构造点/类型检查暴露，而不是静默丢在契约之外。
    """

    session_id: str
    event_count: int
    first_event_time: str | None
    last_event_time: str | None
    first_user_message: str | None
    #: OBS-010：最近一次 run 的 Langfuse trace_id（末事件是 run 终结事件时才有）。
    #: 未配置可观测性时终结事件里本就是 null → 这里也是 None（不变量 #21：可观测性
    #: 缺席既不致命也不伪造）。
    trace_id: str | None = None
    #: ARCH-4b：同一终结事件的 `trace_url`（人类可点击的 Langfuse URL，契约 2d7f87a
    #: / ADR-0018 D7）。与 `trace_id` 同源、同一套守卫；未配置可观测性时为 None。
    trace_url: str | None = None
    #: WS-3 / #153：会话所属项目；**未分组**（历史遗留 / 未命名 workspace / 装配里
    #: 没有 workspace 索引）时为 None，绝不伪造（不变量 #21 同族）。
    #: store 层不认识项目，只提供这个带类型的落点；值由 `SessionService.list_sessions`
    #: 从 `WorkspaceIndex` 回填（AC1 要求三处契约同时有该字段，这是其中之一）。
    workspace: WorkspaceRef | None = None
    #: #171：会话是否已归档（列表可见性，不是删除）。与 `workspace` 同款分工——store
    #: 读的是 JSONL，归档标记在 DB（`session_meta.archived`），值由
    #: `SessionService.list_sessions` 回填。**`session_meta` 无该会话行 = 未归档**
    #: （行由 lineage/fork 懒补，不是 1:1 恒成立），所以这里的默认值与"无行"同义，
    #: 不会撒谎；真值只能由服务层的联接给出（AC3）。
    archived: bool = False


class JsonlSessionStore:
    """JSONL append-only 事件存储。

    文件布局：``<root>/<session_id>/events.jsonl``
    每行一条 JSON 事件，整行写入后立即 flush（崩溃安全：半行 = 没发生）。
    """

    def __init__(self, root: str | Path = ".agent/sessions") -> None:
        self._root = Path(root)
        # ── seq 守卫的进程内状态（BUG-011）──
        # 每会话一把锁：把「读已落盘最大 seq → 写」串成临界区。写者跨线程
        # （事件循环的 Session.append + 恢复扫描下放的工作线程），故用
        # threading.Lock，不能用 asyncio.Lock。
        self._seq_locks: dict[str, threading.Lock] = {}
        # 每会话「已落盘最大 seq」缓存 + 观测到的文件戳（size, mtime_ns）。
        # 缓存只用于省掉每次 append 的 O(n) 全量读；戳变化 = 文件被本实例之外
        # 的写者动过（另一 store 实例 / 另一进程，CLI 与 server 共用同一 sessions
        # 目录）→ 重新以磁盘为准。缓存与锁表的结构由 _state_guard 保护。
        #
        # 边界（不得夸大为「跨进程安全」）：本层没有文件锁，跨进程**同时**追加仍可能
        # 各自通过检查（检查与写入之间的窗口跨进程不互斥）。戳只能察觉「已经落盘」的
        # 外部追加。同一进程内（真实缺陷 BUG-011 的现场：一个 server 的两个并发请求）
        # 由 _lock_for + 本检查共同保证严格单调。
        self._last_seq: dict[str, tuple[int, int, int]] = {}
        self._state_guard = threading.Lock()

    def _session_dir(self, session_id: str) -> Path:
        return self._root / session_id

    def _events_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "events.jsonl"

    def _lock_for(self, session_id: str) -> threading.Lock:
        """取得该会话的写锁（懒创建；表结构由 _state_guard 保护）。

        这把锁是**守卫原子性的一部分**，不是可有可无的优化：`append_event` 的
        「读已落盘最大 seq → 判定 → 写」若不在同一临界区内，两个线程可能都读到同一
        last_seq、都通过判定、都落盘 → 重复 seq。写者跨线程（事件循环的
        `Session.append` + 恢复扫描下放的工作线程），故是 threading.Lock。
        """
        with self._state_guard:
            lock = self._seq_locks.get(session_id)
            if lock is None:
                lock = self._seq_locks[session_id] = threading.Lock()
            return lock

    def _last_seq_on_disk(self, session_id: str) -> int:
        """已落盘最大 seq（无文件 = -1）。带文件戳校验的缓存，必须在会话写锁内调用。

        戳变化即回读磁盘，因此外部（另一实例 / 另一进程）**已经落盘**的追加一定会被
        看见；它不能防的是跨进程**同时**写入（无文件锁），见 ``__init__`` 的边界说明。
        """
        path = self._events_path(session_id)
        try:
            stat = path.stat()
        except OSError:
            return -1
        stamp = (stat.st_size, stat.st_mtime_ns)
        with self._state_guard:
            cached = self._last_seq.get(session_id)
        if cached is not None and cached[1:] == stamp:
            return cached[0]
        last = max((e.seq for e in self.read_events(session_id)), default=-1)
        with self._state_guard:
            self._last_seq[session_id] = (last, *stamp)
        return last

    def append_event(self, session_id: str, event: SessionEvent) -> None:
        """向 Session 的 JSONL 追加一条事件（整行 + flush + fsync）。

        fsync 是断电不丢的底线（用户拍板的耐久性决策）：flush 只把进程缓冲
        推到 OS page cache，断电即失；fsync 才真正落盘。代价是每次 append
        一次磁盘同步——事件流是恢复的唯一真相源，宁慢不丢。

        seq 守卫（BUG-011）：seq ≤ 已落盘最大 seq 是**拒写**而不是写入。
        否则并发取号会留下重复 seq，使该会话此后任何构造聚合的路径
        （``Session.load`` / ``resume``）永久失败。
        """
        path = self._events_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._lock_for(session_id):
            last = self._last_seq_on_disk(session_id)
            if event.seq <= last:
                raise SeqConflict(
                    f"Session '{session_id}' 事件 seq 冲突: seq={event.seq} 已被占用"
                    f"（已落盘最大 seq={last}）——并发写入或日志已损坏，拒绝落盘"
                )
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            stat = path.stat()
            with self._state_guard:
                self._last_seq[session_id] = (
                    event.seq, stat.st_size, stat.st_mtime_ns,
                )

    @staticmethod
    def _parse_event_line(raw_line: str, path_name: str, lineno: int) -> SessionEvent | None:
        """单行解析（容错语义的单一 owner，read_events / summary 共用）。

        容错范围：JSON 语法损坏（半行）、合法 JSON 但非事件字典、非法 UTF-8、
        seq 缺失或类型非法——一行坏数据只损失该行，不得 brick 恢复。
        """
        stripped = raw_line.strip()
        if not stripped:
            return None
        try:
            parsed: Any = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning("跳过损坏行 %s:%d（半行或写入中断）", path_name, lineno)
            return None
        if not isinstance(parsed, dict):
            logger.warning("跳过损坏行 %s:%d（合法 JSON 但非事件字典）", path_name, lineno)
            return None
        seq = parsed.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            logger.warning("跳过损坏行 %s:%d（seq 缺失、类型非法或为负）", path_name, lineno)
            return None
        try:
            return SessionEvent.from_dict(parsed)
        except Exception:  # 单行损坏只损失该行（容错兜底）
            logger.warning(
                "跳过损坏行 %s:%d（事件字段解析失败）", path_name, lineno, exc_info=True,
            )
            return None

    def read_events(self, session_id: str) -> list[SessionEvent]:
        """读取 Session 的全部有效事件，跳过无法解析的损坏行。

        容错范围见 _parse_event_line——一行坏数据只损失该行，不得 brick
        整个 session 的恢复。
        """
        path = self._events_path(session_id)
        if not path.exists():
            return []

        events: list[SessionEvent] = []
        # errors="replace"：非法 UTF-8 字节替换为 U+FFFD，让坏行走统一的跳过路径
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                event = self._parse_event_line(raw_line, path.name, lineno)
                if event is not None:
                    events.append(event)
        return events

    def read_session_summary(self, session_id: str) -> SessionSummaryStats | None:
        """列表页快路径：单趟流式扫描，只解析头部 + 末行。

        GET /api/sessions 曾对每个会话做全量 JSON 解析（30 会话 × 2000 事件
        ≈ 秒级串行阻塞），而列表页只需要：首条 user 消息（头部早退）、首末
        事件时间（首行 + 末行）、事件数（行计数）。本方法把解析量从 O(全部
        事件) 压到 O(头部上限 + 1)。

        精确性契约：扫描路径上发现任何损坏行 → 整体回退 read_events 全量
        解析（列表语义与全量严格一致，只是慢）。未扫描到的中段损坏行会让
        event_count 偏大——该情形只可能来自手工编辑/磁盘异常（正常崩溃损坏
        集中在末行，已覆盖），属显示级字段的已知取舍；resume 恢复仍走
        read_events 全量容错，不受影响。
        """
        path = self._events_path(session_id)
        if not path.exists():
            return None

        event_count = 0
        first_time: str | None = None
        first_user_message: str | None = None
        head_done = False
        head_parsed = 0
        # 末条非空行的 (lineno, stripped)：lineno 留给损坏告警——探针日志必须
        # 可定位，不用哨兵值伪造位置。只保留最后一条：末行损坏一律整体回退
        # （见下方守卫），所以不存在「改用前一行」的分支。
        last_line: tuple[int, str] | None = None

        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                event_count += 1
                last_line = (lineno, stripped)

                if not head_done:
                    event = self._parse_event_line(raw_line, path.name, lineno)
                    if event is None:
                        # 头部存在损坏行：中段完整性不可信 → 全量回退
                        return self._summary_fallback(session_id)
                    if first_time is None:
                        first_time = event.time
                    if (event.type == USER_MESSAGE
                            and isinstance(event.data.get("content"), str)
                            and event.data["content"].strip()):
                        first_user_message = event.data["content"].strip()[:128]
                        head_done = True
                    else:
                        head_parsed += 1
                        if head_parsed >= _SUMMARY_HEAD_PARSE_LIMIT:
                            head_done = True

        # 末行损坏（崩溃半写的常态位置）→ 全量回退，保证精确。
        # 只解析这一次：last_event_time 与 trace_id 同源于本事件，快路径与
        # _summary_fallback 的口径一致因此是**结构性**的，而非两份实现靠约定对齐。
        last_event = (
            self._parse_event_line(last_line[1], path.name, last_line[0])
            if last_line is not None else None
        )
        if last_line is not None and last_event is None:
            return self._summary_fallback(session_id)

        return SessionSummaryStats(
            session_id=session_id,
            event_count=event_count,
            first_event_time=first_time,
            last_event_time=last_event.time if last_event is not None else None,
            first_user_message=first_user_message,
            trace_id=self._terminal_trace_field(last_event, "trace_id"),
            trace_url=self._terminal_trace_field(last_event, "trace_url"),
        )

    @staticmethod
    def _terminal_trace_field(
        event: SessionEvent | None, key: Literal["trace_id", "trace_url"]
    ) -> str | None:
        """从 run 终结事件取 trace 关联字段（`trace_id` / `trace_url`）——取值规则唯一 owner。

        只认 run 终结事件：trace 关联是 **per-run** 事实（`run/completed|failed|
        interrupted` 的 data 里），会话可能有多次 run，末端那次才是列表页要展示的。
        非终结类型 / 缺键 / null / 空串 / 非字符串 → None（不把磁盘上被改坏的值塞进
        API 契约，也不伪造占位串，不变量 #21）。

        两个键（`trace_id` 机器可读 / `trace_url` 人类可点击，ADR-0018 D7 契约、
        互不替代）由本方法**同一套守卫**取——共用实现而非两份约定对齐，所以两者
        不会出现「一个有值一个漏填」的漂移。

        快路径与 `_summary_fallback` 各自把自己的末事件传进来，所以**这条规则**在两条
        路径上的一致性是结构性的。（`last_event_time` 仍是两条各自取值的路径，只由
        `test_fast_path_agrees_with_full_parse_on_clean_session` 断言相等。）

        已知边界（有意取舍）：末事件不是 run 终结事件即返回 None——包括
        「上一轮已 completed，但新轮的 user/message 或 run/started 成了末事件」。
        此时更早那个已完成的 trace 不回填。不向历史回溯是因为那需要逐行
        `json.loads` 直到 EOF，正好抵消 `read_session_summary` 的快路径（列表页
        从秒级全量解析压到几十 ms）。在途/新轮返回「未追踪」属诚实降级：那是
        尚无最终 trace 的 run。
        """
        if event is None or event.type not in RUN_TERMINAL_TYPES:
            return None
        value = event.data.get(key)
        return value if isinstance(value, str) and value else None

    def _summary_fallback(self, session_id: str) -> SessionSummaryStats | None:
        """扫描路径发现损坏 → 全量解析，产出与旧实现严格一致的摘要。"""
        events = self.read_events(session_id)
        if not events:
            return SessionSummaryStats(
                session_id=session_id,
                event_count=0, first_event_time=None,
                last_event_time=None, first_user_message=None,
            )
        first_user_message = next(
            (e.data.get("content") for e in events
             if e.type == USER_MESSAGE and isinstance(e.data.get("content"), str)
             and e.data["content"].strip()),
            None,
        )
        if first_user_message is not None:
            first_user_message = first_user_message.strip()[:128]
        return SessionSummaryStats(
            session_id=session_id,
            event_count=len(events),
            first_event_time=events[0].time,
            last_event_time=events[-1].time,
            first_user_message=first_user_message,
            # 与快路径同口径：只看最后一个事件（保证两条路径严格一致）。
            trace_id=self._terminal_trace_field(events[-1], "trace_id"),
            trace_url=self._terminal_trace_field(events[-1], "trace_url"),
        )

    def list_session_ids(self) -> list[str]:
        """列出 root 下所有有 events.jsonl 的 session_id，按最近修改倒序。

        Phase 9 / Web UI 用：GET /sessions 的基础。空 root 返回空列表。
        """
        if not self._root.exists():
            return []
        ids: list[tuple[str, float]] = []
        for entry in self._root.iterdir():
            if not entry.is_dir():
                continue
            events_path = entry / "events.jsonl"
            if not events_path.exists():
                continue
            try:
                mtime = events_path.stat().st_mtime
            except OSError:
                continue
            ids.append((entry.name, mtime))
        # 按修改时间倒序（最近在前）
        ids.sort(key=lambda x: x[1], reverse=True)
        return [sid for sid, _ in ids]

    def delete_session(self, session_id: str) -> bool:
        """删除该会话的事件日志目录（**唯一真相源**）。返回它是否曾经存在。

        硬删（ADR-0029）里"删掉会话"的实质就是这一句：`list_session_ids` 是按目录扫出来的，
        目录没了会话就从所有列表里消失。

        **安全边界**：只删 `<root>/<session_id>` 这一层——两个成分都是本 store 自己用
        root 与 session_id 拼的，且调用方必须先过 `validate_session_id`（拒绝分隔符）。
        本方法**不读任何外部映射**，因此不可能像 `WorkspaceRegistry.delete` 那样
        `rmtree` 到用户的真实目录（ADR-0029 D2）。

        幂等：目录不存在 → `False`，不抛错（重跑即自愈，ADR-0029 D3）。
        """
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return False
        shutil.rmtree(session_dir, ignore_errors=True)
        # 进程内 seq 缓存与锁表要一起清——否则同 id 再次出现时会带着旧的 last_seq。
        with self._state_guard:
            self._last_seq.pop(session_id, None)
            self._seq_locks.pop(session_id, None)
        return True

    def read_started_header(self, session_id: str) -> StartedHeader | None:
        """只读会话 header（WS-2 / #152 AC14）：第一条 `session/started` 即停。

        **不读事件正文**——workspace 首次引导只允许看 header（id / cwd / createdAt），
        所以这里流式读、命中即返回，正文多长都不碰。区别于 `read_session_summary`
        （那个要数到文件尾才知道事件数）。

        形状非法（没有 events.jsonl / 没有 session/started）→ None，不抛错：引导面对
        的是历史日志，一条坏数据不该拖垮整个启动（与 `read_events` 的容错同款）。
        """
        path = self._events_path(session_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for lineno, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                event = self._parse_event_line(raw_line, path.name, lineno)
                if event is None:
                    continue
                if event.type != SESSION_STARTED:
                    # header 正常就是第一条；遇到别的说明日志形状异常，不再往下翻
                    # （继续翻就等于读正文了）。
                    return None
                data = event.data or {}
                cwd = data.get("cwd")
                return StartedHeader(
                    session_id=session_id,
                    cwd=cwd if isinstance(cwd, str) and cwd else None,
                    created_at=event.time,
                    agent_id=event.agent_id,
                )
        return None
