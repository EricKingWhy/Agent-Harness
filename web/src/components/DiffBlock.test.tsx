/** #186 AC2：归档 diff 的「就地展开」入口。
 *
 *  关键的一条是**什么时候不该有入口**：`DiffBlock` 也被审批卡用于 old/new 预览
 *  （那里的内容不是 artifact，没有会话可读）。给一个点了报错的按钮，比不给更糟——
 *  用户会以为产物丢了。`sessionId` 缺席即不渲染入口。
 */
import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import type { ToolCall } from '../types';
import { DiffBlock } from './DiffBlock';

const archived: NonNullable<ToolCall['diff']> = {
  before: 'b',
  after: 'a',
  truncated: false,
  archived: true,
  artifactId: '0123456789abcdef',
  artifactTool: 'read_artifact',
};

const render = (diff: NonNullable<ToolCall['diff']>, sessionId?: string) =>
  renderToString(
    createElement(DiffBlock, {
      diff,
      ...(sessionId !== undefined ? { sessionId } : {}),
    }),
  ).replaceAll('<!-- -->', '');

describe('#186 AC2：归档 diff 的就地展开', () => {
  it('有会话 → 给展开入口（内容走内容接口，与清单同一渲染器）', () => {
    const html = render(archived, 'sess-1');
    expect(html).toContain('artifact-toggle');
    expect(html).toContain('查看完整内容');
    expect(html).toContain('aria-expanded="false"');
    // 未展开时不请求内容（组件只在展开后取数）——所以此刻没有内容区
    expect(html).not.toContain('artifact-content');
  });

  it('没有会话（审批卡预览）→ **不**给入口，也不给一个点了报错的按钮', () => {
    const html = render(archived);
    // 判据用展开控件的 class，不用"查看完整内容"这句话——那句话也出现在提示文案里，
    // 拿它当判据测的是措辞而不是"有没有入口"。
    expect(html).not.toContain('artifact-toggle');
    expect(html).not.toContain('查看完整内容');
    // 归档占位本身仍在（内容确实已归档这件事必须说出来）
    expect(html).toContain('diff-archived');
  });

  it('非归档 diff → 正常双栏，且没有展开入口', () => {
    const html = render({ before: 'old\n', after: 'new\n', truncated: false }, 'sess-1');
    expect(html).toContain('diff-cols');
    expect(html).not.toContain('artifact-toggle');
  });

  it('归档 + 有会话：占位仍如实说明是哪个工具能读、id 是什么', () => {
    const html = render(archived, 'sess-1');
    expect(html).toContain('read_artifact');
    expect(html).toContain('0123456789abcdef');
    expect(html).toContain('Diff 内容已归档');
  });
});
