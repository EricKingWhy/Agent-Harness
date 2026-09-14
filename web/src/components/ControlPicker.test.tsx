/** ControlPicker 契约测试（Phase 2b / F1）—— SSR 渲染断言：
 *  - 端点缺席（entries 空）：控件不渲染——不伪造列表。
 *  - 目录在场：trigger 按钮渲染 + aria-label 在场。
 *  - selectedId 有值 → trigger 显示该条目的 display_name。
 *  - disabled=true → trigger 标记 aria-disabled。 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { Shield } from 'lucide-react';
import { ControlPicker } from './ControlPicker';
import type { CatalogEntry } from '../lib/api';

const ENTRIES: CatalogEntry[] = [
  { id: 'auto', display_name: 'Auto Approve', description: '自动批准工具调用' },
  { id: 'ask', display_name: 'Ask Each Time', description: '每次工具调用都询问' },
  { id: 'deny', display_name: 'Deny All', description: '拒绝所有工具调用' },
];

describe('ControlPicker（Radix Popover 契约）', () => {
  it('端点缺席（entries 空）：控件不渲染——不伪造列表', () => {
    const html = renderToString(
      createElement(ControlPicker, {
        ariaLabel: '权限模式',
        entries: [],
        selectedId: null,
        onChange: () => {},
        icon: Shield,
        placeholder: '权限',
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).not.toContain('composer-control');
    expect(html).not.toContain('权限');
  });

  it('目录在场：trigger 渲染且 aria-label 在场', () => {
    const html = renderToString(
      createElement(ControlPicker, {
        ariaLabel: '权限模式',
        entries: ENTRIES,
        selectedId: null,
        onChange: () => {},
        icon: Shield,
        placeholder: '权限',
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('composer-control');
    expect(html).toContain('aria-label="权限模式"');
    // 未选中时显示 placeholder
    expect(html).toContain('权限');
  });

  it('selectedId 有值 → trigger 显示该条目的 display_name', () => {
    const html = renderToString(
      createElement(ControlPicker, {
        ariaLabel: '权限模式',
        entries: ENTRIES,
        selectedId: 'ask',
        onChange: () => {},
        icon: Shield,
        placeholder: '权限',
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('Ask Each Time');
    // 不应显示 placeholder
    expect(html).not.toContain('>权限<');
  });

  it('disabled=true → trigger 标记 aria-disabled', () => {
    const html = renderToString(
      createElement(ControlPicker, {
        ariaLabel: '权限模式',
        entries: ENTRIES,
        selectedId: null,
        onChange: () => {},
        icon: Shield,
        placeholder: '权限',
        disabled: true,
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toMatch(/aria-disabled="true"|disabled/);
  });
});
