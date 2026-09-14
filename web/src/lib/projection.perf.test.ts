/** 投影层基准 + 预算断言（HANDOFF_PERF_FRONTEND §4.3 复现脚本的测试化，P2-6）。
 *
 * Perf 手动车道——默认 vitest 已排除本文件（vitest.config.ts exclude），
 * 预算断言只有在本车道才执行。运行：
 *   npx vitest run -c vitest.perf.config.ts
 *
 * 预算设计（workbuddy 实测基线：applyEvent@20k=0.2µs、projectHistory
 * 4650=2.8ms / 20k=7.2ms）：
 *  - 绝对预算放宽 20 倍以上——目的是拦 O(N²) 回潮（退化形态 @20k≈1.35ms），
 *    不是精确基准，容忍慢机器抖动；
 *  - 另设机器无关的**比例探测器**：applyEvent @20k 与 @1k 的单事件成本比
 *    < 8（append-only 修复后应≈1；O(N²) 回潮时为 ~180x）。
 */
import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../types';
import { EventType } from '../types';
import { applyEvent, initConversation, projectHistory } from './projection';

function mkDelta(i: number): AgentEvent {
  return {
    type: EventType.MODEL_DELTA,
    data: { delta: 'x' },
    seq: i,
    run_id: 'r',
    step_id: 1,
    session_id: 'b',
  };
}

function mk(n: number) {
  let s = initConversation('b');
  for (let i = 0; i < n; i++) s = applyEvent(s, mkDelta(i));
  return s;
}

describe('bench: applyEvent 单事件成本随事件总数（§4.3 复现）', () => {
  it('100 / 1k / 5k / 20k', () => {
    for (const n of [100, 1000, 5000, 20000]) {
      const s = mk(n);
      const t0 = performance.now();
      for (let i = 0; i < 200; i++) applyEvent(s, mkDelta(999999));
      const us = ((performance.now() - t0) / 200) * 1000;
      console.log(`applyEvent @${n}: ${us.toFixed(1)}µs/事件`);
    }
  });
});

describe('bench: projectHistory 历史重建', () => {
  it('4650 事件', () => {
    const events = Array.from({ length: 4650 }, (_, i) => mkDelta(i));
    const t0 = performance.now();
    projectHistory('b', events);
    console.log(`projectHistory 4650: ${(performance.now() - t0).toFixed(1)}ms`);
  });

  it('20000 事件', () => {
    const events = Array.from({ length: 20000 }, (_, i) => mkDelta(i));
    const t0 = performance.now();
    projectHistory('b', events);
    console.log(`projectHistory 20000: ${(performance.now() - t0).toFixed(1)}ms`);
  });
});

describe('budget: O(N²) 回潮探测器（HANDOFF §6 P2-6）', () => {
  it('applyEvent @20k vs @1k 单事件成本比 < 8（append-only 应≈1，O(N²) 回潮时 ~180x）', () => {
    const measure = (n: number, iters: number) => {
      const s = mk(n);
      const t0 = performance.now();
      for (let i = 0; i < iters; i++) applyEvent(s, mkDelta(999999));
      return (performance.now() - t0) / iters;
    };
    // 预热各一次，消除首跑 JIT/分配噪声
    measure(1000, 50);
    measure(20000, 10);
    const per1k = measure(1000, 500);
    const per20k = measure(20000, 200);
    // 绝对预算：50µs = 健康值 0.2µs 的 250 倍余量，仍只有 O(N²) 形态（1.35ms）的 1/27
    expect(per20k * 1000).toBeLessThan(50);
    // 比例探测器：机器无关
    expect(per20k / per1k).toBeLessThan(8);
  });

  it('projectHistory 4650 事件 < 50ms（基线 2.8ms，18x 余量）', () => {
    const events = Array.from({ length: 4650 }, (_, i) => mkDelta(i));
    const t0 = performance.now();
    projectHistory('b', events);
    expect(performance.now() - t0).toBeLessThan(50);
  });

  it('projectHistory 20000 事件 < 200ms（基线 7.2ms，28x 余量）', () => {
    const events = Array.from({ length: 20000 }, (_, i) => mkDelta(i));
    const t0 = performance.now();
    projectHistory('b', events);
    expect(performance.now() - t0).toBeLessThan(200);
  });
});
