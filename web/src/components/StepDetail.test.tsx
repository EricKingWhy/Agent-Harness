/** Timeline 尾窗裁剪（P1-4）的渲染行为契约——SSR 测试，无需 testing-library。
 *  真相全量在 conversation.events；视图只渲染窗口（不变量 #22：裁的是视图不是数据）。
 */

import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { EventType } from '../types';
import type { AgentEvent, ConversationState } from '../types';
import { initConversation, applyEvent } from '../lib/projection';
import { TimelineTab, TIMELINE_WINDOW_DEFAULT, TIMELINE_WINDOW_STEP } from './StepDetail';

function bigConversation(n: number): ConversationState {
  let s = initConversation('b');
  for (let i = 0; i < n; i++) {
    s = applyEvent(s, { type: EventType.MODEL_DELTA, data: { delta: 'x' }, seq: i, run_id: 'r', step_id: 1, session_id: 'b' });
  }
  return s;
}

/** UI-03：双 run 会话（run1 完成 3 事件 + run2 进行中 2 事件）。 */
function twoRunConversation(): ConversationState {
  let s = initConversation('two-run');
  const evts: AgentEvent[] = [
    { type: EventType.SESSION_STARTED, data: {}, seq: 1, run_id: 'r1', session_id: 'two-run' },
    { type: EventType.RUN_STARTED, data: {}, seq: 2, run_id: 'r1', session_id: 'two-run' },
    { type: EventType.USER_MESSAGE, data: { content: '第一轮' }, seq: 3, run_id: 'r1', step_id: 1, session_id: 'two-run' },
    { type: EventType.RUN_COMPLETED, data: {}, seq: 4, run_id: 'r1', session_id: 'two-run' },
    { type: EventType.RUN_STARTED, data: {}, seq: 5, run_id: 'r2', session_id: 'two-run' },
    { type: EventType.MODEL_DELTA, data: { delta: 'x' }, seq: 6, run_id: 'r2', step_id: 1, session_id: 'two-run' },
  ];
  for (const ev of evts) s = applyEvent(s, ev);
  return s;
}

const noop = () => {};
/** #183：StepDetail 新增面板视图状态 + 动作入口（状态归 App）。本文件的用例不关心
 *  面板几何，给一份缺省（未钉住/未整页/320px/预览开）。 */
const panelProps = {
  panel: { pinned: false, expanded: false, width: 320, peekOpen: true },
  onPanelAction: noop,
} as const;
const rowCount = (html: string) => (html.match(/timeline-row/g) || []).length;
const renderTab = (conv: ConversationState) =>
  // SSR 会在插值文本节点间插入 <!-- --> 分隔注释——断言前剥离，避免误报
  renderToString(createElement(TimelineTab, { conversation: conv, onFocusEvent: noop })).replaceAll('<!-- -->', '');

describe('TimelineTab 尾窗裁剪', () => {
  it('小会话（≤ 窗口）：全量渲染，无折叠条', () => {
    const html = renderTab(bigConversation(50));
    expect(rowCount(html)).toBe(50);
    expect(html).not.toContain('timeline-window-bar');
  });

  it(`大会话（${TIMELINE_WINDOW_DEFAULT * 3} 事件）：只渲染最近 ${TIMELINE_WINDOW_DEFAULT} 行 + 折叠条`, () => {
    const total = TIMELINE_WINDOW_DEFAULT * 3;
    const html = renderTab(bigConversation(total));
    expect(rowCount(html)).toBe(TIMELINE_WINDOW_DEFAULT);
    expect(html).toContain('timeline-window-bar');
    expect(html).toContain(`共 ${total} 条`);
    // 窗口是"最近"而非"最早"——最后一行必须在
    expect(html).toContain(`>${total - 1}<`);
    // 最早一行被折叠
    expect(html).not.toContain('>--1<');
  });

  it('窗口行 key 用全局序号：扩展窗口后既有行 identity 稳定（append-only 契约）', () => {
    // key = hidden + i：对 2000 事件窗口 200，最后可见行全局序号 1999
    const html = renderTab(bigConversation(2000));
    expect(html).toContain(`>${2000 - 1}<`);
    expect(rowCount(html)).toBe(TIMELINE_WINDOW_DEFAULT);
  });

  it(`步长常量：${TIMELINE_WINDOW_DEFAULT} / ${TIMELINE_WINDOW_STEP}`, () => {
    expect(TIMELINE_WINDOW_DEFAULT).toBe(200);
    expect(TIMELINE_WINDOW_STEP).toBe(500);
  });
});

// ── C2：ToolEventSections Input/Output/Raw 标签条化 ──

import { ToolEventSections } from './StepDetail';
import type { ToolCall } from '../types';

const toolBase: ToolCall = {
  tool_call_id: 'c1',
  name: 'bash',
  args: { command: 'echo hi' },
  status: 'success',
  result: { exit_code: 0, stdout: 'hi' },
  started_at: '2026-09-05T10:00:00Z',
  completed_at: '2026-09-05T10:00:01Z',
};

const renderTool = (tool: ToolCall) =>
  renderToString(createElement(ToolEventSections, { tool })).replaceAll('<!-- -->', '');

describe('ToolEventSections 标签条（PRD §8.4 四段：Overview/Input/Output/Raw）', () => {
  it('有 result 时默认 Output 选中（看结果优先）', () => {
    const html = renderTool(toolBase);
    expect(html).toContain('io-tabs');
    expect(html).toContain('>Overview<');
    expect(html).toContain('>Input<');
    expect(html).toContain('>Output<');
    // 默认 Output 选中（aria-selected）
    expect(html).toMatch(/aria-selected="true"[^>]*>Output</);
    // Output 面板内容在（exit_code 键来自 result 对象树）
    expect(html).toContain('exit_code');
    // Input 面板默认不渲染其 args 内容（command 是 args 独有键）
    expect(html).not.toContain('>command<');
  });

  it('无 result（运行中）：默认 Overview，元信息可见且无 Output 标签', () => {
    const html = renderTool({ ...toolBase, result: undefined, status: 'running' });
    expect(html).toContain('>Overview<');
    expect(html).toMatch(/aria-selected="true"[^>]*>Overview</);
    expect(html).not.toContain('>Output<');
    // Overview 元信息：tool_call_id / status
    expect(html).toContain('tool_call_id');
    expect(html).toContain('running');
  });

  it('有 raw_call/raw_result 才出现 Raw 标签；raw 面板渲染原始事件树', () => {
    const noRaw = renderTool(toolBase);
    expect(noRaw).not.toContain('>Raw<');
    const withRaw = renderTool({
      ...toolBase,
      raw_call: { type: 'tool/call', data: { x: 1 } },
      raw_result: { type: 'tool/result', data: { y: 2 } },
    } as ToolCall);
    expect(withRaw).toContain('>Raw<');
  });
});

// ── C4：Timeline 行 hover 时间戳浮层 ──

import { ChangesTab, formatEventTooltip, StepDetail } from './StepDetail';

describe('formatEventTooltip（C4）', () => {
  it('time + step 齐全：两行（完整时间戳含毫秒 + step）', () => {
    const lines = formatEventTooltip({
      type: EventType.TOOL_CALL, data: {}, seq: 3, run_id: 'r',
      step_id: 9, session_id: 's', time: '2026-09-05T13:17:06.288+08:00',
    } as Parameters<typeof formatEventTooltip>[0]);
    expect(lines).toHaveLength(2);
    expect(lines[0]).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$/);
    expect(lines[1]).toBe('step 9');
  });

  it('time 缺失：只保留 step 行', () => {
    const lines = formatEventTooltip({
      type: EventType.RUN_STARTED, data: {}, seq: 1, run_id: 'r', step_id: 2, session_id: 's', time: undefined,
    } as Parameters<typeof formatEventTooltip>[0]);
    expect(lines).toEqual(['step 2']);
  });

  it('非法 time 字符串：不产出时间行', () => {
    const lines = formatEventTooltip({
      type: EventType.RUN_STARTED, data: {}, seq: 1, run_id: 'r', step_id: null, session_id: 's', time: 'not-a-date',
    } as Parameters<typeof formatEventTooltip>[0]);
    expect(lines).toEqual([]);
  });

  it('step_id 与 time 都缺：空数组（调用方不渲染浮层）', () => {
    const lines = formatEventTooltip({
      type: EventType.RUN_STARTED, data: {}, seq: 1, run_id: 'r', step_id: null, session_id: 's', time: undefined,
    } as Parameters<typeof formatEventTooltip>[0]);
    expect(lines).toEqual([]);
  });

  it('step_id === 0：按合法数值渲染 step 行（0 不是哨兵，null 才是）', () => {
    const lines = formatEventTooltip({
      type: EventType.RUN_STARTED, data: {}, seq: 1, run_id: 'r', step_id: 0, session_id: 's', time: undefined,
    } as Parameters<typeof formatEventTooltip>[0]);
    expect(lines).toEqual(['step 0']);
  });

  it('step_id 键缺失（GET 历史事件省略 null 键的真实线上形状）：不产出 step 行，绝不渲染 "undefined"', () => {
    // GET /events 走 SessionEvent.to_dict：值为 None 的字段整个键省略（不是 null）。
    // 实测 GET /api/sessions/<id>/events 的 seq 0/1/2 均 'step_id' in e === false。
    // 编译期锁：该字面量刻意不带 step_id——类型若改回必填，tsc 在此变红。
    const e: AgentEvent = {
      type: EventType.RUN_STARTED, data: {}, seq: 1, run_id: 'r', session_id: 's',
    };
    expect('step_id' in e).toBe(false);
    expect(formatEventTooltip(e)).toEqual([]);
    const withTime = formatEventTooltip({ ...e, time: '2026-09-05T13:17:06.288+08:00' });
    expect(withTime).toHaveLength(1);
    expect(withTime[0]).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$/);
    expect(withTime.join(' ')).not.toContain('undefined');
  });
});

// ── BUG-008：事件详情 Overview 的 step 行必须按「可能缺失」处理 ──

describe('EventInspector Overview（BUG-008）', () => {
  const renderEvent = (event: AgentEvent) =>
    renderToString(createElement(StepDetail, {
      conversation: initConversation('b'),
      streaming: false,
      focus: { kind: 'event', event },
      onFocusRun: noop,
      onFocusTool: noop,
      onFocusEvent: noop,
      ...panelProps,
    })).replaceAll('<!-- -->', '');
  const baseEvent: AgentEvent = { type: EventType.RUN_STARTED, data: {}, seq: 1, run_id: 'r', session_id: 's', event_id: 'e1' };
  const withStep = (step_id: number | null) => ({ ...baseEvent, step_id });

  it('step_id 键缺失：不渲染空的 step 幽灵行（否则出现「step」后跟空值）', () => {
    const html = renderEvent(baseEvent);
    expect(html).not.toContain('>step<');
    // 阳性对照——面板整体确实渲染了（避免「整个面板没渲染」这种空洞绿）
    expect(html).toContain('run/started');
    expect(html).toContain('>seq<');
  });

  it('同一渲染点的相邻语义：number 渲染 step 行（含值 7），null 哨兵不渲染（0 与数值不是哨兵）', () => {
    const withStepHtml = renderEvent(withStep(7));
    expect(withStepHtml).toContain('>step<');
    expect(withStepHtml).toContain('>7<');
    expect(renderEvent(withStep(0))).toContain('>step<');
    expect(renderEvent(withStep(0))).toContain('>0<');
    expect(renderEvent(withStep(null))).not.toContain('>step<');
  });
});

// ── 修复批（frontend-B）：child focus 不得被「非 run」早退分支吞掉 ──
// 76e9993 回归：委派钻取进 Inspector 即 TypeError（focus.event 对 child 不存在），
// 专用 child 面板成死代码。SSR 契约：child focus 渲染专用面板而非崩溃。
describe('StepDetail child focus（v2 PRD §10.5 委派钻取）', () => {
  const conv: ConversationState = initConversation('parent');

  it('child focus 渲染专用子会话面板（不落事件级早退分支、不崩溃）', () => {
    const html = renderToString(createElement(StepDetail, {
      conversation: conv,
      streaming: false,
      focus: { kind: 'child', childSessionId: 'c1234567890', target: 'research_review' },
      onFocusRun: noop,
      onFocusTool: noop,
      onFocusEvent: noop,
      ...panelProps,
    })).replaceAll('<!-- -->', '');
    expect(html).toContain('子会话');
    expect(html).toContain('research_review');
    expect(html).toContain('child-back-btn');
  });
});

describe('TimelineTab run 分组头（UI-03）', () => {
  it('双 run 会话：两个分组头，序数/状态徽章/计数正确', () => {
    const html = renderTab(twoRunConversation());
    const headers = (html.match(/tl-run-header/g) || []).length;
    expect(headers).toBe(2);
    expect(html).toContain('Run 1');
    expect(html).toContain('Run 2');
    expect(html).toContain('run-badge-completed');
    expect(html).toContain('run-badge-running');
    // 第一组 4 事件（session/started 归入 r1 组）；打在 .tl-run-count 上防 tl-seq 误命中
    expect(html).toMatch(/tl-run-header[^]*?tl-run-count[^>]*>4 事件</);
  });

  it(`尾窗裁剪（窗口 ${TIMELINE_WINDOW_DEFAULT}）：窗口外的组头不渲染，窗口内组头保留`, () => {
    // 双 run 会话仅 6 事件 < 窗口——先造一个尾部大 run 的长会话：
    // run1 完整（3 事件，落在窗口外）+ run2 追加大量事件占满窗口
    let s = initConversation('long');
    s = applyEvent(s, { type: EventType.RUN_STARTED, data: {}, seq: 1, run_id: 'r1', session_id: 'long' });
    s = applyEvent(s, { type: EventType.RUN_COMPLETED, data: {}, seq: 2, run_id: 'r1', session_id: 'long' });
    for (let i = 0; i < TIMELINE_WINDOW_DEFAULT; i++) {
      s = applyEvent(s, { type: EventType.MODEL_DELTA, data: { delta: 'x' }, seq: 3 + i, run_id: 'r2', step_id: 1, session_id: 'long' });
    }
    const html = renderTab(s);
    // r1 的两条已滚出窗口 → 其组头不渲染；r2 组头在场且**保留真序号 Run 2**
    //（序数来自全会话遍历——滚掉前面的 run 后把 r2 重标成 Run 1 正是本票要防的事故）
    expect(html).not.toContain('run-badge-completed');
    expect(html).toContain('tl-run-header');
    expect(html).toContain('>Run 2</span>');
    expect(html).not.toContain('>Run 1</span>');
  });
});

// ── #183 AC9 / #186 AC3：Inspector 的 Changes tab 与中心列共用同一个 diff 渲染器 ──

describe('ChangesTab 使用 DiffBlock（diff 只有一份渲染器）', () => {
  const editTool = (over: Partial<ToolCall>): ToolCall => ({
    tool_call_id: 'tc-diff',
    name: 'edit',
    args: { path: 'src/a.ts' },
    status: 'success',
    result: { ok: true },
    diff: { before: 'old\n', after: 'new\n', truncated: false },
    ...over,
  });

  const renderChanges = (tools: ToolCall[]) =>
    renderToString(createElement(ChangesTab, { tools })).replaceAll('<!-- -->', '');

  it('普通 diff：走 DiffBlock 的结构（.diff-block + .diff-cols），不是自己内联的裸 .diff-cols', () => {
    const html = renderChanges([editTool({})]);
    expect(html).toContain('diff-block');
    expect(html).toContain('变更前');
    expect(html).toContain('变更后');
    expect(html).toContain('old');
    expect(html).toContain('new');
  });

  it('归档 diff：渲染归档占位，**不把 marker 原文当文件内容**（收敛前这里会显示假内容）', () => {
    const marker = '内容过大已归档。use read_artifact(0123456789abcdef) 查看全文';
    const html = renderChanges([
      editTool({
        diff: {
          before: marker,
          after: marker,
          truncated: false,
          archived: true,
          artifactId: '0123456789abcdef',
        },
      }),
    ]);
    expect(html).toContain('diff-archived');
    expect(html).toContain('Diff 内容已归档');
    // 关键断言：marker 那段文字不得出现在 diff 正文里
    expect(html).not.toContain('查看全文');
    expect(html).not.toContain('>变更前<');
  });

  it('截断 diff：给出"已截断"标记（与中心列同一文案）', () => {
    const html = renderChanges([
      editTool({ diff: { before: 'a\n', after: 'b\n', truncated: true } }),
    ]);
    expect(html).toContain('内容过长，已截断显示');
  });

  it('无 diff 的工具不进这个面（bash 的输出不是文件变更）', () => {
    const html = renderChanges([
      { tool_call_id: 'b', name: 'bash', args: { command: 'echo hi' }, status: 'success' } as ToolCall,
    ]);
    expect(html).toContain('本次会话未产生文件变更');
  });
});
