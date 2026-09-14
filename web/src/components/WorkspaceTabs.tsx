/** 中心列 tab 条（#182）。
 *
 *  **纯展示组件**：tab 集、当前面、选中回调都由外面（`App.tsx`）给——能力声明显隐的
 *  决策在 `lib/capabilities.ts`（纯函数），这里只负责把它渲染成 `role="tablist"`
 *  并把键盘事件接回决策函数。
 *
 *  为什么不是 `<select>` / 自绘分段控件：
 *  - `role="tablist"` + `role="tab"` + `aria-selected` 是**如实**表达"这里在切换面"的
 *    标准形状，读屏与 Playwright 都认（e2e 直接按 role 断言，不必靠 class 猜）；
 *  - roving tabindex（选中项 `tabIndex=0`、其余 `-1`）：整条只占**一个** Tab 停靠点，
 *    内部用方向键走——这是 WAI-ARIA tabs 的既定模式，也避免 tab 变多后 Tab 键要按
 *    好几次才能穿过这条。
 *
 *  本仓没有 jsdom，所以交互（方向键真的换了面）由 e2e 覆盖；这里只保证结构/ARIA 契约，
 *  键位语义由 `tabKeyTarget` 的单测覆盖。 */
import { useRef } from 'react';
import { tabKeyTarget, type SurfaceKey } from '../lib/capabilities';

export interface WorkspaceTab {
  key: SurfaceKey;
  label: string;
}

export function WorkspaceTabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: readonly WorkspaceTab[];
  active: SurfaceKey;
  onSelect: (key: SurfaceKey) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    const target = tabKeyTarget(tabs, active, e.key);
    // `null` = 与 tab 无关的键：**不** preventDefault，不吞掉 Enter/Space 等既有语义。
    if (target === null) return;
    e.preventDefault();
    onSelect(target);
    refs.current[tabs.findIndex((t) => t.key === target)]?.focus();
  };

  return (
    <div className="workspace-tabs" role="tablist" aria-label="工作区面">
      {tabs.map((tab, i) => {
        const selected = tab.key === active;
        return (
          <button
            key={tab.key}
            ref={(el) => {
              refs.current[i] = el;
            }}
            id={`workspace-tab-${tab.key}`}
            type="button"
            role="tab"
            className="workspace-tab"
            aria-selected={selected}
            // 面板 id 由 App 渲染时给出（同一命名规则），指向"这个 tab 控制哪个面板"。
            aria-controls={`workspace-panel-${tab.key}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onSelect(tab.key)}
            onKeyDown={handleKeyDown}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
