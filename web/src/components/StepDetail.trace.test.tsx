/** trace_url 契约消费侧组件测试（brief §四 item 6 第二子句）。
 *  SSR 渲染 StepDetail，断言三种降级态：
 *   - trace_url 有值 → trace_id 渲染为 <a class="detail-trace-link" target="_blank">
 *   - trace_id 有值但 trace_url 缺 → 纯 <code>（可复制不可点）
 *   - 两者都 null → 「未追踪」灰字
 *  契约：2d7f87a（trace_id / trace_url 并列不互替，Langfuse 未启用都 null）。 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { EventType } from '../types';
import type { AgentEvent, ConversationState } from '../types';
import { initConversation, applyEvent } from '../lib/projection';
import { ChatTab } from './StepDetail';

const noop = () => {};
const strip = (html: string) => html.replaceAll('<!-- -->', '');

function convWith(completed: Partial<{ trace_id: string | null; trace_url: string | null }>): ConversationState {
  let s = initConversation('s');
  const ev: AgentEvent = {
    type: EventType.RUN_COMPLETED,
    data: { ...completed },
    seq: 1,
    run_id: 'r1',
    step_id: 1,
    session_id: 's',
  };
  s = applyEvent(s, ev);
  return s;
}

const render = (conv: ConversationState) =>
  strip(renderToString(createElement(ChatTab, { conversation: conv, tools: [], onFocusTool: noop })));

describe('StepDetail Trace 行（trace_url 契约 2d7f87a）', () => {
  it('trace_url 有值 → trace_id 渲染为可点超链接（target=_blank rel=noopener）', () => {
    const html = render(convWith({ trace_id: 'lf-abc', trace_url: 'https://cloud.langfuse.com/project/p1/traces/lf-abc' }));
    expect(html).toContain('detail-trace-link');
    expect(html).toContain('href="https://cloud.langfuse.com/project/p1/traces/lf-abc"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('lf-abc');
  });

  it('trace_id 有值但 trace_url 缺 → 纯 mono code（可复制不可点）', () => {
    const html = render(convWith({ trace_id: 'lf-only-id', trace_url: null }));
    expect(html).toContain('lf-only-id');
    expect(html).toContain('detail-val-mono');
    expect(html).not.toContain('detail-trace-link');
    expect(html).not.toContain('<a ');
  });

  it('两者都 null（Langfuse 未启用）→「未追踪」灰字', () => {
    const html = render(convWith({ trace_id: null, trace_url: null }));
    expect(html).toContain('未追踪');
    expect(html).toContain('detail-val-muted');
    expect(html).not.toContain('detail-trace-link');
  });
});
