/** reasoningCursor 纯函数契约（#95，S3 前读视口，规格 03 §7.3）。
 *
 * 策略阈值是 benchmark/UX tuning 参数（规格原文），测试锁定的是策略形状：
 * 基速、积压有界加速、终态收尾、clamp、不循环。 */

import { describe, expect, it } from 'vitest';
import { advanceCursor } from './reasoningCursor';

describe('advanceCursor — 前读游标推进策略', () => {
  it('小积压走基速（≈朗读速度）', () => {
    expect(advanceCursor(0, 200, 1000, 'streaming')).toBe(48);
  });

  it('积压超过软阈值后按比例加速', () => {
    // backlog 720 → factor 1 + 720/240 = 4 → 192 字/秒
    expect(advanceCursor(0, 720, 1000, 'streaming')).toBe(192);
    // 极大积压封顶 6 倍 → 288 字/秒
    expect(advanceCursor(0, 10000, 1000, 'streaming')).toBe(288);
  });

  it('终态收尾加速：completed/interrupted 8 倍速 until 尽头', () => {
    expect(advanceCursor(0, 1000, 1000, 'completed')).toBe(384);
    expect(advanceCursor(0, 1000, 1000, 'interrupted')).toBe(384);
  });

  it('clamp：不越界、追平即停在 len（S3 禁 marquee 循环）', () => {
    expect(advanceCursor(9990, 10000, 1000, 'streaming')).toBe(10000);
    expect(advanceCursor(10000, 10000, 1000, 'streaming')).toBe(10000);
  });

  it('dt=0 不推进；pos 已越界时收敛到 len', () => {
    expect(advanceCursor(50, 200, 0, 'streaming')).toBe(50);
    expect(advanceCursor(500, 200, 1000, 'streaming')).toBe(200);
  });

  it('空文本守卫', () => {
    expect(advanceCursor(0, 0, 1000, 'streaming')).toBe(0);
  });
});
