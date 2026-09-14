"""WebSocket 多路复用通道（T2 / #132，PRD §5.1）。

单连接多路复用所有 session 的 streaming / 推送：
- 客户端 ``subscribe(session_id)`` 后，服务端推该 session 的增量事件。
- 断线重连：客户端开新 WS + ``subscribe(session_id)``，服务端先推一份
  完整快照（session 当前事件投影 + 在途 run baseline），之后增量。
- 心跳：服务端每 ``WS_PING_INTERVAL`` 秒下行 ``{"type": "server_ping"}``，
  客户端须回 ``{"type": "pong"}``；``WS_PING_TIMEOUT`` 秒内未收到任何
  上行消息则判定对端已死并关闭连接（详见 ``_heartbeat_loop``）。

设计原则（不变量守护）：
- WS 不维护第二套 session 真相（#22）：所有事件来自 RunManager 订阅，
  它的源头是 append-only Session listener。
- WS 只是一个传输通道，不做业务决策——业务走 SessionService。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

from agent_harness.web.serialization import build_event_payload

if TYPE_CHECKING:
    from agent_harness.web.app import AppState
    from agent_harness.web.runmanager import RunManager

logger = logging.getLogger("agent_harness.web.websocket")

#: 服务端心跳间隔（秒）——每 N 秒下行一个应用层 ``server_ping``。
WS_PING_INTERVAL: float = 2.0
#: 客户端静默超时（秒）——超过该时长未收到任何上行消息则关闭连接。
WS_PING_TIMEOUT: float = 30.0


async def handle_websocket(websocket: WebSocket, state: AppState) -> None:
    """WebSocket 主入口：接受连接 → 多路复用 session 事件流。

    上行消息格式（JSON）：
      {"type": "subscribe", "session_id": "..."}
      {"type": "send_message", "session_id": "...", "content": "...", "mode": "queue"}
      {"type": "steer", "session_id": "...", "content": "..."}
      {"type": "cancel", "session_id": "..."}
      {"type": "ping"}  — client-initiated ping, server replies pong
      {"type": "pong"}  — reply to server_ping（心跳应答；任意上行都算活性）

    下行消息格式（JSON）：
      {"type": "snapshot", "session_id": "...", "events": [...]}
      {"type": "event", "session_id": "...", "event": {...}}
      {"type": "done", "session_id": "..."}
      {"type": "error", "message": "..."}
      {"type": "pong"}
      {"type": "server_ping"}  — 服务端心跳探测，客户端须回 {"type": "pong"}
    """
    await websocket.accept()

    # 每 WS 连接的订阅追踪：session_id → (ManagedRun, Subscriber)
    subscriptions: dict[str, tuple[Any, Any]] = {}
    # 读循环和写循环之间的事件桥
    outbound_queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

    run_manager: RunManager = state.run_manager

    # 死对端检测游标：任何上行消息都会刷新（PONG 是应用层帧，能到达
    # receive_text()——控制帧 PONG 不行，见 _heartbeat_loop 注释）。
    last_received: list[float] = [time.monotonic()]

    async def _send_json(payload: dict[str, Any]) -> None:
        """安全发送 JSON（连接关闭时静默忽略）。"""
        try:
            await websocket.send_text(json.dumps(payload, default=str))
        except Exception:
            logger.debug("WS send 失败（客户端可能已断开）", exc_info=True)

    async def _push_snapshot(session_id: str) -> None:
        """服务端权威快照：session 当前事件投影 + 在途 run baseline。

        客户端重连时先收到完整快照，之后增量事件无缝接上。
        """
        from agent_harness.session.service import InvalidSessionId, SessionService

        service = SessionService(state)
        try:
            events = await service.get_events(session_id)
        except InvalidSessionId as e:
            await _send_json({"type": "error", "message": str(e)})
            return
        except Exception:  # noqa: BLE001 — WS 错误兜底：任意服务异常都要回 error 帧
            await _send_json({"type": "error", "message": "snapshot failed"})
            return

        active_run = run_manager.get_active(session_id)
        subscriber = active_run.subscribe() if active_run is not None else None
        replay_upto = (
            active_run.last_enqueued_seq if active_run is not None else events[-1].seq
        )

        # 推快照：全部 durable 事件（客户端据 seq 去重）
        await _send_json({
            "type": "snapshot",
            "session_id": session_id,
            "events": [e.to_dict() for e in events],
            "replay_upto": replay_upto,
            "has_active_run": active_run is not None,
        })

        if subscriber is not None:
            subscriptions[session_id] = (active_run, subscriber)
            # 启动事件转发 task
            asyncio.create_task(
                _relay_events(session_id, subscriber, outbound_queue, run_manager)
            )

    async def _relay_events(
        session_id: str,
        subscriber: Any,
        out_q: asyncio.Queue,
        rm: RunManager,
    ) -> None:
        """从 subscriber 队列消费事件，放入 WS 出站队列。"""
        try:
            while True:
                event = await subscriber.queue.get()
                if event is rm.DONE:
                    await out_q.put({"type": "done", "session_id": session_id})
                    break
                await out_q.put({
                    "type": "event",
                    "session_id": session_id,
                    "event": build_event_payload(event, session_id),
                })
        except asyncio.CancelledError:
            pass
        finally:
            # 订阅清理
            run = rm.get_active(session_id)
            if run is not None:
                run.unsubscribe(subscriber)
            subscriptions.pop(session_id, None)

    # ── 主读写循环 ──

    async def _read_loop() -> None:
        """读客户端上行消息；任何消息都刷新 last_received（活性信号）。"""
        try:
            while True:
                raw = await websocket.receive_text()
                last_received[0] = time.monotonic()

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await _send_json({"type": "error", "message": "invalid JSON"})
                    continue

                msg_type = msg.get("type", "")
                if msg_type == "subscribe":
                    sid = msg.get("session_id", "")
                    if sid:
                        await _push_snapshot(sid)
                elif msg_type == "ping":
                    await _send_json({"type": "pong"})
                elif msg_type == "pong":
                    # server_ping 的应答：活性已由上面的 last_received 刷新，
                    # 无需回包（未知 type 本就被忽略，此分支只为契约显式化）。
                    pass
                elif msg_type == "send_message":
                    # 续聊走 SessionService（业务逻辑不进 WS 层）
                    from agent_harness.session.service import (
                        InvalidSessionId,
                        SessionNotFound,
                        SessionService,
                    )

                    sid = msg.get("session_id", "")
                    content = msg.get("content", "")
                    mode = msg.get("mode", "queue")
                    if not sid or not content:
                        await _send_json({"type": "error", "message": "missing session_id or content"})
                        continue
                    service = SessionService(state)
                    try:
                        result = await service.send_message(
                            session_id=sid, content=content, mode=mode,
                        )
                    except (InvalidSessionId, SessionNotFound) as e:
                        await _send_json({"type": "error", "message": str(e)})
                        continue
                    if result.status == "launched":
                        # 新 run 启动 → 自动订阅
                        run, sub = result.run, result.subscriber
                        subscriptions[sid] = (run, sub)
                        asyncio.create_task(
                            _relay_events(sid, sub, outbound_queue, run_manager)
                        )
                        await _send_json({
                            "type": "launched",
                            "session_id": sid,
                            "run_started": True,
                        })
                    elif result.status == "queued":
                        await _send_json({
                            "type": "queued",
                            "session_id": sid,
                            "queue_id": result.queued_message.queue_id,
                        })
                    elif result.status == "steered":
                        await _send_json({
                            "type": "steered",
                            "session_id": sid,
                            "steer_id": result.steer_request.steer_id,
                        })
                elif msg_type == "cancel":
                    sid = msg.get("session_id", "")
                    if sid:
                        from agent_harness.session.service import SessionService

                        service = SessionService(state)
                        try:
                            await service.cancel(sid)
                            await _send_json({"type": "cancelled", "session_id": sid})
                        except Exception:  # noqa: BLE001 — cancel 兜底
                            await _send_json({"type": "error", "message": "cancel failed"})
                # 未知 type → 忽略
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("WS read loop 异常", exc_info=True)

    async def _write_loop() -> None:
        """写出站队列消息。"""
        try:
            while True:
                payload = await outbound_queue.get()
                await _send_json(payload)
        except asyncio.CancelledError:
            pass

    async def _heartbeat_loop() -> None:
        """服务端应用层心跳 + 死对端回收（SDD 02 §7.9「logical heartbeat」）。

        为什么不是控制帧：ASGI 只定义 ``websocket.send``/``websocket.close``，
        Starlette ``WebSocket`` 无 ``send_ping``，uvicorn 对 ``websocket.ping``
        直接抛 RuntimeError——应用层发不出 RFC 6455 PING 控制帧。因此按
        SDD 02 §7.9 允许的「逻辑心跳」实现：

        - 每 ``WS_PING_INTERVAL`` 秒下行 ``{"type": "server_ping"}``；
        - 客户端须以 ``{"type": "pong"}`` 应答（任意上行消息都会刷新
          ``last_received``——应用层帧能到达 ``receive_text()``，而控制帧
          PONG 在协议层被消费、应用层看不到）；
        - ``now - last_received > WS_PING_TIMEOUT`` → 对端已死，close(1001)。

        对照 deepseek-harness：其 Node 服务端能发控制帧 Ping/Pong，故用
        控制帧；本项目受 ASGI 限制，语义一致、载体改为应用层帧。
        """
        try:
            while True:
                await asyncio.sleep(WS_PING_INTERVAL)
                idle = time.monotonic() - last_received[0]
                if idle > WS_PING_TIMEOUT:
                    logger.info("WS 心跳超时（%.0fs 无上行消息），关闭连接", idle)
                    with contextlib.suppress(Exception):
                        await websocket.close(code=1001, reason="heartbeat timeout")
                    break
                try:
                    await websocket.send_text(json.dumps({"type": "server_ping"}))
                except Exception:
                    logger.debug(
                        "WS server_ping 发送失败（对端可能已断开）", exc_info=True
                    )
                    break
        except asyncio.CancelledError:
            pass

    read_task = asyncio.create_task(_read_loop())
    write_task = asyncio.create_task(_write_loop())
    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        # 等待读循环结束（客户端断开 / 心跳判死关闭）
        await read_task
    finally:
        heartbeat_task.cancel()
        write_task.cancel()
        # 清理所有订阅
        for sid, (run, sub) in list(subscriptions.items()):
            if run is not None:
                run.unsubscribe(sub)
        subscriptions.clear()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        with contextlib.suppress(asyncio.CancelledError):
            await write_task
