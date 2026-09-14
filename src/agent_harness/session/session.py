"""Session：Agent 交互历史的领域聚合根。

持有 session_id 与已加载事件列表（内存缓存），对外提供：
    - start() / resume()  构造入口
    - append()            追加事件（分配 seq + 同步写 JSONL + 更新内存）
    - add_listener()      追加监听器（事件落盘后实时回调，ADR-0016 §2.1）
    - derive_messages()   从事件投影模型可见 messages
    - begin_run() / end_run()  标记 Run 边界

SessionStore 负责 IO（薄层），Session 负责业务状态（seq 分配、dangling 修复）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

from langchain_core.messages import AnyMessage

from agent_harness.sandbox.base import Sandbox

if TYPE_CHECKING:
    from pathlib import Path

    from agent_harness.sandbox.registry import WorkspaceRegistry

from agent_harness.session.cwd import cwd_event_data
from agent_harness.session.derive import (
    DANGLING_TOOL_CONTENT,
    derive_messages,
    detect_dangling,
)
from agent_harness.session.errors import SeqConflict, SessionNotFound
from agent_harness.session.event import (
    EVENT_TYPES,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    SESSION_RESUMED,
    SESSION_STARTED,
    STREAM_ONLY_TYPES,
    TOOL_RESULT,
    USER_MESSAGE,
    SessionEvent,
)
from agent_harness.session.store import JsonlSessionStore

logger = logging.getLogger("agent_harness.session")


def validate_event_seq(session_id: str, events: list[SessionEvent]) -> None:
    """校验 seq 严格递增（不容忍重复或回退）——该校验规则的唯一 owner。

    ``Session.load``（加载即校验）与 ``service.change_model``（已自行读过快照，
    不再重复读盘）共用同一判据。

    违反 → ``SeqConflict``，**不是** ``SessionNotFound``：日志确实存在、只是损坏。
    见 BUG-011——旧实现抛裸 ``ValueError``，被 ``service`` 一刀切翻成 404
    「会话不存在」，于是真机会话 ``dd983104`` 的日志损坏（两条 seq=5）显示成
    ``续聊失败：Send failed: 404``。
    """
    seen_seqs: set[int] = set()
    prev_seq = -1
    for event in events:
        if event.seq in seen_seqs:
            raise SeqConflict(f"Session '{session_id}' 事件 seq 重复: {event.seq}")
        if event.seq <= prev_seq:
            raise SeqConflict(
                f"Session '{session_id}' 事件 seq 回退: {event.seq}（前一条: {prev_seq}）"
            )
        seen_seqs.add(event.seq)
        prev_seq = event.seq


class Session:
    """Agent 会话聚合根——Runtime 与外部世界的单一交互入口。"""

    def __init__(
        self,
        session_id: str,
        store: JsonlSessionStore,
        events: list[SessionEvent] | None = None,
        sandbox: Sandbox | None = None,
    ) -> None:
        self.session_id = session_id
        self._store = store
        self._events: list[SessionEvent] = events if events is not None else []
        # 增量 seq 计数器：构造时一次性从已加载事件重算（max+1），append 时 O(1) 分配，
        # 避免每次 append 对全量事件做 O(n) max 扫描（长会话累计 O(n²)）
        self._next_seq: int = max((e.seq for e in self._events), default=-1) + 1
        self._sandbox: Sandbox | None = sandbox
        # 追加监听器（ADR-0016 §2.1）：事件持久化后同步回调——web 层据此实时
        # 广播 durable 事实（含工具执行期间追加的 output_delta）。回调异常被
        # 吞掉（落日志）：listener 是观察者，绝不能破坏 append 的持久化契约。
        self._listeners: list[Callable[[SessionEvent], None]] = []

    @property
    def sandbox(self) -> Sandbox | None:
        """与 Session 绑定的 Sandbox（通过 WorkspaceRegistry 管理）。不传 registry 时为 None。"""
        return self._sandbox

    @property
    def events(self) -> list[SessionEvent]:
        """已加载的事件列表（内存缓存，只读视图）。"""
        return list(self._events)

    @property
    def next_seq(self) -> int:
        """下一条事件的 seq（增量计数器，构造时从已加载事件取 max+1，空列表从 0 开始）。"""
        return self._next_seq

    def mark(self) -> int:
        """当前追加位置的句柄——配合 since() 取"之后追加的事件"。

        调用方不需要知道 events 的内部表示（列表/游标/页）；这是
        Session 拥有的追加语义，替代调用方自己做 len(events) 算术。
        """
        return len(self._events)

    def since(self, marker: int) -> list[SessionEvent]:
        """返回 mark() 之后追加的事件（副本，不影响内部状态）。"""
        return list(self._events[marker:])

    # ── 追加监听器（ADR-0016 §2.1）──

    def add_listener(self, callback: Callable[[SessionEvent], None]) -> None:
        """注册追加监听器：此后每条事件持久化成功后同步回调（任意线程上下文）。"""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[SessionEvent], None]) -> None:
        """注销监听器；未注册时静默（幂等）。"""
        with suppress(ValueError):
            self._listeners.remove(callback)

    # ── 构造入口 ──

    @classmethod
    def start(
        cls,
        store: JsonlSessionStore,
        *,
        agent_id: str = "default",
        session_id: str | None = None,
        workspace_registry: WorkspaceRegistry | None = None,
        started_data: dict | None = None,
        cwd: str | Path | None = None,
    ) -> Session:
        """新建 Session：生成 id、创建 JSONL、append session/started。

        提供 workspace_registry 时，自动创建/绑定 Sandbox 实例到 session.sandbox。
        session_id 允许调用方预生成（web 层"先组装 runtime 后建 Session"的顺序
        需要：_build_runtime 要以 session_id 装配 S3 artifact 命名空间，组装失败
        时不能留下任何已落盘的孤儿 session——R6-6）。
        started_data（T7 #137，加法字段）：会话级初始配置写进 session/started——
        目前用于记录创建时选定的模型（provider / model_id），使"当前模型"可从
        事件流派生。
        cwd（WS-1 #151，加法字段）：会话侧工作目录锚，**由创建者赋予**（不由
        WorkspaceRegistry 反向灌给会话）。经 `canonical_workspace_path` 规范化后
        写进 session/started，此后不可变；None = 不写该字段（历史遗留语义）。
        `started_data` 里若夹带 `cwd` 键会被丢弃并记一条 warning——写侧只认本参数，
        否则那条路径会绕过 AC5 的"唯一一套规范化"。
        """
        session_id = session_id or str(uuid4())
        sandbox = None
        if workspace_registry is not None:
            sandbox = workspace_registry.create(session_id)
        session = cls(session_id, store, sandbox=sandbox)
        data = dict(started_data) if started_data else {}
        # cwd 只认显式参数：started_data 里夹带的同名键会**绕过**唯一一套规范化
        # （AC5），静默写出一个未规范化/相对的 cwd。删掉它，再按参数写入。
        if "cwd" in data:
            logger.warning(
                "Session.start 忽略了 started_data['cwd']=%r：cwd 只由 cwd 参数"
                "赋予（WS-1 #151），否则会绕过规范化",
                data["cwd"],
            )
        data.pop("cwd", None)
        data.update(cwd_event_data(cwd))
        session.append(SESSION_STARTED, data, agent_id=agent_id)
        return session

    @classmethod
    def append_event(
        cls,
        store: JsonlSessionStore,
        session_id: str,
        event_type: str,
        data: dict,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
        step_id: int | None = None,
    ) -> SessionEvent:
        """只追加一条会话事实事件，**不触发 resume 副作用**。

        ``resume()`` 会修复 dangling tool_call 并 append ``session/resumed``——
        那是「恢复会话」的语义。写一条无关事实（排队消息 / 模型切换 / 取消排队 /
        中断标记）时套用它，会把 run 在途的 tool_call 判成悬空并注入合成
        tool/result，破坏 tool_call/result 配对（不变量 #7）。本入口只做
        「加载 + 追加」；run_id / agent_id / step_id 透传事件信封（T8 #138 的
        ``run/interrupted`` 要挂到被中断的 run 上）。

        加载后同样校验 seq（BUG-011）：损坏日志在这里也要报 ``SeqConflict``，不能
        一边说日志已坏、一边继续往上追加（排队消息 / 中断标记等旁路写者）。
        """
        events = store.read_events(session_id)
        if not events:
            raise SessionNotFound(f"Session '{session_id}' 不存在或事件日志为空")
        validate_event_seq(session_id, events)
        session = cls(session_id, store, events)
        return session.append(
            event_type, dict(data),
            run_id=run_id, agent_id=agent_id, step_id=step_id,
        )

    @classmethod
    def load(
        cls,
        store: JsonlSessionStore,
        session_id: str,
        *,
        workspace_registry: WorkspaceRegistry | None = None,
    ) -> Session:
        """加载并校验 seq 的**无副作用**入口：不修复 dangling、不写 session/resumed。

        用于「恢复语义已由上游完成」的场景——崩溃路径先经 RecoveryCoordinator
        按 Ledger 精确回填（不变量 #13/#14），再 load 出 Session 继续跑，
        避免与恢复标记重复再写一条 `session/resumed`。
        """
        events = store.read_events(session_id)
        if not events:
            raise SessionNotFound(f"Session '{session_id}' 不存在或事件日志为空")

        sandbox = (
            workspace_registry.get(session_id)
            if workspace_registry is not None
            else None
        )
        validate_event_seq(session_id, events)
        return cls(session_id, store, events, sandbox=sandbox)

    @classmethod
    def resume(
        cls,
        store: JsonlSessionStore,
        session_id: str,
        *,
        workspace_registry: WorkspaceRegistry | None = None,
    ) -> Session:
        """加载已有 Session：校验 seq、修复 dangling、append session/resumed。

        提供 workspace_registry 时，自动查回/恢复 Sandbox 实例到 session.sandbox。
        """
        session = cls.load(store, session_id, workspace_registry=workspace_registry)

        # 修复 dangling tool_call：为每个未解决的 tool_call 追加合成 tool/result
        dangling_ids = detect_dangling(session._events)
        for tc_id in dangling_ids:
            logger.warning(
                "Resume 修复 dangling tool_call_id=%s，追加合成 tool/result", tc_id
            )
            session.append(
                TOOL_RESULT,
                {"tool_call_id": tc_id, "content": DANGLING_TOOL_CONTENT},
                source_event_ids=[tc_id],
                _mark_dangling=True,
            )

        session.append(SESSION_RESUMED, {})
        return session

    # ── 核心操作 ──

    def append(
        self,
        event_type: str,
        data: dict,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
        step_id: int | None = None,
        block_id: str | None = None,
        source_event_ids: list[str] | None = None,
        _mark_dangling: bool = False,
    ) -> SessionEvent:
        """追加一条事件：分配 seq、同步写 JSONL、更新内存。

        _mark_dangling 仅内部使用——在 data 中写入 dangling=true 标记。
        block_id 是流式块标识（ADR-0016 §3.2，reasoning 块等），透传给 SessionEvent。
        事件类型必须在 EVENT_TYPES 词汇表内；STREAM_ONLY_TYPES（流式专属信号）
        拒绝持久化（invariant #4：Event ≠ Diagnostic Log）。
        """
        # 词汇表校验：先拒绝再写盘，杜绝未知/流式事件悄悄污染 durable log
        if event_type in STREAM_ONLY_TYPES:
            raise ValueError(
                f"流式专属事件 '{event_type}' 不得通过 Session.append 持久化"
                "（仅作为 run_stream() 的 AgentEvent 输出）"
            )
        if event_type not in EVENT_TYPES:
            raise ValueError(f"未知事件类型 '{event_type}'：不在 EVENT_TYPES 词汇表中")
        seq = self._next_seq
        event = SessionEvent(
            seq=seq,
            type=event_type,
            session_id=self.session_id,
            run_id=run_id,
            agent_id=agent_id,
            step_id=step_id,
            block_id=block_id,
            data={**data, "dangling": True} if _mark_dangling else data,
            source_event_ids=source_event_ids,
        )
        self._store.append_event(self.session_id, event)
        self._events.append(event)
        # 写盘成功后才推进计数器——失败不消耗 seq
        self._next_seq += 1
        # 监听器在持久化成功后回调（观察者，异常不破坏 append 契约）
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                logger.exception(
                    "session listener 回调失败（session=%s, event=%s）",
                    self.session_id, event.type,
                )
        return event

    def adopt_history(self, events: list[SessionEvent]) -> list[SessionEvent]:
        """移植既有事件（fork seed 的唯一 owner，ADR-0017 决策 3）。

        重编 seq（本聚合按序分配，child 局部单调），逐字保留原 event_id /
        time / type / data / run_id / agent_id / step_id / source_event_ids，
        session_id 改写为本会话。类型必须在 EVENT_TYPES 词表内（流式专属拒绝）。
        """
        adopted: list[SessionEvent] = []
        for event in events:
            if event.type in STREAM_ONLY_TYPES:
                raise ValueError(
                    f"流式专属事件 '{event.type}' 不得移植进 durable log（invariant #4）"
                )
            if event.type not in EVENT_TYPES:
                raise ValueError(f"未知事件类型 '{event.type}'：不在 EVENT_TYPES 词汇表中")
            moved = replace(event, seq=self._next_seq, session_id=self.session_id)
            self._store.append_event(self.session_id, moved)
            self._events.append(moved)
            self._next_seq += 1
            adopted.append(moved)
        return adopted

    def derive_messages(self) -> list[AnyMessage]:
        """从已加载事件投影出模型可见 messages（委托纯函数）。"""
        return derive_messages(self._events)

    # ── step_id 基数（前端 turn 定位键的服务端镜像）──

    @property
    def max_step_id(self) -> int:
        """已出现过的最大 step_id（无则 0）。

        事件信封的 step_id 是前端 turn 定位键（`projection.resolveStep` →
        `withTurnAt`），必须 session 级单调；续聊 run 以它为步号基数接续，
        否则第二轮 run 再从 1 编号会与首轮冲突（前端把第二轮模型输出折叠进
        首轮 turn）。计算与消费见 `AgentRuntime._drive` 的 `step_base`。
        """
        return max(
            (e.step_id for e in self._events if e.step_id is not None), default=0,
        )

    @property
    def user_turn_count(self) -> int:
        """真实用户发言轮数 = 前端已为「用户消息」开出的 turn 数。

        runtime 注入的纠正消息（`data.injected_by`，同错熔断软触发）不算：
        它带 step_id 落在当前轮内，不新开 turn。
        """
        return sum(
            1 for e in self._events
            if e.type == USER_MESSAGE and not e.data.get("injected_by")
        )

    # ── Run 生命周期 ──

    def begin_run(self, *, agent_id: str = "default") -> tuple[str, int]:
        """生成 run_id、append run/started、返回 ``(run_id, turn_index)``。

        ``turn_index`` = 该 session 里第几个 run（1-based），供 Langfuse
        trace metadata 标记「这是第 N 轮」（T9 #139）。
        """
        run_id = str(uuid4())
        turn_index = sum(1 for e in self._events if e.type == RUN_STARTED) + 1
        self.append(RUN_STARTED, {"turn_index": turn_index},
                    run_id=run_id, agent_id=agent_id)
        return run_id, turn_index

    def end_run(
        self,
        run_id: str,
        *,
        status: str,
        final_text: str = "",
        usage_total: dict | None = None,
        cost_usd: float | None = None,
        trace_id: str | None = None,
        trace_url: str | None = None,
        reason: str | None = None,
        message: str | None = None,
    ) -> SessionEvent:
        """append run/completed 或 run/failed，返回该事件（Phase 9 让流式层镜像它）。

        usage_total / cost_usd / trace_id / trace_url 是前端 Gap 1/2 契约 +
        trace_url 契约（BACKEND_GAP_PROMPT.md / BACKEND_PROMPT_TRACE_URL.md）：
        只扩展 data，不改既有语义；None 表示"未追踪"，前端据此降级显示
        （trace_url=null → 渲染纯 mono code 的 trace_id），不伪造占位字符串。
        trace_id 与 trace_url 并列保留（前者机器可读，后者人类可点击，不互替）。
        对称终态：completed 与 failed 都下发 trace_id / trace_url——失败 run 在
        Langfuse 也有可见 trace，跳转有排查价值。reason 仅 failed 语义使用
        （如 identical_tool_failure_loop），落事件 data——消费者可区分失败原因
        （取消路径的 reason=cancelled 同款先例）。message 同仅 failed：已分类
        故障的固定可读文案（如内容审查拒绝），与上下文超限路径直接 append 的
        reason+message 形状一致；只接受调用方常量，绝不透传 provider 回显原文。
        """
        event_type = RUN_COMPLETED if status == "completed" else RUN_FAILED
        data: dict = {"final_text": final_text} if final_text else {}
        if usage_total:
            data["usage_total"] = usage_total
        if status == "completed":
            data["cost_usd"] = cost_usd
        data["trace_id"] = trace_id
        data["trace_url"] = trace_url
        if status != "completed" and reason:
            data["reason"] = reason
        if status != "completed" and message:
            data["message"] = message
        return self.append(
            event_type,
            data,
            run_id=run_id,
        )
