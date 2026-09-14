/** ToolCard 密度档渲染契约——SSR 测试（C3）。
 *  锁定：detailed/raw 档内联明细的字段标签（Input/Output）、
 *  balanced 档无内联明细、compact 档无图标与全宽参数。
 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { ToolCard } from './ToolCard';
import type { ToolCall } from '../types';

const tool: ToolCall = {
  tool_call_id: 'c1',
  name: 'read',
  args: { path: 'README.md' },
  status: 'success',
  result: { content: 'x', total_lines: 1 },
  started_at: '2026-09-05T10:00:00Z',
  completed_at: '2026-09-05T10:00:01Z',
};

const renderCard = (density: 'compact' | 'balanced' | 'detailed' | 'raw') =>
  renderToString(createElement(ToolCard, { tool, density })).replaceAll('<!-- -->', '');

describe('ToolCard 内联明细字段标签（C3）', () => {
  it('detailed 档：Input/Output 微标签 + args/result 内容', () => {
    const html = renderCard('detailed');
    expect(html).toContain('act-detail-inline');
    expect(html).toContain('act-field-label');
    expect(html).toContain('>Input<');
    expect(html).toContain('>Output<');
    expect(html).toContain('act-detail-args');
    expect(html).toContain('act-detail-result');
  });

  it('raw 档：含原始事件区标签', () => {
    const t: ToolCall = {
      ...tool,
      raw_call: { type: 'tool/call' },
      raw_result: { type: 'tool/result' },
    } as ToolCall;
    const html = renderToString(createElement(ToolCard, { tool: t, density: 'raw' })).replaceAll('<!-- -->', '');
    expect(html).toContain('act-raw-label');
    expect(html).toContain('tool/call 原始事件');
  });

  it('balanced 档：无内联明细', () => {
    const html = renderCard('balanced');
    expect(html).not.toContain('act-detail-inline');
  });

  it('compact 档：无图标、无全宽参数（仅截短参数）', () => {
    const html = renderCard('compact');
    expect(html).not.toContain('act-icon');
    expect(html).toContain('act-args-compact');
  });
});

describe('T3 — ToolOutputStream 流式尾窗（#96，S14/规格 03 §9.3）', () => {
  const outTool = (over: Partial<ToolCall>): ToolCall => ({
    tool_call_id: 'c9', name: 'bash', args: { command: 'npm test' },
    status: 'running', started_at: '2026-09-06T00:00:00Z', ...over,
  });
  const render = (t: ToolCall) =>
    renderToString(createElement(ToolCard, { tool: t, density: 'balanced' as const })).replaceAll('<!-- -->', '');

  it('运行中工具的 stdout 流可见（活流不需展开）', () => {
    const html = render(outTool({ output: [{ channel: 'stdout', text: 'RUN src/a.test.ts\n' }] }));
    expect(html).toContain('tool-out-stream');
    expect(html).toContain('RUN src/a.test.ts');
  });

  it('stderr 分色渲染（通道保真，双通道不串）', () => {
    const html = render(outTool({
      output: [
        { channel: 'stdout', text: 'ok\n' },
        { channel: 'stderr', text: 'warn!\n' },
      ],
    }));
    expect(html).toContain('tool-out-stderr');
    expect(html).toContain('warn!');
  });

  it('万行级输出有界渲染：尾窗裁剪 + 省略标记，DOM 不随总输出线性膨胀', () => {
    const lines = Array.from({ length: 10000 }, (_, i) => `line-${i}`).join('\n');
    const html = render(outTool({ output: [{ channel: 'stdout', text: lines }] }));
    expect(html).toContain('tool-out-tail-mark');
    expect(html).toContain('line-9999');
    expect(html).not.toContain('line-0\n');
    expect(html.length).toBeLessThan(30000);
  });

  it('终态以 result 校准（契约 C2 全量兜底）：L2 渲染 result 路径、chunks 区退位不双写', () => {
    const html = renderToString(
      createElement(ToolCard, {
        tool: outTool({
          status: 'success',
          result: { ok: true, data: { exit_code: 0 } },
          output: [{ channel: 'stdout', text: 'streamed-partial' }],
        }),
        density: 'balanced' as const,
        level: 2,
      }),
    ).replaceAll('<!-- -->', '');
    expect(html).toContain('bash-output');
    expect(html).not.toContain('tool-out-stream');
  });

  it('终态且 result 缺失：chunks 兜底渲染（流式内容不丢弃）', () => {
    const html = render(outTool({
      status: 'success',
      output: [{ channel: 'stdout', text: 'streamed-full' }],
    }));
    expect(html).toContain('tool-out-stream');
    expect(html).toContain('streamed-full');
  });

  it('通道图例：出现过的通道出 chip（票面 channel 徽标）', () => {
    const html = render(outTool({
      output: [
        { channel: 'stdout', text: 'a' },
        { channel: 'stderr', text: 'b' },
      ],
    }));
    expect(html).toContain('tool-out-chip-stdout');
    expect(html).toContain('tool-out-chip-stderr');
  });

  it('无 output 的工具不渲染流式区（既有行为零回归）', () => {
    const html = render(outTool({}));
    expect(html).not.toContain('tool-out-stream');
  });
});

// ── #186 AC2：工具卡的「就地展开」判据是投影挂上的 `tool.artifact` ──

describe('ToolCard 外置产物的就地展开（#186 AC2）', () => {
  const withArtifact: ToolCall = {
    tool_call_id: 'c2',
    name: 'bash',
    args: { command: 'cat big.log' },
    status: 'success',
    result: { exit_code: 0, stdout: '... [truncated, 5000 lines total, use read_artifact(0123456789abcdef) to view]' },
    artifact: {
      artifact_id: '0123456789abcdef',
      size: 4096,
      mime_type: 'text/plain',
      source_tool: 'bash',
    },
    started_at: '2026-09-05T10:00:00Z',
    completed_at: '2026-09-05T10:00:01Z',
  };

  /* 显式给 `level: 2`：`detailed` 档的默认级是 **L1**，L2 内容面（`tool-card-body`）
     在那档根本不渲染——只传 density 的话"不给入口"的两条断言会因为**内容面整块不存在**
     而通过，那测的是密度而不是这条判据。 */
  const render = (tool: ToolCall, sessionId?: string) =>
    renderToString(
      createElement(ToolCard, {
        tool,
        density: 'detailed',
        level: 2,
        ...(sessionId ? { sessionId } : {}),
      }),
    ).replaceAll('<!-- -->', '');

  it('有产物 + 有会话 → L2 内联给展开入口（与 Artifacts 清单同一渲染器）', () => {
    const html = render(withArtifact, 'sess-1');
    // 先确认内容面确实渲染了（否则下面几条都是空断言）
    expect(html).toContain('tool-card-body');
    expect(html).toContain('artifact-toggle');
    expect(html).toContain('查看完整内容');
  });

  it('没有会话 → 不给入口（不渲染一个点不通的按钮）', () => {
    const html = render(withArtifact);
    expect(html).toContain('tool-card-body');
    expect(html).not.toContain('artifact-toggle');
  });

  it('没有产物 → 不给入口（普通命令输出不会凭空多一个控件）', () => {
    const plain: ToolCall = { ...withArtifact, artifact: undefined };
    const html = render(plain, 'sess-1');
    expect(html).toContain('tool-card-body');
    expect(html).not.toContain('artifact-toggle');
  });

  it('归档 diff **不**重复给第二个入口（同一个 artifact 只该有一个展开按钮）', () => {
    /* 归档 diff 的 tool.diff 与 tool.artifact 指向**同一个** artifact：DiffBlock 已经
       渲染了展开入口，通用那一块必须让位。两个同名同效的按钮不是"更多选择"，
       是让用户怀疑它们有区别。 */
    const diffTool: ToolCall = {
      ...withArtifact,
      name: 'write',
      args: { path: 'big.txt' },
      diff: {
        before: '', after: 'marker', truncated: true, archived: true,
        artifactId: '0123456789abcdef', artifactTool: 'read_artifact',
      },
    };
    const html = render(diffTool, 'sess-1');
    expect(html).toContain('diff-archived');
    expect((html.match(/artifact-toggle/g) ?? []).length).toBe(1);
  });
});
