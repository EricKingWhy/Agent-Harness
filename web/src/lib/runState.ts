/** Run Pulse state derivation — signature #1 (docs/UI_DESIGN_DECISIONS.md).
 *
 * Pure functions: ConversationState (+ optional streaming flag) → a single
 * run-state descriptor (state + label + class + icon). Three channels by
 * contract (icon + color + text, never color-only). Color/animation live in
 * CSS keyed by `className`; the icon is a lucide component referenced by type
 * so consumers stay free of parallel lookup tables.
 *
 * This is projection-adjacent truth: derived ONLY from ConversationState fields
 * that themselves come from events — no fabrication (zero-fake-metrics rule).
 */

import { Activity, CircleDashed, CircleSlash, Loader2, SquareCheckBig, SquareX } from 'lucide-react';
import { EventType, type AgentEvent, type ConversationState } from '../types';
import { formatDuration } from './format';

/**
 * run 终态词汇——镜像后端 `session/event.py:RUN_TERMINAL_TYPES`。
 *
 * 「这个 run 收口了吗」是**一个**判断，全前端只有这一个集合：抄第二份就会
 * 漏掉后加的类型。T8（#138）新增 `run/interrupted` 时正好踩了这个坑——
 * `isRecoverableRun` / `StepDetail` 的 run 时长 / `useSession` 的终态检测
 * 三处各自枚举，全都漏了它，于是崩溃会话经后端恢复后「恢复会话」按钮永不
 * 消失、点它又是一次 no-op（用户实测症状：「点了什么反应也没有」）。
 */
export const RUN_TERMINAL_TYPES: ReadonlySet<string> = new Set<string>([
  EventType.RUN_COMPLETED,
  EventType.RUN_FAILED,
  EventType.RUN_INTERRUPTED,
]);

export type RunPulseState =
  | 'idle' // no conversation or nothing has happened
  | 'thinking' // run active, model segment streaming, no tools yet
  | 'tool' // run active, latest tool call still running
  | 'completed'
  | 'interrupted' // 最近一个 run 被进程重启打断（run/interrupted）——终态但非完成
  | 'cancelled' // run/failed.data.reason === 'cancelled'（客户端断连，中断 ≠ 错误）
  | 'failed';

export interface RunPulseDescriptor {
  state: RunPulseState;
  /** Short Chinese label — text channel (never color-only). */
  label: string;
  /** CSS class for the run-pulse element (color + animation channels). */
  className: string;
  /** Icon channel — lucide component type for the consumer to instantiate. */
  Icon: typeof Activity;
}

interface RunPulseRow {
  label: string;
  className: string;
  Icon: typeof Activity;
}

const PULSE_TABLE: Record<RunPulseState, RunPulseRow> = {
  idle: { label: '空闲', className: 'pulse-idle', Icon: CircleDashed },
  thinking: { label: '思考中', className: 'pulse-thinking', Icon: Loader2 },
  tool: { label: '执行工具', className: 'pulse-tool', Icon: Loader2 },
  completed: { label: '已完成', className: 'pulse-completed', Icon: SquareCheckBig },
  // 已中断：进程重启打断（run/interrupted）——中性色，既不是成功也不是失败
  interrupted: { label: '已中断', className: 'pulse-interrupted', Icon: CircleSlash },
  // 已取消：客户端断连（run/failed.reason=cancelled，da394a9）——中性色，非红色报错
  cancelled: { label: '已取消', className: 'pulse-cancelled', Icon: SquareX },
  failed: { label: '失败', className: 'pulse-failed', Icon: SquareX },
};

/** Derive the run pulse for a conversation.
 *  `streaming` = useSession live mode (SSE attached). A conversation whose run
 *  hasn't emitted run/completed|failed but is no longer receiving frames is
 *  still 'running-family' — decided by run_status, not by client timers. */
export function deriveRunPulse(
  conversation: ConversationState | null,
  streaming: boolean,
): RunPulseDescriptor {
  if (!conversation) {
    const r = PULSE_TABLE.idle;
    return { state: 'idle', label: r.label, className: r.className, Icon: r.Icon };
  }

  // 中断优先于 run_status（BUG/OBS-007）——`projectRunInterrupted` 把 run_status
  // 收成 'completed'（冻结决策 69：中断 ≠ 失败，而 finalizeRun 只有 completed/
  // failed 两档），于是被进程重启打断、且之后**没有再跑过**的会话会挂着绿色对勾
  // 说「已完成」，同一屏却有「上次运行…中断」横幅——自相矛盾。
  // `run_interrupted` 的语义是「**最近一个** run 以中断收口」（新 run 开始时由
  // projectRunStarted 清空），所以它比 run_status='completed' 更能说明真相。
  //
  // 连带 `run_status === 'completed'`：后端不变量保证这两者同时成立（中断只与
  // completed 共存），所以该条件是恒真的**显式化**，不是新分支。写成恒真条件是为了
  // 破坏不变量时（更晚的 run/failed|已取消 之后标记仍在）退化到「更晚的终态赢」，
  // 而不是让过期的中断标记把一次失败粉饰成中性色。
  if (conversation.run_interrupted && conversation.run_status === 'completed') {
    const r = PULSE_TABLE.interrupted;
    return { state: 'interrupted', label: r.label, className: r.className, Icon: r.Icon };
  }

  switch (conversation.run_status) {
    case 'completed': {
      const r = PULSE_TABLE.completed;
      return { state: 'completed', label: r.label, className: r.className, Icon: r.Icon };
    }
    case 'failed': {
      // 取消 ≠ 失败：断连导致的 run/failed 走中性「已取消」通道（da394a9 语义）
      const r = conversation.run_cancelled ? PULSE_TABLE.cancelled : PULSE_TABLE.failed;
      return {
        state: conversation.run_cancelled ? 'cancelled' : 'failed',
        label: r.label,
        className: r.className,
        Icon: r.Icon,
      };
    }
    case 'running': {
      // Sub-state: latest event is an unfinished tool call → 'tool',
      // otherwise the model segment is being streamed → 'thinking'.
      const activeTurn =
        conversation.active_step_id !== null
          ? conversation.turns.find((t) => t.step_id === conversation.active_step_id)
          : undefined;
      const hasRunningTool = activeTurn?.tools.some((t) => t.status === 'running') ?? false;
      const r = hasRunningTool ? PULSE_TABLE.tool : PULSE_TABLE.thinking;
      return {
        state: hasRunningTool ? 'tool' : 'thinking',
        label: r.label,
        className: r.className,
        Icon: r.Icon,
      };
    }
    case 'idle': {
      // run_status never left idle but frames may still be arriving (pre-
      // run/started). While live-streaming show thinking, else idle.
      const r = streaming ? PULSE_TABLE.thinking : PULSE_TABLE.idle;
      return {
        state: streaming ? 'thinking' : 'idle',
        label: r.label,
        className: r.className,
        Icon: r.Icon,
      };
    }
  }
}

// ── FE-01（#148）：停顿等待提示——展示层观察，不是会话事实 ──

/** 停顿提示阈值（秒）。口径是**空闲**：距上一次收到新事件的时间。 */
export const WAIT_HINT_IDLE_SEC = 30;

/** 该不该出现等待提示：模型正在思考 **且** 流仍挂着。
 *
 *  两个条件缺一不可，各自挡掉一种失真的提示：
 *  - 脉冲不是 thinking（工具执行 / 审批等待 → 'tool'）挡掉自相矛盾——顶栏不能一边
 *    写「执行工具」一边写「仍在等待模型」；终态同理（没有停顿可言）。
 *  - 流已脱离挡掉「我们根本没在听」——重连额度耗尽或会话已收口时，那句「仍在等待」
 *    是断线条 / 恢复入口的语义地盘，不是这句旁注的。 */
export function shouldShowWaitHint(pulseState: RunPulseState, streaming: boolean): boolean {
  return pulseState === 'thinking' && streaming;
}

/** 空闲 idleSec 秒后的等待说明；未到阈值返回 null（渲染零变化）。
 *
 *  为什么锚「空闲」而不是「流开了多久」：健康的长时间生成里流龄一路增长，用它
 *  当阈值会把正常慢任务报成停顿。文案只陈述已观测到的事实（多久没有新进展），
 *  不含进度/ETA/回退预测——后端此刻并没有发出任何「正在回退」的事实，等待态是
 *  展示层状态（不变量 #4：Event ≠ Diagnostic Log；#22：Web UI 不造第二套真相）。
 *
 *  阈值依据：本仓 `docs/FRONTEND_ISSUES_LOG.md`「停顿提示阈值」小节（可复现的实测方法
 *  与分布，n=13：p50 4.6s / max 61.0s，>30s 占 2/13）；参照实现的 idle 看门狗对照见
 *  后端仓 `docs/RESEARCH_STREAM_STALL_HANDLING.md`。本提示是**展示层旁注、不中止任何
 *  东西**，所以刻意比三方的看门狗（本项目 60s / dsh 300s / ZCode 600s）都早出现。
 *  非有限值不产文案（畸形计时不得被渲染成句子）。 */
export function waitingHintText(idleSec: number): string | null {
  if (!Number.isFinite(idleSec) || idleSec < WAIT_HINT_IDLE_SEC) return null;
  return `已 ${Math.floor(idleSec)}s 没有新进展，仍在等待模型`;
}

// ── Inspector Overview 的 Run 摘要（状态 + 时长） ──

/** 把脉冲的细粒度状态粗化成 Inspector 想显示的那一档。
 *
 *  用**穷尽 switch** 而不是 `else` 兜底：`RunPulseState` 新增一档时 TS 会在这里
 *  报错，逼着我们决定它的粗标签——而不是让它静默落进「运行中」。 */
function coarsenPulseState(state: RunPulseState): string {
  switch (state) {
    case 'thinking':
    case 'tool':
      return '运行中';
    case 'completed':
      return '已完成';
    case 'interrupted':
      return '已中断';
    case 'cancelled':
      return '已取消';
    case 'failed':
      return '失败';
    case 'idle':
      return '空闲';
  }
}

/** Run 的粗口径状态标签 + 首个 run 的时长——Inspector Overview 两行的单一来源。
 *
 *  状态**不在这里再判断一次**：语义（取消 ≠ 失败 da394a9、`run/interrupted` 算终态）
 *  只由 `deriveRunPulse` 的状态机决定，这里仅把它的细粒度（思考中 / 执行工具）合并成
 *  「运行中」（见 `coarsenPulseState`）。此前 `StepDetail` 自己再分支一次
 *  `run_cancelled`/`run_status`，规则一旦变化（T8 加 `run/interrupted` 时就是三处枚举
 *  集体漂移）Inspector 就会与顶栏各说一套。
 *
 *  时长 = **第一个 run 自己的起止**：依赖后端「run 顺序收口」不变量（新 run 只能在
 *  旧 run 有终态之后开始，启动扫描会给中断的 run 补 `run/interrupted`），因此
 *  「首个 `run/started` 之后的第一个终态」属于首个 run。已对 8 个多 run 会话实测确认；
 *  若出现违反该不变量的旧日志（run1 未落终态就起了 run2），起止会配到两个 run 上——
 *  要修得先有真实反例，故仍用全表 `find`（这是**假设**，不是代码保证）。 */
export function deriveRunSummary(conversation: ConversationState): {
  label: string;
  /** 首个 run 的绝对开始时间（ISO）。**缺失为 undefined**（没有 run/started 的裸会话）
   *  ——Inspector「开始」行要用，与 duration 同源，免得调用方再自己 find 一次。 */
  startedAt: string | undefined;
  /** **未收口（无终态）或未开始时为 null——不编造时长。** null 不等于「正在运行」：
   *  运行中的 run 同样没有终态，也是 null。要区分请看 label。 */
  duration: string | null;
} {
  const label = coarsenPulseState(deriveRunPulse(conversation, false).state);
  const start = conversation.events.find((e) => e.type === EventType.RUN_STARTED)?.time;
  const end = conversation.events.find((e) => RUN_TERMINAL_TYPES.has(e.type))?.time;
  return { label, startedAt: start, duration: formatDuration(start, end) };
}

// ── 会话健康度：恢复入口可见性（da394a9 §二.2 建议语义） ──

/**
 * 未配对的 tool_call id 集合（dangling）——纯事件真值，无状态。
 *
 * `isRecoverableRun` 与 recover 成功后的「修了几条」统计共用这一份实现：
 * 两处各写一遍配对逻辑就会漂移（同一个 tool_call 在一处算 dangling、
 * 另一处不算）。append-only 日志下**只增不改**，所以调用方可以安全地
 * 用 before/after 两个集合做差得到「本次恢复修好的条数」。
 */
export function unpairedToolCallIds(events: AgentEvent[]): Set<string> {
  const pending = new Set<string>();
  for (const e of events) {
    if (e.type === EventType.TOOL_CALL) {
      const id = String((e.data as Record<string, unknown> | undefined)?.tool_call_id ?? '');
      if (id) pending.add(id);
    } else if (e.type === EventType.TOOL_RESULT) {
      const id = String((e.data as Record<string, unknown> | undefined)?.tool_call_id ?? '');
      pending.delete(id);
    }
  }
  return pending;
}

/** 最后一个 run 是否有头无尾（`run/started` 之后一个终态都没出现）。
 *
 *  与 `isRecoverableRun` 共用同一趟扫描：恢复反馈要区分「回填了工具结果」与
 *  「补齐了 run 终态」两种修复，而 `repaired` 只数前者——只报 repaired 会把
 *  一次真实的终态修复说成「无可修复项」。
 *  无 run 的裸会话（仅生命周期事件）返回 false（无东西可恢复）。 */
export function hasUnterminatedRun(events: AgentEvent[]): boolean {
  return scanRuns(events).unterminated;
}

/** 一并取出「有没有 run」与「最后一个 run 是否收口」——两个消费者的共同扫描。 */
function scanRuns(events: AgentEvent[]): { hasRun: boolean; unterminated: boolean } {
  let hasRun = false;
  let lastRunTerminated = false;
  for (const e of events) {
    if (e.type === EventType.RUN_STARTED) {
      hasRun = true;
      lastRunTerminated = false;
    } else if (RUN_TERMINAL_TYPES.has(e.type)) {
      lastRunTerminated = true;
    }
  }
  return { hasRun, unterminated: hasRun && !lastRunTerminated };
}

/** 判断会话是否值得展示「恢复」入口。后端建议语义（OR）：
 *  ①最后一个 run 缺少终态（`RUN_TERMINAL_TYPES` 里任一都没出现）；
 *  ②存在无配对 tool/result 的 tool_call（dangling）。
 *  以事件真值判定（不变量 #22），可从 PROJECT 外重复调用（纯函数）。
 *  注意：干净结束的 run（有终态且无 dangling）是终态——不可恢复，
 *  与旧实现「最后事件非 run/completed 即可见」不同（会把干净失败也标成可恢复）。
 *  `run/interrupted` 同样是终态：后端启动扫描已按 Operation Ledger 回填过，
 *  此时仍显示入口等于给用户一个必然 no-op 的按钮。
 *  裸会话（有 dangling 但一个 run/started 都没有）仍然返回 false——比后端字面
 *  语义保守：这种日志本身畸形，暴露「恢复」入口既不解决问题又给出错误承诺。 */
export function isRecoverableRun(events: AgentEvent[]): boolean {
  // 复用同一次扫描：原先 hasRun / hasUnterminatedRun 各扫一遍，同一份事件走两趟。
  const { hasRun, unterminated } = scanRuns(events);
  if (!hasRun) return false;
  return unterminated || unpairedToolCallIds(events).size > 0;
}

/** recover 成功后的反馈文案——结局不能合并成一句「已恢复」：用户看不出后端
 *  到底修了什么，就会把「修好了」与「按钮坏了」看成同一个画面（这正是本缺陷的
 *  原始症状）。纯函数，便于把「不夸大、不误报修复量」锁进单测。
 *
 *  两个「仍未修完」的原因是**分开**传的，不能压成一个布尔：`isRecoverableRun`
 *  是「缺终态 OR 有 dangling」，把布尔当原因就会在「终态已补、只是还有个悬空
 *  tool_call」时误报成「仍缺 run 终态」——和原来那条谎报同一类错。 */
export function recoverDoneMessage(r: {
  repaired: number;
  terminalRepaired: boolean;
  stillUnterminated: boolean;
  stillDangling: boolean;
}): string {
  const remaining =
    r.stillUnterminated && r.stillDangling
      ? '仍缺 run 终态且有未配对工具调用'
      : r.stillUnterminated
        ? '仍缺 run 终态'
        : r.stillDangling
          ? '仍有未配对工具调用'
          : null;
  const fixed =
    r.repaired > 0
      ? r.terminalRepaired
        ? `已恢复：回填 ${r.repaired} 条工具结果，并补齐 run 终态`
        : `已恢复：回填 ${r.repaired} 条工具结果`
      : r.terminalRepaired
        ? '已恢复：补齐 run 终态'
        : null;
  if (fixed) return remaining ? `${fixed}（${remaining}，可重试）` : fixed;
  if (remaining) return `已恢复：本次无回填项（${remaining}，可重试）`;
  return '已恢复：无可修复项（会话事件已完整）';
}
