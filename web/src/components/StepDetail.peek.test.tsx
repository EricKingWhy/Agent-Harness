/** #183 Inspector 升级（清单+详情同框 / peek 升级链）的 SSR 契约测试。
 *
 *  交互（↑↓/Esc/Space/拖拽/整页往返）在 `e2e/y-inspector-peek.spec.ts` 里点；
 *  这里锁的是**结构**——结构错了交互测试会以"看起来过了"的方式骗人：
 *  - **同框**（AC1）：选中项详情与清单必须同时在 DOM 里。此前 `focus` 非 run 时
 *    组件**早退**成"只有详情"，清单整个消失——那正是本票要修的病根，用 SSR 断言
 *    钉住"两者并存"最直接。
 *  - **关闭不卸载**（AC2）：peek 关掉后详情仍在 DOM（`hidden`），否则"关掉再打开"
 *    会丢内部 tab 与滚动位置。
 *  - **aria 如实**（AC7）：钉住/整页是开关（`aria-pressed`），拖宽是 `separator`
 *    并如实报当前值。
 *  - **单一渲染器**（AC9）：命令输出在 Inspector 里也必须走中心列那一个
 *    `ToolOutputStream`，不得另写一套。
 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { EventType } from '../types';
import type { AgentEvent, ConversationState, ToolCall } from '../types';
import { applyEvent, initConversation } from '../lib/projection';
import { StepDetail, type InspectorFocus, type InspectorPanelState } from './StepDetail';

const noop = () => {};

/** 面板视图状态（App 持有；StepDetail 只消费）。 */
function panel(over: Partial<InspectorPanelState> = {}): InspectorPanelState {
  return {
    pinned: false,
    expanded: false,
    width: 320,
    peekOpen: true,
    ...over,
  };
}

function threeEventConversation(): ConversationState {
  let s = initConversation('s183');
  const evts: AgentEvent[] = [
    { type: EventType.RUN_STARTED, data: {}, seq: 1, run_id: 'r1', session_id: 's183', event_id: 'e1' },
    { type: EventType.TOOL_CALL, data: { tool_call_id: 'tc1', name: 'bash', args: { command: 'ls' } }, seq: 2, run_id: 'r1', step_id: 1, session_id: 's183', event_id: 'e2' },
    { type: EventType.RUN_COMPLETED, data: {}, seq: 3, run_id: 'r1', session_id: 's183', event_id: 'e3' },
  ];
  for (const e of evts) s = applyEvent(s, e);
  return s;
}

const renderStepDetail = (args: {
  conversation: ConversationState | null;
  focus: InspectorFocus;
  panelOver?: Partial<InspectorPanelState>;
  streaming?: boolean;
}) =>
  renderToString(
    createElement(StepDetail, {
      conversation: args.conversation,
      streaming: args.streaming ?? false,
      focus: args.focus,
      onFocusRun: noop,
      onFocusTool: noop,
      onFocusEvent: noop,
      panel: panel(args.panelOver),
      onPanelAction: noop,
    }),
  ).replaceAll('<!-- -->', '');

const rowCount = (html: string) => (html.match(/timeline-row/g) || []).length;

describe('#183 AC1 清单与详情同框（不再早退成"只有详情"）', () => {
  const conv = threeEventConversation();
  const focus: InspectorFocus = { kind: 'event', event: conv.events[1] };

  it('选中一个事件：清单（Timeline 行）与选中项详情同时在 DOM 里', () => {
    const html = renderStepDetail({ conversation: conv, focus });
    // 清单在（3 条事件 3 行）
    expect(rowCount(html)).toBe(3);
    // 详情也在（事件类型 + 四段标签条）
    expect(html).toContain('选中项详情');
    expect(html).toContain('tool/call');
    expect(html).toContain('事件详情段');
  });

  it('被选中那一行带 aria-current（不是只靠颜色——AC7 的"aria 如实"）', () => {
    const html = renderStepDetail({ conversation: conv, focus });
    // 事件 seq=2 那行是选中项
    expect(html).toMatch(/aria-current="true"[^]*?>2</);
    // 只有一行被标为当前项
    expect((html.match(/aria-current="true"/g) || []).length).toBe(1);
  });

  it('focus 是 run 级（无选中项）：详情不渲染，清单照常', () => {
    const html = renderStepDetail({ conversation: conv, focus: { kind: 'run' } });
    expect(rowCount(html)).toBe(3);
    expect(html).not.toContain('选中项详情');
  });
});

describe('#183 AC2 关闭不卸载（peek 关掉后详情仍在 DOM）', () => {
  const conv = threeEventConversation();
  const focus: InspectorFocus = { kind: 'event', event: conv.events[1] };

  it('peekOpen=false：详情容器仍在，但带 hidden', () => {
    const html = renderStepDetail({ conversation: conv, focus, panelOver: { peekOpen: false } });
    expect(html).toContain('data-peek="off"');
    expect(html).toMatch(/data-peek="off"[^>]*hidden/);
    // 内容还在（不卸载）——事件类型仍出现在 DOM 里
    expect(html).toContain('tool/call');
  });

  it('peekOpen=true：同一容器 data-peek="on" 且没有 hidden', () => {
    const html = renderStepDetail({ conversation: conv, focus });
    expect(html).toContain('data-peek="on"');
    expect(html).not.toMatch(/data-peek="on"[^>]*hidden/);
  });

  it('空会话也要能看详情：focus 指向的事件不在 events 里（hover Inspect 的历史场景）', () => {
    // 事件来自中间列的直接引用，不保证已进 conversation.events——详情必须照常渲染
    const orphan: AgentEvent = { type: EventType.RUN_STARTED, data: {}, seq: 9, run_id: 'rX', session_id: 's183', event_id: 'eX' };
    const html = renderStepDetail({ conversation: initConversation('s183'), focus: { kind: 'event', event: orphan } });
    expect(html).toContain('选中项详情');
    expect(html).toContain('run/started');
  });
});

describe('#183 AC7 面板控制键的可访问性语义', () => {
  const conv = threeEventConversation();

  it('钉住是开关：aria-pressed 如实反映状态', () => {
    const off = renderStepDetail({ conversation: conv, focus: { kind: 'run' } });
    const on = renderStepDetail({ conversation: conv, focus: { kind: 'run' }, panelOver: { pinned: true } });
    expect(off).toMatch(/aria-pressed="false"[^>]*>[^]*?钉住/);
    expect(on).toMatch(/aria-pressed="true"[^>]*>[^]*?钉住/);
  });

  it('整页是开关：aria-pressed 如实反映状态', () => {
    const off = renderStepDetail({ conversation: conv, focus: { kind: 'run' } });
    const on = renderStepDetail({ conversation: conv, focus: { kind: 'run' }, panelOver: { expanded: true } });
    expect(off).toMatch(/aria-pressed="false"[^>]*>[^]*?整页/);
    expect(on).toMatch(/aria-pressed="true"[^>]*>[^]*?整页/);
  });

  it('关闭按钮有可读名（不是只有一个 X 图标）', () => {
    const html = renderStepDetail({ conversation: conv, focus: { kind: 'run' } });
    expect(html).toContain('aria-label="关闭 Inspector"');
  });

  it('拖宽手柄是 separator：方向 + 当前/上下限都如实报（320→480）', () => {
    const html = renderStepDetail({ conversation: conv, focus: { kind: 'run' }, panelOver: { width: 400 } });
    expect(html).toContain('role="separator"');
    expect(html).toContain('aria-orientation="vertical"');
    expect(html).toContain('aria-valuenow="400"');
    expect(html).toContain('aria-valuemin="320"');
    expect(html).toContain('aria-valuemax="480"');
  });

  it('详情与面板控制在同一容器内：Esc 的层级只作用于面板内部的焦点', () => {
    const html = renderStepDetail({ conversation: conv, focus: { kind: 'event', event: conv.events[1] } });
    // 面板容器带 data-panel（键盘处理挂在这里，而不是 window 上）
    expect(html).toContain('data-panel="inspector"');
  });
});

describe('#183 AC9 单一渲染器：Inspector 的命令输出走中心列同一个 ToolOutputStream', () => {
  /* 取数判据是"终态优先"（`lib/commandOutput.ts` 的优先级：有 result 就以 result 为准）。
     所以 fixture **故意让流式块与终态不同**：块里是半截（大输出还可能被投影合并/重排），
     result 才是权威终态文本。此前 fixture 让两者逐字相同（都是 `'hi\n'`），
     于是"渲染的是 result 还是 chunks"根本测不出来——把实现改回 `chunks={tool.output}`
     也照绿。 */
  const bashTool: ToolCall = {
    tool_call_id: 'tc1',
    name: 'bash',
    args: { command: 'echo hi' },
    status: 'success',
    result: { exit_code: 0, stdout: 'AUTHORITATIVE-TAIL\n' },
    output: [{ channel: 'stdout', text: 'stale-partial-frame\n' }],
    started_at: '2026-09-05T10:00:00Z',
    completed_at: '2026-09-05T10:00:01Z',
  };

  it('有 chunks 也有终态：Output 段是 ToolOutputStream，且内容是**终态**（不是半截流式块）', () => {
    const html = renderStepDetail({
      conversation: threeEventConversation(),
      focus: { kind: 'tool', tool: bashTool },
    });
    expect(html).toContain('tool-out-stream');
    expect(html).toContain('AUTHORITATIVE-TAIL');
    // 流式块的半截文本不得作为内容出现——它只该在 result 缺失时才顶上
    expect(html).not.toContain('stale-partial-frame');
  });

  it('无 chunks 的工具（read/add 这类非命令工具）：仍走结果树，不伪造空输出流', () => {
    const html = renderStepDetail({
      conversation: threeEventConversation(),
      focus: { kind: 'tool', tool: { ...bashTool, name: 'add', output: undefined, result: { sum: 3 } } },
    });
    expect(html).not.toContain('tool-out-stream');
    expect(html).toContain('sum');
  });
});
