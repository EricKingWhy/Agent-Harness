/** DelegationNode — Trace Ladder 编排节点（Phase 13 Multi-Agent，ADR-0015）。
 *
 * agent/delegation-started 创建节点、finished 按 child_session_id 回填
 * （projection.ts 单一投影源，不变量 #22）。视觉复用 DSH 工具四态语言——
 * completed/failed/stopped/running 共享 act-status 状态列（中断 ≠ 错误）；
 * 图标/标签走 eventKind 的 subagent kind 映射表（KIND_ICON/KIND_LABEL），
 * 与 delegate 工具卡同一语义类。
 *
 * - summary 默认折叠，点击行展开全文（节点本地态，不进 L0-L2 disclosure——
 *   那是工具域机制；委派是编排事实，只有「有/无结果摘要」两态）。展开内容
 *   经 truncateForDisplay 防 MB 级文本冻结 UI（20k 上限）；完整输出走
 *   「打开子会话」入口（FRONTEND_PROMPT_PHASE13 §1 认可的替代路径）
 * - child_session_id 可见可复制（CopyButton，含非安全上下文回退）
 * - 后端 #86 溢出指针后缀 → 「摘要已截断」提示（summary 保真渲染不剥离，
 *   指针尾巴是真实事实的一部分——chip 只是让它一眼可辨）
 * - 不渲染进聊天正文——委派是执行链事实（Trace Ladder / Inspector 域）
 */

import { memo, useState } from 'react';
import { Check, Square, X } from 'lucide-react';
import type { Delegation } from '../types';
import type { TraceDensity } from '../lib/density';
import { hasSummaryOverflow } from '../lib/projection';
import { KIND_ICON } from '../lib/eventKind';
import { formatDuration, truncateForDisplay } from '../lib/format';
import { CopyButton } from './CopyButton';

interface Props {
  delegation: Delegation;
  density: TraceDensity;
  /** 打开子会话（复用会话栏同一选择管线——child session 与父同 store）。
   *  缺省时不出现入口，不造假链接。 */
  onOpenSession?: (sessionId: string) => void;
  /** Inspector 钻取（v2 PRD §10.5 委派配对）：在右栏原位展开 child 会话，
   *  父会话上下文不丢。缺省时不出现入口。 */
  onInspectChild?: (child: { childSessionId: string; target: string }) => void;
}

/** 委派状态 → DSH 四态列名（completed→success 共享同一组状态色与图标语言）。 */
const STATUS_CLASS: Record<Delegation['status'], string> = {
  running: 'running',
  completed: 'success',
  failed: 'failed',
  stopped: 'stopped',
};

// memo：projection copy-on-write 保证委派对象仅在自身事件到达时替换——
// 同 turn 其它节点跳过重渲染。
export const DelegationNode = memo(function DelegationNode({ delegation, density, onOpenSession, onInspectChild }: Props) {
  const [open, setOpen] = useState(false);
  const duration = formatDuration(delegation.started_at, delegation.completed_at);
  const overflow = delegation.summary !== undefined && hasSummaryOverflow(delegation.summary);
  const hasSummary = delegation.summary !== undefined;

  return (
    <div className="deleg-node" data-stream-key={`delegation:${delegation.child_session_id}`}>
      <button
        className={`act-node act-node-${density}${hasSummary ? ' deleg-row-expandable' : ''}`}
        onClick={() => {
          if (hasSummary) setOpen((v) => !v);
        }}
        aria-expanded={hasSummary ? open : undefined}
        title={hasSummary ? (open ? '收起结果摘要' : '展开结果摘要') : undefined}
      >
        <span className={`act-status act-status-${STATUS_CLASS[delegation.status]}`}>
          {delegation.status === 'completed' && <Check size={14} />}
          {delegation.status === 'failed' && <X size={14} />}
          {delegation.status === 'stopped' && <Square size={14} />}
          {delegation.status === 'running' && <span className="status-spinner" />}
        </span>
        {density !== 'compact' && (
          <span className="act-icon" aria-hidden="true">
            {(() => { const KindIcon = KIND_ICON.subagent; return <KindIcon size={14} />; })()}
          </span>
        )}
        <span className="act-name">委派 → {delegation.target || '?'}</span>
        {density !== 'compact' && delegation.task && (
          <span className="act-args">{truncateForDisplay(delegation.task.replaceAll('\n', ' '), 48)}</span>
        )}
        {duration && <span className="act-duration">{duration}</span>}
      </button>

      {/* child_session_id 行：编排节点的身份事实——可见、可复制、可跳转（增强 B-lite） */}
      <div className="deleg-child-row">
        <span className="deleg-child-label">子会话</span>
        <code className="deleg-child-id mono" title={delegation.child_session_id}>
          {delegation.child_session_id}
        </code>
        <CopyButton text={delegation.child_session_id} label="复制子会话 ID" />
        {onInspectChild && (
          <button
            className="deleg-open-btn"
            onClick={() =>
              onInspectChild({ childSessionId: delegation.child_session_id, target: delegation.target })
            }
            title="在右侧 Inspector 内展开该子会话（父会话上下文保留）"
          >
            Inspect 子会话
          </button>
        )}
        {onOpenSession && (
          <button
            className="deleg-open-btn"
            onClick={() => onOpenSession(delegation.child_session_id)}
            title="在主窗口打开该子会话（child session 在同一存储中）"
          >
            打开子会话
          </button>
        )}
        {overflow && (
          <span className="deleg-overflow-chip" title="摘要超过 8192 字符被后端截断——完整输出见子会话">
            摘要已截断
          </span>
        )}
      </div>

      {open && delegation.summary !== undefined && (
        <div className="deleg-summary" role="region" aria-label="委派结果摘要">
          {truncateForDisplay(delegation.summary)}
        </div>
      )}
    </div>
  );
});
