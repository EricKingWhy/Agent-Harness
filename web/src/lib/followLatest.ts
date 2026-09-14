/** lib/followLatest — 贴底跟随原语的纯函数核（#95，S8，规格 03 §17）。
 *
 * 「跟随 / 上滚脱离 / 跳到最新」三态的转移逻辑收在这里锁测试；组件层
 * （ReasoningBlock ExpandedBody、ToolCard ToolOutputStream）消费。推广为
 * 跨视图共享 useFollowLatest 原语的时机与形状收敛记 ADR-0016 议题
 * （T2 不引入抽象）。阈值是 tuning 参数。 */

import { useEffect } from 'react';

/** 贴底判定容差（px）。 */
export const FOLLOW_THRESHOLD_PX = 48;

/** 跟随状态：following = 新内容自动滚到底；suspended = 用户脱离，浮现「↓ 跳到最新」。 */
export interface FollowState {
  following: boolean;
  suspended: boolean;
}

export const FOLLOW_BOTTOM: FollowState = { following: true, suspended: false };

/** nearBottom 谓词：滚动容器是否贴底（严格小于容差）。 */
export function nearBottom(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  threshold: number = FOLLOW_THRESHOLD_PX,
): boolean {
  return scrollHeight - scrollTop - clientHeight < threshold;
}

/** scroll 事件转移：贴底即恢复跟随（suspended 解除）；脱离且流式中 → suspended；
 *  脱离但非流式 → 只停跟随，不浮现「跳到最新」（没有「最新」可跳）。 */
export function followOnScroll(prev: FollowState, near: boolean, streaming: boolean): FollowState {
  if (near) return FOLLOW_BOTTOM;
  return streaming
    ? { following: false, suspended: true }
    : { following: false, suspended: prev.suspended };
}

/** 「↓ 跳到最新」动作转移：回底并恢复跟随。 */
export function followOnJump(): FollowState {
  return FOLLOW_BOTTOM;
}

/** 流结束复位跟随（终态无「最新」可跳——suspended 浮标不得残留）。
 *  T3 由 Standards 轴 Duplicated Code finding 收敛：ToolOutputStream 与
 *  ReasoningBlock ExpandedBody 的同族转移，单一实现。 */
export function useFollowResetOnStop(
  streaming: boolean,
  followRef: { current: FollowState },
  setSuspended: (v: boolean) => void,
): void {
  useEffect(() => {
    if (!streaming) {
      followRef.current = FOLLOW_BOTTOM;
      setSuspended(false);
    }
  }, [streaming, setSuspended]);
}

/** 一次上滚（deltaY < 0）折合成需要被消费的像素。
 *
 *  `deltaMode` 只保证 `0` 是像素：Firefox 用 `1`（行）、少数路径用 `2`（页）。
 *  行按 16px、页按视口高折算——**估小的一侧永远安全**：估小了偏向「判定为没吃下
 *  → 释放跟随」，代价只是浮标多出现一次；估大了会误判成「嵌套容器吃下了」，
 *  于是外层已经被拽动、`following` 却仍为真，下一次 delta 把视口拉回底部
 *  （这正是 BUG-003 的原症状）。 */
export function wheelDeltaPixels(deltaY: number, deltaMode: number, viewportHeight: number): number {
  const raw = Math.max(0, -deltaY);
  if (deltaMode === 1) return raw * 16;
  if (deltaMode !== 0) return raw * viewportHeight;
  return raw;
}

/** 嵌套滚动链能否吃下这次上滚。
 *
 *  浏览器把一次 wheel 从最内层往外依次喂给各级滚动容器，只要它们**合计**的
 *  余量够，外层容器就不动。所以要累加链上各 scroller 的 `scrollTop`（各自还能
 *  继续上滚的余量）再和位移比——两种单容器判据都是错的：只看最内层会在内外层
 *  分担时误判「外层要动」（实际没动）而误脱离；「遇到第一个有余量的就算吃下」
 *  会在外层确实被推动时误判为不动（原症状）。
 *  `headrooms` 由组件层按 DOM 走链收集（此处不碰 DOM，便于锁测试）。
 *  外层容器自身的余量**不计入**：链吃不完的部分必然推动外层，就该释放跟随。 */
export function nestedChainAbsorbs(headrooms: number[], need: number): boolean {
  let available = 0;
  for (const h of headrooms) available += h;
  return available >= need;
}
