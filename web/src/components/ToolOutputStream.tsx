/** 流式命令输出区（#96 T3 起就有，本文件是 #190 的**纯搬运**归档）。
 *
 *  为什么要单独成文件：中心列的「输出」面（`OutputPanel.tsx`）与对话里的工具卡
 *  （`ToolCard.tsx`）必须用**同一个**渲染器——票面 AC9 明令"同一数据不得两份独立渲染"。
 *  行为与样式零改动（连同 `tailWindow` / `OUTPUT_TAIL_CHARS` 一起搬），只是从 ToolCard
 *  内部挪到可以被两处导入的位置。
 *
 *  形状：stdout/stderr 分色（channel 保真）、有界尾窗（DOM 不随总输出线性膨胀）、
 *  贴底跟随（`lib/followLatest` 同族谓词）、上滚浮现「↓ 最新」、换行切换、全量复制。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ToolOutputChunk } from '../types';
import { FOLLOW_BOTTOM, followOnJump, followOnScroll, nearBottom, useFollowResetOnStop, type FollowState } from '../lib/followLatest';
import { CopyButton } from './CopyButton';

// ── T3（#96）：流式输出尾窗（S14，规格 03 §9.3/9.4）──

/** 渲染预算：尾窗字符数——DOM 不随总输出线性膨胀（万行级 fixture 不冻结 UI）。
 *  完整内容永远可复制（CopyButton 走全量 chunks）——视图裁剪 ≠ 数据丢弃。 */
const OUTPUT_TAIL_CHARS = 8000;

/** 尾部字符预算裁窗：从末尾向前跨块逐字符取——投影会把相邻同通道 delta
 *  合并进单块（可能巨大），按整块取会让预算失效。 */
function tailWindow(
  chunks: ToolOutputChunk[],
  budget: number,
): { omitted: number; window: ToolOutputChunk[] } {
  const window: ToolOutputChunk[] = [];
  let remaining = budget;
  let omitted = 0;
  for (let i = chunks.length - 1; i >= 0; i--) {
    const c = chunks[i];
    if (remaining <= 0) {
      omitted += c.text.length;
      continue;
    }
    if (c.text.length <= remaining) {
      window.unshift(c);
      remaining -= c.text.length;
    } else {
      window.unshift({ channel: c.channel, text: c.text.slice(c.text.length - remaining) });
      omitted += c.text.length - remaining;
      remaining = 0;
    }
  }
  return { omitted, window };
}

/** 流式输出区：stdout/stderr 分色（channel 保真）、有界尾窗、贴底跟随（S8 同族
 *  谓词 lib/followLatest）、上滚浮现「↓ 最新」、换行切换、全量复制。
 *
 *  两个由**嵌入方**决定的开关（默认值 = 对话里工具卡的既有行为，逐字不变）：
 *  - `showCaret`：流式光标。中心列「输出」面**必须**关掉它（#190 AC5 明令"无光标"）——
 *    一个闪动的方块就是终端提示符的视觉承诺，而本项目没有 PTY；
 *  - `expandable`：有界尾窗之外给一个**就地展开**入口（#190 AC3）。默认 false：工具卡
 *    在对话流里，展开万行输出会拖垮滚动；「输出」面是专门的宽读面，用户显式点开才值得
 *    付那份渲染成本。 */
export function ToolOutputStream({
  chunks,
  streaming,
  showCaret = true,
  expandable = false,
}: {
  chunks: ToolOutputChunk[];
  streaming: boolean;
  /** 是否画流式光标（中心列「输出」面传 false——那里不许出现任何"可输入"的暗示）。 */
  showCaret?: boolean;
  /** 超出尾窗预算时给"展开全部 / 收起"的就地开关（#190 的「输出」面用）。 */
  expandable?: boolean;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const followRef = useRef<FollowState>(FOLLOW_BOTTOM);
  const [suspended, setSuspended] = useState(false);
  const [wrap, setWrap] = useState(true);
  const [expanded, setExpanded] = useState(false);
  // 展开 = 绕过尾窗预算（显式用户动作；不展开时 DOM 仍然有界）。
  const { omitted, window: win } = useMemo(
    () => (expandable && expanded ? { omitted: 0, window: chunks } : tailWindow(chunks, OUTPUT_TAIL_CHARS)),
    [chunks, expandable, expanded],
  );
  const fullText = useMemo(() => chunks.map((c) => c.text).join(''), [chunks]);

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
  }, [chunks, streaming]);

  // 终态清 suspended（复用 followLatest 单一实现，T3 Standards 轴收敛）
  useFollowResetOnStop(streaming, followRef, setSuspended);

  const jump = () => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    followRef.current = followOnJump();
    setSuspended(false);
  };

  const channels = useMemo(() => {
    const set = new Set<string>();
    for (const c of chunks) set.add(c.channel);
    return [...set];
  }, [chunks]);

  return (
    <div className="tool-out-stream">
      <div className="tool-out-bar">
        <span className="tool-out-label">{streaming ? '输出 · 流式' : '输出'}</span>
        {/* 通道图例（票面「channel 徽标」）：出现过的通道才显示 */}
        {channels.map((ch) => (
          <span key={ch} className={`tool-out-chip tool-out-chip-${ch}`}>
            {ch}
          </span>
        ))}
        {expandable && fullText.length > OUTPUT_TAIL_CHARS ? (
          <button
            type="button"
            className="tool-out-expand-btn"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? '收起' : `展开全部（共 ${fullText.length.toLocaleString()} 字符）`}
          </button>
        ) : omitted > 0 ? (
          <span className="tool-out-tail-mark" title={`前 ${omitted} 字符未渲染，完整内容可复制`}>
            …前 {omitted.toLocaleString()} 字符已省略
          </span>
        ) : null}
        <span className="tool-out-bar-gap" />
        <button
          type="button"
          className="tool-out-wrap-btn"
          onClick={() => setWrap((v) => !v)}
        >
          {wrap ? '不换行' : '自动换行'}
        </button>
        <CopyButton text={fullText} label="复制全部输出" />
      </div>
      <div ref={bodyRef} className={`tool-out-body ${wrap ? 'tool-out-wrap' : 'tool-out-nowrap'}`}>
        {win.map((c, i) => (
          <span
            key={i}
            className={c.channel === 'stderr' ? 'tool-out-stderr' : undefined}
            title={c.channel === 'stderr' ? 'stderr' : undefined}
          >
            {c.text}
          </span>
        ))}
        {streaming && showCaret && <span className="stream-caret" />}
      </div>
      {suspended && (
        <button type="button" className="tool-out-jump" onClick={jump}>
          ↓ 最新
        </button>
      )}
    </div>
  );
}
