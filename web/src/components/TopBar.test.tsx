/** FE-01（#148）：停顿等待提示的渲染契约。
 *
 *  SSR：本车道没有 effect（定时器不跑），所以「何时算停顿」的真相在
 *  `runState.waitingHintText` 的单测里，这里只钉渲染决策——阈值以下必须
 *  一个节点都不多（与现状逐字节一致），阈值以上必须带秒数与 CSS 挂点。
 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { WaitingHint } from './TopBar';
import { WAIT_HINT_IDLE_SEC } from '../lib/runState';

const html = (idleSec: number) => renderToStaticMarkup(createElement(WaitingHint, { idleSec }));

describe('WaitingHint', () => {
  it('阈值以下不渲染任何节点（阈值以上的提示不得在正常生成时冒出来）', () => {
    expect(html(0)).toBe('');
    expect(html(WAIT_HINT_IDLE_SEC - 1)).toBe('');
  });

  it('达到阈值渲染说明：含已等待秒数 + CSS 挂点', () => {
    const out = html(WAIT_HINT_IDLE_SEC);
    expect(out).toContain('wait-hint');
    expect(out).toContain(String(WAIT_HINT_IDLE_SEC));
  });

  it('不渲染进度/回退类断言（未被事件证实的话一句都不说）', () => {
    const out = html(95);
    for (const banned of ['%', '进度', '预计', 'ETA', '即将', '回退']) {
      expect(out).not.toContain(banned);
    }
  });
});
