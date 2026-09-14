/** format.ts 时间/数值格式化测试。 */

import { describe, expect, it } from 'vitest';
import { formatDuration, formatRelativeTime, formatTimestamp, truncateForDisplay, formatShortDuration } from './format';

describe('formatDuration', () => {
  it('缺 started/completed 任一（running 中）返回 null', () => {
    expect(formatDuration(undefined, undefined)).toBeNull();
    expect(formatDuration('2026-09-04T00:00:00Z', undefined)).toBeNull();
    expect(formatDuration(undefined, '2026-09-04T00:00:00Z')).toBeNull();
  });

  it('小于 1s 用 ms 表达；<50ms 显 <50ms（UI-04 改约：不再造 1ms 假精度）', () => {
    const t0 = '2026-09-04T00:00:00.000Z';
    expect(formatDuration(t0, '2026-09-04T00:00:00.082Z')).toBe('82ms');
    expect(formatDuration(t0, '2026-09-04T00:00:00.000Z')).toBe('<50ms');
  });

  it('大于等于 1s 用一位小数秒', () => {
    const t0 = '2026-09-04T00:00:00.000Z';
    expect(formatDuration(t0, '2026-09-04T00:00:01.400Z')).toBe('1.4s');
    expect(formatDuration(t0, '2026-09-04T00:01:00.000Z')).toBe('60.0s');
  });
});

describe('formatRelativeTime', () => {
  // 用固定 now 锚定所有断言，避免 Date.now() 副作用。基准：2026-09-04T12:00:00Z。
  const NOW = new Date('2026-09-04T12:00:00Z').getTime();

  it('null/undefined 时间戳返回空串', () => {
    expect(formatRelativeTime(null, NOW)).toBe('');
  });

  it('小于 1 分钟（含未来时间戳容错）显示 刚刚', () => {
    expect(formatRelativeTime('2026-09-04T12:00:00Z', NOW)).toBe('刚刚');
    expect(formatRelativeTime('2026-09-04T11:59:30Z', NOW)).toBe('刚刚');
  });

  it('1–59 分钟显示 N 分钟前（向下取整）', () => {
    expect(formatRelativeTime('2026-09-04T11:59:00Z', NOW)).toBe('1 分钟前');
    expect(formatRelativeTime('2026-09-04T11:01:00Z', NOW)).toBe('59 分钟前');
  });

  it('1–23 小时显示 N 小时前', () => {
    expect(formatRelativeTime('2026-09-04T11:00:00Z', NOW)).toBe('1 小时前');
    expect(formatRelativeTime('2026-09-03T13:00:00Z', NOW)).toBe('23 小时前');
  });

  it('1–6 天显示 N 天前', () => {
    expect(formatRelativeTime('2026-09-03T12:00:00Z', NOW)).toBe('1 天前');
    expect(formatRelativeTime('2026-08-29T12:00:00Z', NOW)).toBe('6 天前');
  });

  it('7 天及以上落到本地化日期字符串（不再用相对措辞）', () => {
    const out = formatRelativeTime('2026-08-28T12:00:00Z', NOW);
    expect(out).toMatch(/[\d]/); // 含日期数字
    expect(out).not.toMatch(/(刚刚|分钟前|小时前|天前)$/);
  });
});

describe('formatTimestamp — 全时间戳（本地时区，含毫秒）', () => {
  it('合法 ISO：YYYY-MM-DD HH:mm:ss.fff 格式', () => {
    expect(formatTimestamp('2026-09-05T13:17:06.288+08:00')).toMatch(
      /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$/,
    );
  });

  it('毫秒精度保留三位（不足补零）', () => {
    // UTC 13:17:06.050 → 本地时区，但毫秒部分恒为 .050
    const out = formatTimestamp('2026-09-05T13:17:06.05Z');
    expect(out).toMatch(/\.050$/);
  });

  it('null / 空串返回 null（调用方不渲染该行）', () => {
    expect(formatTimestamp(null)).toBeNull();
    expect(formatTimestamp('')).toBeNull();
  });

  it('非法时间字符串返回 null（不抛异常）', () => {
    expect(formatTimestamp('not-a-date')).toBeNull();
  });
});

describe('truncateForDisplay — 不可信大输出渲染截断', () => {
  it('未超限原样返回（同一字符串引用语义，无标记）', () => {
    const s = 'hello world';
    expect(truncateForDisplay(s)).toBe(s);
    expect(truncateForDisplay('x'.repeat(20_000))).toHaveLength(20_000); // 恰在默认上限不截断
  });

  it('超限截断到 max 字符并附截断标记（含原始长度，零伪造）', () => {
    const s = 'x'.repeat(25_000);
    const out = truncateForDisplay(s);
    expect(out.startsWith('x'.repeat(20_000))).toBe(true);
    expect(out).toContain('已截断');
    expect(out).toContain('25,000');
    expect(out.length).toBeLessThan(20_100);
  });

  it('自定义 max 生效：刚好等于 max 不截断，超过一个字符即截断', () => {
    expect(truncateForDisplay('abcde', 5)).toBe('abcde');
    const out = truncateForDisplay('abcdef', 5);
    expect(out.startsWith('abcde')).toBe(true);
    expect(out).toContain('已截断');
  });
});

describe('formatShortDuration — 亚秒时长不再给假精度（UI-04 信任裂缝）', () => {
  it('<50ms 显 <50ms（测不到的就说测不到，不显 1ms/13ms 假精度）', () => {
    expect(formatShortDuration(0)).toBe('<50ms');
    expect(formatShortDuration(13)).toBe('<50ms');
    expect(formatShortDuration(49)).toBe('<50ms');
  });
  it('50-999ms 显整 ms', () => {
    expect(formatShortDuration(50)).toBe('50ms');
    expect(formatShortDuration(999)).toBe('999ms');
  });
  it('非有限 / 负值（时钟倒挂）不显数字：负值返回空串、formatDuration 返回 null', () => {
    expect(formatShortDuration(-5)).toBe('');
    expect(formatShortDuration(NaN)).toBe('');
    expect(formatShortDuration(Infinity)).toBe('');
    const t = '2026-09-12T00:00:10Z';
    expect(formatDuration(t, '2026-09-12T00:00:05Z')).toBeNull(); // completedAt < startedAt
  });
  it('≥1s 显一位小数秒', () => {
    expect(formatShortDuration(1000)).toBe('1.0s');
    expect(formatShortDuration(12340)).toBe('12.3s');
  });
  it('formatDuration 走同一短时长语义', () => {
    const t = '2026-09-12T00:00:00Z';
    expect(formatDuration(t, new Date(new Date(t).getTime() + 13).toISOString())).toBe('<50ms');
    expect(formatDuration(t, new Date(new Date(t).getTime() + 1500).toISOString())).toBe('1.5s');
  });
});
