import { describe, expect, it, beforeEach, vi } from 'vitest';
import { applyDensity, DEFAULT_DENSITY, DENSITIES, initDensity } from './density';

/** 最小 DOM stub——项目无 jsdom 依赖，这里只模拟 density.ts 触碰的两个面。 */
function installDomStub() {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    clear: () => void store.clear(),
  });
  const attrs = new Map<string, string>();
  vi.stubGlobal('document', {
    documentElement: {
      setAttribute: (k: string, v: string) => void attrs.set(k, v),
      removeAttribute: (k: string) => void attrs.delete(k),
      getAttribute: (k: string) => attrs.get(k) ?? null,
    },
  });
}

describe('TraceDensity 持久化', () => {
  beforeEach(() => {
    vi.resetModules();
    installDomStub();
  });

  it('默认档为 balanced（冻结决策）', () => {
    expect(DEFAULT_DENSITY).toBe('balanced');
  });

  it('四档齐全且有序：compact / balanced / detailed / raw', () => {
    expect(DENSITIES).toEqual(['compact', 'balanced', 'detailed', 'raw']);
  });

  it('applyDensity 写 data-density 属性 + localStorage', () => {
    applyDensity('detailed');
    expect(document.documentElement.getAttribute('data-density')).toBe('detailed');
    expect(localStorage.getItem('ahi.traceDensity')).toBe('detailed');
  });

  it('未持久化过时 initDensity 回退 balanced 并写入属性', () => {
    expect(initDensity()).toBe('balanced');
    expect(document.documentElement.getAttribute('data-density')).toBe('balanced');
  });

  it('持久化了非法值时 initDensity 回退 balanced（不信任坏数据）', () => {
    localStorage.setItem('ahi.traceDensity', 'extreme');
    expect(initDensity()).toBe('balanced');
    expect(document.documentElement.getAttribute('data-density')).toBe('balanced');
  });

  it('持久化了合法值时 initDensity 恢复该档位', () => {
    localStorage.setItem('ahi.traceDensity', 'raw');
    expect(initDensity()).toBe('raw');
  });
});
