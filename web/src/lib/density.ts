/**
 * TraceDensity — 四档密度状态与持久化（冻结决策：Trace Density 四档 + localStorage）。
 * CSS/渲染侧按档分支：Compact=✓ 摘要行、Balanced=标题+耗时+关键参数（默认）、
 * Detailed=全字段+Input/Output、Raw=原始事件 JSON。
 * 必须在 React 挂载前执行（main.tsx 顶部调用），避免首帧闪错档位。
 */

export type TraceDensity = 'compact' | 'balanced' | 'detailed' | 'raw';

export const DENSITIES: readonly TraceDensity[] = ['compact', 'balanced', 'detailed', 'raw'] as const;

export const DEFAULT_DENSITY: TraceDensity = 'balanced';

const STORAGE_KEY = 'ahi.traceDensity';

function isDensity(v: unknown): v is TraceDensity {
  return typeof v === 'string' && (DENSITIES as readonly string[]).includes(v);
}

function resolveInitial(): TraceDensity {
  const saved = localStorage.getItem(STORAGE_KEY);
  return isDensity(saved) ? saved : DEFAULT_DENSITY;
}

export function initDensity(): TraceDensity {
  const density = resolveInitial();
  document.documentElement.setAttribute('data-density', density);
  return density;
}

export function applyDensity(density: TraceDensity): void {
  document.documentElement.setAttribute('data-density', density);
  localStorage.setItem(STORAGE_KEY, density);
}
