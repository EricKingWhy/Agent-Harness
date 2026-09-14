/** Streaming UI 10k+ 逻辑节点基准（#102，PRD §15.3 验收证据，T9）。
 *
 * 逻辑节点定义 = 执行链 activity（model 段 / tool / reasoning 块）——即
 * Conversation 虚拟化与 Inspector Timeline 的真实渲染单元。fixture：
 * 5000 轮 × 3 activity（reasoning + model + tool，覆盖 T2/T3 新事件管线）
 * = 15k 节点，约 23k 事件——超出 PRD 10k 验收线 50%。
 *
 * 预算纪律同 projection.perf.test.ts：绝对预算放宽 20 倍以上（拦 O(N²)
 * 回潮，非精确基准）+ 机器无关比例探测器。DOM 侧（Conversation 虚拟化
 * 动态测高、Timeline 尾窗 200 行、JsonTree 渲染预算、ToolOutputStream
 * 尾窗 8000 字符）由各处既有预算/窗口机制保证——浏览器滚动实测引用
 * docs/STREAMING_UI_10K_BENCHMARK.md 汇总的历史实测与本基准。
 *
 * 运行：npx vitest run -c vitest.perf.config.ts
 */
import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../types';
import { applyEvent, deriveChain, initConversation, projectHistory } from './projection';

const T0 = '2026-09-06T00:00:00Z';

/** 一轮 = user + model burst + reasoning 块 + tool，共 7 事件 3 activity。 */
function turnEvents(step: number, seqBase: number): AgentEvent[] {
  const pad = String(step).padStart(5, '0');
  const t = (offset: number) => `2026-09-06T00:${String(Math.floor(offset / 60) % 60).padStart(2, '0')}:${String(offset % 60).padStart(2, '0')}.${pad}Z`;
  const e = (type: string, data: Record<string, unknown>, offset: number): AgentEvent => ({
    type,
    data,
    seq: seqBase + offset,
    run_id: 'r',
    step_id: step,
    session_id: 'b',
    time: t(offset),
  });
  return [
    e('user/message', { content: `task ${step}`, step }, 0),
    e('model/started', { step: step }, 1),
    e('model/completed', { content: `answer ${step}`, step: step }, 2),
    e('reasoning/started', { block_id: `rb-${step}` }, 3),
    e('reasoning/completed', { block_id: `rb-${step}` }, 4),
    e('tool/call', { tool_call_id: `tc-${step}`, tool_name: 'bash', args: { command: 'ls' } }, 5),
    e('tool/result', { tool_call_id: `tc-${step}`, content: JSON.stringify({ ok: true, data: { exit_code: 0 } }) }, 6),
  ];
}

function buildFixture(turns: number): AgentEvent[] {
  const events: AgentEvent[] = [e0()];
  let seq = 1;
  for (let step = 1; step <= turns; step++) {
    for (const ev of turnEvents(step, seq)) {
      events.push(ev);
      seq += 1;
    }
  }
  return events;
}

function e0(): AgentEvent {
  return { type: 'run/started', data: {}, seq: 0, run_id: 'r', step_id: null, session_id: 'b', time: T0 };
}

/** 逻辑节点计数（执行链 activity 总和）——fixture 自校验。 */
function countNodes(state: ReturnType<typeof initConversation>): number {
  return state.turns.reduce((n, t) => n + t.activities.length, 0);
}

describe('bench: 10k 逻辑节点（#102，PRD §15.3）', () => {
  it('fixture 自校验：5000 轮 → 15k activity 节点（超 PRD 10k 线 50%）', () => {
    const s = projectHistory('b', buildFixture(5000));
    expect(s.turns.length).toBe(5000);
    expect(countNodes(s)).toBe(15000);
  });

  it('projectHistory 23k 事件 → 15k 节点重建 < 400ms（20x+ 余量）', () => {
    const events = buildFixture(5000);
    const t0 = performance.now();
    const s = projectHistory('b', events);
    const ms = performance.now() - t0;
    console.log(`projectHistory 15k 节点（23k 事件）: ${ms.toFixed(1)}ms`);
    expect(countNodes(s)).toBe(15000);
    expect(ms).toBeLessThan(400);
  });

  it('applyEvent 尾部追加 @15k 节点 < 10µs/事件（热路径后实测 ≈5µs；剩余为 turns 数组 COW 拷贝的 O(turns) 结构性下界——O(N²) 回潮由比例探测器守）', () => {
    const events = buildFixture(5000);
    const s = projectHistory('b', events);
    const t0 = performance.now();
    for (let i = 0; i < 500; i++) {
      applyEvent(s, {
        type: 'model/delta',
        data: { delta: 'x' },
        seq: null,
        run_id: 'r',
        step_id: 5000,
        session_id: 'b',
      });
    }
    const us = ((performance.now() - t0) / 500) * 1000;
    console.log(`applyEvent @15k 节点: ${us.toFixed(2)}µs/事件`);
    expect(us).toBeLessThan(10);
  });

  it('重复 seq 全量重放（15k 节点全命中去重）< 100ms——T1 幂等在 10k+ 规模的成本上界', () => {
    const events = buildFixture(5000);
    const s = projectHistory('b', events);
    const t0 = performance.now();
    for (const ev of events) applyEvent(s, ev);
    const ms = performance.now() - t0;
    console.log(`10k 重复 seq 重放（全去重）: ${ms.toFixed(1)}ms`);
    expect(ms).toBeLessThan(100);
  });

  it('deriveChain @3 活动轮 < 0.1ms/次（Lookup 有界，锁 deriveChain 不引入全量扫描）', () => {
    const s = projectHistory('b', buildFixture(5000));
    const big = s.turns.find((t) => t.activities.length >= 10) ?? s.turns[0];
    const t0 = performance.now();
    for (let i = 0; i < 1000; i++) deriveChain(big);
    const ms = (performance.now() - t0) / 1000;
    console.log(`deriveChain @${big.activities.length} 活动: ${(ms * 1000).toFixed(2)}µs/次`);
    expect(ms).toBeLessThan(0.1);
  });
});

describe('budget: 10k 规模 O(N²) 回潮探测器（机器无关）', () => {
  it('projectHistory 每节点成本 @15k 节点 vs @3k 节点 比 < 8', () => {
    const measure = (turns: number) => {
      const events = buildFixture(turns);
      const t0 = performance.now();
      projectHistory('b', events);
      return (performance.now() - t0) / turns;
    };
    measure(500); // 预热
    measure(5000);
    const per1k = measure(1000);
    const per10k = measure(5000);
    console.log(`每轮重建成本 @1k 轮=${(per1k * 1000).toFixed(2)}µs @5k 轮=${(per10k * 1000).toFixed(2)}µs`);
    expect(per10k / per1k).toBeLessThan(8);
  });
});
