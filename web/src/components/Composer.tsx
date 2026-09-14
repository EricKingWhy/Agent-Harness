/** Composer — task input at the bottom of the conversation column.
 *
 * Submits on Cmd/Ctrl+Enter. Disabled while streaming or when an approval is pending.
 * presetTask: 外部注入的示例任务（空状态 chip 点击），注入后仍可自由编辑。
 */

import { memo, useEffect, useState, type KeyboardEvent } from 'react';
import { ArrowUp, Brain, Layers, Shield, Square, User } from 'lucide-react';
import type { PresetTask } from '../types';
import { modKey } from '../lib/platform';
import type { CatalogEntry, ModelCatalogEntry } from '../lib/api';
import { ModelPicker } from './ModelPicker';
import { ControlPicker } from './ControlPicker';
import { ContextProviderPicker } from './ContextProviderPicker';

interface Props {
  streaming: boolean;
  /** UI-01（D4-⑤）：存在待决审批时锁住 composer——运行被阻塞，新任务
   *  与审批互斥，不允许两条修复路径同时开放（评审 Riley 红旗）。 */
  approvalPending?: boolean;
  onSubmit: (task: string) => void;
  onCancel: () => void;
  presetTask?: PresetTask | null;
  /** T10 #103 模型目录（GET /api/models）：空 = 端点缺席/解析失败 → 选择器
   *  降级隐藏（不伪造列表）。条目即目录真相，零硬编码模型名。 */
  models?: ModelCatalogEntry[];
  /** 当前选中（null = 默认链，提交不带 model 字段）。 */
  selectedModel?: string | null;
  onModelChange?: (name: string | null) => void;
  // ── Phase 2b Composer control row（Ticket F1）──
  /** GET /api/permission-modes 清单。空 → 隐藏控件。 */
  permissionModes?: CatalogEntry[];
  selectedPermissionMode?: string | null;
  onPermissionModeChange?: (id: string | null) => void;
  /** GET /api/agent-profiles 清单。空 → 隐藏控件。 */
  agentProfiles?: CatalogEntry[];
  selectedAgentProfile?: string | null;
  onAgentProfileChange?: (id: string | null) => void;
  /** GET /api/reasoning-efforts 清单。空 → 隐藏控件。 */
  reasoningEfforts?: CatalogEntry[];
  selectedReasoningEffort?: string | null;
  onReasoningEffortChange?: (id: string | null) => void;
  /** GET /api/context-providers 清单。空 → 隐藏控件（不伪造）。多选。 */
  contextProviders?: CatalogEntry[];
  selectedContextProviders?: string[];
  onContextProvidersChange?: (ids: string[]) => void;
}

// memo：流式期间 props 稳定（streaming 布尔不变、回调由 App useCallback 固定），
// 输入框不随对话区每个 delta 重渲染。
export const Composer = memo(function Composer({
  streaming,
  approvalPending = false,
  onSubmit,
  onCancel,
  presetTask,
  models = [],
  selectedModel = null,
  onModelChange,
  permissionModes = [],
  selectedPermissionMode = null,
  onPermissionModeChange,
  agentProfiles = [],
  selectedAgentProfile = null,
  onAgentProfileChange,
  reasoningEfforts = [],
  selectedReasoningEffort = null,
  onReasoningEffortChange,
  contextProviders = [],
  selectedContextProviders = [],
  onContextProvidersChange,
}: Props) {
  const [value, setValue] = useState('');

  // UI-01：审批待决 = 运行被阻塞，与 streaming 同一禁用通道（不建第二状态源）。
  const locked = streaming || approvalPending;
  // 锁定提示只表达「审批阻塞」这一种原因；纯 streaming 有自己的 affordances（停止键/Esc 提示）。
  const showLock = approvalPending && !streaming;

  // 外部示例任务注入（引用变化即触发；每次点击 chip 生成新对象）
  useEffect(() => {
    if (presetTask) setValue(presetTask.text);
  }, [presetTask]);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || locked) return;
    onSubmit(trimmed);
    setValue('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  };

  // 控件行是否渲染——至少有一个非空目录时才显示 control row 容器
  const hasControls =
    models.length > 0 ||
    permissionModes.length > 0 ||
    agentProfiles.length > 0 ||
    reasoningEfforts.length > 0 ||
    contextProviders.length > 0;

  return (
    <div className="composer-wrap">
      <div className="composer-dock surface-floating">
        {/* UI-01：审批待决时给出锁定原因（置灰不是隐形）。 */}
        {showLock && <div className="composer-locked-hint">等待审批决策后再继续</div>}
        <textarea
          id="composer-input"
          name="task"
          className="composer"
          placeholder={showLock ? '等待审批决策…' : `描述一个任务…（${modKey()}+Enter 发送）`}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          disabled={locked}
          aria-label="Agent 任务"
        />
        {hasControls && (
          <div className="composer-controls">
            <ModelPicker
              models={models}
              selectedModel={selectedModel}
              onModelChange={onModelChange ?? (() => {})}
              disabled={locked}
            />
            <ControlPicker
              ariaLabel="权限模式"
              entries={permissionModes}
              selectedId={selectedPermissionMode}
              onChange={onPermissionModeChange ?? (() => {})}
              icon={Shield}
              placeholder="权限"
              disabled={locked}
            />
            <ControlPicker
              ariaLabel="Agent Profile"
              entries={agentProfiles}
              selectedId={selectedAgentProfile}
              onChange={onAgentProfileChange ?? (() => {})}
              icon={User}
              placeholder="Agent"
              disabled={locked}
            />
            <ControlPicker
              ariaLabel="Reasoning Effort"
              entries={reasoningEfforts}
              selectedId={selectedReasoningEffort}
              onChange={onReasoningEffortChange ?? (() => {})}
              icon={Brain}
              placeholder="推理"
              disabled={locked}
            />
            <ContextProviderPicker
              ariaLabel="Context Providers"
              entries={contextProviders}
              selectedIds={selectedContextProviders}
              onChange={onContextProvidersChange ?? (() => {})}
              icon={Layers}
              placeholder="Context"
              disabled={locked}
            />
          </div>
        )}
        {streaming ? (
          <>
            {/* Esc 中断提示（Claude Code "esc to interrupt" 语言）：键位绑定在 App 全局，这里只做可见性 */}
            <span className="composer-esc-hint" aria-hidden="true">
              <kbd>Esc</kbd> 停止
            </span>
            <button className="composer-stop" onClick={onCancel} aria-label="停止" title="停止">
              <Square size={14} />
            </button>
          </>
        ) : (
          <button
            className="composer-send"
            onClick={submit}
            disabled={locked || !value.trim()}
            aria-label="发送"
            title={`发送（${modKey()}+Enter）`}
          >
            <ArrowUp size={16} />
          </button>
        )}
      </div>
    </div>
  );
});
