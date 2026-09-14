/** #189 中心列「文件/改动」面的 SSR 结构契约。
 *
 *  交互（点文件名 → 右侧换 diff）在 `e2e/z-changes-panel.spec.ts`；这里锁结构，因为
 *  本票最容易失守的几条都是**结构**："一个文件一行"（聚合了没有）、"复用 DiffBlock"
 *  （是不是又写了一套 diff 渲染）、"只读"（有没有混进输入类元素）、"不可得就不给数"
 *  （归档/截断时有没有编一个统计）。
 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import type { ToolCall } from '../types';
import { ChangesPanel } from './ChangesPanel';

function editTool(
  id: string,
  path: string,
  before: string,
  after: string,
  over: Partial<ToolCall> = {},
): ToolCall {
  return {
    tool_call_id: id,
    name: 'edit',
    args: { path },
    status: 'success',
    result: { ok: true },
    diff: { before, after, truncated: false },
    ...over,
  };
}

const render = (tools: readonly ToolCall[]) =>
  renderToString(createElement(ChangesPanel, { tools })).replaceAll('<!-- -->', '');

const rowCount = (html: string) => (html.match(/changes-file-row/g) || []).length;

/** 取出所有统计徽标的**可见文本**（`<span class="changes-stat…">…</span>`）。
 *  断言必须落在徽标上，不能拿整页 HTML 去匹配 `-\d`——HTML 里的属性值也会命中，
 *  那样的断言测的是标记而不是"有没有编数字"。 */
const statTexts = (html: string): string[] =>
  [...html.matchAll(/<span class="changes-stat[^"]*"[^>]*>([\s\S]*?)<\/span>/g)].map((m) => m[1]);

/** 所有统计徽标都在说"不可得"（`—`），没有任何一个是数字。 */
function assertAllStatsUnavailable(html: string): void {
  const stats = statTexts(html);
  expect(stats.length).toBeGreaterThan(0);
  expect(stats.filter((s) => s !== '—')).toEqual([]);
}

describe('#189 AC1/AC2：文件列表', () => {
  it('一个文件一行（改两次也是一行），带路径与净统计', () => {
    const html = render([
      editTool('t1', 'src/a.ts', 'a\n', 'a\nb\n'),
      editTool('t2', 'src/b.ts', 'x\n', 'y\n'),
      editTool('t3', 'src/a.ts', 'a\nb\n', 'a\nb\nc\n'),
    ]);
    expect(rowCount(html)).toBe(2);
    expect(html).toContain('src/a.ts');
    expect(html).toContain('src/b.ts');
    // a.ts：原文 a → 最终 a,b,c = +2；b.ts：替换一行 = +1 −1
    expect(html).toContain('+2');
    expect(html).toContain('+1');
    expect(html).toContain('-1');
  });

  it('净零变化如实显示 ±0（不是隐藏统计，也不是编成 +1 −1）', () => {
    const html = render([
      editTool('t1', 'x.txt', 'a\n', 'a\nb\n'),
      editTool('t2', 'x.txt', 'a\nb\n', 'a\n'),
    ]);
    expect(html).toContain('±0');
  });

  it('默认选中第一个文件：右侧直接是它的 diff（不是空白右栏）', () => {
    const html = render([editTool('t1', 'src/a.ts', 'old\n', 'new\n')]);
    expect(html).toContain('diff-cols');
    expect(html).toContain('old');
    expect(html).toContain('new');
  });

  it('同一文件的多次改动按时间序都在右侧（各次一个 diff 块）', () => {
    const html = render([
      editTool('t1', 'src/a.ts', 'v1\n', 'v2\n'),
      editTool('t2', 'src/a.ts', 'v2\n', 'v3\n'),
    ]);
    expect((html.match(/diff-block/g) || []).length).toBe(2);
    expect(html).toContain('第 1 次改动');
    expect(html).toContain('第 2 次改动');
  });
});

describe('#189 AC5/AC6 + 不伪造：不可得与空态', () => {
  it('内容归档（>2000 字符）：统计显示"不可得"而不是假数字，占位由 DiffBlock 给', () => {
    const html = render([
      editTool('t1', 'big.txt', 'b', 'a', {
        diff: {
          before: 'b', after: 'a', truncated: false,
          archived: true, artifactId: '0123456789abcdef',
        },
      }),
    ]);
    expect(html).toContain('已归档');
    // DiffBlock 的归档占位（同一渲染器）在场
    expect(html).toContain('diff-archived');
    // 不得出现编出来的统计：**每一个**徽标（左清单行 + 右详情头）都必须说"不可得"，
    // 而不是各自编一个 +N/−M。按属性断言而不是按个数——多一个徽标不该让用例失效。
    assertAllStatsUnavailable(html);
  });

  it('内容被截断（>50KB）：同样说"不可得"并给出原因', () => {
    const html = render([
      editTool('t1', 'big.txt', 'a', 'b', { diff: { before: 'a', after: 'b', truncated: true } }),
    ]);
    expect(html).toContain('已截断');
    assertAllStatsUnavailable(html);
  });

  /* #186 AC4：marker 里的读回工具名要**原样透到界面**——默认部署（Local / MinIO）
     配的是 `read_artifact`，写死 `inspect_artifact` 会让用户照着复制出一句调不通的
     提示。这里同时覆盖「changedFiles → ChangesPanel → DiffBlock」这条透传链。 */
  it('归档占位回显 marker 里的工具名（read_artifact 不被偷换成 inspect_artifact）', () => {
    const html = render([
      editTool('t1', 'big.txt', 'b', 'a', {
        diff: {
          before: 'b', after: 'a', truncated: false, archived: true,
          artifactId: '0123456789abcdef', artifactTool: 'read_artifact',
        },
      }),
    ]);
    expect(html).toContain('read_artifact');
    expect(html).not.toContain('inspect_artifact');
  });

  it('无改动：空态文案逐字（AC6/AC8——不是空列表，也不是"加载中"）', () => {
    const html = render([]);
    expect(html).toContain('本次会话未改动任何文件');
    expect(rowCount(html)).toBe(0);
  });

  it('无改动但命令输出是唯一内容时也算无改动（bash 不进清单）', () => {
    const html = render([
      { tool_call_id: 'b', name: 'bash', args: { command: 'echo hi' }, status: 'success' } as ToolCall,
    ]);
    expect(html).toContain('本次会话未改动任何文件');
  });

  it('有改动但归属不了文件（缺 path）：脚注如实说明数量，不静默丢', () => {
    const html = render([editTool('t1', '   ', 'a', 'b')]);
    expect(html).toContain('1 次改动无法归属到文件');
  });
});

describe('#189 AC4：只读面（不提供编辑入口）', () => {
  it('面板内不存在 input / textarea / contenteditable / 保存类按钮', () => {
    const html = render([
      editTool('t1', 'src/a.ts', 'old\n', 'new\n'),
      editTool('t2', 'src/a.ts', 'new\n', 'newer\n'),
    ]);
    expect(html).not.toContain('<input');
    expect(html).not.toContain('<textarea');
    expect(html).not.toContain('contenteditable');
    expect(html).not.toMatch(/保存|应用|撤销|编辑/);
  });
});
