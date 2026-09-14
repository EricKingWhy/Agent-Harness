/** JsonTree 渲染行为契约——SSR 测试（与 StepDetail.test.tsx 同款 renderToString）。
 *  锁定：默认展开深度、容器折叠计数、渲染预算余量行、叶子类型着色、
 *  长字符串显示截断、空容器内联形态。
 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { JsonTree, JSON_TREE_MAX_CHILDREN, leafView } from './JsonTree';

const render = (v: unknown, defaultDepth?: number) =>
  renderToString(createElement(JsonTree, { value: v, defaultDepth })).replaceAll('<!-- -->', '');

describe('JsonTree 展开深度契约', () => {
  it('defaultDepth=1：root 展开，第二层容器折叠为计数', () => {
    const html = render({ a: { b: { c: 1 } }, d: 2 }, 1);
    expect(html).toContain('>a<'); // 第一层 key 可见
    expect(html).toContain('>d<');
    expect(html).toContain('1 key'); // b 折叠计数
    expect(html).not.toContain('>c<'); // 第三层不可见
  });

  it('defaultDepth=2：第二层容器展开，第三层折叠', () => {
    const html = render({ a: { b: { c: 1 } } }, 2);
    expect(html).toContain('>b<');
    expect(html).toContain('1 key'); // c 所在容器折叠
  });

  it('数组折叠显示 items 计数', () => {
    const html = render({ list: [1, 2, 3] }, 1);
    expect(html).toContain('3 items');
  });

  it('叶子 root（非容器）也能渲染', () => {
    const html = render(42);
    expect(html).toContain('json-number');
    expect(html).toContain('>42<');
  });
});

describe('JsonTree 叶子视图', () => {
  it('类型 → 着色类', () => {
    expect(leafView('x').cls).toBe('json-string');
    expect(leafView(1).cls).toBe('json-number');
    expect(leafView(true).cls).toBe('json-literal');
    expect(leafView(null).cls).toBe('json-literal');
  });

  it('字符串带引号；长字符串显示截断', () => {
    expect(leafView('v').text).toBe('"v"');
    const long = leafView('x'.repeat(300));
    expect(long.text).toContain('…');
    expect(long.text.length).toBeLessThan(180);
  });
});

describe('JsonTree 渲染预算与边界', () => {
  it('容器超过预算：只渲染前 N 个 + 余量提示行（真值走复制通道）', () => {
    const arr = Array.from({ length: JSON_TREE_MAX_CHILDREN + 10 }, (_, i) => i);
    const html = render(arr, 2);
    expect(html).toContain(`其余 10 项`);
    expect(html).not.toContain(`>${JSON_TREE_MAX_CHILDREN + 5}<`);
  });

  it('空容器无开关，内联 { } / [ ]', () => {
    expect(render({ a: {} }, 2)).toContain('{ }');
    expect(render({ a: [] }, 2)).toContain('[ ]');
  });

  it('对象 key 与数组 index 用不同类名（index 降权）', () => {
    const obj = render({ k: 1 }, 2);
    expect(obj).toContain('json-key');
    const arr = render(['x'], 2);
    expect(arr).toContain('json-index');
  });
});
