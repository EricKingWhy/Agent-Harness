"""RunManager：detached-run 生命周期托管（ADR-0016 §2.1，D-A 核心）。

run 与 HTTP 请求生命周期解耦：`POST /api/sessions` 经 launch() 把
`runtime.run_stream` 驱动为独立 asyncio.Task，SSE 响应只是该 run 的一个
订阅者——断连（generator 被取消）只做 unsubscribe，绝不杀 run。

事件流合并（幂等，不变量 #22 友好）：
- durable 事实的唯一来源是 Session.append → session listener 实时捕获
  （含工具执行期间追加的 tool/output_delta）；
- run_stream 的镜像 yield 经 seq 去重合并（listener 先入队 seq=N，镜像
  到达时 seq ≤ 已入队最大 seq → 跳过）；stream-only 信号（model/started）
  无 seq，总是入队；
- 订阅者队列有界（SUBSCRIBER_QUEUE_MAX）：满时丢最旧（客户端据 seq gap
  断线重连，after_seq 重放自愈，规格 02 §16.3）。

孤儿回收：最后一个订阅者离开后启动宽限计时（Settings.run_disconnect_grace_seconds），
到期仍零订阅者 → 取消 run task（取消臂收尾 run/failed(reason=orphaned)）；
新订阅者接入即撤销计时。显式 POST /cancel 与孤儿回收是仅有的两个外部终止路径。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field

from agent_harness.agent import AgentEvent, AgentRuntime
from agent_harness.memory.types import memory_session_var
from agent_harness.session import Session

logger = logging.getLogger("agent_harness.web.runmanager")

#: 订阅者队列上限（帧）：满时丢最旧（seq gap → 客户端重连自愈）。
SUBSCRIBER_QUEUE_MAX = 2000

_DONE = object()  # run 终结 sentinel（入队后订阅者迭代结束）


@dataclass
class Subscriber:
    """一个 SSE 连接对应一个订阅者：有界队列 + 断连移除。"""

    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX))


class ManagedRun:
    """一个在途 run 的托管状态：task + 订阅者集 + 幂等合并游标。"""

    def __init__(self, session: Session, manager: RunManager) -> None:
        self.session = session
        self._manager = manager
        self.task: asyncio.Task | None = None
        self.subscribers: dict[int, Subscriber] = {}
        self._next_subscriber_id = 0
        self._last_enqueued_seq = -1
        self.terminal = False
        self.reap_requested = False
        self._orphan_handle: asyncio.TimerHandle | None = None

    DONE = _DONE  # 订阅者侧哨兵引用

    # ── 订阅 ──

    def subscribe(self) -> Subscriber:
        """新订阅者接入：撤销孤儿计时。"""
        sub = Subscriber()
        self._next_subscriber_id += 1
        self.subscribers[self._next_subscriber_id] = sub
        self._cancel_orphan_timer()
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        """订阅者离开（断连/正常收尾）：移除；孤儿化则启动宽限计时。"""
        for key, value in list(self.subscribers.items()):
            if value is sub:
                self.subscribers.pop(key, None)
        if not self.subscribers and not self.terminal:
            self._arm_orphan_timer()

    # ── 入队（run task 上下文）──

    def enqueue_agent_event(self, event: AgentEvent) -> None:
        """合并入队：durable 按 seq 幂等（listener 先入、镜像跳过），流式总入队。"""
        if event.seq is not None:
            if event.seq <= self._last_enqueued_seq:
                return
            self._last_enqueued_seq = event.seq
        self._fanout(event)

    def enqueue_session_event(self, event) -> None:
        """listener 通道：SessionEvent → AgentEvent 镜像后合并入队。"""
        from agent_harness.agent.types import to_agent_event

        if event.seq <= self._last_enqueued_seq:
            return
        self._last_enqueued_seq = event.seq
        self._fanout(to_agent_event(event))

    def finish(self) -> None:
        """run task 终结：标记终态、撤销孤儿计时、广播哨兵。

        哨兵必达：满队列丢最旧腾位（review 修复——满队列吞哨兵会让该
        订阅者的 SSE 流永不收尾，直到客户端自行断开）。"""
        self.terminal = True
        self._cancel_orphan_timer()
        for sub in list(self.subscribers.values()):
            try:
                sub.queue.put_nowait(_DONE)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    sub.queue.put_nowait(_DONE)

    @property
    def last_enqueued_seq(self) -> int:
        """已入队的最大 durable seq（重连续传的一致性游标，ADR-0016 §2.3）。

        订阅者注册【后】读取：append 落盘先于 listener 入队，seq ≤ 本值的
        durable 事件此刻必然已在磁盘上——重放读盘 + 队列跳过 seq ≤ 本值，
        与 live 流无缝拼合、零重复。"""
        return self._last_enqueued_seq

    # ── 内部 ──

    def _fanout(self, event: AgentEvent) -> None:
        # 队列携带 AgentEvent（领域对象）；SSE 帧渲染由端点侧生成器做——
        # runmanager 不反向依赖 web.app（避免循环导入）。
        for sub in list(self.subscribers.values()):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # 慢订阅者：丢最旧保最新——seq gap 让客户端走重连自愈
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    sub.queue.put_nowait(event)

    def _arm_orphan_timer(self) -> None:
        grace = self._manager.disconnect_grace_seconds
        if grace <= 0:
            return
        loop = asyncio.get_running_loop()
        self._orphan_handle = loop.call_later(
            grace, self._reap_if_orphaned,
        )

    def _cancel_orphan_timer(self) -> None:
        if self._orphan_handle is not None:
            self._orphan_handle.cancel()
            self._orphan_handle = None

    def _reap_if_orphaned(self) -> None:
        if self.subscribers or self.terminal or self.task is None:
            return
        logger.warning(
            "run 孤儿回收（session=%s，零订阅者超过 %.0fs）",
            self.session.session_id, self._manager.disconnect_grace_seconds,
        )
        # 先置位再取消：cancel_reason_supplier 在取消臂收尾时读取（02 §17：
        # 孤儿回收 ≠ 用户取消，reason=orphaned 落 run/failed data）。
        self.reap_requested = True
        self.task.cancel()

    def _on_session_event(self, event) -> None:
        """session listener：任何线程上下文都安全（put_nowait）。"""
        self.enqueue_session_event(event)
        # 终态事实落盘即视为非在途（02 §17）：checkpoint/memory 回写等收尾
        # await 还会跑一会儿——只等 task.done() 会让 cancel/重连在此窗口
        # 误判"仍在途"（store 已见 run/completed 而 cancel 返回 cancelling）。
        if event.type in ("run/completed", "run/failed") and not self.terminal:
            self.terminal = True
            self._cancel_orphan_timer()


class RunManager:
    """在途 run 注册表：launch / subscribe / cancel / 孤儿回收 / 关停。"""

    DONE = _DONE

    def __init__(self, disconnect_grace_seconds: float = 300.0) -> None:
        self.disconnect_grace_seconds = disconnect_grace_seconds
        self._runs: dict[str, ManagedRun] = {}

    def launch(
        self, session: Session, runtime: AgentRuntime, user_input: str,
    ) -> tuple[ManagedRun, Subscriber]:
        """启动 detached run 并返回（run, 首个订阅者）。

        task 先建、后启动订阅（launch 返回后由调用方订阅）——事件不会丢：
        run 的首批 yield 发生在首个 await 点之后，而订阅者队列在 task 首次
        被调度前就已挂上（同一事件循环内无插队窗口）。
        """
        run = ManagedRun(session, self)
        self._runs[session.session_id] = run
        run.task = asyncio.create_task(
            self._drive(run, runtime, user_input),
            name=f"agent-run-{session.session_id}",
        )
        subscriber = run.subscribe()
        return run, subscriber

    async def _drive(self, run: ManagedRun, runtime: AgentRuntime,
                     user_input: str) -> None:
        """run task 本体：驱动 run_stream，终结时广播哨兵。"""
        token = memory_session_var.set(run.session.session_id)
        run.session.add_listener(run._on_session_event)

        def cancel_reason() -> str:
            return "orphaned" if run.reap_requested else "cancelled"

        try:
            async for event in runtime.run_stream(
                run.session, user_input, cancel_reason_supplier=cancel_reason,
            ):
                run.enqueue_agent_event(event)
        finally:
            run.session.remove_listener(run._on_session_event)
            memory_session_var.reset(token)
            run.finish()

    def get_active(self, session_id: str) -> ManagedRun | None:
        """在途 run（未终态）；重连续传接 live 流用。

        task 已 done 但 terminal 旗标未及置位（finally 在途）的收尾窗口
        视为非在途——否则取消/重连会在终态落盘后误判"仍在途"（store 已见
        run/completed 而 cancel 返回 cancelling 的竞态）。"""
        run = self._runs.get(session_id)
        if run is None or run.terminal:
            return None
        if run.task is not None and run.task.done():
            return None
        return run

    def is_busy(self, session_id: str) -> bool:
        """这个会话此刻是否还有"活没干完"的 run——破坏性操作（如硬删，ADR-0029）的前置。

        **与 `get_active` 的区别是刻意的，不是笔误**：`get_active` 把"task 已 done /
        terminal 旗标未及置位（finally 在途）"的收尾窗口**视为非在途**——对取消/重连
        是对的（见它的 docstring），但对"能不能把这个会话的地面抽走"是错的：那个窗口
        正是 finalizer（Checkpoint 落盘 / 记忆回写）还在跑的时刻。

        所以本判据只问「run 存在且它的 task 未 done」：
        - 没有 run → 不忙；
        - task 已 done → 不忙（终态收尾已完成）；
        - task 未 done（含 terminal 已置位的收尾窗口）→ 忙；
        - task 尚未挂上（`launch` 与赋值之间）→ **保守视为忙**。
        """
        run = self._runs.get(session_id)
        if run is None:
            return False
        task = run.task
        return task is None or not task.done()

    def cancel(self, session_id: str) -> bool:
        """显式取消：有在途 run → task.cancel()（取消臂收尾）；否则 False。"""
        run = self.get_active(session_id)
        if run is None or run.task is None:
            return False
        run.task.cancel()
        return True

    async def aclose(self) -> None:
        """应用关停：取消全部在途 run 并等待收尾（幂等）。"""
        for run in list(self._runs.values()):
            if run.task is not None and not run.task.done():
                run.task.cancel()
        tasks = [run.task for run in self._runs.values()
                 if run.task is not None and not run.task.done()]
        for run in self._runs.values():
            run.finish()
        if tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
        self._runs.clear()
