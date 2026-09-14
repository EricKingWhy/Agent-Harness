import { describe, expect, it } from 'vitest';
import {
  applyOverride,
  defaultLevelFor,
  modelEventKey,
  nextLevel,
  reasoningIsOpen,
  resolveLevel,
  setReasoningOpen,
  toolEventKey,
} from './disclosure';

describe('defaultLevelFor — density → 默认 L 级（PRD §7）', () => {
  it('compact/balanced → L0，detailed → L1，raw → L2', () => {
    expect(defaultLevelFor('compact')).toBe(0);
    expect(defaultLevelFor('balanced')).toBe(0);
    expect(defaultLevelFor('detailed')).toBe(1);
    expect(defaultLevelFor('raw')).toBe(2);
  });
});

describe('resolveLevel — 手动 override 优先于全局（PRD §6 核心契约）', () => {
  it('无 override 时跟随全局 density', () => {
    const empty = new Map();
    expect(resolveLevel(empty, 'tool:1', 'balanced')).toBe(0);
    expect(resolveLevel(empty, 'tool:1', 'detailed')).toBe(1);
  });

  it('手动 override 优先；切全局 density 不丢（不变式）', () => {
    let overrides = applyOverride(new Map(), 'tool:1', 2);
    expect(resolveLevel(overrides, 'tool:1', 'balanced')).toBe(2);
    expect(resolveLevel(overrides, 'tool:1', 'compact')).toBe(2);
    expect(resolveLevel(overrides, 'tool:1', 'raw')).toBe(2);
    // 其它事件不受影响
    expect(resolveLevel(overrides, 'tool:2', 'balanced')).toBe(0);
  });

  it('override 可低于默认（detailed 档手动收起）', () => {
    const overrides = applyOverride(new Map(), 'tool:1', 0);
    expect(resolveLevel(overrides, 'tool:1', 'detailed')).toBe(0);
  });

  it('applyOverride 不可变：原 map 不被改写', () => {
    const original = new Map<string, 0 | 1 | 2>([['tool:1', 1]]);
    const next = applyOverride(original, 'tool:2', 2);
    expect(original.get('tool:2')).toBeUndefined();
    expect(next.get('tool:2')).toBe(2);
    expect(next.get('tool:1')).toBe(1);
  });
});

describe('事件 key 构造 — 命名空间隔离', () => {
  it('tool / model key 不可能相撞', () => {
    expect(toolEventKey('abc')).toBe('tool:abc');
    expect(modelEventKey(3, 1)).toBe('model:3:1');
    expect(toolEventKey('3:1')).not.toBe(modelEventKey(3, 1));
    // model key 内部 step/index 结构稳定
    expect(modelEventKey(12, 0)).toBe('model:12:0');
  });
});

describe('nextLevel — 点击循环 L0→L1→L2→L0', () => {
  it('循环回绕', () => {
    expect(nextLevel(0)).toBe(1);
    expect(nextLevel(1)).toBe(2);
    expect(nextLevel(2)).toBe(0);
  });
});

describe('T2 — reasoning 自动开合（#95，S6/S7，规格 03 §7.5）', () => {
  it('streaming 默认开（balanced/detailed/raw），completed/interrupted 自动收', () => {
    expect(reasoningIsOpen(new Map(), 'b', 'streaming', 'balanced')).toBe(true);
    expect(reasoningIsOpen(new Map(), 'b', 'streaming', 'detailed')).toBe(true);
    expect(reasoningIsOpen(new Map(), 'b', 'streaming', 'raw')).toBe(true);
    expect(reasoningIsOpen(new Map(), 'b', 'completed', 'balanced')).toBe(false);
    expect(reasoningIsOpen(new Map(), 'b', 'interrupted', 'balanced')).toBe(false);
  });

  it('compact 档 streaming 默认收（PRD §9.1：一行实况）', () => {
    expect(reasoningIsOpen(new Map(), 'b', 'streaming', 'compact')).toBe(false);
  });

  it('手动 override 永久优先——delta/完成/密度切换都不改写（S7 user_interacted）', () => {
    const closed = setReasoningOpen(new Map(), 'b', false);
    expect(reasoningIsOpen(closed, 'b', 'streaming', 'balanced')).toBe(false);
    const open = setReasoningOpen(new Map(), 'b', true);
    expect(reasoningIsOpen(open, 'b', 'completed', 'balanced')).toBe(true);
    expect(reasoningIsOpen(open, 'b', 'streaming', 'compact')).toBe(true);
  });
});
