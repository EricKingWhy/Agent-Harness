/** #182 —— 中心列 tab 条的 ARIA 契约（SSR；交互由 e2e 覆盖，见文件头说明）。
 *
 *  锁三件事，都是"读屏与 Playwright 看到的真相"：
 *  - `role="tablist"` / `role="tab"` 且名字来自登记表（不是 class 约定）；
 *  - `aria-selected` 如实（只有一个为 true）；
 *  - roving tabindex：整条只占一个 Tab 停靠点。
 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { WorkspaceTabs } from './WorkspaceTabs';
import type { SurfaceKey } from '../lib/capabilities';

const TABS = [
  { key: 'chat' as SurfaceKey, label: 'Chat' },
  { key: 'terminal' as SurfaceKey, label: '输出' },
];

const html = (active: SurfaceKey) =>
  renderToStaticMarkup(
    createElement(WorkspaceTabs, { tabs: TABS, active, onSelect: () => {} }),
  );

describe('#182 中心列 tab 条', () => {
  it('渲染成 tablist，每个 tab 的名字来自登记表', () => {
    const out = html('chat');
    expect(out).toContain('role="tablist"');
    expect(out).toContain('aria-label="工作区面"');
    expect(out).toContain('>Chat</button>');
    expect(out).toContain('>输出</button>');
    // 反面：名字里不许出现 Terminal（只读输出不叫终端）。
    expect(out).not.toMatch(/>Terminal</);
  });

  it('aria-selected 如实：只有一个 true，且在选中的那个上', () => {
    const out = html('terminal');
    expect(out.match(/aria-selected="true"/g)).toHaveLength(1);
    expect(out.match(/aria-selected="false"/g)).toHaveLength(1);
    // 「输出」那个 tab 带 true：按 id 定位，避免靠顺序猜。
    const terminalTab = /id="workspace-tab-terminal"[^>]*/.exec(out)?.[0] ?? '';
    expect(terminalTab).toContain('aria-selected="true"');
  });

  it('roving tabindex：只有选中的 tab 可 Tab 到达', () => {
    const out = html('chat');
    expect(out.match(/tabindex="0"/g)).toHaveLength(1);
    expect(out.match(/tabindex="-1"/g)).toHaveLength(1);
    const chatTab = /id="workspace-tab-chat"[^>]*/.exec(out)?.[0] ?? '';
    expect(chatTab).toContain('tabindex="0"');
  });

  it('每个 tab 声明它控制哪个面板（面板命名规则：workspace-panel-<key>）', () => {
    const out = html('chat');
    expect(out).toContain('aria-controls="workspace-panel-chat"');
    expect(out).toContain('aria-controls="workspace-panel-terminal"');
  });
});
