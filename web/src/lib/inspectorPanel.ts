/** Inspector 面板的几何与键位**规则**（#183）：面板宽度、清单选中移动、peek 开合。
 *
 *  为什么单独成模块：这些规则的报告方式只有"纯函数 + 逐条断言"（本仓组件测试是
 *  SSR、交互靠 e2e），而它们恰好是"看起来能用、语义却错"的重灾区——
 *  - 夹取写成 `Math.min(MAX, desired)` 会静默把中心列压没（AC6 的"不得压垮"）；
 *  - ↑/↓ 环绕会让"按到底"突然跳回顶部（AC1 的"实时跟随"变成惊吓）；
 *  - Esc 不分层会让"关预览"顺手把整个面板收掉（AC2 的"关闭不卸载"）。
 *
 *  全部是**视图状态**：宽度/钉住/整页都不持久化（不变量 #22 "Panel geometry is
 *  transient — NOT persisted"）。
 */

/** 面板宽度范围（PRD §3.7：320 → 480，不持久化）。 */
export const INSPECTOR_MIN_W = 320;
export const INSPECTOR_MAX_W = 480;

/** 中心列最小可用宽度：拖宽不得把它压垮（AC6）。 */
export const CENTER_MIN_W = 360;

/** Space「快按」阈值（ms）：≤ 阈值 = 保持打开，> 阈值 = 松手关闭（Linear peek）。 */
export const PEEK_TAP_MS = 250;

/**
 * 把目标宽度夹进 `[INSPECTOR_MIN_W, INSPECTOR_MAX_W]`，并保证中心列仍留
 * `CENTER_MIN_W`。
 *
 * `available` = 拖拽开始时「中心列 + 面板」的合计宽度（两个 flex 列的和，
 * 不含左侧 rail）。用实测值而不是 viewport 减去常量：rail 在窄屏会变成 56px，
 * 用常量算出来的上限在同一台机器上会随断点变化而错。
 *
 * 可用空间小到连下限都保不住时**下限优先**：面板本身必须可用；那种宽度下
 * 外层的窄屏折叠（<1200px）已经在管这件事，把一个 200px 的面板交出去只会更难用。
 *
 * ⚠ **这个上限在当前布局下恒等于 `INSPECTOR_MAX_W`**：三栏栅格只在 ≥1201px 生效，
 * 那里 `available = viewport − 240 ≥ 961`，`available − CENTER_MIN_W > 480`。
 * 所以中心列保护是一道**防御性**的夹取（换 rail 宽度、加第四栏、或提高
 * `INSPECTOR_MAX_W` 时它就会生效），目前**只由单元测试**覆盖——e2e 到不了那个宽度
 * （<1200px 的折叠分支把面板列写死成 280px）。改布局的人请同时看这条。
 */
export function clampInspectorWidth(desired: number, available: number): number {
  const ceiling = Math.min(INSPECTOR_MAX_W, available - CENTER_MIN_W);
  return Math.max(INSPECTOR_MIN_W, Math.min(ceiling, Math.round(desired)));
}

/**
 * ↑/↓ 在清单内移动选中项；越界**停在原处**（不环绕）。
 *
 * `current < 0`（还没有选中项）时：`↓` 选第一条、`↑` 选最后一条——与常见列表
 * 一致，也给"键盘先聚焦清单再按 ↓"一条自然的进入路径。
 */
export function nextSelectionIndex(current: number, delta: number, count: number): number {
  if (count <= 0) return -1;
  if (current < 0) return delta > 0 ? 0 : count - 1;
  return Math.max(0, Math.min(count - 1, current + delta));
}

/** Space 松手是否应当关闭 peek：只有「按住」才关（快按 = 保持打开）。 */
export function spaceReleaseCloses(heldMs: number): boolean {
  return heldMs > PEEK_TAP_MS;
}

/** Esc 在当前状态下该做哪一件事（层级：整页 → 预览 → 收起）。 */
export type EscAction = 'exit-fullpage' | 'close-peek' | 'collapse';

/**
 * Esc 的层级语义。
 *
 * 三层而不是一层：整页时 Esc 必须能先退回（否则"退回"只剩按钮一条路，而整页
 * 遮住了它自己的头部时用户会以为卡死）；有预览时 Esc 关预览而**不动面板**
 * （PRD §3.1 的关闭语义 + Linear peek）；都没有才收起面板（既有冻结语义：
 * 收起不卸载）。
 */
export function escAction(state: { expanded: boolean; peekOpen: boolean }): EscAction {
  if (state.expanded) return 'exit-fullpage';
  if (state.peekOpen) return 'close-peek';
  return 'collapse';
}

/**
 * 清单里"某一个事件"的身份：`event_id` 优先（后端已发），缺失时用
 * `session:run:seq` 组合兜底。
 *
 * 为什么不能只用 `seq`：GET 历史事件会把值为 null 的字段整个键省掉，`seq` 在
 * 前几条事件上可能是 `undefined`；而 hover Inspect 传来的事件有时还没进
 * `conversation.events`。身份只在"清单行 ↔ 选中项"之间做等值比较，所以只要
 * 同一事件的两次计算结果相同即可——上面两个来源都用同一份字段，就成立。
 */
export function eventKey(e: {
  event_id?: string | null;
  session_id?: string;
  run_id?: string | null;
  seq?: number | null;
}): string {
  if (e.event_id) return `event:${e.event_id}`;
  return `event:${e.session_id ?? ''}:${e.run_id ?? ''}:${e.seq ?? ''}`;
}

/** 清单里"某一次工具调用"的身份：`tool_call_id` 全局唯一，直接用它。 */
export function toolKey(t: { tool_call_id: string }): string {
  return `tool:${t.tool_call_id}`;
}
