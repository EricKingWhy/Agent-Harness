/** ModelPicker 契约测试（Phase 2a）—— SSR 渲染断言：
 *  - 端点缺席（models 空）：选择器不渲染（不伪造列表）。
 *  - 目录在场：trigger 按钮渲染 + 默认链 label + 当前选中模型名可见。
 *  - aria-haspopup / aria-label 等无障碍属性在场（Radix 注入，但我们的 trigger 包装类要存在）。
 *  - Popover 内容项不在 SSR HTML 中（Radix DropdownMenu 的 portal 是客户端渲染）。
 *
 *  真正的打开/选择交互由 Radix 负责（它的测试覆盖范围），这里只锁定
 *  我们的契约：触发器显示什么、空目录降级隐藏、选中态文本。 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import type { ModelCatalogEntry } from '../lib/api';
import { ModelPicker } from './ModelPicker';

const noop = () => {};

const CATALOG: ModelCatalogEntry[] = [
  { name: 'deepseek-v4-flash-0731', provider: 'senseaudio', model: 'deepseek-v4-flash-0731', default: true },
  { name: 'qwen-max', provider: 'senseaudio', model: 'qwen3.8-max-0902', default: false },
  { name: 'claude-sonnet-4', provider: 'anthropic', model: 'claude-sonnet-4-20250514', default: false },
];

describe('ModelPicker（Radix Popover 契约）', () => {
  it('端点缺席（models 空）：选择器不渲染——不伪造列表', () => {
    const html = renderToString(
      createElement(ModelPicker, { models: [], selectedModel: null, onModelChange: noop, disabled: false }),
    ).replaceAll('<!-- -->', '');
    expect(html).not.toContain('model-picker');
    expect(html).not.toContain('默认链');
  });

  it('目录在场：trigger 渲染且显示「默认链」当前选中（null 选中态）', () => {
    const html = renderToString(
      createElement(ModelPicker, { models: CATALOG, selectedModel: null, onModelChange: noop, disabled: false }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('model-picker');
    expect(html).toContain('默认链');
    // aria-label 保留——回退到原生 select 时仍可达
    expect(html).toContain('aria-label="模型选择"');
  });

  it('selectedModel 有值 → trigger 显示该模型名', () => {
    const html = renderToString(
      createElement(ModelPicker, { models: CATALOG, selectedModel: 'qwen-max', onModelChange: noop, disabled: false }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('qwen-max');
    expect(html).not.toContain('>默认链<');
  });

  it('selectedModel 已不在目录 → 归一化为默认链', () => {
    const html = renderToString(
      createElement(ModelPicker, { models: CATALOG, selectedModel: 'removed-model', onModelChange: noop, disabled: false }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('>默认链<');
    expect(html).not.toContain('removed-model');
  });

  it('Radix DropdownMenu 内容项不在 SSR HTML 中（客户端 portal）', () => {
    const html = renderToString(
      createElement(ModelPicker, { models: CATALOG, selectedModel: null, onModelChange: noop, disabled: false }),
    ).replaceAll('<!-- -->', '');
    // 内容项文案不在初始 SSR 输出里（Radix portal 默认不 SSR）
    expect(html).not.toContain('deepseek-v4-flash-0731');
    expect(html).not.toContain('claude-sonnet-4');
  });

  it('disabled=true → trigger 标记 aria-disabled', () => {
    const html = renderToString(
      createElement(ModelPicker, { models: CATALOG, selectedModel: null, onModelChange: noop, disabled: true }),
    ).replaceAll('<!-- -->', '');
    expect(html).toMatch(/aria-disabled="true"|disabled/);
  });
});
