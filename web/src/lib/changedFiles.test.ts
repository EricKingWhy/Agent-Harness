/** `lib/changedFiles.ts`（#189 中心列「文件/改动」面）纯函数测试。
 *
 *  这一层的三条规则都是"看起来对、其实在骗人"的高危区，必须逐条钉死：
 *  - **按文件聚合**：同一文件改三次是一行，不是三行（AC2）；
 *  - **统计口径**：`+N -M` 是"相对本会话首次改动前的原文"的**净变化**，不是把每次
 *    改动相加（相加会把"改一行"说成 +3 −3）；
 *  - **不可得就不给数**：内容被归档（>2000 字符转 artifact）或截断（>50KB 只留头部）时，
 *    before/after 已不是原文——此时的 `+N -M` 是在 marker/半截文本上算出来的假数字，
 *    必须如实标成"不可得"，而不是给一个看着合理的数（PRD §4 不伪造）。
 */

import { describe, expect, it } from 'vitest';
import type { ToolCall } from '../types';
import { changedFiles, lineDelta, netStatOf } from './changedFiles';

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

describe('lineDelta — 行集合的差（唯一的统计口径）', () => {
  it('追加一行：+1 −0', () => {
    expect(lineDelta('a\nb', 'a\nb\nc')).toEqual({ added: 1, removed: 0 });
  });

  it('删除一行：+0 −1', () => {
    expect(lineDelta('a\nb\nc', 'a\nc')).toEqual({ added: 0, removed: 1 });
  });

  it('替换一行：+1 −1（不是 +0 −0，也不是 +2）', () => {
    expect(lineDelta('a\nb\nc', 'a\nB\nc')).toEqual({ added: 1, removed: 1 });
  });

  it('首尾换行不产生幽灵行（"a\\n" 与 "a" 是同一行内容）', () => {
    expect(lineDelta('a\n', 'a')).toEqual({ added: 0, removed: 0 });
    expect(lineDelta('', 'a\n')).toEqual({ added: 1, removed: 0 });
  });

  it('空 → 有内容 = 全新文件：全部计入 +', () => {
    expect(lineDelta('', 'x\ny')).toEqual({ added: 2, removed: 0 });
  });

  it('重复行按出现次数算，不按集合去重（"a\\na" → "a" 是减了一行）', () => {
    expect(lineDelta('a\na', 'a')).toEqual({ added: 0, removed: 1 });
    expect(lineDelta('a', 'a\na')).toEqual({ added: 1, removed: 0 });
  });
});

describe('netStatOf — 净变化口径（不是把每次改动相加）', () => {
  it('同一行改三次：净 +1 −1，而不是 +3 −3', () => {
    // 原文 v1 → v2 → v3 → v4（每次替换一行）
    const edits = [
      { before: 'a', after: 'b' },
      { before: 'b', after: 'c' },
      { before: 'c', after: 'd' },
    ];
    expect(netStatOf(edits)).toEqual({ stat: { added: 1, removed: 1 }, limited: null });
  });

  it('首次改动前的原文 → 最后一次改动后的内容（中间的往返被抵消）', () => {
    const edits = [
      { before: 'a\nx', after: 'a\nx\ny' },
      { before: 'a\nx\ny', after: 'a\nx' },
    ];
    expect(netStatOf(edits)).toEqual({ stat: { added: 0, removed: 0 }, limited: null });
  });

  it('内容被归档（>2000 字符转 artifact）→ 统计不可得，不给假数字', () => {
    const edits = [
      { before: 'x'.repeat(10), after: 'use inspect_artifact(0123456789abcdef)', archived: true },
    ];
    expect(netStatOf(edits)).toEqual({ stat: null, limited: 'archived' });
  });

  it('内容被截断（>50KB 只留头部）→ 同样不可得（在半截文本上算行数是假数）', () => {
    const edits = [{ before: 'a\nb', after: 'a\nb\nc', truncated: true }];
    expect(netStatOf(edits)).toEqual({ stat: null, limited: 'truncated' });
  });

  it('归档优先于截断上报（两者同时存在时说更严重的那条）', () => {
    const edits = [{ before: 'a', after: 'b', truncated: true, archived: true }];
    expect(netStatOf(edits)).toEqual({ stat: null, limited: 'archived' });
  });

  it('无改动 → 空统计（调用方据此不渲染统计）', () => {
    expect(netStatOf([])).toEqual({ stat: null, limited: null });
  });
});

describe('changedFiles — 按文件聚合（AC2：一个文件一行）', () => {
  it('同一文件改两次 → 一行，两次改动按时间序都在 edits 里', () => {
    const tools = [
      editTool('t1', 'src/a.ts', 'a\n', 'a\nb\n'),
      editTool('t2', 'src/b.ts', 'x\n', 'x\ny\n'),
      editTool('t3', 'src/a.ts', 'a\nb\n', 'a\nb\nc\n'),
    ];
    const { files } = changedFiles(tools);
    expect(files.map((f) => f.path)).toEqual(['src/a.ts', 'src/b.ts']);
    expect(files[0].edits.map((e) => e.toolCallId)).toEqual(['t1', 't3']);
    // 净变化：原文 a → 最终 a,b,c = +2
    expect(files[0].added).toBe(2);
    expect(files[0].removed).toBe(0);
  });

  it('顺序 = 文件首次出现的顺序（不是字母序，也不是最后一次改动的顺序）', () => {
    const tools = [
      editTool('t1', 'z.txt', 'a', 'b'),
      editTool('t2', 'a.txt', 'a', 'b'),
      editTool('t3', 'z.txt', 'b', 'c'),
    ];
    expect(changedFiles(tools).files.map((f) => f.path)).toEqual(['z.txt', 'a.txt']);
  });

  it('write 新建文件（before 为空）：+N −0，且不把空 before 当成"缺数据"', () => {
    const tools = [editTool('t1', 'new.txt', '', 'l1\nl2\n', { name: 'write' })];
    const { files } = changedFiles(tools);
    expect(files[0].added).toBe(2);
    expect(files[0].removed).toBe(0);
    expect(files[0].edits[0].toolName).toBe('write');
  });

  it('非写工具（bash/read）不进清单：它们的产出不是文件改动', () => {
    const tools = [
      { tool_call_id: 'b', name: 'bash', args: { command: 'rm -rf /' }, status: 'success' } as ToolCall,
      { tool_call_id: 'r', name: 'read', args: { path: 'x' }, status: 'success', result: { content: 'x' } } as ToolCall,
    ];
    expect(changedFiles(tools).files).toEqual([]);
  });

  it('三个写工具**都**在集合里：write / edit / apply_patch（漏掉任何一个，那种改动就整类消失）', () => {
    // 这份集合是"什么算文件改动"的**唯一**判据（与后端 `_WRITE_TOOL_NAMES` 同答案）。
    // 逐名断言而不是只测 write/edit：`apply_patch` 是三个里最容易在重构中被漏掉的
    // （它不在任何 mock fixture 的默认路径上），而漏掉的表现是"面板静默少了文件"。
    const tools = ['write', 'edit', 'apply_patch'].map((name, i) =>
      editTool(`t${i}`, `${name}.txt`, 'a\n', 'a\nb\n', { name }),
    );
    const { files } = changedFiles(tools);
    expect(files.map((f) => f.path)).toEqual(['write.txt', 'edit.txt', 'apply_patch.txt']);
    expect(files.every((f) => f.added === 1)).toBe(true);
  });

  it('`./src/a.ts` 与 `src/a.ts` 是同一个文件 → 一行（前导 `./` 可证等价，折掉）', () => {
    const tools = [
      editTool('t1', './src/a.ts', 'a\n', 'a\nb\n'),
      editTool('t2', 'src/a.ts', 'a\nb\n', 'a\nb\nc\n'),
    ];
    const { files } = changedFiles(tools);
    expect(files).toHaveLength(1);
    // 显示的是**首次出现时的原文**（改写的是比对键，不是给用户看的路径）
    expect(files[0].path).toBe('./src/a.ts');
    expect(files[0].edits.map((e) => e.toolCallId)).toEqual(['t1', 't2']);
    expect(files[0].added).toBe(2);
  });

  it('大小写不同**不**合并：区分大小写的文件系统上那是两个文件（宁可两行，不谎报一行）', () => {
    const tools = [
      editTool('t1', 'Src/a.ts', 'a\n', 'a\nb\n'),
      editTool('t2', 'src/a.ts', 'a\n', 'a\nc\n'),
    ];
    expect(changedFiles(tools).files.map((f) => f.path)).toEqual(['Src/a.ts', 'src/a.ts']);
  });

  it('写工具但缺 path：不静默丢——计入 unattributed，界面如实说明', () => {
    const tools = [editTool('t1', '', 'a', 'b')];
    // unattributed 与 files 同一个返回值——不允许"丢了但没处说"
    expect(changedFiles(tools)).toEqual({ files: [], unattributed: 1 });
  });

  it('没有 diff 字段的写工具（结果还没回来）不算改动', () => {
    const pending: ToolCall = {
      tool_call_id: 'p', name: 'write', args: { path: 'x' }, status: 'running',
    };
    expect(changedFiles([pending]).files).toEqual([]);
  });

  it('归档/截断的文件：仍出现在清单里（它确实被改过），只是统计不可得', () => {
    const tools = [
      editTool('t1', 'big.txt', 'use inspect_artifact(0123456789abcdef)', 'use inspect_artifact(0123456789abcdef)', {
        diff: { before: 'b', after: 'a', truncated: false, archived: true, artifactId: '0123456789abcdef' },
      }),
    ];
    const { files } = changedFiles(tools);
    expect(files).toHaveLength(1);
    expect(files[0].added).toBeNull();
    expect(files[0].limited).toBe('archived');
    expect(files[0].edits[0].artifactId).toBe('0123456789abcdef');
  });
});
