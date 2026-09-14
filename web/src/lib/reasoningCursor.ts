/** lib/reasoningCursor — 折叠前读视口的游标推进策略（#95，S3，规格 03 §7.3）。
 *
 * 纯函数、无 DOM：组件层用 rAF 按帧调用 advanceCursor，把结果映射为
 * transform（合成器友好，规格禁 per-token 动画与打字机伪造）。游标是
 * presentation-only 状态——canonical 块缓冲是投影真相，这里从不改写它。
 * 阈值均为 benchmark/UX tuning 参数（规格原文），不是产品冻结值。 */

import type { ReasoningStatus } from '../types';

export type { ReasoningStatus };

/** 基速 ≈48 字/秒（朗读速度量级）——"calm reading window, not a ticker tape"。 */
export const BASE_CPS = 48;
/** 软积压阈值：backlog 超过后线性加速追平（视口不得无限落后于流）。 */
export const BACKLOG_SOFT = 240;
/** 加速封顶：追平有界，也不得变成刷屏。 */
export const MAX_SPEEDUP = 6;
/** 终态收尾倍速：completed/interrupted 在有界时间内定格到末尾（规格 03 §7.3
 *  "on block completion, settle within a short bounded interval"）。 */
export const TERMINAL_SPEEDUP = 8;
/** reduced-motion 降级：无 rAF 动画时每次文本变化的离散前读步长（字符）。 */
export const REDUCED_MOTION_STEP_CHARS = 80;
/** 单帧 dt 上限（ms）：后台标签页 rAF 暂停，回前台首帧 dt 可能是数十秒——
 *  不设上限会把「有界加速」退化成一次性大跳（spec 03 §7.3 bounded catch-up）。
 *  250ms ≈ 正常帧的 15 倍，追赶仍快、但被钳制在策略速度域内。 */
export const MAX_FRAME_DT_MS = 250;

/** 由 pos 推进 dtMs 后的游标位置（字符偏移；可为小数，渲染按比例映射）。 */
export function advanceCursor(
  pos: number,
  textLen: number,
  dtMs: number,
  status: ReasoningStatus,
): number {
  if (textLen <= 0) return 0;
  if (pos >= textLen) return textLen;
  if (dtMs <= 0) return pos;
  const backlog = textLen - pos;
  let cps = BASE_CPS;
  if (status !== 'streaming') cps *= TERMINAL_SPEEDUP;
  else if (backlog > BACKLOG_SOFT) cps *= Math.min(MAX_SPEEDUP, 1 + backlog / BACKLOG_SOFT);
  return Math.min(textLen, pos + cps * (dtMs / 1000));
}
