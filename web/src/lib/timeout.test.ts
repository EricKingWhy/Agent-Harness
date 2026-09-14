/** `withTimeout` 单测（#160 批次审查发现：挂死的 DELETE 会让行永久隐藏、按钮永久禁用）。
 *
 *  用假定时器：真等 30s 既慢又不在门禁预算里。 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { withTimeout } from './timeout';

afterEach(() => {
  vi.useRealTimers();
});

describe('withTimeout', () => {
  it('请求先落地：原样返回结果（不抛超时）', async () => {
    await expect(withTimeout(Promise.resolve(42), 1000, '删除请求')).resolves.toBe(42);
  });

  it('请求失败：原样抛原错误（超时不得掩盖真因）', async () => {
    const boom = new Error('boom');
    await expect(withTimeout(Promise.reject(boom), 1000, '删除请求')).rejects.toBe(boom);
  });

  it('超时：抛带标签与秒数的错误', async () => {
    vi.useFakeTimers();
    const pending = withTimeout(new Promise<never>(() => {}), 30_000, '删除请求');
    const assertion = expect(pending).rejects.toThrow('删除请求超时（30s）');
    await vi.advanceTimersByTimeAsync(30_000);
    await assertion;
  });

  it('请求先落地时清掉定时器（不留悬空 timeout——否则测试进程/事件循环被吊住）', async () => {
    vi.useFakeTimers();
    await withTimeout(Promise.resolve('ok'), 30_000, '删除请求');
    expect(vi.getTimerCount()).toBe(0);
  });
});
