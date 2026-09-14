# ADR-0022 — WebSocket 服务端心跳：应用层逻辑心跳（ASGI 控制帧不可行）

**Status**: Accepted
**Date**: 2026-09-09
**Related**: SDD 02 §7.9（Heartbeat）、ADR-0016（detached-run / SSE 主通道）、
`docs/TECH_DEBT_FIX_SPEC.md` §Q4c/§Q4d、`docs/BACKEND_CONTRACT_STREAMING_UI.md`

---

## Context

`src/agent_harness/web/websocket.py` 里 `WS_PING_INTERVAL = 2.0` 与
`WS_PING_TIMEOUT = 30.0` 两个常量被定义了但从未使用，而模块 docstring 却声称
「心跳 ping/pong（2s 默认，30s 超时断开）」——实际只有**客户端主动**的
`{"type": "ping"}` → `{"type": "pong"}`。这是 Q4 盘点出的死代码 + 注释失真
（技术债 spec §Q4 问题 1/3）。

工作规格 §Q4c 要求实现 **server-initiated heartbeat**，并给出了字面机制：
「每 `WS_PING_INTERVAL` 秒发送一个 WebSocket ping frame（`websocket.send_bytes`
with PING opcode，或使用 Starlette 的 `websocket.send_ping`）」。

### 约束：ASGI 层发不出 RFC 6455 PING 控制帧

对本项目实际运行栈（Starlette + uvicorn，ASGI）做了探测验证：

1. `starlette.websockets.WebSocket` **没有** `send_ping` 方法
   （`AttributeError: 'WebSocket' object has no attribute 'send_ping'`）。
2. ASGI 协议只定义 `websocket.send`（text/bytes 应用帧）与 `websocket.close`
   两种出站消息；uvicorn 对 `websocket.ping` 直接抛
   `RuntimeError: Expected ASGI message 'websocket.send' or 'websocket.close',
   but got 'websocket.ping'`。
3. `websocket.send_bytes` 发的是 **binary 应用帧**，不是控制帧——带上 PING
   opcode 需要自己写帧解析，等于绕过 ASGI 协议与服务器实现，不可维护。

因此 §Q4c 的字面机制在 ASGI 下不可实现；必须按规格允许的替代路径实现。

### 规格授权：SDD 02 §7.9 允许「logical heartbeat」

冻结工程规格 SDD 02 §7.9 的原文语义：

> Transport may use a protocol-native ping/pong **or logical heartbeat**.
> Heartbeat is transport health, not a visible Agent event.

即：心跳的**目的**是探测传输层健康（回收死对端），载体不限定为控制帧。
这为应用层 JSON 心跳提供了明确授权。

### 上游参考：deepseek-harness 的做法与边界

参考 `deepseek-ai/deepseek-harness`（AGENTS.md §6 Reuse First）：

- 它是 **Node 服务端**，可以直接向 socket 写控制帧 Ping/Pong；用
  `websocketHeartbeatIntervalMs`（默认 2000ms）周期性 Ping，发 Ping 前标记
  awaiting-Pong，下一个周期若仍在 await 则判定对端已死并终止 socket。
- 它**明确拒绝**应用层 JSON 心跳，前提正是「服务端能发控制帧」。
- 它的 WS 是**下行专用**（不接收客户端应用消息），所以不存在「上行消息也算
  活性」的补充信号。

本项目受 ASGI 限制（见上）且 WS 是**双向**的（`subscribe` / `send_message` /
`steer` / `cancel` 都是上行），所以采用「语义对齐 deepseek、载体改为应用层帧」
的方案。

## Decision

### 1. 应用层逻辑心跳：`server_ping` 下行 + 任意上行刷新活性

`handle_websocket` 新增 `_heartbeat_loop` 任务：

- 每 `WS_PING_INTERVAL`（2.0s）下行 `{"type": "server_ping"}`；
- 客户端应答 `{"type": "pong"}`；**任何**上行消息（`subscribe` /
  `send_message` / `ping` / …）都刷新 `last_received`，即都算活性信号；
- `now - last_received > WS_PING_TIMEOUT`（30.0s）→ 判定对端已死，
  `close(code=1001, reason="heartbeat timeout")`；
- 任务在 `finally` 中 `cancel()` 并 `await`（带 `CancelledError` 抑制），
  与既有 `read_task` / `write_task` 同生命周期。

**为什么「任意上行都算活性」**：应用层帧会到达 `receive_text()`，而控制帧
PONG 在协议层被消费、应用层看不到。若只认显式 `pong`，一个持续
`subscribe` 的活跃客户端也可能被误判死亡。以「任意上行 = 活性」为准，
显式 `pong` 只是契约上的推荐应答。

### 2. `WS_PING_TIMEOUT` 取 30s（6 个间隔）

间隔沿用 deepseek 的 2000ms；超时取 30s 而非 2–3 个间隔，是因为本项目 WS
下行可能长时间只有事件流、上行稀疏（用户不发消息时没有 `send_message`）。
30s 足以跨过移动网络/NAT 的短暂抖动而不误杀，同时仍能在半分钟内回收死对端。
常量集中定义并带注释，杜绝「定义了但没人用」。

### 3. 协议契约变更（前端需跟进）

WS 下行新增 `{"type": "server_ping"}`；上行新增 `{"type": "pong"}`。
前端义务：收到 `server_ping` 后回 `pong`（或保持任意上行消息），否则 30s
无上行会被服务端关闭。SSE 通道不受影响（SSE 无此机制，前端已有
`RECONNECT_STALL_MS` 客户端 stall 检测）。

## Consequences

### Positive

- 死对端在 30s 内被回收，`subscriptions` 与 RunManager 订阅者不会因半开连接
  长期泄漏（配合 ADR-0016 的 orphan grace）。
- 常量与 docstring 与真实行为一致；`WS_PING_INTERVAL` / `WS_PING_TIMEOUT`
  成为真实控制点，不再是死代码。
- 语义与 deepseek-harness 一致（周期性探测 + await 超时终止），迁移/对照成本低。

### Negative / Trade-offs

- **WS 变成强制双向**：纯下行客户端（只读事件、从不发消息）必须在 30s 内
  至少回一次 `pong`，否则被关闭。前端必须实现应答——这是本 ADR 明确记录的
  跨端契约，不是可选项。
- **应用层帧有额外开销**：每 2s 一个极小 JSON 帧（约 20 字节）。相对控制帧
  多了一层 JSON 解析，但可忽略。
- **无法升级为控制帧**：只要继续用 ASGI（uvicorn/Starlette），就发不出 RFC
  6455 PING；若未来换非 ASGI 服务器或自行实现帧层，才可能回到控制帧。届时
  客户端契约可保持兼容（仍回 `pong`）。

## Alternatives considered

- **按 §Q4c 字面用控制帧**（`send_ping` / `websocket.ping` / PING opcode
  bytes）。**否决**：ASGI 下不可实现（探测已证），强写会抛 RuntimeError。
- **删除常量 + 只改 docstring**（承认没有服务端心跳）。**否决**：§Q4c 的核心
  诉求是「服务端主动回收死对端」，只删代码等于放弃该能力；且客户端 stall
  检测（前端 `RECONNECT_STALL_MS`）只解决客户端视角，服务端订阅者仍会泄漏。
- **完全依赖客户端 `ping`**（现状）。**否决**：半开连接下客户端不会主动
  ping，服务端无从判定，正是 Q4 要修的问题。
- **TCP keepalive / SO_KEEPALIVE**。**否决**：只能探测内核层连接存活，无法
  区分「TCP 还通但应用已死」，且需要改服务器/OS 配置，超出应用层职责。
- **显式 `pong` 才算活性**。**否决**：会把「持续发 `subscribe` 的活跃客户端」
  误判为死对端；与「任何上行都是活性证据」的事实相悖。

## Implementation evidence

- `src/agent_harness/web/websocket.py` — `WS_PING_INTERVAL` / `WS_PING_TIMEOUT`
  常量、`last_received` 游标、`_read_loop` 刷新活性、`_heartbeat_loop`
  （`server_ping` 下行 + 超时 `close(1001)`）、`heartbeat_task` 生命周期、
  协议 docstring 更新。
- Tests: `tests/web/test_web_ws_relay.py` —
  `test_ws_server_heartbeat_ping_arrives`（monkeypatch 间隔 0.2s，验证
  `server_ping` 到达、回 pong 后连接存活）、
  `test_ws_dead_peer_closed_after_timeout`（间隔 0.1s / 超时 0.3s，不应答
  → 服务端关闭）、`test_ws_client_ping_pong`、`test_ws_live_event_relay`
  （订阅 active run 的增量事件）、`test_ws_multisession_real_snapshots`、
  `test_ws_disconnect_cleans_subscriber`。
- Gate: 见本轮提交说明（ruff clean + WS 定向测试 + 全量套件）。
