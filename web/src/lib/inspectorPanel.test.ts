/** `lib/inspectorPanel.ts`（#183 Inspector peek/钉住/整页/拖宽）纯函数测试。
 *
 *  本仓组件测试是 SSR、交互靠 e2e，所以三条"规则本身"必须在这里钉死：
 *  - 拖宽的夹取（320→480，且不得压垮中心列 —— AC6）；
 *  - ↑/↓ 的边界（不环绕）；
 *  - Space 快按/按住的判定与 Esc 的层级（AC2、AC7 的可达性语义）。
 *  它们是"看起来能用但语义错"的重灾区：夹取写成 `Math.min` 就会静默把中心列压没；
 *  环绕翻页会让"按到底"跳回顶部；Esc 不分层会让"关预览"顺手把面板收起。
 */

import { describe, expect, it } from 'vitest';
import {
  CENTER_MIN_W,
  INSPECTOR_MAX_W,
  INSPECTOR_MIN_W,
  PEEK_TAP_MS,
  clampInspectorWidth,
  escAction,
  eventKey,
  nextSelectionIndex,
  spaceReleaseCloses,
  toolKey,
} from './inspectorPanel';

describe('clampInspectorWidth — 拖宽范围与中心列保护（AC6）', () => {
  it('正常区间内原样（四舍五入到整像素）', () => {
    expect(clampInspectorWidth(400, 1440)).toBe(400);
    expect(clampInspectorWidth(400.4, 1440)).toBe(400);
    expect(clampInspectorWidth(400.6, 1440)).toBe(401);
  });

  it('上限 480：拖过头也只到 480', () => {
    expect(clampInspectorWidth(900, 1440)).toBe(INSPECTOR_MAX_W);
  });

  it('下限 320：往左拖过头也不小于 320', () => {
    expect(clampInspectorWidth(120, 1440)).toBe(INSPECTOR_MIN_W);
  });

  it('中心列保护：可用宽度不够时，上限压到 available - CENTER_MIN_W', () => {
    // 中心列 + 面板合计只有 700 → 面板最多 700-360 = 340（而不是 480）
    expect(clampInspectorWidth(480, 700)).toBe(700 - CENTER_MIN_W);
    expect(clampInspectorWidth(900, 700)).toBe(340);
  });

  it('可用宽度小到连下限都保不住时，下限优先（面板本身必须可用）', () => {
    // 700 是 <1200px 的折叠区，但即便真的算到这里，也不能返回一个比下限还小的值
    expect(clampInspectorWidth(480, 500)).toBe(INSPECTOR_MIN_W);
  });
});

describe('nextSelectionIndex — 清单内 ↑/↓ 移动（AC1/AC2）', () => {
  it('常规移动 ±1', () => {
    expect(nextSelectionIndex(2, 1, 10)).toBe(3);
    expect(nextSelectionIndex(2, -1, 10)).toBe(1);
  });

  it('不环绕：两端停在原处', () => {
    expect(nextSelectionIndex(0, -1, 10)).toBe(0);
    expect(nextSelectionIndex(9, 1, 10)).toBe(9);
  });

  it('空清单 → -1（没有可选项，调用方据此不改变选中）', () => {
    expect(nextSelectionIndex(0, 1, 0)).toBe(-1);
    expect(nextSelectionIndex(-1, -1, 0)).toBe(-1);
  });

  it('尚未选中：↓ 选第一条、↑ 选最后一条（与常见列表一致）', () => {
    expect(nextSelectionIndex(-1, 1, 10)).toBe(0);
    expect(nextSelectionIndex(-1, -1, 10)).toBe(9);
  });
});

describe('Space 快按/按住（AC2：快按=保持打开，按住=松手关闭）', () => {
  it('阈值本身不算「按住」（边界取"快按"，不因一次抖动就关）', () => {
    expect(spaceReleaseCloses(PEEK_TAP_MS)).toBe(false);
    expect(spaceReleaseCloses(PEEK_TAP_MS - 1)).toBe(false);
  });

  it('超过阈值才算按住 → 松手关闭', () => {
    expect(spaceReleaseCloses(PEEK_TAP_MS + 1)).toBe(true);
    expect(spaceReleaseCloses(1500)).toBe(true);
  });

  it('阈值是一个人类可感的"快按"时长（150–400ms），不是随手写的大数', () => {
    expect(PEEK_TAP_MS).toBeGreaterThanOrEqual(150);
    expect(PEEK_TAP_MS).toBeLessThanOrEqual(400);
  });
});

describe('escAction — Esc 的层级（AC2/AC5/AC7）', () => {
  it('整页优先退回（整页时 Esc 不该把面板整个收掉，那会连"退回"都做不到）', () => {
    expect(escAction({ expanded: true, peekOpen: true })).toBe('exit-fullpage');
    expect(escAction({ expanded: true, peekOpen: false })).toBe('exit-fullpage');
  });

  it('有预览时先关预览（面板与清单留在原地）', () => {
    expect(escAction({ expanded: false, peekOpen: true })).toBe('close-peek');
  });

  it('都没有时才收起面板（既有冻结语义：收起不卸载）', () => {
    expect(escAction({ expanded: false, peekOpen: false })).toBe('collapse');
  });
});

describe('eventKey / toolKey — 清单行的身份（AC1 选中项与行的等值比较）', () => {
  it('有 event_id 就用它（与 session/run 无关）', () => {
    const a = { event_id: 'e1', session_id: 's1', run_id: 'r1', seq: 1 };
    const b = { event_id: 'e1', session_id: 's9', run_id: 'r9', seq: 99 };
    expect(eventKey(a)).toBe(eventKey(b));
    expect(eventKey(a)).toBe('event:e1');
  });

  it('event_id 缺失：session/run/seq 组合兜底，同一事件两次计算相等', () => {
    const e = { session_id: 's1', run_id: 'r1', seq: 3 };
    expect(eventKey(e)).toBe(eventKey({ ...e }));
    expect(eventKey(e)).not.toBe(eventKey({ ...e, seq: 4 }));
    expect(eventKey(e)).toBe('event:s1:r1:3');
  });

  it('事件字段整个缺失（GET 历史省略 null 键）也不产出 "undefined" 字样', () => {
    const k = eventKey({});
    expect(k).toBe('event:::');   // 空值参与拼接，但绝不出现 undefined
    expect(k).not.toContain('undefined');
  });

  it('toolKey 用 tool_call_id（同一个工具调用在 Timeline/Overview/Terminal 三处同身份）', () => {
    expect(toolKey({ tool_call_id: 'tc1' })).toBe('tool:tc1');
    expect(toolKey({ tool_call_id: 'tc1' })).toBe(toolKey({ tool_call_id: 'tc1' }));
    expect(toolKey({ tool_call_id: 'tc1' })).not.toBe(toolKey({ tool_call_id: 'tc2' }));
  });
});
