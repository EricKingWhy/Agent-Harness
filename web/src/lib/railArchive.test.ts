/** 「显示已归档」开关的持久化契约（#171 AC10）。
 *
 *  这一层小到看起来不值得测——但它有两条**只能靠测试钉住**的性质：
 *  1. 只有 `'1'` 算开（其余一律默认）——手改 localStorage / 旧版本写入的别的形状
 *     不该把开关变成"未知态"；
 *  2. 存储不可用（隐私模式 / 配额满）时**不抛**——读开关发生在渲染路径上，抛出去
 *     就是整个侧栏白屏。
 *
 *  项目没有 jsdom 依赖（见 `density.test.ts` 的同款说明），所以这里用最小 stub
 *  模拟本模块触碰的唯一面：`localStorage`。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_SHOW_ARCHIVED,
  SHOW_ARCHIVED_KEY,
  readShowArchived,
  writeShowArchived,
} from './railArchive';

function installStorageStub(overrides: Partial<Storage> = {}): Map<string, string> {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => void store.clear(),
    ...overrides,
  });
  return store;
}

describe('readShowArchived / writeShowArchived', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('默认关（从未写过）', () => {
    installStorageStub();
    expect(DEFAULT_SHOW_ARCHIVED).toBe(false);
    expect(readShowArchived()).toBe(false);
  });

  it('写 true → 读回 true；写 false → 读回 false（往返）', () => {
    const store = installStorageStub();
    writeShowArchived(true);
    expect(store.get(SHOW_ARCHIVED_KEY)).toBe('1');
    expect(readShowArchived()).toBe(true);

    writeShowArchived(false);
    expect(store.get(SHOW_ARCHIVED_KEY)).toBe('0');
    expect(readShowArchived()).toBe(false);
  });

  it('取值域只有 "1"/"0"：别的值（手改 / 旧版本写的形状）一律按默认处理', () => {
    const store = installStorageStub();
    for (const junk of ['true', 'yes', '2', '', '{"on":true}']) {
      store.set(SHOW_ARCHIVED_KEY, junk);
      expect(readShowArchived(), `junk=${junk}`).toBe(false);
    }
  });

  it('存储不可用时不抛（隐私模式）：读回默认值、写静默失败', () => {
    installStorageStub({
      getItem: () => {
        throw new Error('SecurityError: localStorage is disabled');
      },
      setItem: () => {
        throw new Error('QuotaExceededError');
      },
    });
    expect(readShowArchived()).toBe(false);
    expect(() => writeShowArchived(true)).not.toThrow();
  });
});
