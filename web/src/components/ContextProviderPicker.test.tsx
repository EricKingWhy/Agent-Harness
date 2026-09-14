/** ContextProviderPicker 契约测试（Phase 2b / F1 补齐）—— SSR 渲染断言：
 *  - 端点缺席（entries 空）：控件不渲染——不伪造列表。
 *  - 目录在场：trigger 按钮渲染 + aria-label 在场。
 *  - selectedIds 有值 → trigger 显示计数（如「Context · 2」）。
 *  - disabled=true → trigger 标记 aria-disabled。 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { Layers } from 'lucide-react';
import { ContextProviderPicker } from './ContextProviderPicker';
import type { CatalogEntry } from '../lib/api';

const ENTRIES: CatalogEntry[] = [
  { id: 'memory', display_name: 'Memory', description: '会话记忆上下文 provider' },
  { id: 'knowledge', display_name: 'Knowledge Base', description: '知识库检索 provider' },
  { id: 'web', display_name: 'Web Search', description: '联网搜索 provider' },
];

describe('ContextProviderPicker（多选 Radix Popover 契约）', () => {
  it('端点缺席（entries 空）：控件不渲染——不伪造列表', () => {
    const html = renderToString(
      createElement(ContextProviderPicker, {
        ariaLabel: 'Context Providers',
        entries: [],
        selectedIds: [],
        onChange: () => {},
        placeholder: 'Context',
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).not.toContain('composer-control');
    expect(html).not.toContain('Context Providers');
  });

  it('目录在场：trigger 渲染且 aria-label 在场', () => {
    const html = renderToString(
      createElement(ContextProviderPicker, {
        ariaLabel: 'Context Providers',
        entries: ENTRIES,
        selectedIds: [],
        onChange: () => {},
        icon: Layers,
        placeholder: 'Context',
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('composer-control');
    expect(html).toContain('aria-label="Context Providers"');
    // 未选中时显示 placeholder
    expect(html).toContain('Context');
  });

  it('selectedIds 有值 → trigger 显示计数（Context · 2）', () => {
    const html = renderToString(
      createElement(ContextProviderPicker, {
        ariaLabel: 'Context Providers',
        entries: ENTRIES,
        selectedIds: ['memory', 'web'],
        onChange: () => {},
        icon: Layers,
        placeholder: 'Context',
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('Context · 2');
  });

  it('disabled=true → trigger 标记 aria-disabled', () => {
    const html = renderToString(
      createElement(ContextProviderPicker, {
        ariaLabel: 'Context Providers',
        entries: ENTRIES,
        selectedIds: [],
        onChange: () => {},
        icon: Layers,
        placeholder: 'Context',
        disabled: true,
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('aria-disabled="true"');
  });

  /** FE-R11-07：selectedIds 未与 entries 对账时，会出现"已选但列表里没有、也取消
   *  不掉"的幽灵项——计数还把它算进去（用户看到 Context · 2 却只勾着一个）。
   *  渲染前求交，让"能勾的"与"算进去的"永远是同一集合。 */
  it('selectedIds 含目录里没有的 id → 计数与列表都只认真实条目（幽灵项不算）', () => {
    const html = renderToString(
      createElement(ContextProviderPicker, {
        ariaLabel: 'Context Providers',
        entries: ENTRIES,
        selectedIds: ['memory', '已下线的-provider'],
        onChange: () => {},
        icon: Layers,
        placeholder: 'Context',
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('Context · 1'); // 不是 · 2
    expect(html).not.toContain('Context · 2');
  });

  it('selectedIds 全是幽灵 id → 回到 placeholder（计数 0 不显示「· 0」）', () => {
    const html = renderToString(
      createElement(ContextProviderPicker, {
        ariaLabel: 'Context Providers',
        entries: ENTRIES,
        selectedIds: ['已下线-a', '已下线-b'],
        onChange: () => {},
        icon: Layers,
        placeholder: 'Context',
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('>Context<');
    expect(html).not.toContain('· 0');
  });
});
