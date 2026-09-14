/** #190 —— 命令输出的**聚合层**（纯函数，无 DOM）。
 *
 *  抽出来的原因：本仓已经有两处在读命令输出，但读的**不是同一份东西**——
 *  - Inspector 的 `TerminalTab`（`StepDetail.tsx`）只读 `tool.result.stdout`，不看流式
 *    `tool.output` 块，也不看 stderr；
 *  - 对话里的工具卡（`ToolCard.tsx` 的 `ToolOutputStream`）渲染的是流式 `tool.output`
 *    块（stdout/stderr 分色、有界尾窗、贴底跟随）。
 *
 *  #190 的中心「输出」面如果自己再写第三份，就正好撞上票面 AC9（同一数据不得有两份独立
 *  渲染）。所以这里只做一件事：**把"哪些调用算命令、它们的输出是什么"定成一份纯数据**，
 *  渲染交给既有的 `ToolOutputStream`。
 *
 *  终态优先级（与投影层注释同一口径）：有终态结果的调用以 `result.stdout/stderr` 为准
 *  （"终态顺序由 result 真相恢复"）；还没结果的（在跑 / 被中断且无 result）回落流式块，
 *  否则正在跑的命令在面板里会是一片空白。
 *
 *  ⚠ 被外置（overflow）过的结果里，`stdout` 已被后端替换成"摘要 + `use read_artifact(<id>)`
 *  标记"，这里**原样显示**——把标记解析成可点的入口是 #186 的活（两端 marker 文案统一也在
 *  那张票），本票不碰。
 */

import { describe, expect, it } from 'vitest';
import type { ToolCall } from '../types';
import { commandOutputs, commandOutputText } from './commandOutput';

function bash(over: Partial<ToolCall> = {}): ToolCall {
  return {
    tool_call_id: 'c1',
    name: 'bash',
    args: { command: 'pytest -q' },
    status: 'success',
    result: { exit_code: 0, stdout: 'ok\n', stderr: '' },
    ...over,
  };
}

function tool(name: string, over: Partial<ToolCall> = {}): ToolCall {
  return { tool_call_id: `t-${name}`, name, args: {}, status: 'success', ...over };
}

describe('#190 命令输出的聚合', () => {
  it('只收 bash：其它工具不是"命令输出"', () => {
    const outputs = commandOutputs([
      tool('read', { result: { content: 'file' }, args: { path: 'a.ts' } }),
      bash(),
      tool('write', { result: { ok: true }, args: { path: 'b.ts', content: 'x' } }),
    ]);
    expect(outputs.map((o) => o.toolCallId)).toEqual(['c1']);
  });

  it('命令原文取 args.command；缺失就是空串，不伪造', () => {
    const outputs = commandOutputs([bash({ args: {} }), bash({ tool_call_id: 'c2', args: { command: 42 } })]);
    expect(outputs.map((o) => o.command)).toEqual(['', '42']);
  });

  it('终态以 result 为准：stdout + stderr 按通道成块，exit_code 如实', () => {
    const [out] = commandOutputs([
      bash({ result: { exit_code: 2, stdout: 'part1\n', stderr: 'boom\n' } }),
    ]);
    expect(out.chunks).toEqual([
      { channel: 'stdout', text: 'part1\n' },
      { channel: 'stderr', text: 'boom\n' },
    ]);
    expect(out.exitCode).toBe(2);
    expect(out.streaming).toBe(false);
  });

  it('空的通道不成块——不渲染空 stderr 块', () => {
    const [out] = commandOutputs([bash({ result: { exit_code: 0, stdout: 'only\n', stderr: '' } })]);
    expect(out.chunks).toEqual([{ channel: 'stdout', text: 'only\n' }]);
  });

  it('还在跑（无 result）→ 用流式块，并标记 streaming', () => {
    const [out] = commandOutputs([
      bash({ status: 'running', result: undefined, output: [{ channel: 'stdout', text: 'working…' }] }),
    ]);
    expect(out.chunks).toEqual([{ channel: 'stdout', text: 'working…' }]);
    expect(out.streaming).toBe(true);
  });

  it('终态里没有 stdout/stderr（如被中断）才回落流式块——否则在跑过的输出会凭空消失', () => {
    const [out] = commandOutputs([
      bash({
        status: 'stopped',
        result: { exit_code: -1, cancelled: true },
        output: [{ channel: 'stdout', text: 'partial' }],
      }),
    ]);
    expect(out.chunks).toEqual([{ channel: 'stdout', text: 'partial' }]);
    expect(out.streaming).toBe(false); // 已终态：不再贴底跟随
  });

  it('既无终态输出也无流式块 → 空块（渲染层只显示命令与状态，不编内容）', () => {
    const [out] = commandOutputs([bash({ result: { exit_code: 0 } })]);
    expect(out.chunks).toEqual([]);
    expect(out.streaming).toBe(false);
  });

  it('顺序 = 工具调用顺序（面板按时间读）', () => {
    const outputs = commandOutputs([
      bash({ tool_call_id: 'a' }),
      bash({ tool_call_id: 'b' }),
      bash({ tool_call_id: 'c' }),
    ]);
    expect(outputs.map((o) => o.toolCallId)).toEqual(['a', 'b', 'c']);
  });

  it('复制文本 = 全部块按序拼接（stdout + stderr 都在，不是只复制 stdout）', () => {
    const [out] = commandOutputs([bash({ result: { exit_code: 1, stdout: 'out\n', stderr: 'err\n' } })]);
    expect(commandOutputText(out)).toBe('out\nerr\n');
  });

  it('result 不是对象（字符串/缺失）也不炸，按"没有终态输出"处理', () => {
    const outputs = commandOutputs([
      bash({ result: 'plain string' }),
      bash({ tool_call_id: 'c9', result: null }),
    ]);
    expect(outputs.map((o) => o.chunks)).toEqual([[], []]);
    expect(outputs.map((o) => o.exitCode)).toEqual([null, null]);
  });
});
