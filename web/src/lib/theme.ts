/**
 * Theme — 初始化与持久化（冻结决策：主题切换持久化）。
 * CSS 侧 :root 默认暗色、[data-theme='light'] 覆盖（单一 light 来源，无 @media 重复）。
 * 必须在 React 挂载前执行（main.tsx 顶部调用），避免首帧闪错主题。
 */

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'ahi.theme';

function resolveInitial(): Theme {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === 'dark' || saved === 'light') return saved;
  // 未持久化过：跟随系统偏好
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function initTheme(): Theme {
  const theme = resolveInitial();
  document.documentElement.setAttribute('data-theme', theme);
  return theme;
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(STORAGE_KEY, theme);
}
