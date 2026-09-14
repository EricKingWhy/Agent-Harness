/** lib/eventValidate — 帧级形状校验（#94，spec 02 §14「Network events must be
 *  runtime-validated; TypeScript types alone are insufficient」）。
 *
 * 投影边界（applyEvent）的第一道闸，两层职责：
 *  1. 隔离：完全不可辨的帧（type 缺失/非字符串、data 非普通对象、seq 非有限数、
 *     整体非对象）→ quarantine，由调用方计入 unknown_events，绝不静默丢弃。
 *  2. 归一化：形状合法但可选字段缺失的帧（data 缺失、seq 缺失）补默认值，
 *     applyEvent 内部的 data.x 直取因此获得崩溃免疫。
 *
 * 刻意不做业务级深校验：未知可选字段 verbatim 保留（spec 02 §16 additive 宽容），
 * 各事件载荷语义仍由 projection 分支的 ?? 回退负责——本层只守「可辨、不崩」。 */

import type { AgentEvent } from '../types';

export type EventCheck = { ok: true; event: AgentEvent } | { ok: false };

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** 校验并归一化一帧。通过时返回 event——原对象 verbatim（含未知字段），
 *  仅当 data/seq 缺失时浅拷贝补默认值（不改动调用方对象）。 */
export function validateEvent(raw: unknown): EventCheck {
  if (!isPlainObject(raw)) return { ok: false };
  const { type, data, seq } = raw;
  if (typeof type !== 'string' || type === '') return { ok: false };
  if (data !== undefined && !isPlainObject(data)) return { ok: false };
  if (seq !== undefined && seq !== null && (typeof seq !== 'number' || !Number.isFinite(seq))) {
    return { ok: false };
  }
  let event = raw as unknown as AgentEvent;
  if (data === undefined || seq === undefined) {
    event = {
      ...raw,
      data: isPlainObject(data) ? data : {},
      seq: typeof seq === 'number' ? seq : null,
    } as unknown as AgentEvent;
  }
  return { ok: true, event };
}

/** 隔离记录：把被拒帧包成可渲染的 AgentEvent 形状——type 可辨则原样保留，
 *  否则统一标记 malformed/event；原帧整体存进 data.raw，未知面按 raw 行渲染，
 *  绝不伪造运行时事实。 */
export function quarantineRecord(raw: unknown): AgentEvent {
  const type =
    isPlainObject(raw) && typeof raw.type === 'string' && raw.type !== ''
      ? raw.type
      : 'malformed/event';
  return { type, data: { raw }, seq: null, run_id: null, step_id: null };
}
