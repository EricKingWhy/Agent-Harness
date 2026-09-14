import { describe, expect, it, beforeEach, vi } from 'vitest';
import { forgetResumeAttempt, maxEventSeq, nextResumeAttempt, readStoredSessionId, SELECTED_SESSION_KEY, writeStoredSessionId } from './sessionRestore';

/** 最小 localStorage stub——项目无 jsdom，只模拟本模块触碰的那一个面。 */
function installStorageStub(): Map<string, string> {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  return store;
}

describe('sessionRestore — 选中会话持久化（BUG-005）', () => {
  let store: Map<string, string>;
  beforeEach(() => { store = installStorageStub(); });

  it('写入后可读回；null 写入 = 删除键（回到空态不得复活旧会话）', () => {
    writeStoredSessionId('abc');
    expect(readStoredSessionId()).toBe('abc');
    expect(store.get(SELECTED_SESSION_KEY)).toBe('abc');

    writeStoredSessionId(null);
    expect(readStoredSessionId()).toBeNull();
    expect(store.has(SELECTED_SESSION_KEY)).toBe(false);
  });

  it('localStorage 不可用（隐私模式）时读写都不抛——退化为不持久化', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('denied'); },
      setItem: () => { throw new Error('denied'); },
      removeItem: () => { throw new Error('denied'); },
    });
    expect(readStoredSessionId()).toBeNull();
    expect(() => writeStoredSessionId('abc')).not.toThrow();
    expect(() => writeStoredSessionId(null)).not.toThrow();
  });
});

describe('maxEventSeq — 恢复时接续实时流的游标', () => {
  it('取最大持久 seq，跳过流式帧的 null seq', () => {
    expect(maxEventSeq([{ seq: 1 }, { seq: 7 }, { seq: null }, { seq: 3 }])).toBe(7);
  });

  it('全是 null seq（尚未落盘任何持久事件）→ -1（after_seq=-1 从头重放）', () => {
    expect(maxEventSeq([{ seq: null }, { seq: null }])).toBe(-1);
    expect(maxEventSeq([])).toBe(-1);
  });
});

describe('nextResumeAttempt — 自动接流的去重决策（BUG-006）', () => {
  it('首次尝试：放行，并把 (sid, 游标) 记进去', () => {
    const next = nextResumeAttempt(new Map(), 'A', 6);
    expect(next).not.toBeNull();
    expect(next?.get('A')).toBe(6);
  });

  it('同一 sid + 同一游标：拦下——这是「viewing → 接流 → 空流 → viewing」死循环的断点', () => {
    const first = nextResumeAttempt(new Map(), 'A', 6);
    expect(first).not.toBeNull();
    // 零帧空流不带来新事件，历史重装算出的游标仍是 6
    expect(nextResumeAttempt(first as Map<string, number>, 'A', 6)).toBeNull();
  });

  it('同一 sid + 更大的游标：放行并更新——run 又落了新事件，允许再接一次', () => {
    const first = nextResumeAttempt(new Map(), 'A', 6) as Map<string, number>;
    const second = nextResumeAttempt(first, 'A', 9);
    expect(second).not.toBeNull();
    expect(second?.get('A')).toBe(9);
    // 原记录不被就地改写（返回新 Map，调用方自行替换引用）
    expect(first.get('A')).toBe(6);
  });

  it('换一个 sid：各自独立记账，互不牵连', () => {
    const first = nextResumeAttempt(new Map(), 'A', 6) as Map<string, number>;
    const second = nextResumeAttempt(first, 'B', 6);
    expect(second?.get('B')).toBe(6);
    expect(second?.get('A')).toBe(6);
  });

  it('游标变小（例如切到事件更少的会话）也算新尝试——只按相等去重', () => {
    const first = nextResumeAttempt(new Map(), 'A', 6) as Map<string, number>;
    expect(nextResumeAttempt(first, 'A', 2)?.get('A')).toBe(2);
  });
});

describe('forgetResumeAttempt — 用户显式切回时重新武装（BUG-006 边角）', () => {
  it('删掉该 sid 的记账，使同游标也能再试一次（仅持久帧未落时游标不变）', () => {
    const attempted = nextResumeAttempt(new Map(), 'A', 6) as Map<string, number>;
    expect(nextResumeAttempt(attempted, 'A', 6)).toBeNull(); // 自动路径仍被拦
    const forgotten = forgetResumeAttempt(attempted, 'A');
    expect(nextResumeAttempt(forgotten, 'A', 6)).not.toBeNull(); // 用户手动切回 → 放行
  });

  it('只影响该 sid，别的会话记账不动', () => {
    const a = nextResumeAttempt(new Map(), 'A', 6) as Map<string, number>;
    const both = nextResumeAttempt(a, 'B', 3) as Map<string, number>;
    const forgotten = forgetResumeAttempt(both, 'A');
    expect(forgotten.has('A')).toBe(false);
    expect(forgotten.get('B')).toBe(3);
  });

  it('无记录时原样返回同一引用——不做无意义的 Map 复制', () => {
    const attempted = new Map<string, number>([['A', 6]]);
    expect(forgetResumeAttempt(attempted, 'Z')).toBe(attempted);
  });
});
