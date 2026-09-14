/** useSession — orchestrates session list, history loading, and live streaming.
 *
 * State model: a single discriminated `mode` (SessionMode) is the source of truth —
 *   idle                    → no session (empty state), conversation is null
 *   live(sessionId?)        → a new task is streaming; events paint the conversation
 *   viewing(sessionId)      → a durable session is being viewed (history rebuild)
 * `selectedId` / `streaming` are derived from mode, so conversation.session_id and
 * the highlighted row can never disagree (invariant #22: no second truth).
 *
 * Migrations:
 *   submit    → live(null), conversation reset (a new task never folds into the
 *               previously viewed session's state)
 *   first SSE frame with session_id → live(sid)
 *   done/error/cancel → viewing(known sid) or idle (nothing durable yet) — the
 *               history loader re-reads the durable log so the view always
 *               comes from the fact source.
 *   selectSession → cancels any live stream (idempotent) and switches mode.
 *
 * Disconnect cleanup: SSE handle's cancel() is wired to unmount via useEffect ref.
 * ADR-0016 detached-run（T5 #98）：cancel/abort 只解订阅，run 服务端跑到终态——
 * 显式中断唯一入口是 cancelStream 的 POST /cancel（decideCancel 决策）。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AgentEvent, ConversationState, SessionDeleted, SessionMode, SessionSummary } from '../types';
import { listSessions, getSessionEvents, startSession, startSessionErrorDetail, streamSession, cancelSession, recoverSession, sendMessage as apiSendMessage, changeSessionModel, forkSession, deleteSession, archiveSession, unarchiveSession, NotFoundError, RecoverError, SessionError, type SendMessagePayload, type StartSessionPayload } from '../lib/api';
import { consumeSSE, type SSEHandle } from '../lib/sse';
import { initConversation, applyEvent, projectHistory, deriveSessionTitle, extractSessionTitle } from '../lib/projection';
import { MAX_RECONNECT_ATTEMPTS, RECONNECT_BANNER_DELAY_MS, RECONNECT_STALL_MS, ReconnectController } from '../lib/reconnect';
import { RUN_TERMINAL_TYPES, hasUnterminatedRun, unpairedToolCallIds } from '../lib/runState';
import { forgetResumeAttempt, maxEventSeq, nextResumeAttempt, readStoredSessionId, writeStoredSessionId, type ResumeAttempts } from '../lib/sessionRestore';

/** 流式帧 vs 当前模式一致性判别（不变量 #22：UI 不维护第二套真相）。
 *
 * SSE 流在 submitTask 时开启，回调闭包持有当时的 conv。若用户在流结束前
 * cancel / 切换会话 / 触发 error，mode 迁移到 viewing/idle，但 SSE 在途帧
 * 仍可能晚于这次 mode 变更到达——回调再写 conversation 就会用旧流残留
 * 覆盖刚加载的目标会话视图。
 *
 * 守护：每帧应用前先问「当前模式是否仍是这条流的权威消费者」。提取为
 * 纯函数是为了锁不变量——React 状态机本身的回归需 testing-library，
 * 引入它会扩大 scope；这一层契约纯函数就能锁住。 */
export function shouldApplyStreamFrame(mode: SessionMode, event: AgentEvent): boolean {
  // 离开 live 即丧失权威——viewing 由持久事件源重建，idle 无会话。
  if (mode.kind !== 'live') return false;
  // 首帧尚未确定 sid（sessionId === null）：任意帧都接受。
  if (mode.sessionId === null) return true;
  // 帧未带 sid（理论只会在首帧前出现）：宽容接受，避免误丢首帧。
  const eventSid = event.session_id ?? null;
  if (eventSid === null) return true;
  // sid 不匹配——旧流迟到帧窜入新会话，明确拒绝。
  return mode.sessionId === eventSid;
}

/** Recover 入口的视图状态。
 *
 * `done` 是**成功后的落地态**，不是过场动画：崩溃会话常常已经被后端启动
 * 扫描修完了，此时 recover 是一次真 no-op、投影逐字不变——若成功也回到
 * `idle`，「修好了」与「按钮坏了」在界面上完全同形（用户实测：「点了什么
 * 反应也没有」，连点 15 次）。`repaired` 给出这次到底补了几条工具结果，
 * 0 就是「无可修复项」——两者都是诚实的成功。 */
export interface RecoverState {
  status: 'idle' | 'pending' | 'done' | 'error';
  /** 409 裁决原因 / 404·网络错误的具体信息。 */
  message: string | null;
  /** 409 = 存在需人工裁决的高风险操作（展示态，非普通失败）。 */
  conflict: boolean;
  /** status === 'done' 时：本次恢复补上的 tool/result 条数。 */
  repaired: number;
  /** status === 'done' 时：本次恢复补上了缺失的 run 终态。
   *  与 `repaired` 分开计数——只报工具回填会把「补齐终态」说成「无可修复项」。 */
  terminalRepaired: boolean;
  /** status === 'done' 时：恢复后**投影**仍未收口的两项原因（分开传，见
   *  runState.recoverDoneMessage——压成一个布尔会把原因说错）。 */
  stillUnterminated: boolean;
  stillDangling: boolean;
}

/** Recover 的 idle 初值——两处复用（useState 初值 / mode 迁移重置）。
 *  对象只被整体替换、从不就地修改，共享引用安全。retry 直接置 `pending`，
 *  不经这里（这也是它区别于初值的地方：重试不该先闪一下 idle）。 */
const RECOVER_IDLE: RecoverState = {
  status: 'idle', message: null, conflict: false, repaired: 0,
  terminalRepaired: false, stillUnterminated: false, stillDangling: false,
};

/** Recover 响应落地守护（不变量 #22，shouldApplyStreamFrame 的姊妹契约）。
 *
 * recover 是异步请求：pending 期间用户可能已切走（selectSession /
 * submitTask / cancelStream 都会迁移 mode）。晚到的 200 响应若仍
 * setConversation，会用旧会话的重建结果覆盖刚加载的目标会话视图——
 * 与迟到 SSE 帧同族的 stale-write。仅当当前模式仍是「查看该会话」时，
 * recover 的结果才是当前视图的权威真相。 */
export function shouldApplyRecoverResult(mode: SessionMode, sid: string): boolean {
  return mode.kind === 'viewing' && mode.sessionId === sid;
}

/** T5（#98）显式取消的传输层决策（detached-run 契约回执 §0.3/§3）。
 *
 * 断连不再取消 run（订阅者离开只 unsubscribe）——Esc/停止必须走
 * POST /cancel 借道显式中断；abort 仅剩传输层清理语义。
 *
 * - 已知 sid → cancel-request：POST /cancel（200 cancelling / 200 no_active_run
 *   幂等成功 / 404），**流保持打开**——run/failed(data.reason='cancelled') 经流
 *   广播驱动既有 onDone → viewing 收尾迁移，不用 abort 伪装取消。
 * - sid 未知（POST 在途、首帧未确认，无从显式取消）→ abort-transport：
 *   仅清理订阅；run 由后端孤儿回收兜底（reason=orphaned，契约 §4）。 */
export type CancelDecision =
  | { kind: 'cancel-request'; sessionId: string }
  | { kind: 'abort-transport' };

export function decideCancel(liveSid: string | null): CancelDecision {
  return liveSid ? { kind: 'cancel-request', sessionId: liveSid } : { kind: 'abort-transport' };
}

// ── T4（#97）重连契约（后端契约回执 §3，spec 02 §10 / 03 §20）──
// 决策纯函数与重连状态机同住 lib/reconnect.ts（无 React / 定时器 / I/O，
// 可独立单测）；此处 re-export 保持既有导入路径不破。
export {
  decideStreamEnd,
  reconnectDelayMs,
  RECONNECT_STALL_MS,
  RECONNECT_BANNER_DELAY_MS,
  MAX_RECONNECT_ATTEMPTS,
  type StreamEndDecision,
} from '../lib/reconnect';

/** seq gap 检测（契约 §1：subscriber 队列满时后端丢最旧保最新，gap = 重连信号）。
 *  null seq（ephemeral 帧）与无基线（首帧前）永不构成 gap；回跳 seq 由 T1
 *  去重门/投影宽松契约处理，不算 gap。 */
export function isSeqGap(lastApplied: number | null, incoming: number | null): boolean {
  return lastApplied !== null && incoming !== null && incoming > lastApplied + 1;
}

/** stream/truncated 控制帧载荷解析（backlog > 1000，契约 §3）：latest_seq 是
 *  重建后续传游标，必须为有限数；畸形/缺失 → null（忽略控制帧，按普通断连
 *  路径重连）。after_seq 字段仅为回显，前端不用。 */
export function parseTruncated(data: Record<string, unknown>): { latestSeq: number } | null {
  const seq = data.latest_seq;
  return typeof seq === 'number' && Number.isFinite(seq) ? { latestSeq: seq } : null;
}

/** live→viewing 迁移时是否显示「正在加载历史…」占位符。
 *
 * 流结束的会话 conversation 已是该会话的完整投影真相（同一事件源流式构建，
 * session_id 一致）——历史重读只是后台对账，不得用占位符把它替换掉
 * （替换 = 主窗口闪烁 + 滚动位置丢失，用户可见回归 2026-09-06）。
 * 仅当目标会话与当前视图不一致（首次打开/切换目标）时才需要占位符。 */
export function shouldShowHistoryLoading(
  conversation: ConversationState | null,
  sid: string,
): boolean {
  if (!conversation) return true;
  if (conversation.session_id !== sid) return true;
  return false;
}

/** P1-3 delta 合帧提交器（HANDOFF_PERF_FRONTEND §6）：~24ms 窗口内多个 delta
 * 只触发一次 React 提交。语义边界——只合并「提交」，不合并「折叠」：每帧仍
 * 逐帧过 shouldApplyStreamFrame 守护并立即 applyEvent 进本地 conv（真相不
 * 延迟）；延迟的只是 setConversation 通知。流终止（run/completed、
 * run/failed、onDone、onError）必须 flush，否则尾帧丢失。 */
export interface CommitCoalescer {
  /** 标记有待提交数据；窗口内多次调用只调度一次。 */
  schedule(): void;
  /** 立即提交待合帧数据（无则 no-op），并取消挂起的定时器。 */
  flush(): void;
  /** 丢弃挂起的定时器与待提交标记（流被 cancel 后不再迟到提交）。 */
  cancel(): void;
}

/** T7（#100）可见性注入签名：默认恒 true（前台语义零回归）。 */
export type VisibilityProbe = () => boolean;

export function createCommitCoalescer(
  submit: () => void,
  windowMs = 24,
  isVisible: VisibilityProbe = () => true,
): CommitCoalescer {
  let dirty = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const fire = () => {
    timer = null;
    if (!dirty) return;
    dirty = false;
    submit();
  };
  return {
    schedule() {
      dirty = true;
      if (timer !== null) return;
      // T7（#100）后台降渲染（spec 03 §18.3）：隐藏期不排定时器——dirty 挂起，
      // 真相仍逐帧 applyEvent 进本地 conv（数据零丢失），只延迟 setConversation
      // 通知；回前台由 visibilitychange flush 一次（整段积压合帧单提交）。
      if (!isVisible()) return;
      timer = setTimeout(fire, windowMs);
    },
    flush() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      fire();
    },
    cancel() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      dirty = false;
    },
  };
}

/** 422 = 未知模型（契约 C6）的稳定标记与判定（Standards 轴：消魔法子串跨模块
 *  耦合——useSession 的错误文案是 submitTask 对外的唯一通道，App 据此刷新模型
 *  目录；判定函数+常量单一来源，文案改动不会静默破坏识别）。 */
export const UNKNOWN_MODEL_ERROR_TEXT = '模型不可用（422）：请从模型选择器重新选择';

export function isUnknownModelError(message: string | null | undefined): boolean {
  return message === UNKNOWN_MODEL_ERROR_TEXT;
}

/** 续聊 422 的稳定文案（handoff §5 P2，P1 修复后）：/messages 的 422 现在可能来自
 *  session_id 非法 / 未知 model 或 context_providers（仅 idle→launched 时校验）/
 *  非法 reasoning_effort 或 agent_profile 取值——不再等同于「未知模型」。
 *  后端 detail 不是契约文本（Pydantic 校验与 HTTPException 的形状也不同），
 *  所以不做子串区分，统一提示「刷新选项后重试」。 */
export const CONTINUE_PARAMS_ERROR_TEXT = '续聊参数无效（422）：请刷新选项后重试';

export function useSession() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  /** 首屏即从 localStorage 恢复上次选中的会话（BUG-005）。
   *
   *  用惰性初值，而不是「列表回来后再 setMode」的 effect：① 首帧就是
   *  `viewing(sid)`，直接进「正在加载历史…」，不会先闪一下空态再跳到会话；
   *  ② 选中态本来就是用户上次留下的持久值——它**是**初始值，不是对某次
   *  变更的响应，所以不该由 effect 产生（effect 里同步 setState 也会多一条
   *  lint 告警）。
   *
   *  该 id 可能已经失效（会话被删 / 换过后端实例）：装载报 404 时按
   *  NotFoundError 分支安静回到空态并清键，不做「先查列表再决定」的预校验
   *  ——那要等列表、多一次往返，且仍要处理竞态。 */
  const [mode, setMode] = useState<SessionMode>(() => {
    const stored = readStoredSessionId();
    return stored ? { kind: 'viewing', sessionId: stored } : { kind: 'idle' };
  });
  const [conversation, setConversation] = useState<ConversationState | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Session Rail 行标题缓存（Session Model E 轮）：查看某会话时从首条 user/message
  // 投影出标题，本地缓存供 SessionList 行渲染。无缓存时回退到短 ID——不伪造。
  const [titlesById, setTitlesById] = useState<Record<string, string>>({});

  const sseRef = useRef<SSEHandle | null>(null);
  // T7（#100）：活跃流的合帧提交器镜像——visibilitychange 监听要 flush 当前流，
  // 而 coalescer 在 submitTask 闭包内创建，监听在 hook 顶层只能经 ref 触达。
  const coalescerRef = useRef<CommitCoalescer | null>(null);
  // live 流中已知的首帧 sid——结束/出错/取消时决定迁移目标。
  const liveSidRef = useRef<string | null>(null);
  // mode 的实时镜像——SSE 回调闭包在 submitTask 时定型，读到的 mode 是
  // 提交瞬间快照而非当前真相。镜像让每帧应用前能问「当前模式是否仍是
  // 这条流的权威消费者」（不变量 #22），从而拒绝 cancel / selectSession
  // 之后才到达的迟到帧。
  const modeRef = useRef<SessionMode>(mode);
  modeRef.current = mode;
  // conversation 的实时镜像——sendFollowUp 需要当前 conversation 作为
  // attachLiveStream 的 initialConv，但不能把 conversation 放进 deps
  //（每帧变化会导致回调重建）。用 ref 读最新值即可。
  const conversationRef = useRef<ConversationState | null>(conversation);
  conversationRef.current = conversation;

  // T4（#97）重连状态机 refs：lastAppliedSeq = 已应用最大持久 seq（续传游标，
  // 重放与续传由 seenSeqs 去重吸收重复）；streamGen = 流代际（切走/取消/卸载
  // 即自增，旧流全部回调自失效）；terminalSeen = 终态帧已达（决定流结束走
  // 迁移还是重连）；lastFrameAt = 最后一帧墙钟（停摆检测基准）。
  const lastAppliedSeqRef = useRef<number | null>(null);
  // 重连策略状态机（T4 #97，深化 C1）：额度 / 单飞 / 进展游标三份状态从
  // attachLiveStream 闭包里剥出——它们此前散在一个 ref 与两个闭包变量里，
  // 迁移规则只能靠通读整段闭包确认。控制器无 I/O 无定时器，调度仍留在此处。
  const reconnectRef = useRef<ReconnectController>(new ReconnectController());
  const streamGenRef = useRef(0);
  const terminalSeenRef = useRef(false);
  const lastFrameAtRef = useRef(Date.now());
  // submitTask 闭包内的停摆检查（依赖 gen/coalescer 等闭包状态）——
  // hook 级心跳与 visibilitychange 经此触达当前活跃流。
  const stallCheckRef = useRef<(() => void) | null>(null);
  // 恢复实时流的入口镜像——历史装载 effect 在 hook 上方，而 resumeLiveStream
  // 定义在下方（它依赖 attachLiveStream）。与 stallCheckRef 同一处理：跨
  // 区块调用经 ref 触达，**在 effect 里镜像**（见下方定义处；render 期写 ref
  // 违反 refs 规则，曾据此改过一次，别改回去）。
  const resumeLiveStreamRef = useRef<
    ((sid: string, afterSeq: number, initialConv: ConversationState) => void) | null
  >(null);
  const [reconnecting, setReconnecting] = useState(false);

  // Recover 四态（df4f7d8 §1.1 + 本次修复）：idle → pending → 200 成功落 `done`
  // （整表重建 + 明确的成功反馈，原因见 RecoverState 注释）/ 404·409·网络错误
  // → error。409 是"需人工裁决"（conflict=true），本期只展示原因，不做裁决
  // 交互（不变量 #14：不伪造、不盲跑）。
  const [recoverState, setRecoverState] = useState<RecoverState>(RECOVER_IDLE);

  // Derived, so the UI can never observe a mismatch between them.
  const selectedId = mode.kind === 'idle' ? null : mode.sessionId;
  const streaming = mode.kind === 'live';

  // Load session list on mount.
  /** 重新拉取会话列表。返回**是否成功**——`sessions` 的唯一写入者，所以调用方
   *  （`setArchived`）需要知道"界面现在是不是已经反映了新状态"。
   *  返回值对既有调用方（`void refreshSessions()` / `onSessionsChanged`）无影响：
   *  它们忽略它，失败处理仍走 `error` 那条既有通道（`<T> void` 语义不变）。 */
  const refreshSessions = useCallback(async (): Promise<boolean> => {
    try {
      // #171：**总是**要全量（含已归档）。可见性由 UI 的开关决定，不由请求决定——
      // 否则「已归档」开关一开就得再发一次请求，而两次响应之间列表是两套真相
      // （不变量 #22）。后端默认仍是不带参数就隐藏（其他客户端照旧），这里只是
      // 显式说明「这份 UI 要自己过滤」，也让投影层能对归档行给出真实徽标与计数。
      const list = await listSessions({ includeArchived: true });
      setSessions(list);
      // 后端 Gap 3：列表 payload 携带首条用户消息（截断 128）——零额外请求预填
      // 标题缓存。events 扫描（viewing 路径）保留为后端未返回时的 fallback；
      // 已有标题不覆盖（事件派生值优先，保持单一更新路径语义）。
      setTitlesById((m) => {
        let changed = false;
        const next = { ...m };
        for (const s of list) {
          if (s.first_user_message && !next[s.session_id]) {
            next[s.session_id] = s.first_user_message;
            changed = true;
          }
        }
        return changed ? next : m;
      });
      return true;
    } catch (e) {
      setError(`加载会话列表失败：${(e as Error).message}`);
      return false;
    }
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  // 记住选中的会话（BUG-005）：刷新后要能回到同一个会话，内容与刷新前一致。
  // 落点选在 mode 上——它是选中态的唯一真相（selectedId 由它派生），所以
  // 「何时记住」不需要在 selectSession / 分叉 / 新任务三处各写一遍。
  // idle ⇒ 显式忘记：用户点了「新建会话」就不该在刷新后被拉回旧会话。
  // live(null)（已提交、首帧还没带 sid）不写也不清——等 sid 到。
  useEffect(() => {
    if (mode.kind === 'idle') writeStoredSessionId(null);
    else if (mode.sessionId) writeStoredSessionId(mode.sessionId);
  }, [mode]);

  // History loading: viewing mode reads the durable log; live mode lets the
  // stream paint (a stale/partial disk read would overwrite in-flight state);
  // idle owns no conversation.
  useEffect(() => {
    // 任何 mode 迁移都重置 recover 三态（恢复状态不跨会话/流存活）。
    setRecoverState(RECOVER_IDLE);
    if (mode.kind === 'idle') {
      setConversation(null);
      return;
    }
    if (mode.kind !== 'viewing') return;
    const sid = mode.sessionId;
    let cancelled = false;
    // live→viewing 迁移：conversation 已是同会话真相，后台静默重读对账，
    // 不用占位符替换（防主窗口闪烁）。切到不同会话才显示占位符。
    // live→viewing 自迁移（流终态 / 续聊失败 / 重连放弃）不清错误横幅——否则
    // sendFollowUp 与重连的失败提示会在同一批次被这条 effect 立刻抹掉。
    // 只有真的切到别的会话（或首次加载）才清。
    const switchingSession = shouldShowHistoryLoading(conversation, sid);
    setLoadingHistory(switchingSession);
    if (switchingSession) setError(null);
    getSessionEvents(sid)
      .then((events: AgentEvent[]) => {
        if (cancelled) return;
        const projected = projectHistory(sid, events);
        setConversation(projected);
        // 从真实事件流投影首条用户消息作为行标题（无则空串，回退短 ID）。
        const title = deriveSessionTitle(events);
        if (title) setTitlesById((m) => (m[sid] === title ? m : { ...m, [sid]: title }));
        // BUG-006：这个 run 在服务端可能仍在跑（刷新/重连后最常见的那种会话）。
        // 历史照旧渲染（用户马上看到内容），随后接回实时流继续长；
        // 若其实已经收口，onStreamEnd 的零帧分支静默退回 viewing，不报错。
        if (hasUnterminatedRun(events)) {
          resumeLiveStreamRef.current?.(sid, maxEventSeq(events), projected);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        // 记住的选中会话已不存在（被删 / 换后端）：清键 + 安静回空态。
        // 每次刷新都弹「加载历史事件失败：会话不存在」是用户无法处理的错误。
        if (e instanceof NotFoundError) {
          writeStoredSessionId(null);
          setMode({ kind: 'idle' });
          return;
        }
        setError(`加载历史事件失败：${(e as Error).message}`);
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  // Cleanup SSE on unmount.
  useEffect(() => {
    return () => {
      streamGenRef.current += 1; // 使任何在途重连/停摆检查失效
      stallCheckRef.current = null;
      sseRef.current?.cancel();
    };
  }, []);

  // T4（#97）停摆心跳：每 RECONNECT_STALL_MS 检查一次当前活跃流（检查本体
  // 在 submitTask 闭包内，经 stallCheckRef 触达；非 live 流为 no-op）。
  useEffect(() => {
    const heartbeat = setInterval(() => stallCheckRef.current?.(), RECONNECT_STALL_MS);
    return () => clearInterval(heartbeat);
  }, []);

  // T7（#100）background tab 降渲染（spec 03 §18.3）：隐藏→flush 落盘当前状态
  // （干净暂停点）；回前台→flush 立即对账（后台积压合帧为单次提交，一帧内
  // reconcile，无重放动画）。隐藏期间 schedule 挂起，事件照常逐帧入本地 conv。
  // T4（#97）：回前台附带即时停摆检查——后台期浏览器可能静默杀流。
  useEffect(() => {
    const onVisibility = () => {
      coalescerRef.current?.flush();
      if (document.visibilityState === 'visible') stallCheckRef.current?.();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

/** Submit a new task. Creates a fresh session and streams the response.
   *  The conversation is reset first — a live stream never folds into the
   *  previously viewed session's turns.
   *  T4（#97）：流消费升级为重连状态机——异常关闭 / seq gap / 停摆（含后台
   *  杀流）触发 GET stream?after_seq=lastApplied 续传；stream/truncated 控制
   *  帧走 GET /events 全量重建后续传；终态帧已达 → 正常收尾迁移。 */
  /** SSE 流消费机器——submitTask 和 sendMessage 共用。
   *  P1-3 合帧 + T7 后台降渲染 + T4 重连状态机全部内联于此。
   *  initialConv：新会话传 null（首帧惰性初始化）；续聊传当前 conversation（追加）。
   *  gen：流代际（submit/sendMessage 入口已自增并捕获），旧流全部回调凭此失效。
   *  opts.resume（BUG-006）：这条流是**刷新后恢复**时接上去的，不是新提交。
   *    差别只在 onStreamEnd 的零帧收流分支——见那里的注释。 */
  const attachLiveStream = useCallback(
    (res: Response, gen: number, initialConv: ConversationState | null, opts?: { resume?: boolean }) => {
        // P1-3 合帧 + T7 后台降渲染：窗口内多 delta 一次提交；隐藏期挂起、
        // 回前台 flush 对账。折叠逐帧即时（真相不延迟），延迟的只是通知。
        // T4：conv 由重连路径与 live 帧共享——同一折叠累积器，重放帧经
        // seenSeqs 去重吸收（无缝无重复的关键在 T1 去重门 + seq 游标本地记账）。
        let conv: ConversationState | null = initialConv;
        /** 本代际收到的帧数（含重放帧）——只给 resume 的零帧判定用。 */
        let framesSeen = 0;
        const coalescer = createCommitCoalescer(
          () => {
            if (conv && modeRef.current.kind === 'live') setConversation({ ...conv });
          },
          24,
          () => document.visibilityState === 'visible',
        );
        coalescerRef.current = coalescer;

        /** 正常收尾迁移（终态已达）。 */
        const finishLive = () => {
          coalescer.flush(); // 尾帧不丢（P1-3）
          coalescerRef.current = null;
          setReconnecting(false);
          const sid = liveSidRef.current;
          setMode(sid ? { kind: 'viewing', sessionId: sid } : { kind: 'idle' });
          refreshSessions();
        };

        const onEvent = (event: AgentEvent) => {
          if (streamGenRef.current !== gen) return;
          // 不变量 #22 守护：cancel / selectSession / error 之后才到达的
          // 在途帧不再具有权威——若放行会用旧流残留覆盖刚加载的目标视图。
          if (!shouldApplyStreamFrame(modeRef.current, event)) return;
          framesSeen += 1; // 恢复探测用：见 onStreamEnd 的「零帧收流」
          lastFrameAtRef.current = Date.now();
          // T4 控制帧先于投影（seq=null 不入轮次）：backlog>1000 → 全量重建。
          // 'stream/truncated' 是 web 层控制帧（app.py 内联构造，不在 event.py
          // 词汇表）——generated/event-types.ts 由 event.py 生成，此字面量是
          // 唯一正确落点（勿收进生成产物）。
          if (event.type === 'stream/truncated') {
            const plan = parseTruncated(event.data);
            sseRef.current?.cancel(); // 静默断开，不走 onStreamEnd
            if (plan && liveSidRef.current) void doTruncatedRebuild(liveSidRef.current);
            // 畸形/缺失：按普通断连路径重连（parseTruncated 契约，不留 UI 死区）
            else scheduleReconnect(liveSidRef.current, 'stream/truncated malformed');
            return;
          }
          // T4：seq gap = 后端队列丢帧信号（契约 §1）→ 断开重连，本地不投影半截
          if (isSeqGap(lastAppliedSeqRef.current, event.seq)) {
            sseRef.current?.cancel();
            scheduleReconnect(liveSidRef.current, 'seq gap');
            return;
          }
          if (RUN_TERMINAL_TYPES.has(event.type)) {
            terminalSeenRef.current = true;
          }
          const sid = event.session_id ?? null;
          if (sid) {
            liveSidRef.current = sid;
            // 首帧确认：把 sid 写进 mode（仅从 null 迁移一次）
            setMode((m) =>
              m.kind === 'live' && m.sessionId === null ? { kind: 'live', sessionId: sid } : m,
            );
          }
          if (!conv) conv = initConversation(sid ?? 'streaming');
          conv = applyEvent(conv, event);
          // T4 游标本地记账：续传 after_seq 的真相源（SSE 帧不携带 event_id，
          // cursor = seq；event_id 优先键升级路径已记 ADR-0016 DEFER）。
          if (event.seq !== null) {
            const prev = lastAppliedSeqRef.current;
            lastAppliedSeqRef.current = prev === null ? event.seq : Math.max(prev, event.seq);
          }
          // T4 额度复位以「观察到新 seq 进展」为准（Spec 轴 P0）：悬空 run
          // 每轮重连都是 200 + 重放零新进展——若在 attach 成功时清零额度，
          // give-up 不可达 → 无限重连、recover 入口永不出现。仅当新帧 seq
          // 超过重连起点游标（真进展）才复位。
          reconnectRef.current.observeProgress(event.seq);
          // 首条用户消息到达时缓存行标题（Session Model E 轮）。
          if (sid) {
            const content = extractSessionTitle(event);
            if (content) setTitlesById((m) => (m[sid] ? m : { ...m, [sid]: content }));
          }
          // 终态事件立即 flush（尾帧不得延迟到下一窗口）；中间帧合帧提交。
          if (RUN_TERMINAL_TYPES.has(event.type)) {
            coalescer.flush();
          } else {
            coalescer.schedule();
          }
        };

        const onStreamEnd = () => {
          // gen 检查先于 flush：submit 重入后旧流的迟来收尾不得把旧 conv
          // 写进新视图（modeRef live 守卫在同代际内失效）。
          if (streamGenRef.current !== gen) return;
          coalescer.flush(); // 尾帧不丢（P1-3）
          // 恢复流的零帧收流 = **服务端已经没有在跑的 run**（实测：
          // `GET /stream?after_seq=<max>` 对空闲会话立即 200 + 空 body 关闭，
          // 5ms）。这不是「连接异常关闭」，重连只会重试到一个空流、耗尽额度后
          // 给用户一条假的「连接中断」错误横幅。静默退回 viewing 即可——
          // 历史已在恢复时装载过，界面无变化。
          if (opts?.resume && framesSeen === 0 && !terminalSeenRef.current) {
            coalescerRef.current = null;
            setReconnecting(false);
            const sid = liveSidRef.current;
            setMode(sid ? { kind: 'viewing', sessionId: sid } : { kind: 'idle' });
            return;
          }
          // 终态已见 = 自然终结（含重放收到终态）；未终态 = 服务端提前收流
          //（契约推荐重连时机①：连接异常关闭）。
          if (terminalSeenRef.current) {
            finishLive();
            return;
          }
          scheduleReconnect(liveSidRef.current, 'stream ended unexpectedly');
        };

        const onStreamError = (err: unknown) => {
          if (streamGenRef.current !== gen) return;
          coalescer.flush();
          // 终态已见：错误后置——正常收尾优先（不影响已到真相）。
          if (terminalSeenRef.current) {
            finishLive();
            return;
          }
          scheduleReconnect(liveSidRef.current, (err as Error).message);
        };

        const attach = (streamRes: Response) => {
          sseRef.current = consumeSSE(streamRes, onEvent, onStreamEnd, onStreamError);
        };

        // 单飞守卫（Standards 轴 P1）：同一流实例任一时刻最多一条重连链——
        // 同批多帧 gap / 停摆心跳 / visibility 检查都汇入 scheduleReconnect，
        // 挂起期间重复触发在 request 内短路（对齐 sse.ts cancelled 的单流
        // 实例模式）。额度 / 单飞 / 进展游标三份状态见 lib/reconnect.ts。

        /** 重连调度（契约 §3）：指数退避 + 额度上限（decideStreamEnd）。
         *  404 = 会话不存在，立即放弃不空转。接流成功即释放单飞；额度复位
         *  以 onEvent 观察到真进展为准（见上）。显式 cancel（T5）不经过这里
         *  ——cancel-request 分支不 abort 流，终态帧经流广播驱动 finishLive。 */
        const scheduleReconnect = (sid: string | null, reason: string) => {
          if (streamGenRef.current !== gen) return;
          const req = reconnectRef.current.request({
            sid,
            terminalSeen: terminalSeenRef.current,
            lastAppliedSeq: lastAppliedSeqRef.current,
          });
          if (req === null) return; // 单飞中：已有重连链在途
          if (req.decision === 'migrate') {
            finishLive();
            return;
          }
          if (req.decision === 'give-up') {
            coalescerRef.current = null;
            setReconnecting(false);
            setMode(sid ? { kind: 'viewing', sessionId: sid } : { kind: 'idle' });
            setError(`连接中断（${reason}）：重试 ${MAX_RECONNECT_ATTEMPTS} 次未成功`);
            refreshSessions();
            return;
          }
          // 断线状态条延迟显示（spec 03 §20）：瞬时重连不闪条——延迟到期仍
          // 在挂起中才出现；接流成功即释放单飞，条不显示。
          setTimeout(() => {
            if (streamGenRef.current === gen && reconnectRef.current.isPending) setReconnecting(true);
          }, RECONNECT_BANNER_DELAY_MS);
          setTimeout(() => {
            if (streamGenRef.current !== gen) return;
            void (async () => {
              try {
                const after = lastAppliedSeqRef.current ?? -1;
                const streamRes = await streamSession(sid as string, after);
                if (streamGenRef.current !== gen) return;
                reconnectRef.current.release();
                if (streamRes.status === 404) {
                  coalescerRef.current = null;
                  setReconnecting(false);
                  // 不在这里清 localStorage：live→viewing 会重跑历史装载，那条
                  // 404 → NotFoundError → 清键 + 回 idle，才是落得住的清理点。
                  setMode({ kind: 'viewing', sessionId: sid as string });
                  setError('会话不存在（404）——流已终止');
                  refreshSessions();
                  return;
                }
                if (!streamRes.ok || !streamRes.body) throw new Error(`reconnect ${streamRes.status}`);
                setReconnecting(false);
                attach(streamRes);
              } catch (e) {
                reconnectRef.current.release(); // 放回调度口（额度仍受 decideStreamEnd 约束）
                scheduleReconnect(sid, (e as Error).message || reason);
              }
            })();
          }, req.delayMs);
        };

        /** stream/truncated（backlog>1000，契约 §3）：GET /events 全量重建
         *  （projectHistory 同一管线，不变量 #22）→ 以重建后真实 max seq 续传
         *  （payload latest_seq 仅是回显，游标以本地真实事实为准）。 */
        const doTruncatedRebuild = (sid: string) => {
          reconnectRef.current.hold();
          setReconnecting(true); // 全量重建（GET /events + projectHistory）非瞬时，条即时在场
          void (async () => {
            try {
              const events = await getSessionEvents(sid);
              if (streamGenRef.current !== gen) return;
              conv = projectHistory(sid, events);
              setConversation({ ...conv });
              let maxSeq: number | null = null;
              for (const e of events) {
                if (typeof e.seq === 'number' && (maxSeq === null || e.seq > maxSeq)) maxSeq = e.seq;
              }
              lastAppliedSeqRef.current = maxSeq;
              const streamRes = await streamSession(sid, maxSeq ?? -1);
              if (streamGenRef.current !== gen) return;
              reconnectRef.current.release();
              if (!streamRes.ok || !streamRes.body) throw new Error(`reconnect ${streamRes.status}`);
              setReconnecting(false);
              attach(streamRes);
            } catch (e) {
              reconnectRef.current.release();
              scheduleReconnect(sid, (e as Error).message || 'full rebuild failed');
            }
          })();
        };

        /** 停摆检查（T4）：live 且未终态且超阈值无帧 → 静默断流（后台杀流/
         *  连接僵死），主动断开走重连。经 stallCheckRef 暴露给心跳与
         *  visibilitychange（回前台即时触发）。 */
        const stallCheck = () => {
          if (streamGenRef.current !== gen) return;
          if (modeRef.current.kind !== 'live' || terminalSeenRef.current) return;
          if (Date.now() - lastFrameAtRef.current > RECONNECT_STALL_MS) {
            sseRef.current?.cancel();
            scheduleReconnect(liveSidRef.current, 'connection stalled');
          }
        };
        stallCheckRef.current = stallCheck;

        sseRef.current = consumeSSE(res, onEvent, onStreamEnd, onStreamError);
    },
    [refreshSessions],
  );

  /** Submit a new task. Creates a fresh session and streams the response.
   *  The conversation is reset first — a live stream never folds into the
   *  previously viewed session's turns.
   *
   *  返回值：`null` = 请求已被接受、流已接上；否则 = **给用户看的失败原因**。
   *  默认同时写进全局 error 横幅（Composer 路径的历史行为，App 还据那句话识别
   *  「未知模型」并刷新模型目录）。传 `{ ownError: true }` 时**不**写横幅、只返回
   *  原因——「在此项目中新建任务」确认面（#169 AC12）要把它留在浮层里，而且需要
   *  后端 detail 原文（如「目录不存在：…」），所以那条路径连 422 也不套用
   *  「未知模型」的旧语义。 */
  const submitTask = useCallback(
    async (
      payload: StartSessionPayload,
      opts?: { ownError?: boolean },
    ): Promise<string | null> => {
      setError(null);
      setConversation(null);
      liveSidRef.current = null;
      setReconnecting(false);
      lastAppliedSeqRef.current = null;
      terminalSeenRef.current = false;
      reconnectRef.current.reset();
      streamGenRef.current += 1;
      const gen = streamGenRef.current;
      setMode({ kind: 'live', sessionId: null });
      try {
        const res = await startSession(payload);
        // 422 的旧语义：Composer 唯一的 422 来源是"模型不可用"，App 据这句话刷新
        // 模型目录 —— 保持逐字节不变。确认面（ownError）里 422 更可能是 cwd 校验
        // 失败，必须让后端 detail 说话（它才是可行动的那句）。
        if (res.status === 422 && !opts?.ownError) throw new Error(UNKNOWN_MODEL_ERROR_TEXT);
        if (!res.ok || !res.body) {
          const detail = await startSessionErrorDetail(res);
          throw new Error(detail || `Start failed: ${res.status}`);
        }
        attachLiveStream(res, gen, null);
        return null;
      } catch (e) {
        // 过期请求迟到失败：丢弃，不污染新会话（调用方也不该当成功——返回一句
        // 话让它知道这次提交没有生效）。
        if (streamGenRef.current !== gen) return '提交已被新的会话取代';
        streamGenRef.current += 1;
        setMode({ kind: 'idle' });
        const message = `提交失败：${(e as Error).message}`;
        if (!opts?.ownError) setError(message);
        return message;
      }
    },
    [refreshSessions, attachLiveStream],
  );

  /** 刷新后接回**仍在服务端运行的** run（BUG-006）。
   *
   *  场景：用户盯着一个正在流式的会话按了 F5（或标签页被重载/崩溃后恢复）。
   *  后端是 detached-run（ADR-0016）——run 不因订阅断开而停；`GET /stream?
   *  after_seq=N` 的契约是「先重放 after_seq 之后的 durable 事件，再接续在途
   *  流，无缝无重复」。所以恢复只需：拿已装载事件的最大 seq 当游标接回去，
   *  同一套 `attachLiveStream` 累积器与 seenSeqs 去重门吸收重放帧。
   *
   *  两个必要的副作用：
   *   - `setMode(live)`：让 modeRef 立刻成为这条流的权威消费者
   *     （`shouldApplyStreamFrame` 与合帧提交都读它），否则帧会被守卫丢掉。
   *   - `resume: true`：告诉 onStreamEnd，零帧收流不是断线而是「服务端没有在跑
   *     的 run」——静默退回 viewing，不重连、不报假错。
   *
   *  守卫：同一 sid 已有恢复尝试在途就跳过。StrictMode 的 effect 双跑由装载
   *  路径的 `cancelled` 挡住（第一次装载必在第二次之前被 cleanup 取消），但
   *  「同一会话的重叠装载」（例如连点已选中的行）确实可能双双走到这里——
   *  两次 attach 会让第一条流失去 sseRef 引用而泄漏，后端也多一个订阅者。 */
  /** 本页面会话里，各 sid 上次自动接流试到的游标（见 nextResumeAttempt 的注释）。
   *
   *  为什么必须记：零帧收流会把 mode 退回 `viewing(sid)`，而历史装载 effect 以
   *  mode 为依赖——它会重新装载、又看到 `hasUnterminatedRun` 为真、再发起一次
   *  恢复，形成「viewing → 接流 → 空流 → viewing」的死循环（每轮两次请求）。
   *  按 (sid, 游标) 记账即斩断回路：空流不带来新事件，游标不变，第二次被拦下。
   *  刷新页面 = 新的页面会话，记录清空——下次刷新照常再试一次。 */
  const resumeAttemptedRef = useRef<ResumeAttempts>(new Map());
  const resumeLiveStream = useCallback(
    async (sid: string, afterSeq: number, initialConv: ConversationState) => {
      const nextAttempted = nextResumeAttempt(resumeAttemptedRef.current, sid, afterSeq);
      if (!nextAttempted) return; // 同一游标已试过：零帧结论仍成立，重试无意义
      // 记账放在 await **之前**（故意的，别挪到成功分支后面）：失败路径同样会
      // setMode(live) → setMode(viewing)，mode 每变一次历史 effect 就重跑一次，
      // 于是「失败 → 回 viewing → 重跑 → 再失败」会变成无上限重试（每轮两条请求）。
      // 代价是同一游标下的自动重试额度被这次失败用掉——错误横幅已告知用户，
      // 用户重新点一次该会话行即经 selectSession → forgetResumeAttempt 重新武装。
      resumeAttemptedRef.current = nextAttempted;
      sseRef.current?.cancel();
      liveSidRef.current = sid;
      lastAppliedSeqRef.current = afterSeq;
      terminalSeenRef.current = false;
      lastFrameAtRef.current = Date.now();
      reconnectRef.current.reset();
      streamGenRef.current += 1;
      const gen = streamGenRef.current;
      setMode({ kind: 'live', sessionId: sid });
      try {
        const res = await streamSession(sid, afterSeq);
        if (streamGenRef.current !== gen) return; // 期间切走/取消：丢弃
        if (res.status === 404) {
          // 会话在装载与接流之间消失。这里**不写** writeStoredSessionId(null)：
          // 马上要回到 viewing(sid)，持久化 effect 会立刻把 sid 写回去，清了也是
          // 白清。真正已被删的会话由下面这一步兜住——mode 变更会重跑历史装载，
          // getSessionEvents 404 → NotFoundError → 清键 + 回 idle，那次落得住。
          setMode({ kind: 'viewing', sessionId: sid });
          return;
        }
        if (!res.ok || !res.body) throw new Error(`resume ${res.status}`);
        attachLiveStream(res, gen, initialConv, { resume: true });
      } catch (e) {
        if (streamGenRef.current !== gen) return;
        // 历史已渲染，这里只报告「继续接收」失败——不把视图打回空态。
        setMode({ kind: 'viewing', sessionId: sid });
        setError(`继续接收失败：${(e as Error).message}`);
      }
    },
    [attachLiveStream],
  );
  useEffect(() => {
    resumeLiveStreamRef.current = resumeLiveStream;
  }, [resumeLiveStream]);
  // 镜像给上方历史装载 effect 用（跨区块调用，与 stallCheckRef 同一手法）。
  // 放在 effect 里赋值而不是 render 期：refs 规则禁止 render 期读写 ref，
  // 而这里没有时序风险——历史装载的 .then 在 fetch 之后才跑，远晚于本 effect。

  /** 续聊：向已有会话发消息（PRD §5.3）。
   *  空闲会话 → 后端 launched 直驱新 run（同形 SSE）→ attachLiveStream 续接。
   *  在途 run → 后端 queued 入队（JSON 确认）→ 当前流继续，下个 run 消费消息。
   *
   *  amend（可选，后端 Q2 批次）：续聊时携带当前 Composer 档位。仅在
   *  「空闲 → launched 新 run」时被后端应用；在途 run 的 queued 消息忽略。
   *  空值不发键（api.sendMessage 兜底归一化；App.tsx 侧另有与 create 分支
   *  同款的「有值才带」展开），与 create 分支同一语义。 */
  const sendFollowUp = useCallback(
    async (
      sessionId: string,
      content: string,
      opts?: {
        maxSteps?: number;
        /** 字段集直接取自 /messages 的请求契约——Omit 出 amend 面，不会随
         *  请求契约增删字段而漂移。 */
        amend?: Omit<SendMessagePayload, 'content' | 'mode' | 'max_steps'>;
      },
    ) => {
      setError(null);
      // 续聊不重置 conversation——在现有对话上追加新 run 的事件。
      liveSidRef.current = sessionId;
      setReconnecting(false);
      terminalSeenRef.current = false;
      reconnectRef.current.reset();
      streamGenRef.current += 1;
      const gen = streamGenRef.current;
      setMode({ kind: 'live', sessionId });
      try {
        const res = await apiSendMessage(sessionId, {
          content,
          mode: 'queue',
          max_steps: opts?.maxSteps ?? 10,
          ...(opts?.amend ?? {}),
        });
        if (res.status === 422) throw new Error(CONTINUE_PARAMS_ERROR_TEXT);
        if (res.status === 409) {
          // T8 #138：409 = 存在需人工裁决的 UNKNOWN Operation。
          // detail 含 tool_name 和 tool_call_id；不伪造「结果未知」继续。
          let detail = '';
          try { detail = (await res.json())?.detail ?? ''; } catch { /* keep '' */ }
          throw new Error(detail || '存在需要人工裁决的高风险操作');
        }
        if (!res.ok || !res.body) throw new Error(`Send failed: ${res.status}`);
        // launched → SSE 流（同 POST /api/sessions 形状），续接消费机器。
        // queued/steered → JSON 确认——当前 run 仍在跑，消息入队待消费。
        // 后者不 attach 新流；回到 viewing 让用户看到当前 run 继续推进。
        const ct = res.headers.get('content-type') ?? '';
        if (ct.includes('text/event-stream')) {
          attachLiveStream(res, gen, conversationRef.current);
        } else {
          // queued/steered JSON：当前流仍在跑，回 viewing 等终态帧迁移。
          setMode({ kind: 'viewing', sessionId });
        }
      } catch (e) {
        if (streamGenRef.current !== gen) return; // 过期请求迟到失败：丢弃，不污染新会话
        streamGenRef.current += 1;
        setMode({ kind: 'viewing', sessionId });
        setError(`续聊失败：${(e as Error).message}`);
      }
    },
    [attachLiveStream],
  );

  /** Explicit stop (Esc / Composer 停止按钮，T5 #98)：按 decideCancel 分派——
   *  已知 sid 发 POST /cancel 且流保持打开（终态帧驱动正常收尾迁移）；
   *  sid 未知仅清理订阅（孤儿回收兜底）。POST 失败静默不双报：流自身的
   *  终态（onDone）/错误（onError）路径是 UI 收尾的权威。 */
  const cancelStream = useCallback(() => {
    const decision = decideCancel(liveSidRef.current);
    if (decision.kind === 'cancel-request') {
      // 显式取消不触发重连（issue #97）：POST /cancel 后流保持打开，终态帧
      // run/failed(reason=cancelled) 经流广播驱动 finishLive；若流此间异常
      // 断开，重连重放只会带回同一终态帧——语义收敛。自愈路径：网络级故障
      // 会让 SSE 自身 onError 收尾；瞬时失败用户再按一次 Esc 即重试——
      // POST /cancel 幂等，重复取消无害。
      void cancelSession(decision.sessionId).catch(() => {
        // 取消请求失败不双报：流终态/错误路径是 UI 收尾权威（契约 §3）。
      });
      return;
    }
    streamGenRef.current += 1; // abort = 订阅清理，旧流的重连/停摆检查全部失效
    stallCheckRef.current = null;
    setReconnecting(false);
    sseRef.current?.cancel();
    sseRef.current = null;
    coalescerRef.current = null;
    setMode(
      liveSidRef.current
        ? { kind: 'viewing', sessionId: liveSidRef.current }
        : { kind: 'idle' },
    );
  }, []);

  /** Switch sessions. Cancels any live stream first (idempotent, no-op when idle) —
   *  the UI only ever presents the session the mode points at.
   *  T5（#98）语义修订：切走只是 unsubscribe（detached-run 契约），run 服务端
   *  继续跑到终态——切会话不再等于取消 run；流上残留订阅随 abort 清理。 */
  const selectSession = useCallback((id: string | null) => {
    // 用户显式切到某个会话 = 明确要看它：忘掉自动接流的去重记账，让「切走
    // 再切回来」照常再接一次（自动重入的死循环不经过这里，断点仍在）。
    if (id) resumeAttemptedRef.current = forgetResumeAttempt(resumeAttemptedRef.current, id);
    streamGenRef.current += 1;
    stallCheckRef.current = null;
    setReconnecting(false);
    sseRef.current?.cancel();
    sseRef.current = null;
    coalescerRef.current = null;
    liveSidRef.current = null;
    setMode(id ? { kind: 'viewing', sessionId: id } : { kind: 'idle' });
  }, []);

  /** 用户显式硬删会话（#172 / ADR-0029）——**不可恢复**：无墓碑、无回收站、无撤销。
   *
   *  入口层（`DeleteSessionDialog`）负责拿到显式二次确认，本函数负责"确认之后收敛"
   *  ——三件事缺一项都会留下"删了还看得见"的假象：
   *   1. 重拉会话列表（行才会消失）。App 跟着 `sessions` 重拉项目列表，所以"它属于
   *      哪个项目"也一并跟上——归属真相在项目账本里，前端不本地掰一份。
   *   2. 被删的正是当前打开的会话时 `selectSession(null)`：它自增流代际、取消 SSE
   *      订阅、回 idle——历史装载 effect 随即清空对话区，持久化 effect 清掉记住的
   *      会话 id（刷新页面不会被拉回一个已经不存在的会话）。
   *   3. 失败时**不动**列表。409（有在途 run / 有挂起审批 / fork 父会话）是后端明确
   *      拒绝：列表必须保持原样——乐观地抹掉它才是真正的假象。404 相反：那是"这个
   *      会话本就不在了"（第二次删除就是这个，后端刻意不伪装成"又删了一次"），
   *      说明本地这行已过期，再收敛一次让它消失，否则用户会对着一个永远删不掉的
   *      幽灵行反复重试。
   *
   *  异常原样抛给调用方（确认面据此把后端 detail 留在原地）。 */
  const convergeAfterDelete = useCallback(
    (sessionId: string) => {
      // 只在"当前看的正是它"时离开视图：用户可能已经切到别的会话，那时不该把他的
      // 视野拽走（同 shouldApplyStreamFrame 的 stale-write 纪律，用 mode 的实时
      // 镜像而非闭包快照——本回调在请求之后才跑）。
      const current = modeRef.current;
      if (current.kind !== 'idle' && current.sessionId === sessionId) selectSession(null);
      void refreshSessions();
    },
    [selectSession, refreshSessions],
  );

  const removeSession = useCallback(
    async (sessionId: string): Promise<SessionDeleted> => {
      try {
        const receipt = await deleteSession(sessionId);
        convergeAfterDelete(sessionId);
        return receipt;
      } catch (e) {
        if (e instanceof SessionError && e.status === 404) convergeAfterDelete(sessionId);
        throw e;
      }
    },
    [convergeAfterDelete],
  );

  /** 归档 / 取消归档（#171）。
   *
   *  **不动视野**：与硬删（`convergeAfterDelete`）刻意相反。硬删之后会话已经没了，
   *  留在原地等于展示一个幻影；归档只是列表可见性标记——事件、lineage、resume 在
   *  后端照旧可用（#171 AC5 把这点钉成契约），所以「我正在读的会话被归档」不该把我
   *  从内容里踢出去，那是在为一个可逆的标记付不可逆的代价。
   *
   *  开关关着时归档会让当前选中行从侧栏消失（主区仍显示内容）——这是可见性过滤的
   *  正常结果，不是不一致：两份视图读的是同一份真值（不变量 #22）。
   *
   *  成功后整表重建：`refreshSessions` 是唯一写 `sessions` 的路径，所以这里只 await
   *  它，不自己拼一个乐观行——回执的 `archived` 才是动作后的真值，请求参数的意图
   *  不是（幂等重放时两者同形，但只有响应能证明）。失败**不吞**：抛给调用方显示
   *  后端 detail（404 / 409 在途 run）。
   *
   *  **列表刷新失败也要抛**（不是"归档成功就算成功"）：那一刻后端已经写好了标记、
   *  而界面上的行还是旧状态——沉默会让用户以为动作没生效，再点一次。抛出的这句
   *  只描述**界面**的处境（"已生效但没刷新出来"），不冒充后端 detail。 */
  const setArchived = useCallback(
    async (sessionId: string, archived: boolean) => {
      if (archived) await archiveSession(sessionId);
      else await unarchiveSession(sessionId);
      if (!(await refreshSessions())) {
        throw new Error('归档已生效，但会话列表刷新失败——请刷新页面查看最新状态');
      }
    },
    [refreshSessions],
  );

  /** 恢复中断会话（POST /recover）。200 → 整表重建：响应是与 GET events
   *  同构的全量事件数组，走同一 projectHistory 管线（不变量 #22——不引入第二套
   *  会话真相）；404/409 → error（409 附裁决原因，conflict=true）。
   *  落地前先过 shouldApplyRecoverResult 守护：pending 期间切走即丢弃。
   *
   *  成功落 `done` 而非回 `idle`：崩溃会话往往已被后端启动扫描修完，recover
   *  是一次真 no-op、投影逐字不变；回 idle 会让「修好了」与「按钮坏了」同形。
   *  `repaired` = 恢复前 dangling 的 tool_call 里、恢复后已配上的条数
   *  （append-only 日志下集合只减不增，差集即本次修复量）；`terminalRepaired`
   *  = 恢复前缺 run 终态、恢复后补上了。两者分开——只看 `repaired` 会把一次
   *  真实的终态修复报成「无可修复项」。
   *
   *  守护覆盖**全部**状态写入，不只 setConversation：`done`/`error` 都是用户看得见
   *  的反馈，晚到的响应若落到已切走的会话上，等于把 A 会话的恢复结论贴在 B 会话
   *  界面（同族的 stale-write）。同理 `unpairedBefore` 只在该响应确实属于当前视图
   *  时才用来算差集——否则它取自别的会话，`repaired` 就是个凭空造出来的数字。 */
  const recover = useCallback(
    async (sid: string) => {
      setRecoverState({
        status: 'pending', message: null, conflict: false, repaired: 0,
        terminalRepaired: false, stillUnterminated: false, stillDangling: false,
      });
      const viewed = conversationRef.current;
      const mineBefore = viewed?.session_id === sid ? viewed.events : null;
      const unpairedBefore = mineBefore === null ? null : unpairedToolCallIds(mineBefore);
      const unterminatedBefore = mineBefore === null ? false : hasUnterminatedRun(mineBefore);
      try {
        const events = await recoverSession(sid);
        // 会话列表的计数要跟着更新，与"当前看的是哪个会话"无关。
        void refreshSessions();
        if (!shouldApplyRecoverResult(modeRef.current, sid)) return;
        const unpairedAfter = unpairedToolCallIds(events);
        const repaired = unpairedBefore === null
          ? 0
          : [...unpairedBefore].filter((id) => !unpairedAfter.has(id)).length;
        const terminalRepaired = unterminatedBefore && !hasUnterminatedRun(events);
        setConversation(projectHistory(sid, events));
        setRecoverState({
          status: 'done', message: null, conflict: false, repaired, terminalRepaired,
          // 原因分开算：isRecoverableRun 是 OR，压回一个布尔就会把原因说错。
          stillUnterminated: hasUnterminatedRun(events),
          stillDangling: unpairedAfter.size > 0,
        });
      } catch (e) {
        if (!shouldApplyRecoverResult(modeRef.current, sid)) return;
        if (e instanceof RecoverError) {
          setRecoverState({
            status: 'error',
            message: e.message,
            conflict: e.status === 409,
            repaired: 0,
            terminalRepaired: false,
            stillUnterminated: false,
            stillDangling: false,
          });
        } else {
          setRecoverState({
            status: 'error', message: (e as Error).message, conflict: false,
            repaired: 0, terminalRepaired: false, stillUnterminated: false, stillDangling: false,
          });
        }
      }
    },
    [refreshSessions],
  );

  /** T7 #137：切换会话当前模型（POST /api/sessions/{id}/model）。
   *
   * - 切换不打断在途 run——下一轮 run 从事件流派生当前模型生效
   * - 响应回传规范 model_id，不回显请求值
   * - 404 = session 不存在；422 = provider/model_id 不在 catalog
   *
   * 错误向上抛——调用方决定是否展示。
   *
   * 本层**不做**去重：一次用户意图只对应一个请求这条契约由选档入口保证
   * （ModelPicker.commitSelection：弹层已关即忽略选中）——模型项被双击时第二次
   * `click` 落在「弹层已关、节点仍在退出动画中可命中」的窗口里，入口丢弃它即可
   * （实测 `dblclick` 与 ≤120ms 双击都拦得住）。放在这里做「同目标在途复用
   * Promise」是测不到的死层：两次 click 之间 React 已提交 `open=false`，
   * 第二个请求根本到不了本函数。 */
  const changeModel = useCallback(
    async (sessionId: string, provider: string, modelId: string) => {
      return changeSessionModel(sessionId, provider, modelId);
    },
    [],
  );

  /** T7 #137：从历史用户消息 seq 派生 child session（POST /api/sessions/{id}/forks）。
   *
   * - 锚点消息本身不进 child seed
   * - child 继承父会话当前模型
   * - copy-on-fork：父 workspace 整目录复制为 child 的
   *
   * 成功后返回 child session_id——调用方决定是否跳转。 */
  const fork = useCallback(
    async (sessionId: string, fromSeq: number) => {
      return forkSession(sessionId, fromSeq);
    },
    [],
  );

  return {
    sessions,
    selectedId,
    conversation,
    loadingHistory,
    streaming,
    reconnecting,
    error,
    titlesById,
    recoverState,
    selectSession,
    submitTask,
    sendMessage: sendFollowUp,
    cancelStream,
    removeSession,
    setArchived,
    recover,
    refreshSessions,
    changeModel,
    fork,
  };
}
