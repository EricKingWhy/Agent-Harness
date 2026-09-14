/** eventValidate 纯函数契约（#94，spec 02 §14：网络事件必须运行时校验）。 */

import { describe, expect, it } from 'vitest';
import { validateEvent } from './eventValidate';

describe('validateEvent — 帧级形状校验', () => {
  it('合法最小帧：type 字符串 + data 对象', () => {
    const r = validateEvent({ type: 'user/message', data: { content: 'hi' } });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.event.data).toEqual({ content: 'hi' });
  });

  it('data 缺失归一化为 {}；seq 缺失归一化为 null；其余字段 verbatim 保留', () => {
    const r = validateEvent({ type: 'run/started', agent_id: 'research_review', time: '2026-09-06T00:00:00Z' });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.event.data).toEqual({});
      expect(r.event.seq).toBeNull();
      expect((r.event as unknown as Record<string, unknown>).agent_id).toBe('research_review');
      expect(r.event.time).toBe('2026-09-06T00:00:00Z');
    }
  });

  it('seq 有限数字放行并保持', () => {
    const r = validateEvent({ type: 'run/started', seq: 3 });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.event.seq).toBe(3);
  });

  it('type 缺失 / 非字符串 / 空串 → 隔离', () => {
    expect(validateEvent({ data: {} }).ok).toBe(false);
    expect(validateEvent({ type: 123, data: {} }).ok).toBe(false);
    expect(validateEvent({ type: '', data: {} }).ok).toBe(false);
  });

  it('data 非普通对象（字符串 / null / 数组）→ 隔离', () => {
    expect(validateEvent({ type: 'x', data: 'nope' }).ok).toBe(false);
    expect(validateEvent({ type: 'x', data: null }).ok).toBe(false);
    expect(validateEvent({ type: 'x', data: [1, 2] }).ok).toBe(false);
  });

  it('seq 非有限数（字符串 / NaN）→ 隔离', () => {
    expect(validateEvent({ type: 'x', data: {}, seq: 'a' }).ok).toBe(false);
    expect(validateEvent({ type: 'x', data: {}, seq: Number.NaN }).ok).toBe(false);
  });

  it('null / 非对象整体 → 隔离', () => {
    expect(validateEvent(null).ok).toBe(false);
    expect(validateEvent('frame').ok).toBe(false);
    expect(validateEvent(42).ok).toBe(false);
    expect(validateEvent(undefined).ok).toBe(false);
  });
});
