/** 记忆管理浮层（MEM-5 / #160）：列出用户记忆 + 单条硬删（二次确认）。
 *
 *  为什么是浮层而不是第 4 个常驻面板：单帧三段（Rail | Workspace | Inspector）是
 *  已冻结的布局（App.tsx 头注释），记忆管理是低频、破坏性的管理动作——与项目
 *  CRUD 同一类，按仓库既有惯例（ProjectDialogs）放进 Radix Dialog：焦点陷阱 +
 *  Esc + backdrop 提供一个"用户明确确认"的边界，且失败原因留在原地可见。
 *
 *  数据只在**打开时**拉取（内容组件仅在 open 时挂载）：记忆是后端权威的可变集合，
 *  每次打开都是一次新的权威读取——既不给首页加一个用不到的请求，也不会把上次
 *  打开的陈旧列表当真相（不变量 #22）。
 *
 *  删除的两次确认都在**行内**（点「删除」→ 原地展开确认条）而不是再套一层 Dialog：
 *  嵌套 dialog 的焦点/portal 语义容易出错，而"确认条就在被删的那条旁边"更好——
 *  用户能同时看到要删的正文与"不可恢复"的警告。 */

import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Brain, ChevronDown, ChevronUp, Trash2, TriangleAlert, X } from 'lucide-react';
import { describeMemoryError } from '../lib/api';
import { formatMemoryTime, scopeLabel } from '../lib/memory';
import { useMemories } from '../hooks/useMemories';
import type { MemorySummary } from '../types';

/** 正文折叠阈值：短记忆不必给"展开"按钮（多一个控件反而是噪音）。 */
const CLAMP_THRESHOLD = 180;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function MemoryPanel({ open, onOpenChange }: Props) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="palette-overlay" />
        {open && <MemoryPanelBody />}
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function MemoryPanelBody() {
  const memories = useMemories();
  /** 当前展开确认条的行 id（同时只允许一行——避免一堆"待确认"堆在列表里）。 */
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<{ id: string; message: string } | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());

  const confirmDelete = async (id: string) => {
    setDeleteError(null);
    try {
      await memories.remove(id);
      // 成功后该行已从权威列表消失——确认条随之作废。
      setConfirmId((cur) => (cur === id ? null : cur));
    } catch (error) {
      // 失败：hook 已把列表回滚成权威状态；错误优先留在**这一行**的确认条里，
      // 用户能立刻看到"哪条没删掉、为什么"。
      //
      // 但有一类失败会让那一行**根本不在权威列表里**：404（这条已被别处删掉）。
      // 此时按 id 挂在行上的错误无处渲染 → 界面上等于把失败吞了。所以下面还有一条
      // 面板级错误条：行在 → 行内显示；行不在 → 面板级显示（同一个错误，只有一个来源）。
      setDeleteError({ id, message: describeMemoryError(error, '删除记忆失败') });
    }
  };

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const { visible, loading, loadingMore, loadError, disabled, hasMore, pending } = memories;

  return (
    <Dialog.Content className="memory-panel">
      <div className="project-dialog-head">
        <Dialog.Title className="project-dialog-title">
          <Brain size={14} aria-hidden="true" /> 记忆管理
        </Dialog.Title>
        <Dialog.Close asChild>
          <button className="icon-btn project-dialog-close" aria-label="关闭">
            <X size={14} />
          </button>
        </Dialog.Close>
      </div>
      <Dialog.Description className="project-dialog-desc">
        这里是当前身份记住的<strong>长期事实</strong>（来自你的对话）。删除是<strong>硬删除</strong>：
        记录与索引都会被移除，<strong>删除不可恢复</strong>（没有回收站，也没有恢复入口）。
        列表每次打开都从后端重新读取，界面不保存副本。
      </Dialog.Description>

      <div className="memory-body">
        {disabled !== null ? (
          // 降级态（AC4）：能力未装配是**配置状态**，不是故障——不给"重试"，
          // 因为重试修不了一个没配置的能力（不变量 #21）。
          <div className="memory-degraded" role="status">
            <span className="memory-degraded-title">记忆未启用</span>
            <span className="memory-degraded-detail">{disabled}</span>
            <span className="memory-degraded-hint">
              这是配置状态而非故障：后端 <code>CAPABILITIES</code> 里没有 <code>memory</code>
              时，记忆不会被写入，这里的列表也无从列出。配置后重新打开本面板即可看到。
            </span>
          </div>
        ) : loading ? (
          <div className="memory-loading" role="status">
            正在加载记忆…
          </div>
        ) : visible.length === 0 && loadError === null ? (
          // 空态只在"确实读到了空列表"时出现（零伪造）：HTTP 503 走上面的降级态，
          // 读取失败走下面的错误条——**一条行都没有 + 读取失败**时这里必须是空
          // （只留错误条），否则"读不到"就被伪装成了"没有"。
          <div className="memory-empty" role="status">
            <span className="memory-empty-title">还没有记忆</span>
            <span className="memory-empty-hint">
              当对话里出现关于你的稳定事实时，Harness 可能会把它写进记忆库以便后续复用。
              目前一条都没有——不是加载失败，是真的没有。
            </span>
          </div>
        ) : visible.length === 0 ? null : (
          <ul className="memory-list">
            {visible.map((memory) => (
              <MemoryRow
                key={memory.id}
                memory={memory}
                confirming={confirmId === memory.id}
                pending={pending.has(memory.id)}
                error={deleteError?.id === memory.id ? deleteError.message : null}
                expanded={expanded.has(memory.id)}
                onAskDelete={() => {
                  setDeleteError(null);
                  setConfirmId((cur) => (cur === memory.id ? null : memory.id));
                }}
                onCancelDelete={() => {
                  setDeleteError(null);
                  setConfirmId(null);
                }}
                onConfirmDelete={() => void confirmDelete(memory.id)}
                onToggleExpanded={() => toggleExpanded(memory.id)}
              />
            ))}
          </ul>
        )}

        {/* 加载失败（非 503）：保留已加载的行，只补一条错误条 + 重试——一次网络
            抖动不该把用户已经看到的内容抹掉（同 useProjects 的 loadError 纪律）。 */}
        {loadError !== null && (
          <div className="memory-error" role="alert">
            <span>{loadError}</span>
            <button className="memory-retry" onClick={() => void memories.retry()}>
              重试
            </button>
          </div>
        )}

        {/* 删除失败但**那一行已不在权威列表里**（404：这条已被别处删掉）：
            行内错误条随行一起没了，这里补一条面板级错误条，否则失败被界面吞掉
            （批次审查发现）。与 `loadError` 分开：一个是"列表读不到"，一个是
            "你刚点的那条删不掉"。 */}
        {deleteError !== null && !visible.some((memory) => memory.id === deleteError.id) && (
          <div className="memory-error" role="alert">
            <span>{deleteError.message}</span>
            <button className="memory-retry" onClick={() => setDeleteError(null)}>
              知道了
            </button>
          </div>
        )}

        {disabled === null && !loading && visible.length > 0 && (
          <div className="memory-more">
            {hasMore ? (
              <button
                className="memory-more-btn"
                onClick={() => void memories.loadMore()}
                disabled={loadingMore}
              >
                {loadingMore ? '加载中…' : '加载更多'}
              </button>
            ) : (
              <span className="memory-more-end">已全部加载</span>
            )}
          </div>
        )}
      </div>

      <div className="project-dialog-actions">
        <Dialog.Close asChild>
          <button className="project-btn project-btn-primary">关闭</button>
        </Dialog.Close>
      </div>
    </Dialog.Content>
  );
}

interface RowProps {
  memory: MemorySummary;
  confirming: boolean;
  pending: boolean;
  error: string | null;
  expanded: boolean;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  onToggleExpanded: () => void;
}

function MemoryRow({
  memory,
  confirming,
  pending,
  error,
  expanded,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
  onToggleExpanded,
}: RowProps) {
  const long = memory.content.length > CLAMP_THRESHOLD;
  const showFull = expanded || !long;
  return (
    <li className="memory-row">
      <div className="memory-row-head">
        <p
          className={`memory-content${showFull ? '' : ' clamped'}`}
          // 折叠时把全文放进 title：用户在被要求"决定删不删"之前必须能读到全文
          // （展开按钮是主路径，title 是鼠标用户的快捷读数）。
          title={memory.content}
        >
          {memory.content}
        </p>
        {long && (
          <button
            className="memory-expand"
            onClick={onToggleExpanded}
            aria-expanded={expanded}
            aria-label={expanded ? '收起全文' : '展开全文'}
          >
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        )}
      </div>
      <div className="memory-row-meta">
        <span className={`memory-scope scope-${memory.scope}`}>{scopeLabel(memory.scope)}</span>
        <time className="memory-time" dateTime={memory.created_at}>
          {formatMemoryTime(memory.created_at)}
        </time>
        {!confirming && (
          <button
            className="memory-delete"
            onClick={onAskDelete}
            disabled={pending}
            aria-label="删除这条记忆"
          >
            <Trash2 size={13} aria-hidden="true" /> 删除
          </button>
        )}
      </div>

      {confirming && (
        <div className="memory-confirm" role="group" aria-label="确认删除这条记忆">
          <div className="memory-confirm-warn">
            <TriangleAlert size={13} aria-hidden="true" />
            <span>
              这是<strong>硬删除</strong>，<strong>删除不可恢复</strong>
              ——没有回收站，删掉后模型不会再想起这条。
            </span>
          </div>
          {error && (
            <div className="project-error" role="alert">
              {error}
            </div>
          )}
          <div className="memory-confirm-actions">
            <button className="project-btn" onClick={onCancelDelete} disabled={pending}>
              取消
            </button>
            <button
              className="project-btn project-btn-danger"
              onClick={onConfirmDelete}
              disabled={pending}
            >
              {pending ? '删除中…' : '确认删除'}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
