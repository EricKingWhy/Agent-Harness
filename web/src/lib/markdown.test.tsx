/** markdown.tsx 白名单渲染测试——结构断言（无需 DOM）。 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ReactElement } from 'react';
import { parseFenceLang, renderMarkdown, MdCodeBlock } from './markdown';

// React 19 类型中 ReactElement.props 是 unknown——测试里断言结构需要访问 props，
// 收窄为 any 是测试代码的局部决定，不扩散到产品代码。
type AnyEl = ReactElement<Record<string, any>>;

function firstElement(nodes: ReturnType<typeof renderMarkdown>): AnyEl {
  return nodes[0] as AnyEl;
}

describe('renderMarkdown', () => {
  it('**bold** 渲染为 strong', () => {
    const nodes = renderMarkdown('**创建文件**：hi.txt');
    const el = firstElement(nodes);
    expect(el.props.children[0].type).toBe('strong');
    expect(el.props.children[0].props.children).toBe('创建文件');
  });

  it('`code` 渲染为 code 元素', () => {
    const nodes = renderMarkdown('内容为 `hello`（5 字符）');
    const el = firstElement(nodes);
    // renderInline split: ['内容为 ', '`hello`', '（5 字符）'] → code 在 index 1
    expect(el.props.children[1].type).toBe('code');
    expect(el.props.children[1].props.children).toBe('hello');
  });

  it('- 列表聚合为 md-ul/md-li', () => {
    const nodes = renderMarkdown('- a\n- b');
    const ul = firstElement(nodes);
    expect(ul.type).toBe('ul');
    expect(ul.props.className).toBe('md-ul');
    expect(ul.props.children).toHaveLength(2);
  });

  it('#/## 渲染为 h3，###/#### 渲染为 h4', () => {
    const h3 = firstElement(renderMarkdown('# 标题'));
    const h4 = firstElement(renderMarkdown('### 小节'));
    expect(h3.type).toBe('h3');
    expect(h4.type).toBe('h4');
    expect(h4.props.className).toBe('md-heading');
  });

  /** 围栏代码块现为 MdCodeBlock 组件（.md-code wrapper 含复制按钮）——
   *  未渲染元素树无法穿透函数组件，按组件类型 + code 属性断言。 */
  it('围栏代码块渲染为 MdCodeBlock（wrapper 含复制按钮）', () => {
    const nodes = renderMarkdown('```py\nprint(1)\n```');
    const wrapper = firstElement(nodes);
    expect(wrapper.type).toBe(MdCodeBlock);
    expect(wrapper.props.code).toBe('print(1)');
  });

  it('未闭合围栏按代码块收尾（流式安全）', () => {
    const nodes = renderMarkdown('```py\nprint(1)');
    const wrapper = firstElement(nodes);
    expect(wrapper.type).toBe(MdCodeBlock);
    expect(wrapper.props.code).toBe('print(1)');
  });

  it('HTML 文本不产生 script 元素（无注入面，React 结构化渲染）', () => {
    const nodes = renderMarkdown('<script>alert(1)</script>');
    // 结构化断言：整树不存在字符串 'script' 类型的元素节点
    const types: unknown[] = [];
    const walk = (n: unknown) => {
      if (Array.isArray(n)) return n.forEach(walk);
      if (n && typeof n === 'object' && 'type' in n) {
        types.push((n as AnyEl).type);
        walk((n as AnyEl).props?.children);
      }
    };
    walk(nodes);
    expect(types).not.toContain('script');
    expect(types).toContain('span'); // 原文作为纯文本 children
  });

  it('纯文本按行分段', () => {
    const nodes = renderMarkdown('第一行\n\n第二行');
    expect(nodes).toHaveLength(2);
    // md-paragraph 的 children 是 renderInline 数组，文本在首个 span 里
    expect((nodes[0] as AnyEl).props.children[0].props.children).toBe('第一行');
  });
});

describe('T6 — 围栏语言提取与代码块控件（#99）', () => {
  it('parseFenceLang：语言 id 提取、多词 info 取首词、空白 → null', () => {
    expect(parseFenceLang('python')).toBe('python');
    expect(parseFenceLang(' ts strict ')).toBe('ts');
    expect(parseFenceLang('')).toBeNull();
    expect(parseFenceLang('   ')).toBeNull();
  });

  it('renderMarkdown 围栏产出 MdCodeBlock（md-code 容器在场）', () => {
    const blocks = renderMarkdown('```js\nconst a = 1;\n```');
    const html = renderToStaticMarkup(createElement('div', null, ...blocks));
    expect(html).toContain('md-code');
    expect(html).toContain('const a = 1;');
  });

  it('MdCodeBlock fallback：纯文本 + wrap 控件 + 复制（SSR 不触发异步高亮）', () => {
    const html = renderToStaticMarkup(createElement(MdCodeBlock, { code: 'const a = 1;', lang: 'js' }));
    expect(html).toContain('const a = 1;');
    expect(html).toContain('md-code-wrap-btn');
    expect(html).toContain('复制代码');
    // wrap 初始 off：容器不挂 md-code-wrap（Standards 轴 Dead-Code finding 的回归锚）
    expect(html).not.toContain('md-code md-code-wrap');
  });
});
