/** ReasoningBlock — 推理/进度流块（#95，S2-S8，规格 03 §7）。
 *
 * 数据 = 投影层 ReasoningBlock（契约 C1 reasoning 事件族）。折叠行与展开面
 * 消费同一份块缓冲（两视图永不失同步）。折叠行的前读游标是 presentation-only
 * 状态（lib/reasoningCursor 纯策略 + rAF transform），绝不改写 canonical 文本、
 * 不调用任何模型做摘要、不做固定步进打字机（S3/S20 硬约束）。
 *
 * 结构（PRD §6.3 / 规格 03 §7）：
 *   [Brain] 正在思考 · 36 秒 <one-line 前读视口>      [chevron]   ← collapsed
 *   [Brain] 思考 · 持续了 36 秒                       [chevron]   ← expanded
 *           <有界滚动正文 + 贴底跟随>
 *
 * a11y（规格 03 §19）：header 是 button（aria-expanded/aria-controls）；
 * 前读视口 aria-hidden（装饰性重复，屏幕阅读器只听 header 粗粒度状态，不逐 token）。 */

import { memo, useEffect, useRef, useState } from 'react';
import { Brain, ChevronDown } from 'lucide-react';
import type { ReasoningBlock } from '../types';
import { advanceCursor, MAX_FRAME_DT_MS, REDUCED_MOTION_STEP_CHARS, type ReasoningStatus } from '../lib/reasoningCursor';
import { reasoningIsOpen } from '../lib/disclosure';
import { FOLLOW_BOTTOM, followOnJump, followOnScroll, nearBottom, useFollowResetOnStop, type FollowState } from '../lib/followLatest';
import { useTickingNow } from '../hooks/useTickingNow';
import type { TraceDensity } from '../lib/density';

/** reasoning 开合控制 API（useReasoningDisclosure 返回形状；缺省时组件内
 *  本地 state 兜底——测试/独立渲染可用，生产由 App 统一提供）。 */
export interface ReasoningDisclosureApi {
  isOpen: (blockId: string, status: ReasoningStatus) => boolean;
  toggle: (blockId: string, currentOpen: boolean) => void;
}

/** 流式秒级时长叶子——每秒只重渲染这一个 span（ticker 隔离，规格 03 §7.1）。 */
function LiveDuration({ startedAt }: { startedAt?: string }) {
  const now = useTickingNow(1000);
  if (!startedAt) return null;
  const ms = now - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return <span className="reasoning-duration num"> · {Math.floor(ms / 1000)} 秒</span>;
}

/** 终态时长（固定值，无 tick）。秒粒度取整并与流式态同单位（「N 秒」）——
 *  S5 要求 streaming→completed 的 header 切换平滑，单位/格式跳变会破坏它。 */
function TerminalDuration({
  startedAt,
  completedAt,
  interrupted,
}: {
  startedAt?: string;
  completedAt?: string;
  interrupted: boolean;
}) {
  if (!startedAt || !completedAt) return null;
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  /* UI-04 信任裂缝：秒级向下取整对亚秒思考显「持续了 0 秒」是自相矛盾——
   * N===0 改说 <1s（不再出现 0 秒）；N≥1 保持既有措辞（中断显「中断于 N 秒」，与 run 徽标的
   * 中立第四态一致，不把中断塌缩成 completed）。 */
  const seconds = Math.floor(ms / 1000);
  const interruptedLabel = interrupted ? `中断于 ${seconds} 秒` : `持续了 ${seconds} 秒`;
  return (
    <span className="reasoning-duration num">
      {' '}
      ·{' '}
      {seconds >= 1 ? interruptedLabel : interrupted ? '中断于 <1s' : '持续 <1s'}
    </span>
  );
}

/** 折叠前读视口（S3）：单行、从头前读、transform + mask 渐隐。
 *
 * rAF 循环只在「落后于文本」时运转：追平或终态定格即停（不空转、不循环）；
 * 新文本到达由 effect 重启。宽度只在文本长度变化时测量一次（每合帧批次至多
 * 一次布局读取，帧间零测量）。reduced-motion 降级为离散前读（无动画，信息不丢）。 */
function ReasoningReadLine({ text, status }: { text: string; status: ReasoningStatus }) {
  const wrapRef = useRef<HTMLSpanElement>(null);
  const innerRef = useRef<HTMLSpanElement>(null);
  const cursorRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const lastTsRef = useRef<number | null>(null);
  const metricsRef = useRef({ textLen: -1, innerW: 0, wrapW: 0 });
  const statusRef = useRef(status);
  statusRef.current = status;
  const textRef = useRef(text);
  textRef.current = text;

  useEffect(() => {
    const wrap = wrapRef.current;
    const inner = innerRef.current;
    if (!wrap || !inner) return;

    const measure = () => {
      metricsRef.current = {
        textLen: textRef.current.length,
        innerW: inner.scrollWidth,
        wrapW: wrap.clientWidth,
      };
    };
    const apply = (pos: number, len: number) => {
      const { innerW, wrapW } = metricsRef.current;
      const range = Math.max(0, innerW - wrapW);
      const x = len > 0 ? (pos / len) * range : 0;
      inner.style.transform = `translateX(${-x}px)`;
    };

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      // 无动画降级：离散前读——每次文本变化推进一小步，信息保留、零动画。
      cursorRef.current = Math.min(
        textRef.current.length,
        cursorRef.current + REDUCED_MOTION_STEP_CHARS,
      );
      measure();
      apply(cursorRef.current, textRef.current.length);
      return;
    }

    const tick = (ts: number) => {
      // dt 钳制（MAX_FRAME_DT_MS）：后台标签页 rAF 暂停后的首帧巨 dt 不得绕过
      // 有界加速策略（T7 #100）
      const dt =
        lastTsRef.current === null ? 0 : Math.min(ts - lastTsRef.current, MAX_FRAME_DT_MS);
      lastTsRef.current = ts;
      const len = textRef.current.length;
      if (len !== metricsRef.current.textLen) measure();
      const pos = advanceCursor(cursorRef.current, len, dt, statusRef.current);
      cursorRef.current = pos;
      apply(pos, len);
      if (pos >= len) {
        rafRef.current = null; // 追平/定格——停环，新文本由 effect 重启
        lastTsRef.current = null;
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    if (rafRef.current === null) {
      lastTsRef.current = null;
      rafRef.current = requestAnimationFrame(tick);
    }
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [text, status]);

  return (
    <span ref={wrapRef} className="reasoning-readline" aria-hidden="true">
      <span ref={innerRef} className="reasoning-readline-inner">
        {text}
      </span>
    </span>
  );
}

export const ReasoningBlockView = memo(function ReasoningBlockView({
  block,
  density,
  disclosure,
}: {
  block: ReasoningBlock;
  density: TraceDensity;
  /** 生产路径由 App 提供（跨块自动开合 + user_interacted 持久）；缺省走组件内
   *  本地兜底（auto 规则 + 手动翻转），测试/独立渲染无需装配 hook。 */
  disclosure?: ReasoningDisclosureApi;
}) {
  const [fallbackOpen, setFallbackOpen] = useState<boolean | null>(null);
  // 兜底自动规则复用 disclosure.ts 的 S6 单一实现（空 override = 纯自动），
  // 避免规则演化时两处同步改（Standards 轴 Duplicated Code finding）。
  const autoOpen = reasoningIsOpen(new Map(), block.blockId, block.status, density);
  const open = disclosure ? disclosure.isOpen(block.blockId, block.status) : (fallbackOpen ?? autoOpen);
  const toggle = () => {
    if (disclosure) disclosure.toggle(block.blockId, open);
    else setFallbackOpen(!open);
  };
  const bodyId = `reasoning-body-${block.blockId}`;

  return (
    <div className={`reasoning-block reasoning-${block.status}`} data-reasoning-key={`reasoning:${block.blockId}`}>
      <button
        type="button"
        className="reasoning-header"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={toggle}
      >
        <Brain
          size={14}
          className={`reasoning-icon${block.status === 'streaming' ? ' reasoning-icon-live' : ''}`}
          aria-hidden="true"
        />
        <span className="reasoning-label">
          {block.status === 'streaming' ? '正在思考' : '思考'}
        </span>
        {block.source === 'agent' && <span className="reasoning-source">进度</span>}
        {block.status === 'streaming' ? (
          <LiveDuration startedAt={block.started_at} />
        ) : (
          <TerminalDuration
            startedAt={block.started_at}
            completedAt={block.completed_at}
            interrupted={block.status === 'interrupted'}
          />
        )}
        {!open && <ReasoningReadLine text={block.text} status={block.status} />}
        <ChevronDown
          size={14}
          className={`reasoning-chevron${open ? ' reasoning-chevron-open' : ''}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div className="reasoning-expanded" id={bodyId}>
          <ExpandedBody text={block.text} streaming={block.status === 'streaming'} />
        </div>
      )}
    </div>
  );
});

/** 展开正文：有界滚动 + 贴底跟随（S8）——贴底时随新文本滚动，上滚即停跟随，
 *  浮现「↓ 跳到最新」，点击回底并恢复跟随。状态转移走 lib/followLatest 纯函数
 *  （锁测试）；推广为跨视图共享 useFollowLatest 原语记 ADR-0016 议题。 */
function ExpandedBody({ text, streaming }: { text: string; streaming: boolean }) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const followRef = useRef<FollowState>(FOLLOW_BOTTOM);
  const [suspended, setSuspended] = useState(false);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const onScroll = () => {
      const near = nearBottom(el.scrollHeight, el.scrollTop, el.clientHeight);
      followRef.current = followOnScroll(followRef.current, near, streaming);
      setSuspended(followRef.current.suspended);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [streaming]);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !streaming || !followRef.current.following) return;
    el.scrollTop = el.scrollHeight;
  }, [text, streaming]);

  // 流结束清 suspended（T3 同族修复，复用 followLatest 单一实现）
  useFollowResetOnStop(streaming, followRef, setSuspended);

  const jump = () => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    followRef.current = followOnJump();
    setSuspended(false);
  };

  return (
    <div className="reasoning-expanded-inner">
      <div ref={bodyRef} className="reasoning-text">
        {text}
        {streaming && <span className="stream-caret" />}
      </div>
      {suspended && (
        <button type="button" className="reasoning-jump" onClick={jump}>
          ↓ 跳到最新
        </button>
      )}
    </div>
  );
}
