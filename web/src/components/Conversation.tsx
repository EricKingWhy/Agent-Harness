/** Conversation — center column rendering the projected ConversationState.
 *
 * Each Turn renders as (Trace Ladder, signature #2 — Brief §24 Phase 3):
 *   - user message (right-aligned bubble)
 *   - execution chain in TRUE event order: model segments ↔ ToolCards,
 *     projected by deriveChain (shared projection.ts layer — no second truth)
 *
 * Turn collapse: completed turns with model text collapse to a derived
 * summary line (N tools · M 轮 · 真实耗时) — replaces the old fabricated
 * "~N tok" estimate (zero-fake-metrics rule).
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Activity } from 'lucide-react';
import type { ChainNode } from '../lib/projection';
import { deriveChain, emptyChildTurnIndex } from '../lib/projection';
import type { TraceDensity } from '../lib/density';
import type { Disclosure } from '../lib/disclosure';
import { nextLevel, toolEventKey } from '../lib/disclosure';
import {
  FOLLOW_BOTTOM, followOnJump, followOnScroll, nearBottom, nestedChainAbsorbs,
  wheelDeltaPixels, type FollowState,
} from '../lib/followLatest';
import { KIND_ICON, KIND_LABEL, modelKind, type RuntimeEventKind } from '../lib/eventKind';
import type { ConversationState, ToolCall, Turn } from '../types';
import { formatDuration, truncateForDisplay } from '../lib/format';
import { renderMarkdown } from '../lib/markdown';
import { ToolCard } from './ToolCard';
import { DelegationNode } from './DelegationNode';
import { ReasoningBlockView, type ReasoningDisclosureApi } from './ReasoningBlock';
import { CopyButton } from './CopyButton';
import { ApprovalCard } from './ApprovalCard';

interface Props {
  conversation: ConversationState | null;
  loadingHistory: boolean;
  /** Trace Density 四档（Brief 冻结决策）——控制执行链节点粒度。 */
  density: TraceDensity;
  /** L0-L2 展开状态（manual override ?? density 默认）。缺省 = 无手动层。 */
  disclosure?: Disclosure;
  /** T2（#95）reasoning 开合状态（S6/S7 自动规则 + user_interacted override）。 */
  reasoningDisclosure?: ReasoningDisclosureApi;
  /** Inspector → 主区反向联动（PRD §9.2）：定位目标 key + 变更序号（nonce 保证
   *  重复跳同一目标也触发 effect）。 */
  jumpRequest?: { key: string; nonce: number } | null;
  /** 空状态示例任务回调——点击 chip 时由 App 注入 Composer。 */
  onPresetTask?: (text: string) => void;
  /** hover Inspect → 钻取到事件级 Inspector（PRD §9.1 联动）。 */
  onFocusTool?: (tool: ToolCall) => void;
  /** 打开子会话（Phase 13 委派节点入口，复用会话栏同一选择管线）。 */
  onOpenSession?: (sessionId: string) => void;
  /** Inspector 钻取子会话（v2 PRD §10.5 委派配对）——右栏原位展开 child。 */
  onInspectChild?: (child: { childSessionId: string; target: string }) => void;
  /** T7 #137：从指定用户消息 seq 分叉新会话。 */
  onFork?: (fromSeq: number) => void;
  /** APR-01：审批卡提交时后端回 404（队列已 GC）→ 把该 approval_id 上报为失效。
   *  失效事实由 App 持有（同时驱动 composer 解锁与卡片只读），卡内不存第二份。 */
  goneApprovalIds?: ReadonlySet<string>;
  onApprovalGone?: (approvalId: string) => void;
}

const EMPTY_TURNS: Turn[] = [];

const EXAMPLE_TASKS = [
  '写一个 FizzBuzz 脚本并运行验证',
  '创建 todo.md，写入三条今日计划',
  '列出当前目录的文件结构并总结',
];

export function Conversation({ conversation, loadingHistory, density, disclosure, reasoningDisclosure, jumpRequest, onPresetTask, onFocusTool, onOpenSession, onInspectChild, onFork, goneApprovalIds, onApprovalGone }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Follow-mode（pi-mono TUI 语言）：贴底跟随流式增长；用户上滚即脱离跟随，
  // 出现「↓ 最新」浮标一键回归。纯视图状态，不碰投影（#22）。
  //
  // 三个状态收在 FOLLOW 原语里（lib/followLatest，ReasoningBlock / ToolCard 已
  // 在用同一份实现）：本组件此前另抄了一份内联判断（阈值硬编码 120、只在
  // effect 里现算 nearBottom），于是 follow 状态与 nearBottom 成了两套并行真相，
  // 且每个 delta 都重发 `scrollIntoView({behavior:'smooth'})` —— 动画被下一次
  // delta 反复重启，把用户的手动滚动一起吃掉（用户实测：「滑轮往下滚他就自动
  // 又上去了…必须要输出完才能看见」）。现在只有 followRef 决定要不要跟随。
  const followRef = useRef<FollowState>(FOLLOW_BOTTOM);
  const [suspended, setSuspended] = useState(false);

  // PRD §20.2 / ADR-0014 D7：turns 列表窗口化（@tanstack/react-virtual）。
  // turn 是虚拟单元（user 消息 + 执行链，高度差异大）→ measureElement 动态测高；
  // overscan 6 保证滚动无白边；流式活跃 turn 高度连续变化由动态测量吸收。
  // 少 turn（<15）时与全渲染等价，统一路径避免双渲染逻辑。
  const turns = conversation?.turns ?? EMPTY_TURNS;
  const virtualizer = useVirtualizer({
    count: turns.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 240,
    overscan: 6,
    getItemKey: (i) => turns[i].step_id,
  });

  // B3：**能说「本轮之前没有历史」的那一轮**——纯函数在 projection.ts，见
  // emptyChildTurnIndex 的注释（只有第 0 轮可分叉时才是它，否则不给提示）。
  // turns 数组每个投影提交都会换引用，所以这趟扫描跟着重算（O(turns)）。
  const emptyChildTurnIdx = useMemo(() => emptyChildTurnIndex(turns), [turns]);

  // PRD §9.2 反向联动：Inspector Timeline 点行 → 中间滚动定位 + 短促 pulse。
  // 目标可能是工具行（data-stream-key）或轮次容器（data-step-key）。
  // 虚拟化后目标行可能不在已挂载窗口内：先定位归属 turn，scrollToIndex 渲染
  // 出来后再 pulse（requestAnimationFrame 等一帧 DOM 提交）。
  // nonce 守卫：turns/virtualizer 在依赖里（窗口外兜底需要最新值），流式期间
  // 每 delta 都会变——已处理的 jumpRequest 不得重复触发 pulse。
  const processedJumpNonce = useRef<number | null>(null);
  useEffect(() => {
    if (!jumpRequest || processedJumpNonce.current === jumpRequest.nonce) return;
    processedJumpNonce.current = jumpRequest.nonce;
    const root = scrollRef.current;
    if (!root) return;
    const pulse = (el: HTMLElement) => {
      el.classList.remove('stream-jump-pulse');
      void el.offsetWidth; // 强制 reflow：同目标重复跳转也重启动画
      el.classList.add('stream-jump-pulse');
      window.setTimeout(() => el.classList.remove('stream-jump-pulse'), 900);
    };
    /* 三个 key 命名空间互不相交：`tool:`/`step:`（事件→轮次内定位）、`delegation:`、
     *  `approval:`（#184 审批卡——它在虚拟化列表**之外**，必须始终可见，所以有自己的
     *  data 属性）。一次查询按序试，命中即停。 */
    const key = jumpRequest.key;
    const approvalKey = key.startsWith('approval:') ? key.slice('approval:'.length) : null;
    const el =
      root.querySelector<HTMLElement>(`[data-stream-key="${key}"]`) ??
      root.querySelector<HTMLElement>(`[data-step-key="${key}"]`) ??
      (approvalKey === null
        ? null
        : root.querySelector<HTMLElement>(`[data-approval-key="${approvalKey}"]`));
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      pulse(el);
      return;
    }
    // 窗口外兜底：key → turn index → scrollToIndex
    const idx = turns.findIndex((t) => turnHasStreamKey(t, jumpRequest.key));
    if (idx === -1) return;
    virtualizer.scrollToIndex(idx, { align: 'center' });
    requestAnimationFrame(() => {
      const el2 =
        root.querySelector<HTMLElement>(`[data-stream-key="${jumpRequest.key}"]`) ??
        root.querySelector<HTMLElement>(`[data-step-key="${jumpRequest.key}"]`);
      if (el2) pulse(el2);
    });
  }, [jumpRequest, turns, virtualizer]);

  // 跟随态复位——两个「内容基线换了」的时刻必须回到贴底跟随：
  //  - 换会话（sessionId 变）：新会话的 follow 从底部起算（`.conversation-scroll`
  //    带 key，重挂载后 scrollTop 归 0；「打开就停在底部」不在这里做——那是
  //    历史加载完的落点问题，本 effect 只负责状态，不写 scrollTop）；
  //  - run 开始（false → true）：用户刚提交消息，要看的是新输出。
  //
  // 「run 开始」这一条是必须的，漏掉会**复现用户的原始症状**：在已结束的会话里
  // 上滚脱离（following=false、suspended=false，因为非流式期不浮现浮标），然后
  // 发一条新消息——新 run 继承 following=false，自动贴底静默，suspended 又是
  // false 所以「↓ 最新」也不出现 → 用户又一次「看不到下面」。
  //
  // 「run 结束」的悬浮态清理在这里是顺带的（复位本身覆盖了它），不是
  // useFollowResetOnStop 搬过来的——那个 hook 只服务 ReasoningBlock / ToolCard
  // 的内部滚动体。
  const sessionId = conversation?.session_id ?? null;
  const runActive = conversation?.run_status === 'running';
  // run 结束的那一提交也会改高度：流式期间的纯文本要重渲染成 markdown、kind 行
  // 撤掉、复制按钮出现。而 runActive 已转 false，自动贴底 effect 不再跑，于是视口
  // 停在距底几十像素处；此时又不是流式（`suspended` 恒 false），连浮标都没有。
  // 所以「结束」这一拍要自己补一次瞬时贴底——但只在用户本来就在跟随时：上滚脱离
  // 的用户不能被他没要的滚动拽走。复位与补底都在同一个 effect 里，顺序是
  // 「先记下 wasFollowing → 复位 → 需要则补底」。
  const prevRunActiveRef = useRef(false);
  useEffect(() => {
    const wasActive = prevRunActiveRef.current;
    prevRunActiveRef.current = runActive;
    const wasFollowing = followRef.current.following;
    followRef.current = FOLLOW_BOTTOM;
    setSuspended(false);
    if (wasActive && !runActive && wasFollowing) {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [sessionId, runActive]);

  // 流式期间的自动贴底——**只在 follow 为真时**，且用瞬时 `scrollTop = scrollHeight`
  // （不做 smooth 动画：动画中间态会被下一次 delta 重启，把用户的手动滚动一起吃掉）。
  //
  // 依赖是有意保留整个 `conversation` 的（HANDOFF C.4.3 要求收窄，此处偏离并记录
  // 理由）：内容增长才是必须贴底的信号，而它既来自模型 delta、也来自工具输出，任何
  // 单一窄信号都接不住——`turns.length` 在纯文本 delta 时**根本不变**（漏触发、
  // 流式期间完全不贴底），`conversation.seq`/`events.length` 则每个事件都变（等频，
  // 收窄不减少运行次数）。原始症状的真正成因不是「跑太多次」，而是**没有 follow
  // 闸门 + smooth 动画**——这两个都已在别处解决，所以这条依赖不再是缺陷。
  //
  // 「用户上滚 → follow 置 false」这一步交给 scroll 监听 + wheel 监听。**只有
  // scroll 监听是不够的**（实测踩到）：scroll 事件要等下一个渲染时机才派发，而
  // delta 提交可能先到——本 effect 抢先贴底把位置拽回底部，等 scroll 事件终于派发时
  // nearBottom 已经是 true，用户的脱离意图被整个吞掉：位置每帧被拽回、浮标永不出现，
  // 即用户报的那个症状。所以脱离跟随还需一个**同步于用户意图**的信号，见 setScrollNode
  // 里的 wheel 监听。
  useEffect(() => {
    if (!runActive) return;
    if (!followRef.current.following) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [conversation, runActive]);

  // Follow-mode：用户滚动即转移跟随态（贴底恢复跟随；上滚脱离并浮现「↓ 最新」）。
  // 流式增长本身不触发 scroll 事件，而我们写入 scrollTop 会触发——nearBottom
  // 判定天然收敛（写入后仍贴底 → followOnScroll 返回 FOLLOW_BOTTOM，状态不变，
  // 不产生额外渲染、不闪烁）。
  //
  // 监听器绑在**节点**上（回调 ref），不绑在 effect 依赖上。effect + scrollRef
  // 有个致命缺口：本次渲染返回加载态/空态时树上没有滚动容器，effect 拿到 null
  // 直接 return，而依赖（runActive/sessionId）不变就不会重跑——监听器再也补不上，
  // 于是 following 永远为真：用户上滚既不脱离跟随（视口被下一次 delta 拽回底部），
  // 也不浮现「↓ 最新」。实测复现路径：点开一个会话（加载态与 sessionId 同一次提交）
  // → 续聊 → 上滚，浮标始终不出现。
  // 依赖 `runActive`：回调 ref 的 identity 一变，React 会先以 null 调旧回调（摘监听）
  // 再以节点调新回调（挂监听），闭包里的 streaming 因此永远是最新值，不需要额外
  // 的 ref 镜像（少一个「提交后才同步」的滞后窗口）。
  const detachScrollListenerRef = useRef<(() => void) | null>(null);
  const setScrollNode = useCallback((el: HTMLDivElement | null) => {
    detachScrollListenerRef.current?.();
    detachScrollListenerRef.current = null;
    scrollRef.current = el;
    if (!el) return;
    const onScroll = () => {
      const near = nearBottom(el.scrollHeight, el.scrollTop, el.clientHeight);
      followRef.current = followOnScroll(followRef.current, near, runActive);
      setSuspended(followRef.current.suspended);
    };
    // 滚轮向上 = 「我要看上面的内容」的**用户意图**，必须在输入任务里同步处理：
    // 位置法（onScroll）有个躲不掉的竞态——scroll 事件要等下一个渲染时机才派发，
    // 而 delta 提交可能先到，自动贴底会抢先执行把位置拽回底部；等 scroll 事件终于
    // 派发时 nearBottom 已经是 true，脱离意图被整个吞掉（实测：上滚后每 300ms
    // 被拽回底部 ~2500px，浮标永不出现）。wheel 同步于用户操作，抢占不到。
    //
    // 只在**向上滚**时脱离：向下滚可能只是想滚到底，若也脱离，滚到底后位置没变、
    // 不会再有 scroll 事件来恢复跟随，跟随就再也回不来了。回到贴底由 onScroll 的
    // nearBottom 负责。
    //
    // 这个监听**不能被删**（哪怕 e2e 看起来不依赖它）：它唯一的存在理由是抢在下一次
    // delta 提交之前同步脱离。一旦上滚真的越过了阈值，onScroll 单独也能脱离——所以
    // 任何确定性测试都无法把它与「只有 scroll 监听」区分开（要复现竞态必须在 wheel
    // 之后、scroll 事件派发之前插入一次提交）。证据是真机埋点实测，见
    // docs/FRONTEND_ISSUES_LOG.md 第 19 项与 e2e/j-scroll.spec.ts 文件头。
    //
    // 触屏不做等价处理：一次触摸手势会持续产生成串 scroll 事件，位置法在其中大多数
    // 帧都能生效（只有手势第一帧可能被抢跑）；而「鼠标滚轮一次一格」是一次性的离散
    // 事件，没有后续事件来纠正，所以必须在这里接住。
    //
    // wheel 会**冒泡**：工具输出面板（`.tool-out-body`）/ reasoning 展开体本身就是
    // 独立滚动容器，在它们里面上滚也会冒到这里。那个手势的意图是看那段输出，不是
    // 离开对话底部——不排除就会在对话根本没动的情况下脱离跟随、弹出「↓ 最新」。
    //
    // 判据是**整条嵌套链能不能吃下这次上滚**。累加语义与 deltaMode 折算都在
    // lib/followLatest.ts 的纯函数里（`nestedChainAbsorbs` / `wheelDeltaPixels`，
    // 有单测）；这里只负责按 DOM 把链上可滚祖辈的余量收出来。
    // 用 `Element` 而不是 `HTMLElement`：wheel 目标可能是 lucide 图标之类的
    // `SVGElement`（非 HTMLElement），按 HTMLElement 判会在图标上短路成 false，
    // 正好漏掉要挡的那一幕。
    const nestedAbsorbsWheel = (target: EventTarget | null, wheel: WheelEvent): boolean => {
      const need = wheelDeltaPixels(wheel.deltaY, wheel.deltaMode, el.clientHeight);
      const headrooms: number[] = [];
      let node: Element | null = target instanceof Element ? target : null;
      while (node && node !== el) {
        if (node.scrollHeight > node.clientHeight) {
          const overflowY = getComputedStyle(node).overflowY;
          if (overflowY === 'auto' || overflowY === 'scroll') headrooms.push(node.scrollTop);
        }
        node = node.parentElement;
      }
      return nestedChainAbsorbs(headrooms, need);
    };
    const onWheel = (e: WheelEvent) => {
      if (e.deltaY >= 0) return;
      // 容器自己已经在顶上（内容没超过视口，或上滚到头）：这一下上滚什么都不会动，
      // 不是「用户要离开底部」。判据缺失会让浮标为一个没发生的滚动弹出来。
      if (el.scrollTop <= 0) return;
      if (nestedAbsorbsWheel(e.target, e)) return;
      followRef.current = followOnScroll(followRef.current, false, runActive);
      setSuspended(followRef.current.suspended);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    el.addEventListener('wheel', onWheel, { passive: true });
    detachScrollListenerRef.current = () => {
      el.removeEventListener('scroll', onScroll);
      el.removeEventListener('wheel', onWheel);
    };
  }, [runActive]);

  if (loadingHistory) {
    return (
      <div className="conversation">
        <div className="conversation-empty">正在加载历史…</div>
      </div>
    );
  }

  if (!conversation || conversation.turns.length === 0) {
    return (
      <div className="conversation">
        <div className="conversation-empty">
          <div className="empty-logo"><Activity size={20} /></div>
          <div className="empty-hero">暂无对话</div>
          <div className="empty-sub">在下方提交任务，实时观看 Agent 执行。</div>
          {onPresetTask && (
            <div className="empty-examples">
              {EXAMPLE_TASKS.map((task) => (
                <button key={task} className="example-chip" onClick={() => onPresetTask(task)}>
                  {task}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="conversation">
      {/* key 换 session 时整组 turn remount，触发 fade-in = 切换 crossfade 感 */}
      <div className="conversation-scroll" key={conversation.session_id} ref={setScrollNode}>
        {/* 虚拟化：绝对定位行 + 动态测高（PRD §20.2）。只有窗口内 turn 参与 DOM。 */}
        <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualizer.getVirtualItems().map((vi) => (
            <div
              key={vi.key}
              data-index={vi.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${vi.start}px)`,
              }}
            >
              <TurnView
                turn={turns[vi.index]}
                turnIndex={turns[vi.index].turn_index}
                model={conversation.model}
                density={density}
                disclosure={disclosure}
                reasoningDisclosure={reasoningDisclosure}
                onFocusTool={onFocusTool}
                onOpenSession={onOpenSession}
                onInspectChild={onInspectChild}
                onFork={onFork}
                isFirstUserTurn={vi.index === emptyChildTurnIdx}
                sessionId={conversation.session_id}
              />
            </div>
          ))}
        </div>
        {/* #37 交互式审批——pending_approvals 非空时内联渲染。
         *  位于虚拟化轮次列表之后、列表末尾之前，确保：
         *  - 不参与虚拟化窗口（审批卡必须始终可见）
         *  - 瞬时贴底（scrollTop = scrollHeight）会把审批卡包含进来 */}
        {conversation.pending_approvals.map((a, i) => (
          /* `data-approval-key` 是 Inspector PERMISSION 段（#184）反向联动的落点：
             点那一行的"待审批"→ jumpRequest key `approval:<id>` → 滚到这里 + pulse。 */
          <div key={a.approval_id} data-approval-key={a.approval_id}>
            <ApprovalCard
              sessionId={conversation.session_id}
              approval={a}
              /* 失效 = 投影判定（run 已终结）∪ 后端实证（该卡提交过且回了 404） */
              invalid={a.stale === true || goneApprovalIds?.has(a.approval_id) === true}
              onGone={onApprovalGone ? () => onApprovalGone(a.approval_id) : undefined}
              /* UI-01：多卡并存只有第一张自动聚焦（alertdialog 焦点不打架）。 */
              autoFocus={i === 0}
            />
          </div>
        ))}
      </div>
      {/* Follow-mode 浮标（pi-mono "jump to latest"）：在**投影上仍是 running 的
          run** 里、用户已上滚时出现。`suspended` 由 FOLLOW 原语给出（= 已脱离跟随），
          但它只在 `streaming=true` 时被置起、却**不会**被非流式的转移清掉：
          `followOnScroll(prev, near=false, streaming=false)` 保持 `prev.suspended`
          （原语语义：非流式期没有「最新」可跳，所以不新置、也不撤销）。于是流结束后
          到达的滚动事件（settle 提交改高度、虚拟化重测高都会产生）会把粘性的
          suspended 一直带下去——只看 suspended 就会在终态留下一个点不动的浮标
          （流已结束，"最新"就是用户眼前这屏），所以渲染条件必须同时看 `runActive`。
          注意 `runActive` 读的是投影的 run_status（不变量 #22），崩溃会话可能停在
          running 且无终态，此时浮标仍会出现——这是有意的：用户可以借此回到最新内容。 */}
      {runActive && suspended && (
        <button
          className="follow-pill"
          onClick={() => {
            followRef.current = followOnJump();
            setSuspended(false);
            const el = scrollRef.current;
            if (el) el.scrollTop = el.scrollHeight;
          }}
          aria-label="滚动到最新内容"
        >
          ↓ 最新
        </button>
      )}
    </div>
  );
}

// memo + 投影层 copy-on-write（未触及 turn 引用稳定）：流式期间每个 delta 只
// 重渲染活跃轮次——已完成轮次不再重跑 deriveChain 与全量 markdown 重解析。
export const TurnView = memo(function TurnView({ turn, turnIndex, model, density, disclosure, reasoningDisclosure, onFocusTool, onOpenSession, onInspectChild, onFork, isFirstUserTurn, sessionId }: { turn: Turn; turnIndex?: number | null; model: string | null; density: TraceDensity; disclosure?: Disclosure; reasoningDisclosure?: ReasoningDisclosureApi; onFocusTool?: (tool: ToolCall) => void; onOpenSession?: (sessionId: string) => void; onInspectChild?: (child: { childSessionId: string; target: string }) => void; onFork?: (fromSeq: number) => void; isFirstUserTurn?: boolean; sessionId?: string }) {
  // 折叠是纯手动选项（用户指令 2026-09-05，覆盖冻结决策 L48 的"默认折叠"）：
  // 完成轮一律默认展开——先让用户看到模型回答，想收起再手动点。live 与
  // 历史重挂载行为一致；流式中/无模型文本的轮次不出现折叠按钮。
  const collapsible = turn.status !== 'streaming' && turn.model.text.length > 0;
  const [collapsed, setCollapsed] = useState(false);

  const duration = formatDuration(turn.started_at, turn.completed_at);
  const chain = useMemo(() => deriveChain(turn), [turn]);
  // D12/PRD §10：chain 中最后一个 model 节点 = Final Answer（高对比正文），
  // 其余 done model 段是中间输出（低对比 + 语义行）。
  const lastModelIndex = useMemo(() => {
    for (let i = chain.length - 1; i >= 0; i--) {
      if (chain[i].kind === 'model') return i;
    }
    return -1;
  }, [chain]);
  // hover 时间戳（调研：完成后才展示，流式期间不打扰；title 属性最轻实现）
  const completedTitle = turn.completed_at
    ? `完成于 ${new Date(turn.completed_at).toLocaleString()}`
    : undefined;

  return (
    <div className={`turn turn-${turn.status}`} data-step-key={`step:${turn.step_id}`}>
      {/* T9 #139：轮次标签——turn_index 为 per-turn 事实（run/started 携带）。
          仅正整数显示：null=旧版后端缺字段，≤0=防御性不渲染。 */}
      {turnIndex != null && turnIndex > 0 && (
        <div className="turn-index-label">第 {turnIndex} 轮</div>
      )}
      {/* User message — minimal, right-aligned；harness 注入的纠正消息
          （failure-guard soft）渲染为系统提示条而非用户气泡（不是真人说的话） */}
      {turn.user_message &&
        (turn.injected_by ? (
          <div className="msg msg-system">
            <div
              className="system-notice"
              title={`注入来源：${turn.injected_by}`}
            >
              <span className="system-notice-badge">系统注入</span>
              <span className="system-notice-text">{turn.user_message}</span>
            </div>
          </div>
        ) : (
          <div className="msg msg-user">
            <div className="msg-bubble-user">{turn.user_message}</div>
            {onFork && turn.status !== 'streaming' && turn.user_message_seq !== null && (
              <button
                className="fork-btn"
                title={
                  isFirstUserTurn
                    ? '本轮之前没有历史：child 会话将是空会话'
                    : '从此处分叉新会话'
                }
                onClick={() => onFork(turn.user_message_seq!)}
              >
                分叉
              </button>
            )}
          </div>
        ))}

      {/* Phase 12 白盒透明：failure-guard 事件条——soft 提示 / hard 终止标记 */}
      {turn.notices?.map((n, i) => (
        <div key={`${n.level}-${n.tool_name}-${i}`} className={`notice-strip notice-strip-${n.level}`}>
          <span className="notice-strip-badge">{n.level === 'hard' ? '终止' : '熔断'}</span>
          <span className="notice-strip-text">
            工具 {n.tool_name || '?'} 连续失败 {n.consecutive_failures} 次
          </span>
        </div>
      ))}

      {/* Execution chain — model segments and tools in true event order */}
      {turn.activities.length > 0 && (
        <div className="msg msg-model" title={completedTitle}>
          <div className="msg-body">
            {/* 工具行：折叠按钮（手动选项）+ 模型名小标签（调研 pitfall #6：
                每条 AI 消息标注模型名，升级/降级模型时一眼可辨） */}
            {(collapsible || (model && turn.model.text)) && (
              <div className="turn-tools-row">
                {collapsible && (
                  <button className="turn-collapse-btn" onClick={() => setCollapsed((v) => !v)}>
                    {collapsed
                      ? `已折叠 · ${turn.tools.length} 个工具 · ${turn.segments.length} 轮${duration ? ` · ${duration}` : ''}`
                      : '折叠'}
                  </button>
                )}
                {model && turn.model.text && (
                  <span className="model-tag" title="本次运行使用的模型">{model}</span>
                )}
              </div>
            )}
            {!collapsed && (
              <div className="act-chain">
                {chain.map((node, i) => (
                  <ChainNodeView
                    key={chainKey(node, i)}
                    node={node}
                    density={density}
                    disclosure={disclosure}
                    reasoningDisclosure={reasoningDisclosure}
                    isFinalModel={i === lastModelIndex}
                    onFocusTool={onFocusTool}
                    onOpenSession={onOpenSession}
                    onInspectChild={onInspectChild}
                    sessionId={sessionId}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

function chainKey(node: ChainNode, i: number): string {
  if (node.kind === 'tool') return node.tool.tool_call_id;
  if (node.kind === 'delegation') return node.delegation.child_session_id;
  if (node.kind === 'reasoning') return node.block.blockId;
  return `model-${i}`;
}

/** 反向联动窗口外兜底的 key→turn 匹配（tool:/delegation:/step: 三定位域，
 *  与 streamKeyFromEvent 的 key 词汇一一对应）。 */
function turnHasStreamKey(t: Turn, key: string): boolean {
  if (key.startsWith('tool:')) return t.tools.some((x) => `tool:${x.tool_call_id}` === key);
  if (key.startsWith('delegation:')) {
    return t.delegations?.some((x) => `delegation:${x.child_session_id}` === key) ?? false;
  }
  return `step:${t.step_id}` === key;
}

// ── 语义事件渲染注册表（spec 03 §10 Semantic Event Renderer Registry）──
// kind → 渲染器映射，禁止在单一巨型组件里硬编码全部运行时类型。
// 键由 ChainNode['kind'] 类型系统穷举——新增节点类型必须注册渲染器才过 tsc；
// 事件级未知类型在投影层已隔离（unknown_events 兜底），注册表不承担该职责。

/** 执行链节点的渲染上下文（TurnView 透传，注册表内不再取 React hook）。 */
interface ChainRenderCtx {
  node: ChainNode;
  density: TraceDensity;
  disclosure?: Disclosure;
  reasoningDisclosure?: ReasoningDisclosureApi;
  /** 该 model 段是否为 turn 最后一个模型段（final-answer 高对比）。缺省 true
   *  （与旧 ChainNodeView 默认一致——直接调用方多省略此 prop）。 */
  isFinalModel?: boolean;
  onFocusTool?: (tool: ToolCall) => void;
  onOpenSession?: (sessionId: string) => void;
  onInspectChild?: (child: { childSessionId: string; target: string }) => void;
  /** #186：这条链属于哪个会话——工具卡的归档 diff 要按会话读 artifact 内容。 */
  sessionId?: string;
}

/** 每种 kind 的渲染器只接收窄化后的 node 类型（Extract 按 kind 收紧）。 */
type RendererFor<K extends ChainNode['kind']> = (
  ctx: Omit<ChainRenderCtx, 'node'> & { node: Extract<ChainNode, { kind: K }> },
) => ReactNode;

const CHAIN_RENDERERS: { [K in ChainNode['kind']]: RendererFor<K> } = {
  tool: ({ node, density, disclosure, onFocusTool, sessionId }) => {
    const key = toolEventKey(node.tool.tool_call_id);
    const cycle = disclosure
      ? () => disclosure.setLevel(key, nextLevel(disclosure.levelFor(key, density)))
      : undefined;
    return (
      <ToolCard
        tool={node.tool}
        density={density}
        level={disclosure ? disclosure.levelFor(key, density) : undefined}
        onCycleLevel={cycle}
        onFocus={onFocusTool}
        sessionId={sessionId}
      />
    );
  },
  delegation: ({ node, density, onOpenSession, onInspectChild }) => (
    <DelegationNode
      delegation={node.delegation}
      density={density}
      onOpenSession={onOpenSession}
      onInspectChild={onInspectChild}
    />
  ),
  reasoning: ({ node, density, reasoningDisclosure }) => (
    <ReasoningBlockView block={node.block} density={density} disclosure={reasoningDisclosure} />
  ),
  model: ({ node, density, isFinalModel: isFinal = true }) => {
    const { segment } = node;
    const kind: RuntimeEventKind = modelKind(segment.status, isFinal);
    // Compact 档下 done 的 model 段只渲染首行摘要（渐进披露：详情留给 Inspector）
    if (density === 'compact' && segment.status !== 'streaming') {
      const first = segment.text.split('\n').find((l) => l.trim()) ?? '';
      if (!first) return null;
      return (
        <div className="model-output done model-output-compact">{renderMarkdown(truncateForDisplay(first))}</div>
      );
    }
    if (!segment.text && segment.status !== 'streaming') return null;
    // 模型文本与工具输出同级不可信——单行超长模型输出同样会冻结 UI，渲染前截断
    // （41e7360 只覆盖了工具路径，code-review 补齐此处）。
    const display = truncateForDisplay(segment.text);
    // 语义图标行（PRD §5.2/§10）：思考中（streaming）/ 中间输出（done 非终段）。
    // final-answer 不出行（高对比正文直接呈现，PRD §11.2）。
    const kindRow =
      kind === 'final-answer' ? null : (
        <div className={`model-kind-row model-kind-row-${kind}`}>
          <span className="model-kind-icon">{(() => { const Icon = KIND_ICON[kind]; return <Icon size={14} />; })()}</span>
          <span className="model-kind-label">{KIND_LABEL[kind]}</span>
          {kind === 'thinking' && <span className="model-kind-ellipsis" aria-hidden="true" />}
        </div>
      );
    // P0-2a 流式 markdown 增量化（HANDOFF §6）：streaming 段渲染纯文本
    // （pre-wrap 样式保留换行，标记原样透传——打字机状态本就不需要排版），
    // model/completed 置 done 后一次性 renderMarkdown。消灭流式期间每 delta
    // 全量重解析的 CPU 开销。纯文本走 React 文本节点，天然零 XSS 面。
    if (segment.status === 'streaming') {
      return (
        <div className="model-output-wrap">
          {kindRow}
          <div className="model-output streaming">
            {display}
            <span className="stream-caret" />
          </div>
        </div>
      );
    }
    // hover 复制（调研：per-message copy 是 AI chat 标配动作；仅完成段提供，
    // 流式段文本还在增长，复制半成品是噪音）。中间段低对比（D17 分层），
    // final-answer 保持正文高对比。
    return (
      <div className="model-output-wrap">
        {kindRow}
        <div className={`model-output ${segment.status}${kind === 'model' ? ' model-output-intermediate' : ''}`}>
          {renderMarkdown(display)}
        </div>
        {segment.text && <CopyButton text={segment.text} label={kind === 'final-answer' ? '复制回答' : '复制输出'} />}
      </div>
    );
  },
};

export function ChainNodeView(ctx: ChainRenderCtx): ReactNode {
  // 单点窄化：键与 node.kind 出自同一 ctx（编译期保证一致），注册表内部
  // 已按 Extract 收紧各自 node 类型——调度处一次性还原宽签名。
  const render = CHAIN_RENDERERS[ctx.node.kind] as (c: ChainRenderCtx) => ReactNode;
  return render(ctx);
}
