/** lib/disclosure — Progressive Disclosure L0-L2 状态机（ADR-0014 D2，PRD §6）。
 *
 * 双层模型：全局 density 决定每事件的**默认**展开级，用户手动展开进入
 * override map（手动优先于全局，切 density 不丢——PRD §6 规则）。
 * L3 不在本状态机内：L3 = Inspect 进 Inspector（联动，App 层 selected 状态）。
 *
 * 契约用纯函数锁（useSession.test 同款纪律：React 壳只做 useState 胶水）。
 * override 随 session 切换清空（hook 壳 effect），不跨会话记忆。
 */

import { useCallback, useEffect, useState } from 'react';
import type { TraceDensity } from './density';
import type { ReasoningStatus } from './reasoningCursor';

/** 中间主区展开级：L0 摘要行 / L1 inline detail / L2 advanced inline。
 *  L3（Inspector Raw）不是 inline 级，走联动选中。 */
export type DisclosureLevel = 0 | 1 | 2;

/** 全局 density → 默认展开级（PRD §7 四档语义）。 */
export function defaultLevelFor(density: TraceDensity): DisclosureLevel {
  switch (density) {
    case 'compact':
      return 0;
    case 'balanced':
      return 0;
    case 'detailed':
      return 1;
    case 'raw':
      return 2;
  }
}

/** 稳定事件 key：工具用 tool_call_id（跨重渲染稳定）；模型段用 step+index。
 *  命名空间前缀隔离两类 id 空间。 */
export function toolEventKey(toolCallId: string): string {
  return `tool:${toolCallId}`;
}

export function modelEventKey(stepId: number, segmentIndex: number): string {
  return `model:${stepId}:${segmentIndex}`;
}

/** 不可变 override map：set 后返回新 map（React 状态约定）。 */
export function applyOverride(
  overrides: ReadonlyMap<string, DisclosureLevel>,
  key: string,
  level: DisclosureLevel,
): ReadonlyMap<string, DisclosureLevel> {
  const next = new Map(overrides);
  next.set(key, level);
  return next;
}

/** 生效级 = 手动 override 优先，否则全局 density 默认（PRD §6："手动展开
 *  状态优先于全局模式"，切换四档不丢手动展开）。 */
export function resolveLevel(
  overrides: ReadonlyMap<string, DisclosureLevel>,
  key: string,
  density: TraceDensity,
): DisclosureLevel {
  return overrides.get(key) ?? defaultLevelFor(density);
}

/** 点击循环下一级：L0→L1→L2→L0（PRD §6"点击事件展开 / 再次展开 View details"）。 */
export function nextLevel(level: DisclosureLevel): DisclosureLevel {
  return ((level + 1) % 3) as DisclosureLevel;
}

/** Disclosure 消费面（Conversation/ToolCard props 类型）。 */
export interface Disclosure {
  /** 事件的生效级：override 优先，否则全局 density 默认。 */
  levelFor: (key: string, density: TraceDensity) => DisclosureLevel;
  /** 设置手动 override（点击事件行循环 L0→L1→L2→L0 时调用）。 */
  setLevel: (key: string, level: DisclosureLevel) => void;
}

/** 逐会话的手动展开状态（hook 壳：sessionKey 变化即清空）。 */
export function useDisclosure(sessionKey: string | null): Disclosure {
  const [overrides, setOverrides] = useState<ReadonlyMap<string, DisclosureLevel>>(() => new Map());

  useEffect(() => {
    setOverrides(new Map());
  }, [sessionKey]);

  const setLevel = useCallback((key: string, level: DisclosureLevel) => {
    setOverrides((prev) => applyOverride(prev, key, level));
  }, []);

  const levelFor = useCallback(
    (key: string, density: TraceDensity): DisclosureLevel => resolveLevel(overrides, key, density),
    [overrides],
  );

  return { levelFor, setLevel };
}

// ── T2（#95）reasoning 自动开合（S6/S7，规格 03 §7.5 DisclosureState）──

/** 自动规则：streaming 且非 compact → 开（Balanced/Detailed 默认自动展开）；
 *  其余 → 收（完成自动收、interrupted 收、compact 一行实况）。 */
export function reasoningIsOpen(
  overrides: ReadonlyMap<string, boolean>,
  blockId: string,
  status: ReasoningStatus,
  density: TraceDensity,
): boolean {
  const manual = overrides.get(blockId);
  if (manual !== undefined) return manual;
  return status === 'streaming' && density !== 'compact';
}

/** 手动开合：写入 override 即 user_interacted=true——此后 delta/完成/密度切换
 *  都不改写该块（S7：手动折叠期间流继续，绝不重开）。 */
export function setReasoningOpen(
  overrides: ReadonlyMap<string, boolean>,
  blockId: string,
  open: boolean,
): ReadonlyMap<string, boolean> {
  const next = new Map(overrides);
  next.set(blockId, open);
  return next;
}

/** 逐会话的 reasoning 开合状态（override 随 sessionKey 变化清空——
 *  呈现状态是页内局部的，不进持久真相，规格 01 §17）。 */
export function useReasoningDisclosure(sessionKey: string | null, density: TraceDensity) {
  const [overrides, setOverrides] = useState<ReadonlyMap<string, boolean>>(() => new Map());

  useEffect(() => {
    setOverrides(new Map());
  }, [sessionKey]);

  const isOpen = useCallback(
    (blockId: string, status: ReasoningStatus) =>
      reasoningIsOpen(overrides, blockId, status, density),
    [overrides, density],
  );

  const toggle = useCallback((blockId: string, currentOpen: boolean) => {
    setOverrides((prev) => setReasoningOpen(prev, blockId, !currentOpen));
  }, []);

  return { isOpen, toggle };
}
