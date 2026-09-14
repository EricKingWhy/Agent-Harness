/** #186 Artifact 内容查看器的 SSR 契约。
 *
 *  为什么只测纯渲染那一半：本仓组件测试无 jsdom，`ArtifactViewer` 的取数在测试里
 *  不会 resolve。所以把"状态 → 视图"这一层逐态断言（这里），取数那一层交给
 *  `e2e/z-artifact-content.spec.ts`（真网络、真三态）。
 *
 *  这一面的三条纪律各有一组用例：
 *  - **三态如实**：加载中 / 拿不到（分因、带后端 detail 原文）/ 拿到了；
 *  - **不完整要说**：整体 `truncated` 与单行超长各是各的标记，不合并、不省略；
 *  - **只读**：没有输入类元素（同各面纪律）。
 */
import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { ArtifactContentView, type ArtifactContentState } from './ArtifactViewer';

const render = (state: ArtifactContentState, artifactId = '0123456789abcdef') =>
  renderToString(createElement(ArtifactContentView, { state, artifactId })).replaceAll('<!-- -->', '');

const ready = (over: Partial<Extract<ArtifactContentState, { status: 'ready' }>['slice']> = {}) =>
  ({
    status: 'ready',
    slice: {
      artifact_id: '0123456789abcdef',
      lines: [
        { line_number: 1, text: 'first line' },
        { line_number: 2, text: 'second line' },
      ],
      total_lines: 2,
      returned_lines: 2,
      truncated: false,
      ...over,
    },
  }) as ArtifactContentState;

describe('#186 AC1：三态如实', () => {
  it('加载中：明确说"正在读取"，不装成空内容', () => {
    const html = render({ status: 'loading' });
    expect(html).toContain('正在读取内容');
    expect(html).toContain('aria-busy="true"');
  });

  it('拿到了：带行号的逐行内容 + 总行数', () => {
    const html = render(ready());
    expect(html).toContain('first line');
    expect(html).toContain('second line');
    expect(html).toContain('共 2 行');
    // 行号在场（左列）
    expect(html).toContain('artifact-line-no');
    expect(html).toContain('>1<');
  });

  it('拿到了但一行都没有：如实说"没有内容"，不是"加载中"', () => {
    const html = render(ready({ lines: [], total_lines: 0, returned_lines: 0 }));
    expect(html).toContain('没有可显示的内容');
    expect(html).not.toContain('正在读取');
  });

  /* 404 与 503 对用户是两句不同的话：前者"这个产物不在这里"，后者"这个部署没有可读
     存储"。合并成一句"加载失败"会让用户去追一个不存在的丢失事故。 */
  it('拿不到（404 不在本会话）：说明不在本会话，并给出 id', () => {
    const html = render({ status: 'error', kind: 'gone', detail: '' });
    expect(html).toContain('不在本会话里');
    expect(html).toContain('0123456789abcdef');
    expect(html).toContain('role="alert"');
  });

  it('拿不到（503 没配存储）：说清是部署配置问题，不是产物丢了', () => {
    const html = render({ status: 'error', kind: 'no-storage', detail: '本部署没有可读取的 artifact 存储' });
    expect(html).toContain('本部署没有可读取的 artifact 存储');
    expect(html).toContain('部署配置问题');
  });

  it('后端 detail **原文**照显（不替它翻译成更短的话）', () => {
    const detail = "artifact '0123456789abcdef' 不在会话 's1' 的命名空间里（不存在，或属于别的会话）";
    const html = render({ status: 'error', kind: 'gone', detail });
    expect(html).toContain('不在会话');
  });

  it('detail 为空时不补一句自造的错误文案', () => {
    const html = render({ status: 'error', kind: 'error', detail: '' });
    expect(html).toContain('读取 artifact 内容失败');
    expect(html).not.toContain('artifact-content-detail');
  });
});

describe('#186 AC1：不完整必须说', () => {
  it('整体截断：显示"显示 N / 共 M 行（已截断）"——两个数都来自后端', () => {
    const html = render(ready({ total_lines: 5000, returned_lines: 200, truncated: true }));
    expect(html).toContain('显示 200 / 共 5000 行');
    expect(html).toContain('已截断');
  });

  it('单行超长被截断：行内标记 + 原长提示（不把半截行当完整行）', () => {
    const html = render(
      ready({
        lines: [{ line_number: 7, text: 'x'.repeat(40), truncated: true, full_length: 9000 }],
        total_lines: 1,
        returned_lines: 1,
      }),
    );
    expect(html).toContain('artifact-line-cut');
    expect(html).toContain('原长 9000 字符');
  });

  it('未截断时**不**出现"已截断"字样（不吓唬人）', () => {
    const html = render(ready());
    expect(html).not.toContain('已截断');
  });
});

describe('#186 AC1：只读面', () => {
  it('三种状态下都没有输入类元素', () => {
    for (const state of [ready(), { status: 'loading' } as ArtifactContentState]) {
      const html = render(state);
      expect(html).not.toContain('<input');
      expect(html).not.toContain('<textarea');
      expect(html).not.toContain('contenteditable');
    }
  });
});
