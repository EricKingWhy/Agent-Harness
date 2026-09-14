/** useSession 流式-模式一致性契约——纯函数锁不变量 #22。
 *
 * 关注的 bug 形态：SSE 在途帧晚于 cancel / selectSession / onError 到达，
 * 仍然写 conversation 而覆盖刚加载的目标会话视图。提取一个纯函数
 * 决定「当前模式是否仍是该流的权威消费者」，所有回调路径据此短路。
 *
 * 这一层的契约只能用纯函数锁——React 状态机本身需要 testing-library，
 * 引入它会扩大 scope；提取是真正的深模块化（参 codebase-design）。
 */

import { describe, expect, it, vi } from 'vitest';
import type { AgentEvent, SessionMode } from '../types';
import { createCommitCoalescer, decideCancel, decideStreamEnd, isSeqGap, isUnknownModelError, MAX_RECONNECT_ATTEMPTS, parseTruncated, reconnectDelayMs, shouldApplyRecoverResult, shouldApplyStreamFrame, UNKNOWN_MODEL_ERROR_TEXT } from './useSession';

const ev = (type: string, session_id: string | null): AgentEvent => ({
  type,
  data: {},
  seq: null,
  run_id: null,
  step_id: null,
  session_id: session_id ?? undefined,
});

describe('shouldApplyStreamFrame — 流式帧是否仍是当前模式的权威真相', () => {
  it('live(null) 初始态：任意帧都应用（首帧尚未确定 sid）', () => {
    const mode: SessionMode = { kind: 'live', sessionId: null };
    expect(shouldApplyStreamFrame(mode, ev('run/started', 'A'))).toBe(true);
    expect(shouldApplyStreamFrame(mode, ev('run/started', null))).toBe(true);
  });

  it('live(sid) + 匹配 sid：应用', () => {
    const mode: SessionMode = { kind: 'live', sessionId: 'A' };
    expect(shouldApplyStreamFrame(mode, ev('model/delta', 'A'))).toBe(true);
  });

  it('live(sid) + 不同 sid：拒绝——旧流窜入新会话属于不变量违反', () => {
    const mode: SessionMode = { kind: 'live', sessionId: 'A' };
    expect(shouldApplyStreamFrame(mode, ev('model/delta', 'B'))).toBe(false);
  });

  it('viewing(sid) 模式：一律拒绝——流已不再是权威消费者', () => {
    // 这是「切会话 / 取消」之后的核心保护：迟到帧不能覆盖刚加载的历史视图。
    const mode: SessionMode = { kind: 'viewing', sessionId: 'A' };
    expect(shouldApplyStreamFrame(mode, ev('model/delta', 'A'))).toBe(false);
    expect(shouldApplyStreamFrame(mode, ev('model/delta', 'B'))).toBe(false);
  });

  it('idle 模式：一律拒绝——已无持有会话', () => {
    const mode: SessionMode = { kind: 'idle' };
    expect(shouldApplyStreamFrame(mode, ev('run/started', 'A'))).toBe(false);
  });

  it('live(sid) + 帧 session_id 缺省（首帧未带 sid）：仍应用——sid 首帧才落定', () => {
    const mode: SessionMode = { kind: 'live', sessionId: 'A' };
    expect(shouldApplyStreamFrame(mode, ev('model/delta', null))).toBe(true);
  });
});

describe('shouldApplyRecoverResult — recover 响应是否仍是当前模式的权威真相', () => {
  // 同 shouldApplyStreamFrame 家族的 stale-write 守护：recover pending 期间
  // 用户可能已切走（selectSession / submitTask / cancelStream），晚到的 200
  // 响应不得覆盖刚加载的目标会话视图（不变量 #22）。

  it('viewing(sid) 且 sid 匹配：应用重建结果（正常路径）', () => {
    const mode: SessionMode = { kind: 'viewing', sessionId: 'A' };
    expect(shouldApplyRecoverResult(mode, 'A')).toBe(true);
  });

  it('viewing(其他 sid)：拒绝——pending 期间已切到别的会话，旧响应不得覆盖', () => {
    const mode: SessionMode = { kind: 'viewing', sessionId: 'B' };
    expect(shouldApplyRecoverResult(mode, 'A')).toBe(false);
  });

  it('live：拒绝——pending 期间已开始新流，recover 结果与当前视图无关', () => {
    const mode: SessionMode = { kind: 'live', sessionId: null };
    expect(shouldApplyRecoverResult(mode, 'A')).toBe(false);
    const modeLive = { kind: 'live', sessionId: 'A' } as const;
    expect(shouldApplyRecoverResult(modeLive, 'A')).toBe(false);
  });

  it('idle：拒绝——已无持有会话', () => {
    const mode: SessionMode = { kind: 'idle' };
    expect(shouldApplyRecoverResult(mode, 'A')).toBe(false);
  });
});

describe('createCommitCoalescer — P1-3 delta 合帧提交（HANDOFF §6）', () => {
  it('窗口内多次 schedule 只触发一次提交', () => {
    vi.useFakeTimers();
    try {
      let commits = 0;
      const c = createCommitCoalescer(() => commits++, 24);
      c.schedule();
      c.schedule();
      c.schedule();
      expect(commits).toBe(0);
      vi.advanceTimersByTime(24);
      expect(commits).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('flush 立即提交待合帧数据并取消挂起定时器（流终止尾帧不丢、不重复）', () => {
    vi.useFakeTimers();
    try {
      let commits = 0;
      const c = createCommitCoalescer(() => commits++, 24);
      c.schedule();
      c.flush();
      expect(commits).toBe(1);
      vi.advanceTimersByTime(100);
      expect(commits).toBe(1); // 定时器已取消，不重复提交
    } finally {
      vi.useRealTimers();
    }
  });

  it('无待提交数据时 flush 是 no-op', () => {
    let commits = 0;
    const c = createCommitCoalescer(() => commits++, 24);
    c.flush();
    expect(commits).toBe(0);
  });

  it('cancel 丢弃挂起定时器（cancel 流后不再迟到提交）', () => {
    vi.useFakeTimers();
    try {
      let commits = 0;
      const c = createCommitCoalescer(() => commits++, 24);
      c.schedule();
      c.cancel();
      vi.advanceTimersByTime(100);
      expect(commits).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

// ── shouldShowHistoryLoading：live→viewing 迁移的占位符决策（Bug：流结束后
//    完整对话被「正在加载历史…」占位符替换再重建 = 主窗口闪烁）──
import { shouldShowHistoryLoading } from './useSession';

describe('shouldShowHistoryLoading — 迁移到 viewing 时是否显示加载占位符', () => {
  const conv = (session_id: string) => ({
    session_id, turns: [], active_step_id: null, run_status: 'completed' as const,
    run_cancelled: false, compactions: [], reconcile_queue: [], pending_approvals: [],
    approval_decisions: [], permission_policy: null,
    events: [], unknown_events: [], model: null, usage_total: null, cost_usd: null,
    trace_id: null, trace_url: null, model_fallback: null, run_id: null,
    run_interrupted: null, turn_index: null,
    seenSeqs: new Set<number>(),
  });

  it('同一会话（live 流刚产出完整真相）：后台静默重读，不显示占位符', () => {
    expect(shouldShowHistoryLoading(conv('s1'), 's1')).toBe(false);
  });

  it('无 conversation（idle→viewing / 首次打开）：显示占位符', () => {
    expect(shouldShowHistoryLoading(null, 's1')).toBe(true);
  });

  it('不同会话（切换目标）：显示占位符——旧会话内容不得冒充新会话', () => {
    expect(shouldShowHistoryLoading(conv('s-old'), 's-new')).toBe(true);
  });
});

describe('T7 — createCommitCoalescer 后台降渲染（#100，spec 03 §18.3）', () => {
  it('隐藏期 schedule 挂起：不排定时器、不提交（真相仍逐帧入本地 conv，只延迟通知）', () => {
    vi.useFakeTimers();
    try {
      let commits = 0;
      const c = createCommitCoalescer(() => commits++, 24, () => false);
      c.schedule();
      c.schedule();
      vi.advanceTimersByTime(1000);
      expect(commits).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('回前台 flush：整段后台积压合帧为单次提交（一帧内 reconcile）', () => {
    vi.useFakeTimers();
    try {
      let commits = 0;
      let visible = false;
      const c = createCommitCoalescer(() => commits++, 24, () => visible);
      c.schedule();
      c.schedule();
      c.schedule();
      visible = true;
      c.flush();
      expect(commits).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('isVisible 缺省恒 true——既有前台契约零回归（省略第三参走缺省路径）', () => {
    vi.useFakeTimers();
    try {
      let commits = 0;
      const c = createCommitCoalescer(() => commits++, 24);
      c.schedule();
      vi.advanceTimersByTime(24);
      expect(commits).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('隐藏→可见翻转后恢复调度：挂起的 dirty 与新 schedule 合帧单次提交', () => {
    vi.useFakeTimers();
    try {
      let commits = 0;
      let visible = false;
      const c = createCommitCoalescer(() => commits++, 24, () => visible);
      c.schedule(); // hidden：挂起（dirty 挂起、无定时器）
      visible = true;
      c.schedule(); // visible：补排定时器
      vi.advanceTimersByTime(24);
      expect(commits).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

// ── T5（#98）：Esc/停止显式取消的传输层决策（detached-run 契约回执 §0.3/§3）──
describe('decideCancel — 显式取消走 POST /cancel 还是传输层清理（#98 detached-run）', () => {
  it('已知 sid：cancel-request——POST /cancel，流保持打开等终态帧广播', () => {
    expect(decideCancel('A')).toEqual({ kind: 'cancel-request', sessionId: 'A' });
  });

  it('sid 未知（首帧未确认）：abort-transport——无从显式取消，孤儿回收兜底', () => {
    expect(decideCancel(null)).toEqual({ kind: 'abort-transport' });
  });

  it('空串 sid 视同未知（liveSidRef 只写真值，防御不留空串）', () => {
    expect(decideCancel('')).toEqual({ kind: 'abort-transport' });
  });
});

// ── T4（#97）：重连/resume 契约（后端契约回执 §3，spec 02 §10 / 03 §20）──
describe('T4 — 重连契约纯函数（#97）', () => {
  it('decideStreamEnd：终态已见 → migrate（正常收尾迁移）', () => {
    expect(decideStreamEnd({ terminalSeen: true, sidKnown: true, attempts: 0 })).toBe('migrate');
    expect(decideStreamEnd({ terminalSeen: true, sidKnown: false, attempts: 5 })).toBe('migrate');
  });

  it('decideStreamEnd：未终态 + sid 已知 + 额度内 → reconnect', () => {
    expect(decideStreamEnd({ terminalSeen: false, sidKnown: true, attempts: 0 })).toBe('reconnect');
    expect(decideStreamEnd({ terminalSeen: false, sidKnown: true, attempts: MAX_RECONNECT_ATTEMPTS - 1 })).toBe('reconnect');
  });

  it('decideStreamEnd：sid 未知（首帧未确认无从续传）或额度耗尽 → give-up', () => {
    expect(decideStreamEnd({ terminalSeen: false, sidKnown: false, attempts: 0 })).toBe('give-up');
    expect(decideStreamEnd({ terminalSeen: false, sidKnown: true, attempts: MAX_RECONNECT_ATTEMPTS })).toBe('give-up');
  });

  it('isSeqGap：null seq（ephemeral）与无基线永不构成 gap；跳号构成，连续/回跳不构成', () => {
    expect(isSeqGap(null, 5)).toBe(false);
    expect(isSeqGap(5, null)).toBe(false);
    expect(isSeqGap(5, 6)).toBe(false);
    expect(isSeqGap(5, 7)).toBe(true);
    expect(isSeqGap(5, 4)).toBe(false);
  });

  it('parseTruncated：合法 latest_seq 提取；畸形/缺失/非有限数 → null（按普通断连路径）', () => {
    expect(parseTruncated({ after_seq: 3, latest_seq: 1042 })).toEqual({ latestSeq: 1042 });
    expect(parseTruncated({})).toBeNull();
    expect(parseTruncated({ latest_seq: 'x' })).toBeNull();
    expect(parseTruncated({ latest_seq: Number.POSITIVE_INFINITY })).toBeNull();
  });

  it('reconnectDelayMs：500ms 起步指数 ×2，封顶 4s', () => {
    expect(reconnectDelayMs(1)).toBe(500);
    expect(reconnectDelayMs(2)).toBe(1000);
    expect(reconnectDelayMs(3)).toBe(2000);
    expect(reconnectDelayMs(9)).toBe(4000);
  });
});

describe('isUnknownModelError — 422 具名判定（#103，消魔法子串）', () => {
  it('仅精确匹配未知模型专项错误', () => {
    expect(isUnknownModelError(UNKNOWN_MODEL_ERROR_TEXT)).toBe(true);
    expect(isUnknownModelError('模型不可用（422）：请从模型选择器重新选择 ')).toBe(false);
    expect(isUnknownModelError('Start failed: 422')).toBe(false);
    expect(isUnknownModelError('加载会话列表失败：422')).toBe(false);
    expect(isUnknownModelError(null)).toBe(false);
    expect(isUnknownModelError(undefined)).toBe(false);
  });
});
