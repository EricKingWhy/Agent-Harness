/** followLatest 纯函数契约（#95，S8，规格 03 §17 跟随原语的状态机核）。 */

import { describe, expect, it } from 'vitest';
import { FOLLOW_THRESHOLD_PX, followOnJump, followOnScroll, nearBottom, nestedChainAbsorbs, wheelDeltaPixels } from './followLatest';

describe('nearBottom — 贴底谓词', () => {
  it('距底 < 阈值 → true；= 阈值 → false（严格小于）', () => {
    const h = 1000, ch = 400;
    expect(nearBottom(h, h - ch - FOLLOW_THRESHOLD_PX + 1, ch)).toBe(true);
    expect(nearBottom(h, h - ch - FOLLOW_THRESHOLD_PX, ch)).toBe(false);
  });

  it('精确贴底（差 0）→ true', () => {
    expect(nearBottom(1000, 600, 400)).toBe(true);
  });

  it('自定义阈值生效', () => {
    expect(nearBottom(1000, 500, 400, 101)).toBe(true);
    expect(nearBottom(1000, 500, 400, 99)).toBe(false);
  });
});

describe('followOnScroll / followOnJump — 跟随状态转移', () => {
  it('贴底 → 回到跟随底态（suspended 解除）', () => {
    expect(followOnScroll({ following: false, suspended: true }, true, true)).toEqual({
      following: true, suspended: false,
    });
  });

  it('脱离底部且流式中 → suspended（S8：上滚停跟随 + 浮现跳到最新）', () => {
    expect(followOnScroll({ following: true, suspended: false }, false, true)).toEqual({
      following: false, suspended: true,
    });
  });

  it('脱离底部但非流式 → 不进入 suspended（无「最新」可跳）', () => {
    expect(followOnScroll({ following: true, suspended: false }, false, false)).toEqual({
      following: false, suspended: false,
    });
  });

  it('jump → 底态（S8：回底并恢复跟随）', () => {
    expect(followOnJump()).toEqual({ following: true, suspended: false });
  });
});

describe('wheelDeltaPixels — deltaMode 折算（BUG-003 嵌套容器判据的输入）', () => {
  it('deltaMode 0（像素，Chrome 默认）→ 原值取正', () => {
    expect(wheelDeltaPixels(-120, 0, 800)).toBe(120);
  });

  it('deltaMode 1（Firefox 行）→ ×16px/行', () => {
    expect(wheelDeltaPixels(-3, 1, 800)).toBe(48);
  });

  it('deltaMode 2（页）→ ×视口高', () => {
    expect(wheelDeltaPixels(-1, 2, 800)).toBe(800);
  });

  it('未知 deltaMode（>2）按「页」折算，而不是当成像素', () => {
    // 估小是安全侧，但也不能把未知模式当像素——1 页的物理位移远大于 1px，
    // 当成像素会严重估小、每次嵌套上滚都误判成「没吃下」而弹浮标。
    expect(wheelDeltaPixels(-1, 3, 800)).toBe(800);
  });

  it('向下滚 / 零位移 → 0（不产生「需要被吃下」的量）', () => {
    expect(wheelDeltaPixels(120, 0, 800)).toBe(0);
    expect(wheelDeltaPixels(0, 0, 800)).toBe(0);
  });
});

describe('nestedChainAbsorbs — 嵌套滚动链能否吃下这次上滚', () => {
  it('单层余量足够 → true（内层自己吃下，外层不动）', () => {
    expect(nestedChainAbsorbs([200], 120)).toBe(true);
  });

  it('单层余量不足 → false（外层会被推动，必须释放跟随）', () => {
    expect(nestedChainAbsorbs([50], 120)).toBe(false);
  });

  it('余量恰好等于位移 → true（边界含等号）', () => {
    expect(nestedChainAbsorbs([120], 120)).toBe(true);
  });

  it('内外层分担：合计够即 true——只看最内层会把这一幕误判为「外层要动」', () => {
    expect(nestedChainAbsorbs([40, 80], 120)).toBe(true);
  });

  it('链上都是 0（已滚到顶）→ 除非位移为 0，否则 false', () => {
    expect(nestedChainAbsorbs([0, 0], 120)).toBe(false);
    expect(nestedChainAbsorbs([0, 0], 0)).toBe(true);
  });

  it('空链（wheel 目标就是对话容器本身）→ 只有零位移才 true', () => {
    expect(nestedChainAbsorbs([], 1)).toBe(false);
    expect(nestedChainAbsorbs([], 0)).toBe(true);
  });
});
