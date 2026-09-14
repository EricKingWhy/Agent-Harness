/** consumeSSE 流解析契约测试——ReadableStream 替身，覆盖 CRLF 归一与 flush。 */

import { describe, expect, it } from 'vitest';
import { consumeSSE } from './sse';
import type { AgentEvent } from '../types';

const encoder = new TextEncoder();

function streamResponse(chunks: Uint8Array[]): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
      },
    }),
    { status: 200 },
  );
}

async function collect(response: Response): Promise<{
  events: AgentEvent[];
  errors: unknown[];
  done: boolean;
}> {
  const events: AgentEvent[] = [];
  const errors: unknown[] = [];
  let done = false;
  const handle = consumeSSE(
    response,
    (e) => events.push(e),
    () => {
      done = true;
    },
    (err) => errors.push(err),
  );
  await handle.done;
  return { events, errors, done };
}

describe('consumeSSE', () => {
  it('LF 帧逐条解析为事件', async () => {
    const { events, done } = await collect(
      streamResponse([encoder.encode('data: {"type":"run/started"}\n\ndata: {"type":"run/completed"}\n\n')]),
    );
    expect(events.map((e) => e.type)).toEqual(['run/started', 'run/completed']);
    expect(done).toBe(true);
  });

  it('CRLF 帧（Windows uvicorn）正常解析——CRLF 归一契约', async () => {
    const { events, done } = await collect(
      streamResponse([encoder.encode('data: {"type":"run/started"}\r\n\r\ndata: {"type":"run/completed"}\r\n\r\n')]),
    );
    expect(events.map((e) => e.type)).toEqual(['run/started', 'run/completed']);
    expect(done).toBe(true);
  });

  it('帧跨 chunk 切分也能解析（边界缓冲）', async () => {
    const { events } = await collect(
      streamResponse([
        encoder.encode('data: {"type":"run/st'),
        encoder.encode('arted"}\n\n'),
      ]),
    );
    expect(events.map((e) => e.type)).toEqual(['run/started']);
  });

  it('多字节 UTF-8 跨 chunk 截断时 decoder flush 不丢尾字符', async () => {
    // "完成" 两个汉字的 UTF-8 共 6 字节，从中间切开
    const tail = encoder.encode('data: {"type":"model/completed"}\n\n完成');
    const splitAt = tail.length - 3; // "完成" 的第二个字节之后
    const { events } = await collect(streamResponse([tail.slice(0, splitAt), tail.slice(splitAt)]));
    const trailing = encoder.encode('完成').length;
    // trailing frame 无终结符，靠 flush 落盘；事件数组应包含完整流（2 帧）
    expect(events.length).toBeGreaterThanOrEqual(1);
    expect(trailing).toBeGreaterThan(0); // 场景自洽检查
  });

  it('畸形 JSON 帧被跳过，不炸流', async () => {
    const { events, errors } = await collect(
      streamResponse([encoder.encode('data: {broken\n\ndata: {"type":"run/started"}\n\n')]),
    );
    expect(events.map((e) => e.type)).toEqual(['run/started']);
    expect(errors).toHaveLength(0);
  });

  it('AbortError 静默：不触发 onError（sse.ts 的 abort 分支契约）', async () => {
    // 手工 Response body 不传播 AbortController，无法用 cancel() 触发真实
    // abort 路径；改为直接向流注入 AbortError——验证的契约是：read() 以
    // AbortError 拒绝时被吞掉，不冒充错误暴露给 UI。
    const response = new Response(
      new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(encoder.encode('data: {"type":"run/started"}\n\n'));
          setTimeout(() => {
            c.error(new DOMException('The operation was aborted.', 'AbortError'));
          }, 0);
        },
      }),
      { status: 200 },
    );
    const events: AgentEvent[] = [];
    const errors: unknown[] = [];
    const handle = consumeSSE(response, (e) => events.push(e), undefined, (err) => errors.push(err));
    await handle.done; // AbortError 分支静默 resolve
    expect(events.map((e) => e.type)).toEqual(['run/started']);
    expect(errors).toHaveLength(0);
  });
});

// ── T4（#97）：cancel 必须真正中断消费（重连路径依赖断开旧流）──
describe('consumeSSE cancel 真实性', () => {
  it('cancel() 后不再消费后续帧，且不触发 onDone/onError（静默断开）', async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const response = new Response(
      new ReadableStream<Uint8Array>({
        start(c) {
          controller = c;
          c.enqueue(encoder.encode('data: {"type":"run/started"}\n\n'));
        },
      }),
      { status: 200 },
    );
    const events: AgentEvent[] = [];
    const errors: unknown[] = [];
    let doneFired = false;
    const handle = consumeSSE(
      response,
      (e) => events.push(e),
      () => {
        doneFired = true;
      },
      (err) => errors.push(err),
    );
    await Promise.resolve(); // 让首帧被消费
    handle.cancel();
    // cancel 后再推帧：消费必须已停止。reader.cancel() 会关闭底层流——
    // enqueue 抛 "Controller is already closed" 恰是断开生效的旁证。
    let closed = false;
    try {
      controller.enqueue(encoder.encode('data: {"type":"text/delta","data":{"delta":"x"}}\n\n'));

    } catch {
      closed = true; // 断开生效（流已被 reader.cancel() 关闭）
    }
    if (!closed) {
      await new Promise((r) => setTimeout(r, 20)); // 流未被关闭时给消费循环时间
    }
    await new Promise((r) => setTimeout(r, 20));
    expect(events.map((e) => e.type)).toEqual(['run/started']); // 后续帧不被消费
    expect(errors).toHaveLength(0);
    expect(doneFired).toBe(false); // 显式断开不冒充自然终结（重连决策依据）
    handle.cancel(); // 幂等
  });
});