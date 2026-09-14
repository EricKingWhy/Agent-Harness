"""工具输出流通道（ADR-0016 §4.2）：执行期 stdout/stderr 增量 → durable tool/output_delta。

数据流：sandbox reader 线程（任意线程）→ ToolOutputStream.push（thread-safe，
call_soon_threadsafe 入 asyncio.Queue）→ executor 启动的 drain task（事件循环内）
→ 合帧（相邻同 channel 合并 + 帧尺寸切分）→ Session.append（TOOL_OUTPUT_DELTA）。

上限（不变量 #15 旁路防护）：每 channel 每 tool_call 最多 TOOL_OUTPUT_MAX_CHANNEL_CHARS
字符的增量——超出丢弃；tool/result 的截断/artifact 语义仍是完整真相，绝不因流式
通道把 2M 级输出灌进 durable log。

sink 经 contextvar（tool_output_sink_var）向工具开放：Tool.execute 签名零改动，
自愿接入的工具（BashTool 首发）读取并转发给 sandbox.on_output；asyncio.to_thread
复制 context，工作线程内可读。非流式工具不读 var → 零 delta。
"""

from __future__ import annotations

import asyncio
import contextvars

from agent_harness.session import TOOL_OUTPUT_DELTA, Session, SessionEvent

#: 每 channel 每 tool_call 的增量总量上限（字符）。
TOOL_OUTPUT_MAX_CHANNEL_CHARS = 65_536
#: 单帧尺寸上限（字符）：drain 合帧后按此切分，限制单事件体积。
TOOL_OUTPUT_MAX_FRAME_CHARS = 8_192
#: 合帧窗口（秒）：与 runtime 文本/思考合帧同一量级（02 §9.1）。
TOOL_OUTPUT_FLUSH_WINDOW_SECONDS = 0.030

#: 执行期 sink（executor 设置、工具读取；None = 本工具不流式）。
tool_output_sink_var: contextvars.ContextVar[ToolOutputStream | None] = (
    contextvars.ContextVar("tool_output_sink", default=None)
)

_CHANNELS = frozenset({"stdout", "stderr"})


class ToolOutputStream:
    """一次 tool_call 执行期的输出增量收集器（线程安全入队 + loop 侧合帧落盘）。"""

    def __init__(
        self,
        session: Session,
        *,
        tool_call_id: str,
        run_id: str | None,
        step_id: int | None,
        window: float | None = None,
        max_frame_chars: int = TOOL_OUTPUT_MAX_FRAME_CHARS,
        max_channel_chars: int = TOOL_OUTPUT_MAX_CHANNEL_CHARS,
    ) -> None:
        self._session = session
        self._tool_call_id = tool_call_id
        self._run_id = run_id
        self._step_id = step_id
        self._window = (TOOL_OUTPUT_FLUSH_WINDOW_SECONDS
                        if window is None else window)
        self._max_frame_chars = max_frame_chars
        self._max_channel_chars = max_channel_chars
        self._aq: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()
        self._loop = asyncio.get_running_loop()
        self._channel_counts = {"stdout": 0, "stderr": 0}
        self._closed = False

    # ── 生产侧（任意线程；sandbox reader 线程回调）──

    def push(self, channel: str, text: str) -> None:
        """收一段输出；channel 总量超限后丢弃（loop 已死/已关闭时静默）。"""
        if self._closed or not text or channel not in _CHANNELS:
            return
        remaining = self._max_channel_chars - self._channel_counts[channel]
        if remaining <= 0:
            return
        if len(text) > remaining:
            text = text[:remaining]
        self._channel_counts[channel] += len(text)
        try:
            self._loop.call_soon_threadsafe(self._aq.put_nowait, (channel, text))
        except RuntimeError:
            pass  # 事件循环已关闭（进程收尾竞态）：增量丢弃，result 仍兜底

    def close(self) -> None:
        """关闭入队口（幂等）：drain 收到 sentinel 后做最终 flush 并退出。"""
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.call_soon_threadsafe(self._aq.put_nowait, None)
        except RuntimeError:
            pass

    # ── 消费侧（事件循环内；executor 以 task 运行）──

    async def drain(self) -> list[SessionEvent]:
        """排空队列并合帧落盘，直到 close sentinel。返回已 append 的事件（镜像用）。"""
        events: list[SessionEvent] = []
        pending: list[tuple[str, str]] = []
        while True:
            try:
                if pending:
                    item = await asyncio.wait_for(
                        self._aq.get(), timeout=self._window,
                    )
                else:
                    item = await self._aq.get()
            except TimeoutError:
                events.extend(self._flush(pending))
                continue
            if item is None:
                events.extend(self._flush(pending))
                return events
            pending.append(item)
            if sum(len(text) for _, text in pending) >= self._max_frame_chars:
                events.extend(self._flush(pending))

    def _flush(self, pending: list[tuple[str, str]]) -> list[SessionEvent]:
        """相邻同 channel 合并 → 按帧上限切分 → append durable 事件。"""
        if not pending:
            return []
        merged: list[list[str]] = []
        for channel, text in pending:
            if merged and merged[-1][0] == channel:
                merged[-1][1] += text
            else:
                merged.append([channel, text])
        pending.clear()
        events: list[SessionEvent] = []
        for channel, text in merged:
            for start in range(0, len(text), self._max_frame_chars):
                events.append(self._session.append(
                    TOOL_OUTPUT_DELTA,
                    {
                        "tool_call_id": self._tool_call_id,
                        "channel": channel,
                        "delta": text[start:start + self._max_frame_chars],
                    },
                    run_id=self._run_id, step_id=self._step_id,
                ))
        return events
