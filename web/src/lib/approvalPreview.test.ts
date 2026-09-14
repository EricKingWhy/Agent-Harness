/** UI-01（R7）：审批参数预览的结构化分类——不直出转义 JSON 给用户。
 *  已知键（path/command/content/old+new）结构化消费，其余进 rest 兜底；
 *  只认字符串值（类型不符的一律进 rest，不猜）。 */
import { describe, expect, it } from 'vitest';
import { classifyPreviewArgs } from './approvalPreview';

describe('classifyPreviewArgs — 审批参数结构化分类（UI-01）', () => {
  it('write 形状：path + content 被结构化消费，rest 为空，content 保留真实换行', () => {
    const c = classifyPreviewArgs({
      path: 'deploy.sh',
      content: '#!/usr/bin/env bash\nrsync -av dist/ server:/srv/app',
    });
    expect(c.path).toBe('deploy.sh');
    expect(c.content).toBe('#!/usr/bin/env bash\nrsync -av dist/ server:/srv/app');
    expect(c.command).toBeUndefined();
    expect(c.diff).toBeUndefined();
    expect(c.rest).toEqual({});
  });

  it('bash 形状：command 被结构化消费', () => {
    const c = classifyPreviewArgs({ command: 'npx vitest run 2>&1 | tail -40' });
    expect(c.command).toBe('npx vitest run 2>&1 | tail -40');
    expect(c.path).toBeNull();
    expect(c.rest).toEqual({});
  });

  it('edit 形状：old+new → diff（before/after 键名适配 DiffBlock），path 同时提取', () => {
    const c = classifyPreviewArgs({ path: 'src/a.ts', old: 'const a = 1', new: 'const a = 2' });
    expect(c.path).toBe('src/a.ts');
    expect(c.diff).toEqual({ before: 'const a = 1', after: 'const a = 2', truncated: false });
    expect(c.rest).toEqual({});
  });

  it('路径键优先级：path > file_path > file', () => {
    expect(classifyPreviewArgs({ path: 'a', file_path: 'b' }).path).toBe('a');
    expect(classifyPreviewArgs({ file_path: 'b', file: 'c' }).path).toBe('b');
    expect(classifyPreviewArgs({ file: 'c' }).path).toBe('c');
  });

  it('全未知键：全部进 rest，path 为 null', () => {
    const c = classifyPreviewArgs({ foo: 1, bar: 'x' });
    expect(c.path).toBeNull();
    expect(c.rest).toEqual({ foo: 1, bar: 'x' });
  });

  it('类型不符的已知键不消费（非字符串 content/path 进 rest，不猜）', () => {
    const c = classifyPreviewArgs({ path: 42, content: { nested: true }, command: ['x'] });
    expect(c.path).toBeNull();
    expect(c.content).toBeUndefined();
    expect(c.command).toBeUndefined();
    expect(c.rest).toEqual({ path: 42, content: { nested: true }, command: ['x'] });
  });

  it('old 只有其一（缺 new）→ 不构成 diff，进 rest', () => {
    const c = classifyPreviewArgs({ old: 'only-old' });
    expect(c.diff).toBeUndefined();
    expect(c.rest).toEqual({ old: 'only-old' });
  });

  it('空串已知键不消费（留 rest 走兜底，信息不静默消失）', () => {
    const c = classifyPreviewArgs({ command: '', content: '', path: '', old: 'a', new: '' });
    expect(c.path).toBeNull();
    expect(c.command).toBeUndefined();
    expect(c.content).toBeUndefined();
    expect(c.diff).toBeUndefined();
    expect(c.rest).toEqual({ command: '', content: '', path: '', old: 'a', new: '' });
  });

  it('原型链形状键（JSON.parse 产物）按自有属性处理，不炸不误伤', () => {
    const raw = JSON.parse('{"constructor":"x","hasOwnProperty":1,"command":"ls"}') as Record<string, unknown>;
    const c = classifyPreviewArgs(raw);
    expect(c.command).toBe('ls');
    expect(c.rest).toEqual({ constructor: 'x', hasOwnProperty: 1 });
  });

  it('undefined / 空 preview → 全空分类', () => {
    expect(classifyPreviewArgs(undefined)).toEqual({ path: null, rest: {} });
    expect(classifyPreviewArgs({})).toEqual({ path: null, rest: {} });
  });
});
