/** 重连策略状态机（架构深化 C1 的第一刀）。
 *
 * 背景：`useSession.attachLiveStream` 里有三份重连状态——额度计数、单飞标记、
 * 进展游标——此前作为闭包变量 / ref 与 setTimeout、gen 世代校验、setState 交织
 * 在一起。纯决策函数（`decideStreamEnd` / `reconnectDelayMs`）有测试，但
 * **状态迁移本身没有**：「额度什么时候涨、什么时候复位、单飞什么时候放」
 * 只能靠读那 230 行闭包来确认——而重连 bug 恰恰住在这些迁移里。
 *
 * 本类把这三份状态收进一个有明确接口的对象，且**不含 I/O 与定时器**：
 * 调用方拿到 decision 与 delayMs 后自行调度。时间与 I/O 留在调用方，是本类
 * 能在 node 环境同步测试的前提（同一思路见 deepseek-harness 的
 * `BlockStreamer(clock=time.monotonic)`：把时钟交给调用方注入）。
 *
 * 参考设计：pi-mono `packages/agent/src/harness/runtime/lane.ts` 把一次
 * operation 的生命周期状态从编排循环里剥出来。本类是同一动作的最小切片——
 * 只剥重连策略，不动 SSE 消费与投影。
 *
 * 生命周期与不变量：
 * - `request` 准入即占用单飞并递增额度（migrate / give-up 不占用）。
 * - `observeProgress` 只在 seq **严格超过**重连起点游标时复位额度——
 *   重连本身会重放已见过的帧，那些帧不是「真进展」，不得重置额度
 *   （否则额度永不耗尽，失败流会无限重连）。
 * - `release` 只放单飞，不动额度（失败的那次尝试要计入额度）。
 * - `hold` 是同一单飞位的另一种占用方式：truncated 全量重建不是一次重连
 *   尝试，占位只为挡住并发 `request`，不计额度。
 * - `reset` 是整条流的生命周期边界（新 submit / 新续聊）。 */

/** 流终结裁决（契约 §3）：终态帧已见 = 正常收尾；sid 未知或额度耗尽 = 放弃；
 *  否则重连。额度受 MAX_RECONNECT_ATTEMPTS 约束——耗尽后走错误路径
 *  （悬空 run 的恢复入口由既有 recover UI 承接）。 */
export type StreamEndDecision = 'migrate' | 'reconnect' | 'give-up';
export const MAX_RECONNECT_ATTEMPTS = 3;

export function decideStreamEnd(input: {
  terminalSeen: boolean;
  sidKnown: boolean;
  attempts: number;
}): StreamEndDecision {
  if (input.terminalSeen) return 'migrate';
  if (!input.sidKnown || input.attempts >= MAX_RECONNECT_ATTEMPTS) return 'give-up';
  return 'reconnect';
}

/** 重连退避（issue #97：指数退避）：500ms 起步 ×2，封顶 4s。attempt 从 1 计。 */
export function reconnectDelayMs(attempt: number): number {
  return Math.min(500 * 2 ** (attempt - 1), 4000);
}

/** 停摆检测阈值（ms）：live 流超过该时长无任何帧且未终态 → 视为静默断流
 *  （后台杀流 / 连接僵死），主动断开走重连（重放幂等，代价小）。回前台由
 *  visibilitychange 即时触发同一检查；hook 级心跳兜底其余路径。 */
export const RECONNECT_STALL_MS = 10_000;

/** 断线条显示延迟（ms，spec 03 §20「only if reconnect lasts long enough to
 *  matter」）：500ms 级瞬时重连不闪条；超时未接通才出现（role=status 不轰炸）。 */
export const RECONNECT_BANNER_DELAY_MS = 800;

/** `request` 的裁决结果：允许重连（带调度参数）或终态迁移。 */
export type ReconnectRequest =
  | { decision: 'reconnect'; attempt: number; delayMs: number }
  | { decision: 'migrate' }
  | { decision: 'give-up' };

export class ReconnectController {
  /** 已尝试的重连次数（额度消耗量）。 */
  private attempts = 0;
  /** 单飞标记：同一流实例任一时刻最多一条重连链在途。 */
  private pending = false;
  /** 本次重连的起点游标——额度复位只认真实超过它的进展。 */
  private progressBase: number | null = null;

  /** 单飞中？（断线状态条的延迟显示条件之一） */
  get isPending(): boolean {
    return this.pending;
  }

  /** 已消耗额度——UI 诊断与测试用。 */
  get attemptCount(): number {
    return this.attempts;
  }

  /** 重连准入。
   *
   * 单飞中直接返回 null（调用方短路，不重复调度）。
   * `terminalSeen` = 已见终态帧 → migrate；sid 未知或额度耗尽 → give-up；
   * 否则占用单飞、递增额度、记录本次重连起点，返回调度参数。 */
  request(input: {
    sid: string | null;
    terminalSeen: boolean;
    lastAppliedSeq: number | null;
  }): ReconnectRequest | null {
    if (this.pending) return null;
    const decision = decideStreamEnd({
      terminalSeen: input.terminalSeen,
      sidKnown: Boolean(input.sid),
      attempts: this.attempts,
    });
    if (decision === 'migrate') return { decision: 'migrate' };
    if (decision === 'give-up') return { decision: 'give-up' };
    this.pending = true;
    this.attempts += 1;
    this.progressBase = input.lastAppliedSeq;
    return { decision: 'reconnect', attempt: this.attempts, delayMs: reconnectDelayMs(this.attempts) };
  }

  /** 观察到事件 seq：严格超过本次重连起点才算真进展 → 额度复位。
   *  重连重放的旧帧（seq ≤ 游标）不算——否则额度永不耗尽。
   *  起点游标为 null（sid 已知但尚无持久帧）时永不复位——照搬重构前的
   *  闭包守卫，实测路径上 sid 由首帧带入而首帧带 seq，属窄边角。
   *  返回是否发生了复位：调用方当前不消费，但单测据此直接锁定迁移，
   *  不必为断言去反推内部状态。 */
  observeProgress(seq: number | null): boolean {
    if (this.progressBase === null || seq === null || seq <= this.progressBase) return false;
    this.attempts = 0;
    this.progressBase = null;
    return true;
  }

  /** 占用单飞位而不计额度（truncated 全量重建路径）。 */
  hold(): void {
    this.pending = true;
  }

  /** 一次重连尝试收尾（成功接流 / 拉流失败 / 重建结束）——放单飞，
   *  **不动额度**：失败的那次尝试已计入额度，重建本就不计。 */
  release(): void {
    this.pending = false;
  }

  /** 整条流的生命周期边界（新 submit / 新续聊）——全量复位。 */
  reset(): void {
    this.attempts = 0;
    this.pending = false;
    this.progressBase = null;
  }
}
