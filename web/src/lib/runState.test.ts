import { describe, expect, it } from 'vitest';
import { RUN_TERMINAL_TYPES, WAIT_HINT_IDLE_SEC, deriveRunPulse, deriveRunSummary, hasUnterminatedRun, isRecoverableRun, recoverDoneMessage, shouldShowWaitHint, unpairedToolCallIds, waitingHintText } from './runState';
import { initConversation, applyEvent } from './projection';
import { EventType } from '../types';
import type { AgentEvent } from '../types';

function ev(type: string, data: Record<string, unknown>, step_id: number | null = 1): AgentEvent {
  return { type, data, seq: null, run_id: null, step_id };
}

describe('deriveRunPulse', () => {
  it('idle when no conversation', () => {
    expect(deriveRunPulse(null, false).state).toBe('idle');
  });

  it('thinking while model streams, tool while tool running', () => {
    let s = initConversation('s1');
    s = applyEvent(s, ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.MODEL_STARTED, {}, 1));
    s = applyEvent(s, ev(EventType.MODEL_DELTA, { delta: 'hi' }, 1));
    expect(deriveRunPulse(s, true).state).toBe('thinking');

    s = applyEvent(
      s,
      ev(EventType.TOOL_CALL, { tool_call_id: 't1', tool_name: 'bash' }, 1),
    );
    expect(deriveRunPulse(s, true).state).toBe('tool');
    expect(deriveRunPulse(s, true).label).toBe('执行工具');

    s = applyEvent(
      s,
      ev(
        EventType.TOOL_RESULT,
        {
          tool_call_id: 't1',
          content: JSON.stringify({ ok: true, message: 'done', data: null }),
        },
        1,
      ),
    );
    expect(deriveRunPulse(s, true).state).toBe('thinking');
  });

  it('completed / failed terminal states', () => {
    let s = initConversation('s1');
    s = applyEvent(s, ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_COMPLETED, {}));
    expect(deriveRunPulse(s, false).state).toBe('completed');

    let f = initConversation('s1');
    f = applyEvent(f, ev(EventType.RUN_STARTED, {}));
    f = applyEvent(f, ev(EventType.RUN_FAILED, {}));
    expect(deriveRunPulse(f, false).state).toBe('failed');
    expect(deriveRunPulse(f, false).label).toBe('失败');
  });

  it('idle run_status + not streaming stays idle', () => {
    expect(deriveRunPulse(initConversation('s1'), false).state).toBe('idle');
  });

  it('idle run_status + streaming shows thinking (pre-run/started frames)', () => {
    expect(deriveRunPulse(initConversation('s1'), true).state).toBe('thinking');
    expect(deriveRunPulse(initConversation('s1'), true).label).toBe('思考中');
  });
});

// ── OBS-007：中断是第三种终态，不能冒充「已完成」──

describe('deriveRunPulse — interrupted 通道', () => {
  it('run/interrupted → 已中断（中性），而不是绿色「已完成」', () => {
    let s = applyEvent(initConversation('s'), ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_INTERRUPTED, { reason: 'process_restart' }));
    // run_status 仍是 completed（冻结决策 69：中断 ≠ 失败，finalizeRun 只有两档）
    expect(s.run_status).toBe('completed');
    // 但脉冲必须说「已中断」，与同屏的「上次运行…中断」横幅一致
    expect(deriveRunPulse(s, false).state).toBe('interrupted');
    expect(deriveRunPulse(s, false).label).toBe('已中断');
    expect(deriveRunPulse(s, false).className).toBe('pulse-interrupted');
    // Inspector Overview 的标签是**另一条**映射（coarsenPulseState），
    // 单独断言：改错成任一同类型字符串（如「已完成」）都不会被上面的断言拦住。
    expect(deriveRunSummary(s).label).toBe('已中断');
  });

  it('不变量被破坏时：更晚的终态（failed）优先于过期的中断标记', () => {
    // 后端不变量保证 run_interrupted 只与 run_status='completed' 共存（新 run
    // 开始即清标记），所以下面这份日志在真实数据里**不可达**。这里锁的是
    // 破坏不变量时的退化语义：宁可显示更晚那个终态（失败/红），也不让过期的
    // 中断标记把一次失败粉饰成中性色。
    let s = applyEvent(initConversation('s'), ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_INTERRUPTED, { reason: 'process_restart' }));
    s = applyEvent(s, ev(EventType.RUN_FAILED, {}));
    expect(s.run_interrupted).not.toBeNull(); // 标记确实还在（run/failed 不清它）
    expect(deriveRunPulse(s, false).state).toBe('failed');
    expect(deriveRunSummary(s).label).toBe('失败');
  });

  it('中断之后再起一个 run 并正常完成 → 回到「已完成」（提示不再过期挂着）', () => {
    let s = applyEvent(initConversation('s'), ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_INTERRUPTED, { reason: 'process_restart' }));
    s = applyEvent(s, ev(EventType.RUN_STARTED, {}));
    // 新 run 开始即清空中断标记：提示的「上次运行」已被取代
    expect(s.run_interrupted).toBeNull();
    s = applyEvent(s, ev(EventType.RUN_COMPLETED, {}));
    expect(deriveRunPulse(s, false).state).toBe('completed');
  });
});

// ── da394a9 批：取消态脉冲 + 恢复可见性 ──

describe('deriveRunPulse — cancelled 通道', () => {
  it('run/failed + run_cancelled → 已取消（中性）而非失败（红）', () => {
    let s = applyEvent(initConversation('s'), ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_FAILED, { reason: 'cancelled' }));
    const pulse = deriveRunPulse(s, false);
    expect(pulse.state).toBe('cancelled');
    expect(pulse.label).toBe('已取消');
    expect(pulse.className).toBe('pulse-cancelled');
  });

  it('run/failed 无取消标记 → 失败（红）', () => {
    let s = applyEvent(initConversation('s'), ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_FAILED, {}));
    expect(deriveRunPulse(s, false).state).toBe('failed');
  });
});

describe('isRecoverableRun — 恢复入口可见性（da394a9 §二.2）', () => {
  it('run/started 无终态 → true（中断会话可恢复）', () => {
    const events = [ev(EventType.RUN_STARTED, {})];
    expect(isRecoverableRun(events)).toBe(true);
  });

  it('干净完成 → false；干净失败 → false（终态，不可恢复）', () => {
    const done = [ev(EventType.RUN_STARTED, {}), ev(EventType.RUN_COMPLETED, {})];
    const failed = [ev(EventType.RUN_STARTED, {}), ev(EventType.RUN_FAILED, {})];
    expect(isRecoverableRun(done)).toBe(false);
    expect(isRecoverableRun(failed)).toBe(false);
  });

  it('干净失败 + 未配对 tool_call → true（dangling 可修）', () => {
    const events = [
      ev(EventType.RUN_STARTED, {}),
      ev(EventType.TOOL_CALL, { tool_call_id: 't1', tool_name: 'bash' }),
      // t1 的 tool/result 丢了（dangling）
      ev(EventType.TOOL_CALL, { tool_call_id: 't2', tool_name: 'bash' }),
      ev(EventType.TOOL_RESULT, { tool_call_id: 't2', content: 'ok' }),
      ev(EventType.RUN_FAILED, {}),
    ];
    expect(isRecoverableRun(events)).toBe(true);
  });

  it('无 run 的裸会话 → false（无可恢复物）', () => {
    expect(isRecoverableRun([ev(EventType.SESSION_STARTED, {})])).toBe(false);
  });
});

// ── T8 run/interrupted 必须算终态（否则崩溃会话修好后按钮永不消失）──

describe('isRecoverableRun — run/interrupted 是终态', () => {
  it('run/interrupted 且无 dangling → false（后端已按 Ledger 回填完，入口必须消失）', () => {
    const events = [
      ev(EventType.RUN_STARTED, {}),
      ev(EventType.TOOL_CALL, { tool_call_id: 't1', tool_name: 'bash' }),
      ev(EventType.TOOL_RESULT, { tool_call_id: 't1', content: 'ok' }),
      ev(EventType.RUN_INTERRUPTED, { interrupted_seq: 3, reason: 'process_restart' }),
    ];
    expect(isRecoverableRun(events)).toBe(false);
  });

  it('run/interrupted + 未配对 tool_call → true（仍有 dangling 可修）', () => {
    const events = [
      ev(EventType.RUN_STARTED, {}),
      ev(EventType.TOOL_CALL, { tool_call_id: 't1', tool_name: 'bash' }),
      // t1 的 tool/result 丢了（dangling）
      ev(EventType.RUN_INTERRUPTED, { interrupted_seq: 2, reason: 'process_restart' }),
    ];
    expect(isRecoverableRun(events)).toBe(true);
  });

  it('RUN_TERMINAL_TYPES 锁本端字面集合（三处枚举的唯一事实源）', () => {
    // 防止这里被误删/误加——三处枚举曾各自漏掉 run/interrupted。
    // 「后端新增第四种终态」这一侧由下面独立的 EventType 词表漂移锁接住。
    expect([...RUN_TERMINAL_TYPES].sort()).toEqual([
      EventType.RUN_COMPLETED,
      EventType.RUN_FAILED,
      EventType.RUN_INTERRUPTED,
    ]);
  });
});

// ── EventType 词表漂移锁（跨 worktree 的唯一可用信号：生成物）──

describe('EventType 词表漂移锁', () => {
  it('生成物里每个 run 事件都必须被显式分类（终态或 run/started）', () => {
    // 单测读不到另一个 worktree 的后端源码，但**读得到生成物**
    // （web/src/generated/event-types.ts 由后端 scripts/gen_event_types.py 生成）。
    // 后端加第四种 run 终态时会重新生成它，这里的「有未分类的 run 事件」随即变红，
    // 逼着维护者回答「它是不是终态」——T8 加 run/interrupted 时三处枚举集体漏掉，
    // 正是因为没有这道门（已 mutation 验证：注入 run/paused → 本测试变红）。
    // 已分类 = 终态集合里的，或已知非终态的 run/started。
    const runTypes: string[] = Object.values(EventType).filter((v) => v.startsWith('run/'));
    expect(runTypes.length).toBeGreaterThan(1); // 生成物没读到时应立刻失败，而不是静默通过
    const unclassified = runTypes.filter((v) => v !== EventType.RUN_STARTED && !RUN_TERMINAL_TYPES.has(v));
    expect(unclassified).toEqual([]);
  });
});

// ── hasUnterminatedRun：recover 反馈区分「回填工具结果」与「补齐 run 终态」──

describe('hasUnterminatedRun', () => {
  it('run/started 之后无终态 → true（无论有没有 dangling）', () => {
    expect(hasUnterminatedRun([ev(EventType.RUN_STARTED, {})])).toBe(true);
    expect(hasUnterminatedRun([
      ev(EventType.RUN_STARTED, {}),
      ev(EventType.TOOL_CALL, { tool_call_id: 't1', tool_name: 'bash' }),
    ])).toBe(true);
  });

  it('三种终态任一都算收口；之后的 run 重新开一局', () => {
    for (const t of [EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_INTERRUPTED]) {
      expect(hasUnterminatedRun([ev(EventType.RUN_STARTED, {}), ev(t, {})])).toBe(false);
    }
    expect(hasUnterminatedRun([
      ev(EventType.RUN_STARTED, {}),
      ev(EventType.RUN_COMPLETED, {}),
      ev(EventType.RUN_STARTED, {}),
    ])).toBe(true);
  });

  it('无 run 的裸会话 → false（无东西可恢复）', () => {
    expect(hasUnterminatedRun([ev(EventType.SESSION_STARTED, {})])).toBe(false);
    expect(hasUnterminatedRun([])).toBe(false);
  });

  it('与 isRecoverableRun 的「缺终态」分支一致', () => {
    const evs = [ev(EventType.RUN_STARTED, {}), ev(EventType.MODEL_COMPLETED, { content: 'x' })];
    expect(hasUnterminatedRun(evs)).toBe(true);
    expect(isRecoverableRun(evs)).toBe(true);
  });

  it('裸会话（有 dangling 但无 run/started）仍不可恢复——比后端字面语义保守', () => {
    // 这种日志本身畸形：暴露「恢复」入口既不解决问题又给出错误承诺。
    const evs = [
      ev(EventType.SESSION_STARTED, {}),
      ev(EventType.TOOL_CALL, { tool_call_id: 't1', tool_name: 'bash' }),
    ];
    expect(unpairedToolCallIds(evs).size).toBe(1);
    expect(isRecoverableRun(evs)).toBe(false);
  });
});

// ── recoverDoneMessage：结局不得合并（合并用户就看不出修没修） ──

describe('recoverDoneMessage', () => {
  const none = { stillUnterminated: false, stillDangling: false };

  it('回填了工具结果', () => {
    expect(recoverDoneMessage({ repaired: 2, terminalRepaired: false, ...none }))
      .toBe('已恢复：回填 2 条工具结果');
  });

  it('回填工具结果 + 补齐终态：两条都说', () => {
    expect(recoverDoneMessage({ repaired: 1, terminalRepaired: true, ...none }))
      .toBe('已恢复：回填 1 条工具结果，并补齐 run 终态');
  });

  it('只补齐终态：不能说成「无可修复项」', () => {
    const m = recoverDoneMessage({ repaired: 0, terminalRepaired: true, ...none });
    expect(m).toBe('已恢复：补齐 run 终态');
    expect(m).not.toContain('无可修复项');
  });

  it('回填了但仍缺终态：修复陈述后必须附可重试提示（不能被 repaired>0 吞掉）', () => {
    const m = recoverDoneMessage({
      repaired: 1, terminalRepaired: false, stillUnterminated: true, stillDangling: false,
    });
    expect(m).toContain('回填 1 条工具结果');
    expect(m).toContain('仍缺 run 终态');
    expect(m).toContain('可重试');
  });

  it('原因分开报：终态已补、只剩悬空 tool_call 时不得说「仍缺 run 终态」', () => {
    const m = recoverDoneMessage({
      repaired: 0, terminalRepaired: true, stillUnterminated: false, stillDangling: true,
    });
    expect(m).toContain('仍有未配对工具调用');
    expect(m).not.toContain('仍缺 run 终态');
  });

  it('两个原因都在时报全', () => {
    const m = recoverDoneMessage({
      repaired: 0, terminalRepaired: false, stillUnterminated: true, stillDangling: true,
    });
    expect(m).toContain('仍缺 run 终态且有未配对工具调用');
  });

  it('后端没修完（仍缺终态）→ 如实说可重试，不谎报完整', () => {
    const m = recoverDoneMessage({
      repaired: 0, terminalRepaired: false, stillUnterminated: true, stillDangling: false,
    });
    expect(m).toContain('仍缺 run 终态');
    expect(m).not.toContain('已完整');
  });

  it('事件本已完整 → 无可修复项', () => {
    expect(recoverDoneMessage({ repaired: 0, terminalRepaired: false, ...none }))
      .toContain('已完整');
  });
});

// ── dangling 集合：isRecoverableRun 与「修了几条」统计的共享实现 ──

describe('unpairedToolCallIds', () => {
  it('无配对结果的 tool_call 计入，已配对的剔除', () => {
    const events = [
      ev(EventType.TOOL_CALL, { tool_call_id: 't1', tool_name: 'bash' }),
      ev(EventType.TOOL_RESULT, { tool_call_id: 't1', content: 'ok' }),
      ev(EventType.TOOL_CALL, { tool_call_id: 't2', tool_name: 'bash' }),
      ev(EventType.TOOL_CALL, { tool_call_id: 't3', tool_name: 'bash' }),
      ev(EventType.TOOL_RESULT, { tool_call_id: 't3', content: 'ok' }),
    ];
    expect([...unpairedToolCallIds(events)]).toEqual(['t2']);
  });

  it('恢复补上结果后，before\\after 即「本次修好的条数」', () => {
    const before = [
      ev(EventType.TOOL_CALL, { tool_call_id: 't1' }),
      ev(EventType.TOOL_CALL, { tool_call_id: 't2' }),
    ];
    const after = [...before, ev(EventType.TOOL_RESULT, { tool_call_id: 't1', content: 'ok' })];
    const repaired = [...unpairedToolCallIds(before)].filter(
      (id) => !unpairedToolCallIds(after).has(id),
    );
    expect(repaired).toEqual(['t1']);
  });

  it('无 tool_call → 空集合', () => {
    expect(unpairedToolCallIds([ev(EventType.RUN_STARTED, {})]).size).toBe(0);
  });
});

describe('deriveRunSummary — Inspector Overview 的状态 + 时长（单一来源）', () => {
  it('运行中 → 粗标签「运行中」（不细分思考中/执行工具，那是脉冲的粒度）', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev(EventType.RUN_STARTED, {}));
    expect(deriveRunSummary(s).label).toBe('运行中');
  });

  it('run/failed(reason=cancelled) → 「已取消」，不是「失败」', () => {
    // 取消 ≠ 失败（da394a9）：这条语义与顶栏脉冲必须同一处判断，否则 Inspector
    // 与顶栏会各说一套——此前 StepDetail 自己再分支一次 run_cancelled。
    let s = initConversation('s');
    s = applyEvent(s, ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_FAILED, { reason: 'cancelled' }));
    expect(deriveRunSummary(s).label).toBe('已取消');
  });

  it('run/failed（无 reason，真实失败）→ 「失败」', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_FAILED, {}));
    expect(deriveRunSummary(s).label).toBe('失败');
  });

  it('run/completed → 「已完成」；裸会话 → 「空闲」', () => {
    let s = initConversation('s');
    s = applyEvent(s, ev(EventType.RUN_STARTED, {}));
    s = applyEvent(s, ev(EventType.RUN_COMPLETED, {}));
    expect(deriveRunSummary(s).label).toBe('已完成');
    expect(deriveRunSummary(initConversation('empty')).label).toBe('空闲');
  });

  it('时长取首个 run 的起止，且 run/interrupted 也算终态', () => {
    // 旧代码只认 completed/failed：被进程重启打断的会话在这里算不出时长
    // （T8 加 run/interrupted 时漏掉的三处之一）。本用例锁住回归。
    // 注意 applyEvent 会**原地 push** 进 state.events（projection.ts 的
    // `state.events.push(event)`），所以「未收口的 run」必须独立建一份——
    // 在同一份 state 上继续 applyEvent 会把它的 events 数组一起改掉。
    const done = applyEvent(
      applyEvent(initConversation('s'), {
        ...ev(EventType.RUN_STARTED, {}, null), time: '2026-09-11T00:00:02.000Z',
      }),
      { ...ev(EventType.RUN_INTERRUPTED, { reason: 'process_restart' }, null), time: '2026-09-11T00:00:05.000Z' },
    );
    const summary = deriveRunSummary(done);
    expect(summary.startedAt).toBe('2026-09-11T00:00:02.000Z');
    expect(summary.duration).not.toBeNull();

    // 未收口的 run 有开始时间但无终态 → 时长为 null（不编造）
    const unfinished = applyEvent(initConversation('s'), {
      ...ev(EventType.RUN_STARTED, {}, null), time: '2026-09-11T00:00:02.000Z',
    });
    expect(deriveRunSummary(unfinished).startedAt).toBe('2026-09-11T00:00:02.000Z');
    expect(deriveRunSummary(unfinished).duration).toBeNull();
  });

  it('多 run 会话：时长取**首个 run 自己**的起止，不是首起→末止', () => {
    // 「首个 run/started 之后的第一个终态属于首个 run」是承重假设（后端 run 顺序
    // 收口）。这里把它锁住：run1 02s→05s，run2 10s→12s ⇒ 时长 3s，而不是 10s。
    let s = initConversation('s');
    s = applyEvent(s, { ...ev(EventType.RUN_STARTED, {}, null), time: '2026-09-11T00:00:02.000Z' });
    s = applyEvent(s, { ...ev(EventType.RUN_COMPLETED, {}, null), time: '2026-09-11T00:00:05.000Z' });
    s = applyEvent(s, { ...ev(EventType.RUN_STARTED, {}, 2), time: '2026-09-11T00:00:10.000Z' });
    s = applyEvent(s, { ...ev(EventType.RUN_FAILED, {}, 2), time: '2026-09-11T00:00:12.000Z' });
    const summary = deriveRunSummary(s);
    expect(summary.startedAt).toBe('2026-09-11T00:00:02.000Z');
    expect(summary.duration).toBe('3.0s');
    expect(summary.label).toBe('失败'); // 最后一次 run 的状态（与脉冲一致）
  });
});

// ── FE-01（#148）：停顿等待提示——展示层观察，不是会话事实 ──

describe('waitingHintText', () => {
  it('阈值以下返回 null（生成态渲染与现状逐字节一致）', () => {
    expect(waitingHintText(0)).toBeNull();
    expect(waitingHintText(WAIT_HINT_IDLE_SEC - 1)).toBeNull();
  });

  it('恰好等于阈值即出现，并带上已等待秒数', () => {
    const text = waitingHintText(WAIT_HINT_IDLE_SEC);
    expect(text).not.toBeNull();
    expect(text).toContain(String(WAIT_HINT_IDLE_SEC));
  });

  it('只说「还在等」——不预测进度/回退（零伪造：等待态不是会话事实）', () => {
    const text = waitingHintText(95) ?? '';
    expect(text).toContain('95');
    for (const banned of ['%', '进度', '预计', 'ETA', '即将', '回退']) {
      expect(text).not.toContain(banned);
    }
  });

  it('非有限值不产提示——畸形计时不得渲染成文案', () => {
    expect(waitingHintText(Number.NaN)).toBeNull();
    expect(waitingHintText(Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe('shouldShowWaitHint', () => {
  it('只有「思考中 + 流仍挂着」才提示', () => {
    expect(shouldShowWaitHint('thinking', true)).toBe(true);
  });

  it('工具执行 / 审批等待不提示——否则顶栏一边写「执行工具」一边写「仍在等待模型」', () => {
    expect(shouldShowWaitHint('tool', true)).toBe(false);
  });

  it('终态不提示（没有停顿可言）', () => {
    for (const s of ['completed', 'failed', 'interrupted', 'cancelled', 'idle'] as const) {
      expect(shouldShowWaitHint(s, true)).toBe(false);
    }
  });

  it('流已脱离不提示——我们没在听，那句「仍在等待」是断线条的地盘', () => {
    expect(shouldShowWaitHint('thinking', false)).toBe(false);
  });
});
