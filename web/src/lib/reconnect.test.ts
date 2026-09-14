/** ReconnectController 契约测试——重连策略的**状态迁移**（深化 C1）。
 *
 *  decision 纯函数（decideStreamEnd / reconnectDelayMs）已在
 *  useSession.test.ts 经 re-export 路径锁住；本文件锁的是此前无测试的部分：
 *  额度什么时候涨、什么时候复位、单飞什么时候占用与释放。
 *
 *  最重要的一条是「重放不重置额度」（Spec 轴 P0）：悬空 run 每轮重连都是
 *  200 + 重放零新进展，若把重放帧当成进展就会再给三次额度 → 额度永不耗尽
 *  → give-up 不可达 → 无限重连、recover 入口永不出现。 */

import { describe, expect, it } from 'vitest';
import { MAX_RECONNECT_ATTEMPTS, ReconnectController, reconnectDelayMs } from './reconnect';

const req = (c: ReconnectController, over: Partial<Parameters<ReconnectController['request']>[0]> = {}) =>
  c.request({ sid: 's1', terminalSeen: false, lastAppliedSeq: 0, ...over });

describe('ReconnectController — 单飞与额度', () => {
  it('首次 request：占用单飞、额度 +1、返回退避参数', () => {
    const c = new ReconnectController();
    expect(req(c)).toEqual({ decision: 'reconnect', attempt: 1, delayMs: reconnectDelayMs(1) });
    expect(c.isPending).toBe(true);
    expect(c.attemptCount).toBe(1);
  });

  it('单飞中重复 request → null（不重复调度、不再消耗额度）', () => {
    const c = new ReconnectController();
    req(c);
    expect(req(c)).toBeNull();
    expect(c.attemptCount).toBe(1);
  });

  it('release 放单飞但**不**退额度——失败尝试必须计入（Spec P0）', () => {
    const c = new ReconnectController();
    req(c);
    c.release();
    expect(c.isPending).toBe(false);
    expect(c.attemptCount).toBe(1);
    expect(req(c)).toEqual({ decision: 'reconnect', attempt: 2, delayMs: reconnectDelayMs(2) });
  });

  it('额度耗尽 → give-up，且不再递增额度', () => {
    const c = new ReconnectController();
    for (let i = 0; i < MAX_RECONNECT_ATTEMPTS; i += 1) {
      c.release();
      expect(req(c)?.decision).toBe('reconnect');
    }
    c.release();
    expect(req(c)).toEqual({ decision: 'give-up' });
    expect(c.attemptCount).toBe(MAX_RECONNECT_ATTEMPTS);
    expect(c.isPending).toBe(false); // give-up 不占单飞
  });
});

describe('ReconnectController — 终态与 sid 未知的终局', () => {
  it('terminalSeen → migrate（终态已见，正常收尾）', () => {
    const c = new ReconnectController();
    expect(req(c, { terminalSeen: true })).toEqual({ decision: 'migrate' });
    expect(c.attemptCount).toBe(0);
    expect(c.isPending).toBe(false);
  });

  it('terminalSeen 优先于 sid 未知与额度耗尽（收尾永远优先）', () => {
    const c = new ReconnectController();
    expect(req(c, { terminalSeen: true, sid: null })).toEqual({ decision: 'migrate' });
  });

  it('sid 未知（首帧未确认，无从续传）→ give-up', () => {
    const c = new ReconnectController();
    expect(req(c, { sid: null })).toEqual({ decision: 'give-up' });
    expect(c.attemptCount).toBe(0);
  });

  it('空串 sid 视同未知（falsy 判定与 live 模式的实际取值一致）', () => {
    expect(req(new ReconnectController(), { sid: '' })).toEqual({ decision: 'give-up' });
  });
});

describe('ReconnectController — 进展观察与额度复位（Spec 轴 P0）', () => {
  it('无重连在途时 observeProgress 恒 false（无起点游标可比）', () => {
    const c = new ReconnectController();
    expect(c.observeProgress(99)).toBe(false);
    expect(c.attemptCount).toBe(0);
  });

  it('seq **严格超过**起点游标才复位额度；等于/小于都不算进展', () => {
    const c = new ReconnectController();
    req(c, { lastAppliedSeq: 10 });
    expect(c.observeProgress(10)).toBe(false); // 重放命中游标本身
    expect(c.observeProgress(9)).toBe(false); // 回跳/乱序
    expect(c.attemptCount).toBe(1);
    expect(c.observeProgress(11)).toBe(true); // 真进展
    expect(c.attemptCount).toBe(0);
  });

  it('null seq（ephemeral 帧）不算进展', () => {
    const c = new ReconnectController();
    req(c, { lastAppliedSeq: 10 });
    expect(c.observeProgress(null)).toBe(false);
    expect(c.attemptCount).toBe(1);
  });

  it('额度复位不释放单飞——在途重连链继续（与旧闭包语义一致）', () => {
    const c = new ReconnectController();
    req(c, { lastAppliedSeq: 10 });
    c.observeProgress(11);
    expect(c.isPending).toBe(true);
    expect(req(c)).toBeNull();
  });

  it('起点游标为 null（sid 已知但尚无持久帧）：不构成进展——**与重构前一致**', () => {
    // 旧闭包守卫是 `reconnectProgressBase !== null && …`，null 起点永不复位。
    // 本切片只搬运状态、不改语义，故照实锁定；实际路径上 sid 由首帧带入而
    // 首帧带 seq，null 起点是「仅收到 ephemeral 帧」的窄边角（见 reconnect.ts）。
    const c = new ReconnectController();
    req(c, { lastAppliedSeq: null });
    expect(c.observeProgress(0)).toBe(false);
    expect(c.attemptCount).toBe(1);
  });

  it('**重放不给新额度**：悬空 run 的零进展重连最终可达 give-up', () => {
    const c = new ReconnectController();
    const base = 10;
    for (let i = 0; i < MAX_RECONNECT_ATTEMPTS; i += 1) {
      c.release();
      expect(req(c, { lastAppliedSeq: base })?.decision).toBe('reconnect');
      c.observeProgress(base); // 重放：每轮都收到到游标为止的旧帧
    }
    c.release();
    expect(req(c, { lastAppliedSeq: base })).toEqual({ decision: 'give-up' });
  });

  it('每次 request 重新捕获起点游标（上一轮进展不泄露到下一轮）', () => {
    const c = new ReconnectController();
    req(c, { lastAppliedSeq: 10 });
    c.observeProgress(11); // 复位额度，progressBase 清空
    c.release();
    req(c, { lastAppliedSeq: 50 });
    expect(c.observeProgress(11)).toBe(false); // 旧进展不再是进展
    expect(c.observeProgress(51)).toBe(true);
  });
});

describe('ReconnectController — hold（truncated 全量重建）', () => {
  it('hold 占单飞但不计额度；request 在 hold 期间短路', () => {
    const c = new ReconnectController();
    c.hold();
    expect(c.isPending).toBe(true);
    expect(req(c)).toBeNull();
    expect(c.attemptCount).toBe(0);
  });

  it('hold 释放后 request 仍从第 1 次额度起算', () => {
    const c = new ReconnectController();
    c.hold();
    c.release();
    expect(req(c)).toEqual({ decision: 'reconnect', attempt: 1, delayMs: reconnectDelayMs(1) });
  });

  it('hold 幂等（重复 hold 不叠加状态）', () => {
    const c = new ReconnectController();
    c.hold();
    c.hold();
    c.release();
    expect(c.isPending).toBe(false);
  });
});

describe('ReconnectController — reset（流的生命周期边界）', () => {
  it('清空额度、单飞与起点游标', () => {
    const c = new ReconnectController();
    req(c, { lastAppliedSeq: 10 });
    req(c); // 单飞中 → null，但状态仍在
    c.reset();
    expect(c.isPending).toBe(false);
    expect(c.attemptCount).toBe(0);
    expect(c.observeProgress(999)).toBe(false); // 起点游标已清 → 无进展可言
    expect(req(c)).toEqual({ decision: 'reconnect', attempt: 1, delayMs: reconnectDelayMs(1) });
  });
});
