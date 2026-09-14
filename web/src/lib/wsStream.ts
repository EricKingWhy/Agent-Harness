/** WS 传输层的 live 流：把 `/api/ws` 多路复用通道包成「形如 SSE 的 Response」。
 *
 * ## 为什么必须走 WS（实测结论，非推测）
 *
 * 部署交付层（`Server: CloudStudio Gateway`，前置腾讯 EdgeOne）会把**整个 HTTP
 * 响应攒到流结束才下发**，GET / POST 一视同仁：
 *
 * | 通道 | 响应头到达 | 帧到达跨度 |
 * | --- | --- | --- |
 * | `POST /api/sessions` | 发出后 **44.158s**（≈ run 全长） | 326 帧全在 0.094s 内 |
 * | `GET /sessions/{id}/stream` | 发出后 **41.551s** | 326 帧全在 0.082s 内 |
 *
 * 后果在 `submitTask` 里非常具体：`await startSession(payload)` 在响应头到达前
 * 不会 resolve，而响应头要等 run 跑完——于是前端**在答案已经答完之后**才拿到第一帧，
 * 打字机效果不可能存在。
 *
 * WebSocket 是帧协议，交付层无法这样攒帧。同一交付链路上的实测：
 * - 服务端 2s 心跳准点到（3.91 / 5.91 / 7.91 / 9.91 / 11.91s）；
 * - 同一轮 run 的 `text/delta` 在 **28.69s 内逐帧到达**（1.65s → 30.35s），
 *   而并行的 POST SSE 仍是 32.9s 后一次性到齐。
 *
 * ## 设计边界（不变量守护）
 *
 * - 本模块**只是传输层**：事件真相仍来自 RunManager 订阅（PRD §5.1 / 不变量 #22），
 *   这里不解释、不聚合、不丢事件。
 * - 刻意把 WS 帧**重新编码成 SSE 文本**喂给既有的 `consumeSSE`，因此
 *   `attachLiveStream` / 合帧器 / seenSeqs 去重门 / 重连调度全部零改动——
 *   换掉的只有字节从哪来。
 * - seq 幂等：快照与 live 窗口会重叠（服务端先订阅后取游标），按 `seq` 去重
 *   （契约「重放帧与 live 帧做同一 seq 幂等投影」）。`model/started` /
 *   `model/delta` 是 stream-only（seq=null、从不落库），不会出现在快照里，
 *   故 null-seq 帧无需去重也不会重复。
 */

import type { AgentEvent } from '../types';
import { listSessions } from './api';

/** 终态事件类型（与 useSession 的 RUN_TERMINAL_TYPES 同集合）。 */
const RUN_TERMINAL_TYPES = new Set(['run/completed', 'run/failed', 'run/interrupted']);

/** 抖动窗口：`done` 未及时到达时，收到终态事件后兜底收流。 */
const TERMINAL_FALLBACK_MS = 2500;

function wsEndpoint(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/api/ws`;
}

/**
 * 订阅一个 session 的 live 流，返回 SSE 形状的 `Response`。
 *
 * @param sessionId 目标会话
 * @param afterSeq  游标：≤ 该 seq 的事件不再下发给上层（-1 = 从头发）。用于接流/续传，
 *                  让快照只补「本地还没有的」那一截，避免历史被重复投影。
 */
export function wsStreamResponse(sessionId: string, afterSeq = -1): Response {
  const encoder = new TextEncoder();
  let sock: WebSocket | null = null;
  let closed = false;
  let maxSeq = afterSeq;
  let terminalTimer: ReturnType<typeof setTimeout> | null = null;

  const teardown = () => {
    if (terminalTimer !== null) {
      clearTimeout(terminalTimer);
      terminalTimer = null;
    }
    const s = sock;
    sock = null;
    if (s && s.readyState !== WebSocket.CLOSED) {
      try {
        s.close();
      } catch {
        /* 关闭失败无意义 */
      }
    }
  };

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const settle = (err?: Error) => {
        if (closed) return;
        closed = true;
        teardown();
        try {
          if (err) controller.error(err);
          else controller.close();
        } catch {
          /* 上层已取消：controller 已失效，静默 */
        }
      };
      const emit = (event: unknown) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        } catch {
          /* controller 已关闭 */
        }
      };

      try {
        sock = new WebSocket(wsEndpoint());
      } catch (e) {
        settle(e as Error);
        return;
      }
      const s = sock;

      s.onopen = () => {
        s.send(JSON.stringify({ type: 'subscribe', session_id: sessionId }));
      };

      s.onmessage = (msg: MessageEvent) => {
        if (closed) return;
        let frame: { type?: string; [k: string]: unknown };
        try {
          frame = JSON.parse(String(msg.data)) as typeof frame;
        } catch {
          return; // 非 JSON 帧（理论上不存在）：忽略，不污染流
        }

        switch (frame.type) {
          case 'server_ping':
            // 应用层心跳（WS_PING_INTERVAL=2s；30s 无上行即被判死）
            try {
              s.send(JSON.stringify({ type: 'pong' }));
            } catch {
              /* 发送失败由 onclose 兜底 */
            }
            return;
          case 'snapshot': {
            const events = (frame.events as AgentEvent[] | undefined) ?? [];
            for (const ev of events) {
              if (typeof ev.seq === 'number') {
                if (ev.seq <= maxSeq) continue;
                maxSeq = ev.seq;
              }
              emit(ev);
            }
            // 服务端无在途 run：不会有 done（没有 relay task 在跑）——快照即全量
            if (frame.has_active_run === false) settle();
            return;
          }
          case 'event': {
            const ev = frame.event as AgentEvent | undefined;
            if (!ev) return;
            if (typeof ev.seq === 'number') {
              if (ev.seq <= maxSeq) return;
              maxSeq = ev.seq;
            }
            emit(ev);
            // 终态已投影；正常路径由服务端 done 收流，这里只做兜底
            if (RUN_TERMINAL_TYPES.has(ev.type) && terminalTimer === null) {
              terminalTimer = setTimeout(() => settle(), TERMINAL_FALLBACK_MS);
            }
            return;
          }
          case 'done':
            settle();
            return;
          case 'error':
            settle(new Error(String(frame.message ?? 'ws error')));
            return;
          default:
            return; // 未知下行（如 launched/queued/steered）：非本订阅关心
        }
      };

      s.onerror = () => settle(new Error('ws error'));
      // 异常关闭：不冒充自然终结——让 onStreamEnd 依 terminalSeen 决定收尾还是重连
      s.onclose = () => settle();
    },
    cancel() {
      // 上层 cancel()（导航离开 / 显式断开 / 重连前静默断开）
      closed = true;
      teardown();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  });
}

/** 轮询会话列表，找出本轮新建的那个 session_id。
 *
 * ## 为什么需要它
 *
 * 交付层攒包导致 `POST /api/sessions` 的响应头要等 run 结束才到，**响应体里的
 * session_id 因此不可用于「立刻接流」**。而会话一旦创建就落进 durable 存储，
 * `GET /api/sessions`（普通 JSON、立即返回）能马上看到它——用「发起前基线 +
 * 差分」认出新建的那条，既不改动后端，也不影响 POST 上原有的全部字段语义
 * （模型 / 权限 / 校验一律照旧生效）。
 *
 * @param known     发起 POST **之前**已存在的会话 id 集合（基线）
 * @param timeoutMs 认领超时
 */
export async function discoverNewSessionId(
  known: ReadonlySet<string>,
  timeoutMs = 6000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastErr: unknown = null;
  while (Date.now() < deadline) {
    try {
      const rows = await listSessions({ includeArchived: true });
      // rows 通常已按时间倒序；仍全表扫以容忍排序变化
      const fresh = rows.find((r) => !known.has(r.session_id));
      if (fresh) return fresh.session_id;
    } catch (e) {
      lastErr = e;
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(
    lastErr instanceof Error ? `未认领到新会话：${lastErr.message}` : '未认领到新会话（超时）',
  );
}

/** 取当前会话 id 基线（给 discoverNewSessionId 用）。失败返回空集=
 *  退化为「最新一条」，不至于让提交直接失败。 */
export async function sessionIdBaseline(): Promise<Set<string>> {
  try {
    const rows = await listSessions({ includeArchived: true });
    return new Set(rows.map((r) => r.session_id));
  } catch {
    return new Set<string>();
  }
}
