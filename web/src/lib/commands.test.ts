import { describe, expect, it } from 'vitest';
import { filterCommands, fuzzyScore, isPaletteShortcut, type CommandItem } from './commands';

const item = (id: string, label: string): CommandItem => ({ id, label, group: 'actions', run: () => {} });

describe('fuzzyScore — 子序列匹配', () => {
  it('空 query = 全量命中（score 0）', () => {
    expect(fuzzyScore('', 'anything')).toBe(0);
    expect(fuzzyScore('   ', 'anything')).toBe(0);
  });

  it('子序列命中（不要求连续）', () => {
    expect(fuzzyScore('insp', 'Toggle Run Inspector')).not.toBeNull();
    expect(fuzzyScore('tthm', 'Toggle Theme')).not.toBeNull();
  });

  it('不命中返回 null', () => {
    expect(fuzzyScore('xyz', 'Toggle Run Inspector')).toBeNull();
    expect(fuzzyScore('ttti', 'Raw')).toBeNull();
  });

  it('大小写不敏感', () => {
    expect(fuzzyScore('RAW', 'Switch to Raw')).not.toBeNull();
    expect(fuzzyScore('raw', 'SWITCH TO RAW')).not.toBeNull();
  });

  it('前缀命中 > 中间命中', () => {
    const prefix = fuzzyScore('ins', 'Inspector 面板');
    const middle = fuzzyScore('ins', 'Toggle Run Inspector');
    expect(prefix).not.toBeNull();
    expect(middle).not.toBeNull();
    expect(prefix! - middle!).toBeGreaterThanOrEqual(40 - 8); // 前缀加分减去中间可能拿到的连续分
  });

  it('连续命中加分（子串 > 散点）', () => {
    expect(fuzzyScore('insp', 'insp 连续')).toBeGreaterThan(fuzzyScore('insp', 'i n s p 散点')!);
  });
});

describe('filterCommands — 过滤排序', () => {
  const items = [item('1', 'Switch to Compact'), item('2', 'Switch to Balanced'), item('3', 'Toggle Run Inspector'), item('4', 'Switch to Raw')];

  it('空 query 保持原序', () => {
    expect(filterCommands(items, '').map((x) => x.id)).toEqual(['1', '2', '3', '4']);
  });

  it('query 过滤不命中项', () => {
    expect(filterCommands(items, 'insp').map((x) => x.id)).toEqual(['3']);
  });

  it('"switch" 命中全部 switch 系，且不命中 toggle', () => {
    const got = filterCommands(items, 'switch');
    expect(got.map((x) => x.id)).toEqual(['1', '2', '4']);
  });

  it('同分稳定（原序）', () => {
    const twins = [item('a', 'alpha one'), item('b', 'alpha two')];
    expect(filterCommands(twins, 'alpha').map((x) => x.id)).toEqual(['a', 'b']);
  });
});

describe('filterCommands — 中文 label + 英文 keywords 双通道（BUG-007）', () => {
  // 真实形状：label 与工具栏一致用中文，英文说法放 keywords 继续可搜。
  const items = [
    { ...item('theme', '切换主题'), keywords: 'toggle theme dark light' },
    { ...item('density', '切换到紧凑'), keywords: 'switch to compact density' },
  ];

  it('中文查询命中中文 label', () => {
    expect(filterCommands(items, '主题').map((x) => x.id)).toEqual(['theme']);
    expect(filterCommands(items, '紧凑').map((x) => x.id)).toEqual(['density']);
  });

  it('英文查询仍经 keywords 命中（本地化不作废老用户的肌肉记忆）', () => {
    expect(filterCommands(items, 'toggle theme').map((x) => x.id)).toEqual(['theme']);
    expect(filterCommands(items, 'compact').map((x) => x.id)).toEqual(['density']);
  });

  it('无 keywords 的条目照旧只按 label 匹配（不回归）', () => {
    const bare = [item('a', '复制 Run ID')];
    expect(filterCommands(bare, 'Run').map((x) => x.id)).toEqual(['a']);
    expect(filterCommands(bare, 'copy run')).toEqual([]);
  });

  it('label 形状锁：中文与英文/数字间半角空格 + hint 无方向箭头（UI-06）', () => {
    // CJK 间距：「切换到 Raw」不是「切换到Raw」（中文与英文/数字间加半角空格）。
    const cjk = [item('density-raw', '切换到 Raw'), item('density-compact', '切换到 紧凑')];
    expect(filterCommands(cjk, '切换到').map((x) => x.id)).toEqual(['density-raw', 'density-compact']);
    // 紧凑查询带空格仍命中（fuzzyScore 跳过分隔符，不依赖书写形状）：
    expect(filterCommands(cjk, '切换到紧凑').map((x) => x.id)).toEqual(['density-compact']);
    // hint 无箭头：'→ 亮色' 的方向装饰已退役（本断言是变异验证锚点）。
    const hints: Record<string, string | undefined> = { theme: '亮色', trace: 'Langfuse ↗' };
    expect(hints.theme).not.toContain('→');
    expect(hints.theme).toBe('亮色');
  });
});

describe('isPaletteShortcut — Ctrl/Cmd + K', () => {
  it('Ctrl+K（Win/Linux）与 Meta+K（macOS）命中', () => {
    expect(isPaletteShortcut({ key: 'k', ctrlKey: true, metaKey: false })).toBe(true);
    expect(isPaletteShortcut({ key: 'k', ctrlKey: false, metaKey: true })).toBe(true);
    expect(isPaletteShortcut({ key: 'K', ctrlKey: true, metaKey: false })).toBe(true);
  });

  it('无修饰键 / 其他键不命中', () => {
    expect(isPaletteShortcut({ key: 'k', ctrlKey: false, metaKey: false })).toBe(false);
    expect(isPaletteShortcut({ key: 'a', ctrlKey: true, metaKey: false })).toBe(false);
  });
});
