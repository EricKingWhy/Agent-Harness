"""流式块记账（ADR-0016 §3.3/§3.4）：思考/文本 delta 合帧落盘 + reasoning 块生命周期。

职责（一次 run 一个实例，由 _drive 持有）：
- 思考（reasoning_content）与文本（content）分别缓冲，按窗口/尺寸/生命周期
  边界合帧成 durable 事件（S19：禁止 per-token 行；S20：绝不扣数据做打字机）；
- reasoning 块生命周期状态机（02 §8.1）：started → delta* → completed |
  interrupted；文本转场关块，post-tool 新思考段取新 block_id；
- 中断收口：取消/失败臂调用 interrupt()——残余缓冲先落盘（部分内容保留，
  S18/16.4），再补 reasoning/interrupted。

flush 无定时器：chunk 到达时惰性检查窗口到期（确定性、无竞态）。窗口常量
经模块属性读取（测试 monkeypatch 归零即可逐 offer flush）。

事件全部经 Session.append 持久化后由调用方镜像 yield；本类只 append 不 yield
（取消臂的生成器关闭上下文禁止产出）。
"""

from __future__ import annotations

import time

from agent_harness.session import (
    REASONING_COMPLETED,
    REASONING_DELTA,
    REASONING_INTERRUPTED,
    REASONING_STARTED,
    TEXT_DELTA,
    Session,
    SessionEvent,
)

#: 合帧窗口（秒）：02 §9.1 建议的 10-30ms 区间上限；实测 chunk 间隔普遍
#: 低于此值，窗口到期即补帧，感知延迟 ≤ 窗口 + 网络。
FLUSH_WINDOW_SECONDS = 0.030
#: 单帧尺寸上限（字符）：高频大块场景下窗口未到也先落盘，限制单事件体积。
FLUSH_MAX_CHARS = 4096


class BlockStreamer:
    """一次 run 的流式块记账：合帧落盘 + reasoning 块状态机。"""

    def __init__(
        self,
        session: Session,
        *,
        window: float | None = None,
        max_chars: int = FLUSH_MAX_CHARS,
        clock=time.monotonic,
    ) -> None:
        self._session = session
        self._window = FLUSH_WINDOW_SECONDS if window is None else window
        self._max_chars = max_chars
        self._clock = clock
        self._run_id: str | None = None
        # 思考块状态：None = 无 open 块
        self._rsn_block: str | None = None
        self._rsn_buf = ""
        self._rsn_since = 0.0
        self._block_counter = 0
        # 文本缓冲（block_id 恒 None：文本由既有 step/turn 语义聚合）
        self._text_buf = ""
        self._text_since = 0.0

    def begin_run(self, run_id: str) -> None:
        self._run_id = run_id

    # ── chunk 入口（_drive 流式循环逐 chunk 调用）──

    def offer_reasoning(self, text: str, *, step: int) -> list[SessionEvent]:
        """思考 chunk：无 open 块则开新块（reasoning/started），缓冲并按需 flush。"""
        events: list[SessionEvent] = []
        if self._rsn_block is None:
            self._block_counter += 1
            self._rsn_block = f"rsn-{step}-{self._block_counter}"
            events.append(self._session.append(
                REASONING_STARTED, {"source": "model"},
                run_id=self._run_id, step_id=step, block_id=self._rsn_block,
            ))
        if not self._rsn_buf:
            # 窗口锚点随缓冲重建（review 回归：只随开块设置会让首个窗口过期
            # 后的每次 offer 都"即时过期"，长块退化为逐 chunk 落盘，S19）
            self._rsn_since = self._clock()
        self._rsn_buf += text
        events.extend(self._flush_if_due(self._rsn_buf, self._rsn_since,
                                         self._flush_reasoning, step))
        return events

    def offer_text(self, text: str, *, step: int) -> list[SessionEvent]:
        """文本 chunk：思考块让位（completed 转场），缓冲并按需 flush。"""
        events: list[SessionEvent] = []
        if self._rsn_block is not None:
            events.extend(self._close_reasoning(step, interrupted=False))
        if not self._text_buf:
            self._text_since = self._clock()
        self._text_buf += text
        events.extend(self._flush_if_due(self._text_buf, self._text_since,
                                         self._flush_text, step))
        return events

    def end_step(self, *, step: int) -> list[SessionEvent]:
        """一次模型流结束：关思考块（completed）+ 落文本残余。"""
        events: list[SessionEvent] = []
        if self._rsn_block is not None:
            events.extend(self._close_reasoning(step, interrupted=False))
        events.extend(self._flush_text(step))
        return events

    def interrupt(self, *, step: int) -> list[SessionEvent]:
        """取消/失败臂收口：残余缓冲先落盘（部分内容保留）+ reasoning/interrupted。

        同步方法、禁止 yield 的上下文里调用（append 本身同步安全）。
        """
        events: list[SessionEvent] = []
        if self._rsn_block is not None:
            events.extend(self._close_reasoning(step, interrupted=True))
        events.extend(self._flush_text(step))
        return events

    # ── 内部 ──

    def _close_reasoning(self, step: int, *, interrupted: bool) -> list[SessionEvent]:
        """关思考块：先 flush 残余思考（部分内容落盘），再补终态事件。"""
        events = self._flush_reasoning(step)
        event_type = REASONING_INTERRUPTED if interrupted else REASONING_COMPLETED
        events.append(self._session.append(
            event_type, {},
            run_id=self._run_id, step_id=step, block_id=self._rsn_block,
        ))
        self._rsn_block = None
        return events

    def _flush_if_due(self, buf: str, since: float, flush, step: int) -> list[SessionEvent]:
        if buf and (self._clock() - since >= self._window or len(buf) >= self._max_chars):
            return flush(step)
        return []

    def _flush_reasoning(self, step: int) -> list[SessionEvent]:
        if not self._rsn_buf:
            return []
        event = self._session.append(
            REASONING_DELTA,
            {"delta": self._rsn_buf, "source": "model"},
            run_id=self._run_id, step_id=step, block_id=self._rsn_block,
        )
        self._rsn_buf = ""
        return [event]

    def _flush_text(self, step: int) -> list[SessionEvent]:
        if not self._text_buf:
            return []
        event = self._session.append(
            TEXT_DELTA, {"delta": self._text_buf},
            run_id=self._run_id, step_id=step,
        )
        self._text_buf = ""
        return [event]
