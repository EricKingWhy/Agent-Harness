/** StepDetail — right rail Run Inspector（PRD §8，ADR-0014 D3 重排）.
 *
 * Timeline 升为 Inspector 常驻主体（PRD §8.3 "Timeline 是 Inspector 的核心"）：
 *   Timeline  → 每条事件 verbatim（seq · type · summary），默认 tab；点击行钻取
 *               事件详情，并反向定位中间主区（PRD §9.2 联动）
 *   Overview  → Run 级摘要（RUN / TOOLS / CONTEXT / MODEL / TRACE——原 Chat tab）
 *   Changes   → 文件 diff 聚合（保留，D11 不删）
 *   Terminal  → bash 调用聚合（保留）
 *   Artifacts → artifact ref 聚合（保留）
 *
 * Event-level inspector（PRD §8.4 四段）：Overview / Input / Output / Raw，
 * 顶部返回按钮回 Timeline（无弹窗——"上下文 Inspector"）。
 */

import { Fragment, memo, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react';
import {
  AlertTriangle, ArrowLeft, ChevronRight, Clock, Database, FileCheck2, FileDiff,
  Hash, Layers, ListTree, Maximize2, Minimize2, Package, Pin, ShieldCheck,
  TerminalSquare, X,
} from 'lucide-react';
import type { AgentEvent, ConversationState, ToolCall } from '../types';
import { formatDuration, formatTimestamp, stringifyForDisplay, truncateForDisplay } from '../lib/format';
import { groupEventsByRun, type RunGroupStatus } from '../lib/timelineGroups';
import { allTools, summarizeEvent } from '../lib/projection';
import { permissionView } from '../lib/permission';
import { commandOutputs, commandResult, isCommand } from '../lib/commandOutput';
import {
  INSPECTOR_MAX_W, INSPECTOR_MIN_W,
  clampInspectorWidth, escAction, eventKey, nextSelectionIndex, spaceReleaseCloses, toolKey,
} from '../lib/inspectorPanel';
import { deriveRunPulse, deriveRunSummary } from '../lib/runState';
import { useChildConversation } from '../hooks/useChildConversation';
import { ArtifactViewer } from './ArtifactViewer';
import { CopyButton } from './CopyButton';
import { DiffBlock } from './DiffBlock';
import { JsonTree } from './JsonTree';
import { ToolOutputStream } from './ToolOutputStream';

/** Inspector focus: Run-level overview, a drilled-in event, or a child session
 *  (Phase 13 委派钻取，v2 PRD §10.5 "delegation start ↔ child run" 配对）。 */
export type InspectorFocus =
  | { kind: 'run' }
  | { kind: 'tool'; tool: ToolCall }
  | { kind: 'event'; event: AgentEvent }
  | { kind: 'child'; childSessionId: string; target: string };

type Tab = 'timeline' | 'chat' | 'changes' | 'terminal' | 'artifacts';

/** Tab 图标 —— 每个 tab 一个 lucide icon，与 label 配对。
 *  Inspector 分段控件（segmented control）参考 Linear issue 面板与 VS Code
 *  侧栏：icon + label 在宽面板下并排，窄面板（<300px）降级为 icon-only + title。 */
const TAB_ICONS: Record<Tab, typeof ListTree> = {
  timeline: ListTree,
  chat: Hash,
  changes: FileDiff,
  terminal: TerminalSquare,
  artifacts: Package,
};

const TABS: readonly { id: Tab; label: string }[] = [
  { id: 'timeline', label: 'Timeline' },
  { id: 'chat', label: 'Overview' },
  { id: 'changes', label: 'Changes' },
  { id: 'terminal', label: 'Terminal' },
  { id: 'artifacts', label: 'Artifacts' },
];

// C4 Timeline hover 浮层布局常量（与 .tl-tooltip CSS 对齐——行高 16、内距 12、
// 与行边的 4px 间隙、上方放置需要的 16px 顶部裕量）。改一个地方即可。
const TIP_LINE_H = 16;
const TIP_PADDING = 12;
const TIP_GAP = 4;
const TIP_TOP_MARGIN = 16;

interface Props {
  conversation: ConversationState | null;
  streaming: boolean;
  focus: InspectorFocus;
  onFocusRun: () => void;
  onFocusTool: (tool: ToolCall) => void;
  onFocusEvent: (event: AgentEvent) => void;
  /** PRD §9.2 反向联动：点 Timeline 行 → 中间主区滚动定位对应事件。 */
  onJumpToStream?: (event: AgentEvent) => void;
  /** #184 反向联动：点 PERMISSION 段的待审批行 → 中间主区滚动定位审批卡。 */
  onJumpToApproval?: (approvalId: string) => void;
  /** #183 面板视图状态（钉住 / 整页 / 宽度 / peek 开合）。状态归 App——面板宽度与整页
   *  要改的是 `.app-regions` 的栅格，StepDetail 只是消费方与触发方。 */
  panel: InspectorPanelState;
  /** #183 面板动作。**显式动作而不是 toggle**：Esc 要的是"退出整页"而非"翻转整页"，
   *  用一个 `toggle` 表达两件事会让"连按两次 = 回到原点"这类事故无法从类型上排除。 */
  onPanelAction: (action: InspectorPanelAction) => void;
}

/** #183 面板视图状态（全部**不持久化**，不变量 #22）。 */
export interface InspectorPanelState {
  /** 钉住：切换会话时不自动收起（AC4）。 */
  pinned: boolean;
  /** 整页：面板占满工作区宽度，长 trace / 大 diff 宽读（AC5）。 */
  expanded: boolean;
  /** 面板宽度 px（320→480，AC6）。 */
  width: number;
  /** 选中项详情（peek）是否展开。关掉只是 `hidden`，**不卸载**（AC2）。 */
  peekOpen: boolean;
}

/** #183 面板动作（单入口，App 用一个 handler 消费）。 */
export type InspectorPanelAction =
  | { type: 'pin'; value: boolean }
  | { type: 'expand'; value: boolean }
  | { type: 'close' }
  | { type: 'open-peek' }
  | { type: 'close-peek' }
  | { type: 'resize'; width: number };

export function StepDetail({ conversation, streaming, focus, onFocusRun, onFocusTool, onFocusEvent, onJumpToStream, onJumpToApproval, panel, onPanelAction }: Props) {
  const [tab, setTab] = useState<Tab>('timeline');
  /* 头标 run-id 列表（title + 「N runs」计数同源）。必须挂在此处——useMemo 不许
   * 出现在下方任何 early-return 之后（Rules of Hooks：focus/tool 分支返回的渲染
   * 不跑这些 hook，先后两次渲染的 hook 数就会不一致 → React 崩溃）。 */
  const runIdList = useMemo(
    () => [...new Set((conversation?.events ?? []).flatMap((e) => (e.run_id ? [e.run_id] : [])))],
    [conversation?.events],
  );
  /* #183：面板根节点（拖宽要量出"中心列 + 面板"的实际可用宽度）与键盘计时/拖拽状态。
   * 同样是 hook——必须在 early-return 之前。 */
  const panelRef = useRef<HTMLElement>(null);
  const spaceDownAt = useRef<number | null>(null);
  const dragRef = useRef<{ startX: number; startW: number; available: number } | null>(null);
  const [resizing, setResizing] = useState(false);

  if (!conversation) {
    return (
      <aside className="step-detail" data-panel="inspector">
        <DetailEmpty />
      </aside>
    );
  }

  // Phase 13 委派钻取（v2 PRD §10.5 "delegation start ↔ child run" 配对）：
  // child 会话在 Inspector 内原位展开——父会话上下文不丢，「返回 Run」一键回。
  // 置于 run 级派生（tools/pulse）之前——child 视图不消费它们（Standards P3）。
  // 仍是**独占**面板（不是 peek）：它是从中间列显式钻进来的另一个会话视图，
  // 与"清单 + 选中项详情"不同性质（#183 的 peek 只服务当前会话的选择）。
  if (focus.kind === 'child') {
    return (
      <aside className="step-detail" data-panel="inspector">
        <div className="detail-header">
          <button className="child-back-btn" onClick={onFocusRun} title="返回父会话 Run 视图">
            <ArrowLeft size={14} /> Run
          </button>
          <span className="panel-label">子会话 · {focus.target || '?'}</span>
          <span className="detail-run-id mono num" title={`child session ${focus.childSessionId}`}>
            {focus.childSessionId.slice(0, 8)}
          </span>
        </div>
        <div className="detail-body">
          <ChildSessionView childSessionId={focus.childSessionId} />
        </div>
      </aside>
    );
  }

  // 单一走法（#190）：与中心列「输出」面共用 projection.allTools。
  const tools = allTools(conversation);
  // #186：归档 diff 的「就地展开」要按会话读 artifact 内容——归属只能由 session 决定
  // （artifact_id 是内容哈希，跨会话可重名），所以从投影的会话 id 取，不另存一份。
  const sessionId = conversation.session_id;
  const pulse = deriveRunPulse(conversation, streaming);
  /* UI-03：tab 条目计数（与各 tab 的数据源同一判据，不建第二真相）。
   * Overview 是摘要页不计数；Changes/Terminal/Artifacts 的过滤条件与对应
   * Tab 组件内的 filter 逐字一致。 */
  const tabCounts: Partial<Record<Tab, number>> = {
    timeline: conversation.events.length,
    changes: tools.filter((t) => t.diff).length,
    terminal: tools.filter(isCommand).length,
    artifacts: tools.filter((t) => t.artifact).length,
  };

  /* #183 清单条目：↑/↓ 的移动域 = **当前 tab 里可点击选中的行**。
   *
   * 只登记"行本身可点"的三个面（Timeline 事件 / Overview 工具行 / Terminal 命令行）：
   * Changes / Artifacts 的行目前是只读卡片（不是按钮），为它们造一个只能用键盘到达的
   * 选中态，等于做出一个鼠标无法复现的选择——违反 AC3「鼠标默认可用，不做键盘唯一」。
   * 那两面的行要不要变成可选中，是它们各自票里的事。 */
  const listTargets: { key: string; focus: () => void }[] = (() => {
    switch (tab) {
      case 'timeline':
        return conversation.events.map((e) => ({ key: eventKey(e), focus: () => onFocusEvent(e) }));
      case 'chat':
        return tools.map((t) => ({ key: toolKey(t), focus: () => onFocusTool(t) }));
      case 'terminal':
        return tools
          .filter(isCommand)
          .map((t) => ({ key: toolKey(t), focus: () => onFocusTool(t) }));
      default:
        return [];
    }
  })();
  const selectedKey =
    focus.kind === 'event' ? eventKey(focus.event) : focus.kind === 'tool' ? toolKey(focus.tool) : null;
  const selectedIndex = selectedKey === null ? -1 : listTargets.findIndex((t) => t.key === selectedKey);
  const hasSelection = focus.kind === 'event' || focus.kind === 'tool';

  const moveSelection = (delta: number) => {
    if (listTargets.length === 0) return;
    const next = nextSelectionIndex(selectedIndex, delta, listTargets.length);
    if (next < 0 || next === selectedIndex) return;
    /* 只移动**选中项**，不搬 DOM 焦点：焦点搬家的收益（读屏"当前项"与视觉一致）
       由行上的 `aria-current` 承担，而代价是一个新的失败模式——选中项滚出 Timeline
       的渲染窗口时那一行还不存在，`focus()` 会静默打空、焦点留在旧行上。行内的
       滚动与窗口展开归 Timeline 自己（它知道窗口边界）。 */
    listTargets[next].focus();
  };

  /** Space 的生效范围：清单与面板 chrome。详情面板内部有自己的按钮（复制/标签条），
   *  表单域与详情内部一律不抢——否则"在详情里按空格切换标签"会变成开合预览。 */
  const spaceExcluded = (target: HTMLElement) =>
    Boolean(target.closest('input, textarea, select, [contenteditable="true"], .detail-peek'));

  /** #183 面板键位（AC2/AC5/AC7）。挂在 <aside> 上而**不是 window**：
   *  ① 只有焦点在面板内才生效——面板外的 Esc 仍归全局"中断流式"（既有行为）；
   *  ② 帧内 `stopPropagation` 让面板内的 Esc 不再被全局监听吃成"停止运行"：
   *     用户按 Esc 的意图是"关掉我正在看的这层"，而不是"杀掉正在跑的 run"。 */
  const onPanelKeyDown = (e: ReactKeyboardEvent<HTMLElement>) => {
    const target = e.target as HTMLElement;
    if (target.closest('[role="dialog"]')) return; // 弹层优先（同 App 的既有口径）
    if (e.key === 'Escape') {
      e.stopPropagation();
      const action = escAction({ expanded: panel.expanded, peekOpen: panel.peekOpen && hasSelection });
      if (action === 'exit-fullpage') onPanelAction({ type: 'expand', value: false });
      else if (action === 'close-peek') onPanelAction({ type: 'close-peek' });
      else onPanelAction({ type: 'close' });
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (listTargets.length === 0) return;
      e.preventDefault(); // 选中与滚动不要同时发生（滚动由列表在选中后自己做）
      moveSelection(e.key === 'ArrowDown' ? 1 : -1);
      return;
    }
    if (e.code === 'Space' || e.key === ' ') {
      if (spaceExcluded(target)) return;
      e.preventDefault(); // 不让浏览器把它当"滚动/激活当前按钮"
      if (e.repeat) return; // 长按的重复事件不重置计时
      spaceDownAt.current = performance.now();
      // 已有选中项但预览关着 → Space = 预览（Linear：Space 开 peek）。
      if (hasSelection && !panel.peekOpen) onPanelAction({ type: 'open-peek' });
    }
  };

  /** AC2：快按 = 保持打开，按住 = 松手关闭。判定在 lib/inspectorPanel（有测试钉住）。 */
  const onPanelKeyUp = (e: ReactKeyboardEvent<HTMLElement>) => {
    if (e.code !== 'Space' && e.key !== ' ') return;
    if (spaceExcluded(e.target as HTMLElement)) return;
    const startedAt = spaceDownAt.current;
    spaceDownAt.current = null;
    if (startedAt === null) return;
    if (spaceReleaseCloses(performance.now() - startedAt)) onPanelAction({ type: 'close-peek' });
  };

  /** AC6 拖宽：`available` 用**实测**的「中心列 + 面板」宽度（不含 rail——窄屏 rail
   *  会变 56px，用常量算出来的上限会随断点变化而错）。 */
  const onResizeStart = (e: ReactPointerEvent<HTMLElement>) => {
    const workspace = panelRef.current?.parentElement?.querySelector<HTMLElement>('.app-workspace');
    dragRef.current = {
      startX: e.clientX,
      startW: panel.width,
      available: (workspace?.clientWidth ?? 0) + panel.width,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    setResizing(true);
  };
  const onResizeMove = (e: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    onPanelAction({
      type: 'resize',
      width: clampInspectorWidth(drag.startW + (e.clientX - drag.startX), drag.available),
    });
  };
  const onResizeEnd = (e: ReactPointerEvent<HTMLElement>) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setResizing(false);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  };
  /** 拖宽手柄的键盘通路（AC7：面板控制要么键鼠双通，要么别做成分隔条——
   *  一个 `role="separator"` 不能被键盘操作是**假**的可访问性声明）。 */
  const onResizeKeyDown = (e: ReactKeyboardEvent<HTMLElement>) => {
    const step = e.shiftKey ? 64 : 16;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    e.stopPropagation(); // 与清单 ↑/↓ 分开：这里左右调宽度
    const workspace = panelRef.current?.parentElement?.querySelector<HTMLElement>('.app-workspace');
    const available = (workspace?.clientWidth ?? 0) + panel.width;
    const next = panel.width + (e.key === 'ArrowRight' ? step : -step);
    onPanelAction({ type: 'resize', width: clampInspectorWidth(next, available) });
  };

  const peekVisible = hasSelection && panel.peekOpen;

  return (
    <aside
      className="step-detail"
      data-panel="inspector"
      data-expanded={panel.expanded ? 'true' : 'false'}
      data-resizing={resizing ? 'true' : 'false'}
      ref={panelRef}
      onKeyDown={onPanelKeyDown}
      onKeyUp={onPanelKeyUp}
    >
      {/* #183 AC6：拖宽手柄。`separator` + 当前值/范围如实上报（AC7），左右键可调。 */}
      <div
        className="detail-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整 Inspector 宽度"
        aria-valuenow={panel.width}
        aria-valuemin={INSPECTOR_MIN_W}
        aria-valuemax={INSPECTOR_MAX_W}
        aria-valuetext={`${panel.width} 像素`}
        tabIndex={0}
        onPointerDown={onResizeStart}
        onPointerMove={onResizeMove}
        onPointerUp={onResizeEnd}
        onPointerCancel={onResizeEnd}
        onKeyDown={onResizeKeyDown}
      />
      <div className="detail-header">
        <span className="panel-label">Run Inspector</span>
        <span className={`run-badge run-badge-${pulse.state}`}>{pulse.label}</span>
        {/* UI-03 头标对齐：时间线平铺全会话事件，头标就得描述全会话范围
            （N runs · M 事件）——此前显示单个 run_id 短码，与列表范围自相矛盾
            （原 PRD §8.2 短码方案随本票退役，完整 run_id 回到分组头 title 与
            Overview 的 run 行）。 */}
        {conversation.events.length > 0 && (
          <span
            className="detail-run-id mono num"
            title={`runs: ${runIdList.join(', ')}`}
          >
            {runIdList.length} runs · {conversation.events.length} 事件
          </span>
        )}
        {/* #183 AC4/AC5/AC7：钉住 / 整页 / 关闭。三个都是键盘可达的按钮，开关类用
            `aria-pressed` 如实上报（不是靠 icon 换形状暗示状态）。 */}
        <span className="detail-header-actions">
          <button
            type="button"
            className={`detail-ctrl${panel.pinned ? ' sel' : ''}`}
            aria-pressed={panel.pinned}
            /* 名与状态分离：`aria-pressed` 说状态，`aria-label` 说"这是什么"。
               名字**必须**在这里给——窄面板（<360px）隐藏 `.detail-ctrl-label`
               之后，按钮的可访问名会变成空（icon 是 aria-hidden 的）。 */
            aria-label="钉住"
            onClick={() => onPanelAction({ type: 'pin', value: !panel.pinned })}
            title="钉住：切换会话时不自动收起（视图状态，不持久化）"
          >
            <Pin size={13} aria-hidden="true" />
            <span className="detail-ctrl-label">钉住</span>
          </button>
          <button
            type="button"
            className={`detail-ctrl${panel.expanded ? ' sel' : ''}`}
            aria-pressed={panel.expanded}
            aria-label="整页"
            onClick={() => onPanelAction({ type: 'expand', value: !panel.expanded })}
            title={panel.expanded ? '退回（Esc）' : '整页打开：长 trace / 大 diff 宽读'}
          >
            {panel.expanded ? <Minimize2 size={13} aria-hidden="true" /> : <Maximize2 size={13} aria-hidden="true" />}
            <span className="detail-ctrl-label">整页</span>
          </button>
          <button
            type="button"
            className="detail-ctrl"
            aria-label="关闭 Inspector"
            onClick={() => onPanelAction({ type: 'close' })}
            title="关闭（Esc）"
          >
            <X size={13} aria-hidden="true" />
          </button>
        </span>
      </div>

      <div className="detail-tabs" role="tablist" aria-label="Inspector 视图">
        {TABS.map((t) => {
          const Icon = TAB_ICONS[t.id];
          /* UI-03：识别而非回忆——每个视图 tab 带条目计数（Overview 是摘要页无计数）。 */
          const count = tabCounts[t.id];
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className={`detail-tab ${tab === t.id ? 'sel' : ''}`}
              onClick={() => setTab(t.id)}
              title={t.label}
              /* 计数徽标是 tab 的真实文本内容：窄面板 label 隐藏（容器查询
                 icon-only）后它就成了唯一可访问名，getByRole(tab, 'Timeline')
                 会变成 name '4'。aria-label 钉住语义名，不受徽标/显隐影响。 */
              aria-label={t.label}
            >
              <Icon size={13} className="detail-tab-icon" aria-hidden="true" />
              <span className="detail-tab-label">{t.label}</span>
              {count !== undefined && (
                <span className="detail-tab-count num" aria-hidden="true">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* 结构分层：header/tabs 钉在面板顶部，只有内容滚动（用户反馈 2026-09-06：
          长内容把 tabs 滚出视口后无法切换）。

          #183 AC1：**清单与选中项详情同框**。此前 `focus` 非 run 时这里早退成
          "只有详情"，清单整个消失——用户无法"在清单里移动、看详情跟随"（Timeline
          好用的原因正是清单与详情同框）。现在两者是两个独立滚动区：清单保住自己的
          滚动位置，详情实时跟着选中项换内容（组件实例不重建）。 */}
      <div className="detail-body" data-has-peek={peekVisible ? 'on' : 'off'}>
        <div className="detail-list">
          {tab === 'chat' && (
            <ChatTab
              conversation={conversation}
              tools={tools}
              onFocusTool={onFocusTool}
              onJumpToApproval={onJumpToApproval}
              selectedKey={selectedKey}
            />
          )}
          {tab === 'timeline' && (
            <TimelineTab
              key={conversation.session_id}
              conversation={conversation}
              onFocusEvent={onFocusEvent}
              onJumpToStream={onJumpToStream}
              selectedKey={selectedKey}
            />
          )}
          {tab === 'changes' && <ChangesTab tools={tools} sessionId={sessionId} />}
          {tab === 'terminal' && (
            <TerminalTab tools={tools} onFocusTool={onFocusTool} selectedKey={selectedKey} />
          )}
          {tab === 'artifacts' && <ArtifactsTab tools={tools} sessionId={sessionId} />}
        </div>

        {/* AC2：peek 关掉只是 `hidden`（**不卸载**）——内部标签条与滚动位置留着，
            再打开是"接着看"而不是"重新开始"。 */}
        {hasSelection && (
          <section
            className="detail-peek"
            data-peek={peekVisible ? 'on' : 'off'}
            hidden={!peekVisible}
            aria-label="选中项详情"
          >
            <div className="detail-peek-head">
              <span className="panel-label">选中项详情</span>
              <span className="detail-peek-kind mono">
                {focus.kind === 'tool' ? focus.tool.name : focus.event.type}
              </span>
              <button
                type="button"
                className="detail-ctrl detail-peek-close"
                aria-label="关闭预览（保持选中）"
                title="关闭预览（Esc）"
                onClick={() => onPanelAction({ type: 'close-peek' })}
              >
                <X size={13} aria-hidden="true" />
              </button>
            </div>
            <div className="detail-peek-body">
              <EventInspector focus={focus} />
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}

/** UI-03：run 分组头状态徽章文案（与 run-badge-<state> 色域一一对应）。 */
const RUN_GROUP_STATUS_LABEL: Record<RunGroupStatus, string> = {
  completed: '已完成',
  failed: '失败',
  interrupted: '已中断',
  running: '进行中',
};

// ── Chat tab：Run 级摘要（真数据区块 + 空槽标注） ──

export function ChatTab({
  conversation, tools, onFocusTool, onJumpToApproval, selectedKey,
}: {
  conversation: ConversationState;
  tools: ToolCall[];
  /** 工具行点击回调——子会话视图等只读场景缺省：行渲染为静态行（假按钮≠诚实）。 */
  onFocusTool?: (tool: ToolCall) => void;
  /** 待审批行点击 → 中间主区滚动定位到审批卡（#184）。与 `onFocusTool` 同规则：
   *  缺省时行渲染为静态行，不画一个点不动的按钮。 */
  onJumpToApproval?: (approvalId: string) => void;
  /** #183：当前选中项身份——工具行据此标 `aria-current`（清单与详情同框后，
   *  "哪一条被选中"必须在列表里可读，否则右下方详情与列表对不上号）。 */
  selectedKey?: string | null;
}) {
  // Run 状态 + 时长由 lib/runState 的 deriveRunSummary 单一提供：粗标签的
  // 「取消 ≠ 失败」语义、以及「终态集合必须含 run/interrupted」这条与顶栏脉冲
  // 共用同一份判据（此处原先自己再分支一次 run_cancelled/run_status，规则一变
  // Inspector 就会与顶栏说法不一致——T8 加 run/interrupted 时正是三处集体漂移）。
  const { label: runStatusLabel, startedAt: runStart, duration: runDuration } = deriveRunSummary(conversation);

  return (
    <>
      <div className="detail-section">
        <div className="detail-section-title">
          <Hash size={14} /> RUN
        </div>
        <div className="detail-row">
          <span className="detail-key">run</span>
          <code className="detail-val detail-val-mono">{conversation.run_id ?? '—'}</code>
        </div>
        <div className="detail-row">
          <span className="detail-key">会话</span>
          <code className="detail-val detail-val-mono">{conversation.session_id.slice(0, 16)}</code>
        </div>
        <div className="detail-row">
          <span className="detail-key">状态</span>
          <span className="detail-val">{runStatusLabel}</span>
        </div>
        <div className="detail-row">
          <span className="detail-key">轮次</span>
          <span className="detail-val">{conversation.turns.length}</span>
        </div>
        {runStart && (
          <div className="detail-row">
            <span className="detail-key">开始</span>
            <span className="detail-val">{new Date(runStart).toLocaleTimeString()}</span>
          </div>
        )}
        <div className="detail-row">
          <span className="detail-key">耗时</span>
          <span className="detail-val">{runDuration ?? '—'}</span>
        </div>
        <div className="detail-row">
          <span className="detail-key">tokens</span>
          <span className="detail-val num">
            {conversation.usage_total
              ? conversation.usage_total.total_tokens.toLocaleString()
              : <span className="detail-val-muted">—</span>}
          </span>
        </div>
        {/* Langfuse trace 关联（ADR-0018 D7 + 契约 2d7f87a）：
            trace_url 有值 → trace_id 渲染为可点超链接直达 Langfuse dashboard；
            trace_id 有值但 trace_url 缺 → 纯 mono code（可复制，手动粘到 Langfuse 搜索）；
            两者都 null（Langfuse 未启用）→「未追踪」灰字（预期降级非故障）。 */}
        <div className="detail-row">
          <span className="detail-key">Trace</span>
          {conversation.trace_id ? (
            conversation.trace_url ? (
              <a
                className="detail-val detail-val-mono detail-trace-link"
                href={conversation.trace_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {conversation.trace_id}
              </a>
            ) : (
              <code className="detail-val detail-val-mono">{conversation.trace_id}</code>
            )
          ) : (
            <span className="detail-val detail-val-muted">未追踪</span>
          )}
        </div>
      </div>

      <div className="detail-section">
        <div className="detail-section-title">
          <Package size={14} /> TOOLS
        </div>
        <div className="detail-row">
          <span className="detail-key">计数</span>
          <span className="detail-val">{tools.length}</span>
        </div>
        <div className="detail-row">
          <span className="detail-key">活跃</span>
          <span className="detail-val">{tools.filter((t) => t.status === 'running').length}</span>
        </div>
        <div className="detail-row">
          <span className="detail-key">失败</span>
          <span className="detail-val">{tools.filter((t) => t.status === 'failed').length}</span>
        </div>
        {tools.map((t) => {
          const selected = selectedKey != null && toolKey(t) === selectedKey;
          const rowClass = `detail-tool-row${selected ? ' sel' : ''}`;
          return onFocusTool ? (
            <button
              key={t.tool_call_id}
              className={rowClass}
              data-list-key={toolKey(t)}
              aria-current={selected ? 'true' : undefined}
              onClick={() => onFocusTool(t)}
            >
              <ChevronRight size={14} />
              <span className={`tool-status-dot tool-status-dot-${t.status}`} />
              <span className="detail-tool-name">{t.name}</span>
            </button>
          ) : (
            <div key={t.tool_call_id} className={`${rowClass} detail-tool-row-static`}>
              <span className={`tool-status-dot tool-status-dot-${t.status}`} />
              <span className="detail-tool-name">{t.name}</span>
            </div>
          );
        })}
      </div>

      {conversation.compactions.length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">
            <Layers size={14} /> CONTEXT
          </div>
          {conversation.compactions.map((c, i) => (
            <div key={i} className="detail-compaction-row">
              <div className="detail-row">
                <span className="detail-key">压缩轮次</span>
                <span className="detail-val">{c.compacted_turn_count}</span>
              </div>
              <div className="detail-row">
                <span className="detail-key">Token 估算</span>
                <span className="detail-val">{c.token_estimate.toLocaleString()}</span>
              </div>
              {c.fallback_used && (
                <div className="detail-row detail-row-warn">
                  <AlertTriangle size={14} /> <span>兜底降级（非模型摘要）</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {conversation.reconcile_queue.length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">
            <AlertTriangle size={14} /> 需人工裁决
          </div>
          {conversation.reconcile_queue.map((r, i) => (
            <div key={i} className="detail-reconcile-row">
              <div className="detail-row">
                <span className="detail-key">工具</span>
                <span className="detail-val">{r.tool_name}</span>
              </div>
              <div className="detail-row">
                <span className="detail-key">参数身份</span>
                <code className="detail-val detail-val-mono">{r.args_identity}</code>
              </div>
              <div className="detail-row">
                <span className="detail-key">状态</span>
                <span className="detail-val detail-val-tag">{r.state}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="detail-section">
        <div className="detail-section-title">
          <ListTree size={14} /> TRACE
        </div>
        <div className="detail-row">
          <span className="detail-key">事件数</span>
          <span className="detail-val">{conversation.events.length}</span>
        </div>
        {conversation.unknown_events.length > 0 && (
          <div className="detail-row detail-row-warn">
            <span className="detail-key">未知事件</span>
            <span className="detail-val">{conversation.unknown_events.length}</span>
          </div>
        )}
        {seqGaps(conversation.events).map((gap, i) => (
          <div key={i} className="detail-row detail-row-warn">
            <span className="detail-key">seq 缺口</span>
            <span className="detail-val detail-val-mono">{gap}</span>
          </div>
        ))}
      </div>

      {/* MODEL：后端 Gap 1 已落地（model/completed + run/completed 观测字段）。
          全部缺失时保留空槽语义（提示而非留白），有任一真值则逐行渲染，
          缺失行显示「—」——绝不伪造 0（零伪造指标冻结决策）。 */}
      {conversation.model === null && conversation.usage_total === null && conversation.cost_usd === null ? (
        <div className="detail-section detail-reserved">
          <div className="detail-section-title">
            <Database size={14} /> MODEL
          </div>
          <div className="detail-empty-hint">暂无观测数据（等待 model/completed）</div>
        </div>
      ) : (
        <div className="detail-section">
          <div className="detail-section-title">
            <Database size={14} /> MODEL
          </div>
          <div className="detail-row">
            <span className="detail-key">模型</span>
            <span className="detail-val detail-val-mono">{conversation.model ?? '—'}</span>
          </div>
          {conversation.model_fallback && (
            <div className="detail-row">
              <span className="detail-key">已切换</span>
              <span className="detail-val detail-val-mono model-fallback-val" title="model/fallback：主模型失稳后切换">
                {conversation.model_fallback.from_model} → {conversation.model_fallback.to_model}
                {conversation.model_fallback.reason ? ` · ${conversation.model_fallback.reason}` : ''}
              </span>
            </div>
          )}
          <div className="detail-row">
            <span className="detail-key">用量</span>
            <span className="detail-val">
              {conversation.usage_total
                ? `${conversation.usage_total.total_tokens.toLocaleString()} tok（${conversation.usage_total.prompt_tokens.toLocaleString()} + ${conversation.usage_total.completion_tokens.toLocaleString()}）`
                : '—'}
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-key">成本</span>
            <span className="detail-val">{conversation.cost_usd !== null ? `$${conversation.cost_usd}` : '—'}</span>
          </div>
        </div>
      )}
      <PermissionSection conversation={conversation} onJumpToApproval={onJumpToApproval} />
      <div className="detail-section detail-reserved">
        <div className="detail-section-title">
          <Database size={14} /> CHECKPOINT
        </div>
        <div className="detail-empty-hint">后端未暴露（无 API，集成阶段处理）</div>
      </div>
    </>
  );
}

/** PERMISSION 段（#184，PRD §12）。
 *
 *  数据全部来自事件流投影（`tool/approval-requested` → 队列；`permission/resolved`
 *  → 裁决留痕），**没有新 API**。权限档是唯一需要解释的字段：`permission_mode` 不在
 *  任何事件里、也没有 GET 接口，能证明的只有审批请求携带的 `policy`（ToolExecutor
 *  当时实际用的阈值）——所以整段措辞都在 `lib/permission.ts` 里定，这里只接线。
 *
 *  两处刻意的"不消失"：零待审批 → 显示「无待审批」；零裁决 → 「尚无裁决」。段本身
 *  永远渲染（除非 conversation 为空）——段消失会被读成"这个会话没有权限概念"。 */
function PermissionSection({
  conversation, onJumpToApproval,
}: {
  conversation: ConversationState;
  onJumpToApproval?: (approvalId: string) => void;
}) {
  const view = permissionView(conversation);
  return (
    <div className="detail-section" data-section="permission">
      <div className="detail-section-title">
        <ShieldCheck size={14} /> PERMISSION
      </div>
      <div className="detail-row">
        <span className="detail-key">权限档</span>
        <span className="detail-val detail-val-mono">
          {view.policy ?? <span className="detail-val-muted">—</span>}
        </span>
      </div>
      {view.policy === null && (
        // AC4：拿不到就说明为什么——「—」不带理由会被读成"没有权限约束"。
        <div className="detail-empty-hint">本会话无审批事件，生效阈值无从得知</div>
      )}
      <div className="detail-row">
        <span className="detail-key">待审批</span>
        {/* 零待审批 → 明说（AC2），但仍用静音色：这是"没有"，不是计数 0。 */}
        <span className={`detail-val${view.pending.length === 0 ? ' detail-val-muted' : ''}`}>
          {view.pendingLabel}
        </span>
      </div>
      {view.pending.map((a) =>
        onJumpToApproval ? (
          <button
            key={a.approval_id}
            className="detail-permission-row"
            onClick={() => onJumpToApproval(a.approval_id)}
          >
            <ChevronRight size={14} />
            <span className="detail-tool-name">{a.tool_name || '—'}</span>
            <span className="detail-permission-action">{a.action_type || '—'}</span>
            {/* 失效是事实，不是错误：run 已终结 → 决策永不可能再提交（APR-01）。 */}
            {a.stale === true && <span className="detail-val-tag">已失效</span>}
          </button>
        ) : (
          <div key={a.approval_id} className="detail-permission-row detail-permission-row-static">
            <span className="detail-tool-name">{a.tool_name || '—'}</span>
            <span className="detail-permission-action">{a.action_type || '—'}</span>
            {a.stale === true && <span className="detail-val-tag">已失效</span>}
          </div>
        ),
      )}
      <div className="detail-row">
        <span className="detail-key">已裁决</span>
        <span className={`detail-val${view.decisions.length === 0 ? ' detail-val-muted' : ''}`}>
          {view.decisionsLabel}
        </span>
      </div>
      {view.decisions.map((d) => (
        <div key={d.approval_id} className="detail-permission-decision">
          <span className={`detail-val-tag permission-verdict-${d.tone}`}>{d.verdict}</span>
          <span className="detail-tool-name">{d.toolName}</span>
          {d.reason && <span className="detail-permission-reason" title={d.reason}>{d.reason}</span>}
        </div>
      ))}
    </div>
  );
}

// ── Timeline tab：事件真序日志（真相源 conversation.events，零过滤） ──

/** 尾窗默认大小 / 「加载更早」步长（P1-4）。200 行 ≈4ms 全量渲染（实测），
 * 40fps 合帧下余量充足；步长 500 一次多翻约 2.5 屏。 */
export const TIMELINE_WINDOW_DEFAULT = 200;
export const TIMELINE_WINDOW_STEP = 500;

/** seq 跳转检测（Inspector Scope "TRACE 事件计数 + seq 跳转"）：
 *  返回相邻可比较 seq 对之间的缺口描述（"12 → 15"），不可比较（null/乱序）则跳过。 */
export function seqGaps(events: AgentEvent[]): string[] {
  const gaps: string[] = [];
  let prev: number | null = null;
  for (const e of events) {
    if (e.seq === null) continue;
    if (prev !== null && e.seq > prev + 1) gaps.push(`${prev} → ${e.seq}`);
    prev = Math.max(prev ?? e.seq, e.seq);
  }
  return gaps;
}

/** 事件行的单行摘要——单一投影源（lib/projection.ts summarizeEvent）。 */
const eventSummary = summarizeEvent;

/** Timeline 行 hover 浮层内容（C4）：完整时间戳（含毫秒，本地时区）+ step。
 *  纯函数导出以便 SSR 测试锁定；行内已显示 seq/type，浮层只补看不到的。
 *  step_id 语义：**缺失或 null** 都 = 无归属（后端省略值为 null 的字段 → 键缺失；
 *  recover 合成事件等用 null 哨兵），不渲染该行；数值（含 0，后端从 1 起但类型
 *  契约为 number）按合法 step 渲染。判空必须宽松——严格 `!== null` 会把缺失的键
 *  渲染成字面量 "step undefined"（BUG-008）。 */
export function formatEventTooltip(e: AgentEvent): string[] {
  const lines: string[] = [];
  const ts = formatTimestamp(e.time);
  if (ts) lines.push(ts);
  if (e.step_id != null) lines.push(`step ${e.step_id}`);
  return lines;
}

interface TipState {
  x: number;
  y: number;
  lines: string[];
}

export function TimelineTab({ conversation, onFocusEvent, onJumpToStream, selectedKey }: { conversation: ConversationState; onFocusEvent: (e: AgentEvent) => void; onJumpToStream?: (e: AgentEvent) => void; selectedKey?: string | null }) {
  // 尾窗裁剪（P1-4，DSH "cropped client views"）：真相全量留在 conversation.events
  // （不变量 #22 不动），视图只渲染最近窗口。实测依据：2k 全量渲染 40ms、20k 359ms
  // （流式合帧 40fps 下 Timeline tab 每秒烧 14s CPU）——200 行窗口 ≈4ms，流畅。
  const total = conversation.events.length;
  const [windowSize, setWindowSize] = useState(TIMELINE_WINDOW_DEFAULT);
  // C4：hover 时间戳浮层——单元素 fixed 浮层 + 容器事件委托（零每行 handler）。
  const [tip, setTip] = useState<TipState | null>(null);
  const visibleRef = useRef<AgentEvent[]>([]);
  const lastRowRef = useRef<HTMLElement | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  /* run 分组派生：events 引用不变则不重算（流式每帧 delta 不触发全量重分组）。 */
  const runGroups = useMemo(() => groupEventsByRun(conversation.events), [conversation.events]);

  /* #183：键盘选中项必须在**渲染窗口**里，否则"选中了却看不见"（↑/↓ 到窗口外
   * 就停在原地）。窗口下界由选中项**派生**（`effectiveWindow`），不在 effect 里
   * setState：那是纯函数关系，用 effect 追会多一轮渲染（oxlint
   * `react(set-state-in-effect)` 说的就是这条）。`windowSize` 只保存用户手动
   * "加载更早"的意图，两者取大——精确到 `total - selectedIndex`，不是一把拉到全量
   * （全量渲染正是 200 行窗口要避免的成本，见文件头的实测）。 */
  const selectedIndex = useMemo(() => {
    if (!selectedKey) return -1;
    return conversation.events.findIndex((e) => eventKey(e) === selectedKey);
  }, [conversation.events, selectedKey]);
  const effectiveWindow =
    selectedIndex >= 0 ? Math.max(windowSize, total - selectedIndex) : windowSize;
  const hidden = Math.max(0, total - effectiveWindow);
  /* 选中项滚进视野：`nearest` 保证已经在视野里时**不动**（否则每次 ↑/↓ 都会把
     列表拉到中间，滚动位置就"丢"了——AC1 要的正是滚动位置不被选中的副作用骚扰）。 */
  useEffect(() => {
    if (!selectedKey) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-list-key="${selectedKey}"]`)
      ?.scrollIntoView({ block: 'nearest' });
  }, [selectedKey]);

  // 滚动/缩放即隐藏（fixed 定位不随容器滚动，留着会错位）。
  useEffect(() => {
    const hide = () => {
      lastRowRef.current = null;
      setTip(null);
    };
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    return () => {
      window.removeEventListener('scroll', hide, true);
      window.removeEventListener('resize', hide);
    };
  }, []);

  if (total === 0) {
    return <TabEmpty hint="本会话尚无事件。" icon={ListTree} />;
  }
  const visible = hidden > 0 ? conversation.events.slice(hidden) : conversation.events;
  visibleRef.current = visible;

  const handleOver = (e: ReactMouseEvent<HTMLDivElement>) => {
    const btn = (e.target as HTMLElement).closest?.('[data-tl-i]') as HTMLElement | null;
    if (btn === lastRowRef.current) return;
    lastRowRef.current = btn;
    if (!btn) {
      setTip(null);
      return;
    }
    const ev = visibleRef.current[Number(btn.dataset.tlI)];
    const lines = ev ? formatEventTooltip(ev) : [];
    if (lines.length === 0) {
      setTip(null);
      return;
    }
    const r = btn.getBoundingClientRect();
    const tipH = lines.length * TIP_LINE_H + TIP_PADDING;
    const above = r.top > tipH + TIP_TOP_MARGIN;
    setTip({ x: Math.max(8, r.left + 6), y: above ? r.top - tipH - TIP_GAP : r.bottom + TIP_GAP, lines });
  };
  const handleLeave = () => {
    lastRowRef.current = null;
    setTip(null);
  };

  return (
    <div className="detail-timeline" ref={listRef} onMouseOver={handleOver} onMouseLeave={handleLeave}>
      {hidden > 0 && (
        <div className="timeline-window-bar">
          <button
            className="timeline-earlier"
            /* 以**当前实际可见**的窗口为基准再加一段：选中项派生出来的扩大部分
               不该被一次点击"缩回去"（那会让点一下反而少看几行）。 */
            onClick={() => setWindowSize(effectiveWindow + TIMELINE_WINDOW_STEP)}
          >
            加载更早 {Math.min(TIMELINE_WINDOW_STEP, hidden)} 条
          </button>
          <span className="timeline-window-hint">
            显示最近 {visible.length} / 共 {total} 条（前段已折叠，真相完整保留）
          </span>
        </div>
      )}
      {/* UI-03：run 分组头——按 run_id 首现顺序插入分隔行（序数取自**全会话**
          遍历，尾窗裁剪后组号不重排）；组与窗口的交集非空才渲染头。
          data-tl-i 仍是 visible 窗口内下标（hover 反查契约不变）。 */}
      {runGroups.map((g) => {
        const from = Math.max(g.start, hidden);
        const to = Math.min(g.start + g.count, total);
        if (from >= to) return null;
        return (
          <Fragment key={g.start}>
            <div
              className="tl-run-header"
              title={g.runId ? `run ${g.runId}` : '会话开场（无 run 归属）'}
            >
              <span className="tl-run-name">{g.runId ? `Run ${g.ordinal}` : '会话'}</span>
              {g.runId && (
                <span className={`run-badge run-badge-${g.status}`}>
                  {RUN_GROUP_STATUS_LABEL[g.status]}
                </span>
              )}
              <span className="tl-run-count num">{g.count} 事件</span>
            </div>
            {Array.from({ length: to - from }, (_, k) => {
              const abs = from + k;
              /* key = 数组绝对下标：稳定性依赖 P0-1 的 append-only 事件契约
               * （events 只追加不重排/删除，见 HANDOFF_PERF_FRONTEND §9 P0-1）。 */
              return (
                <TimelineRow
                  key={abs}
                  index={abs - hidden}
                  event={conversation.events[abs]}
                  onFocusEvent={onFocusEvent}
                  onJumpToStream={onJumpToStream}
                  selected={selectedKey != null && eventKey(conversation.events[abs]) === selectedKey}
                />
              );
            })}
          </Fragment>
        );
      })}
      {tip && (
        <div className="tl-tooltip" role="tooltip" style={{ left: tip.x, top: tip.y }}>
          {tip.lines.map((l, i) => (
            <div key={i} className="tl-tooltip-line">
              {l}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// memo：投影层 events 数组为追加式（既有事件引用稳定），流式期间新 delta 到达时
// 旧行跳过 summarizeEvent 重算——只有新增行参与渲染。
const TimelineRow = memo(function TimelineRow({
  index,
  event,
  onFocusEvent,
  onJumpToStream,
  selected,
}: {
  /** 可见窗口内下标（hover 浮层经 data-tl-i 反查事件）。 */
  index: number;
  event: AgentEvent;
  onFocusEvent: (e: AgentEvent) => void;
  onJumpToStream?: (e: AgentEvent) => void;
  /** #183：是否为当前选中项（`aria-current` 如实上报，不是只加一层颜色）。 */
  selected?: boolean;
}) {
  return (
    <button
      className={`timeline-row${selected ? ' sel' : ''}`}
      data-tl-i={index}
      data-list-key={eventKey(event)}
      aria-current={selected ? 'true' : undefined}
      onClick={() => {
        onFocusEvent(event);
        // PRD §9.2 反向联动：选中行同时定位中间主区（App 层处理 pulse）。
        onJumpToStream?.(event);
      }}
    >
      <span className="tl-seq">{event.seq ?? '·'}</span>
      <span className="tl-type">{event.type}</span>
      <span className="tl-summary">{eventSummary(event)}</span>
    </button>
  );
});

// ── Changes tab：文件 diff 聚合（渲染复用 `DiffBlock`——diff 只有一份渲染器） ──

/** 导出供 SSR 测试直接渲染（同 `TimelineTab` / `ToolEventSections`：`tab` 是内部
 *  状态，从 `StepDetail` 外面进不到这个面）。 */
export function ChangesTab({ tools, sessionId }: { tools: ToolCall[]; sessionId?: string }) {
  const diffs = tools.filter((t) => t.diff);
  if (diffs.length === 0) {
    return <TabEmpty hint="本次会话未产生文件变更。" icon={FileDiff} />;
  }
  return (
    <>
      {diffs.map((t) => (
        <div key={t.tool_call_id} className="detail-section">
          <div className="detail-section-title">
            <FileDiff size={14} /> {t.name}: {String(t.args.path ?? '')}
          </div>
          {/* 这里此前自己内联一份 `.diff-cols`——同一份 before/after 在 Inspector 与
              中心列各有一套渲染，且这套**认不出归档态**（before/after 已被换成
              `use read_artifact(<id>)` marker 摘要时，会把 marker 原文当 diff 正文
              渲染出来，即"显示了一段并不存在的文件内容"）。收敛到 `DiffBlock`
              （#183 AC9 / #186 AC3）后归档占位态与中心列逐字一致。 */}
          <DiffBlock diff={t.diff!} sessionId={sessionId} />
        </div>
      ))}
    </>
  );
}

// ── Terminal tab：bash 调用聚合（命令执行面） ──

function TerminalTab({ tools, onFocusTool, selectedKey }: { tools: ToolCall[]; onFocusTool: (t: ToolCall) => void; selectedKey?: string | null }) {
  // 判定与读取都来自 lib/commandOutput（票面 AC2）：
  // "什么算一次命令"只允许有一处答案——两边各写一份会各自演化。
  const bashes = tools.filter(isCommand);
  if (bashes.length === 0) {
    return <TabEmpty hint="本次会话未执行命令。" icon={TerminalSquare} />;
  }
  return (
    <>
      {bashes.map((t) => {
        const result = commandResult(t);
        const selected = selectedKey != null && toolKey(t) === selectedKey;
        return (
          <button
            key={t.tool_call_id}
            className={`detail-terminal-row${selected ? ' sel' : ''}`}
            data-list-key={toolKey(t)}
            aria-current={selected ? 'true' : undefined}
            onClick={() => onFocusTool(t)}
          >
            <div className="detail-terminal-cmd">
              <span className="bash-prompt">$</span>
              <code>{String(t.args.command ?? '')}</code>
            </div>
            {result?.stdout !== undefined && <pre className="detail-terminal-out">{truncateForDisplay(result.stdout)}</pre>}
            {result?.exit_code !== undefined && (
              <span className={`exit-badge ${result.exit_code === 0 ? 'exit-ok' : 'exit-err'}`}>exit {result.exit_code}</span>
            )}
          </button>
        );
      })}
    </>
  );
}

// ── Artifacts tab：artifact 聚合页（工具挂载 ref，单一投影源——不变量 #22） ──

function ArtifactsTab({ tools, sessionId }: { tools: ToolCall[]; sessionId: string }) {
  // Artifacts only reach this tab through the projection attaching an ArtifactRef
  // to the producing ToolCall (lib/projection.ts ARTIFACT_CREATED case). If an
  // artifact/created event's tool isn't found by the projection, that's a
  // projection concern — not something to paper over here with a second truth
  // path (invariant #22).
  const artifacts = tools.filter((t) => t.artifact);
  if (artifacts.length === 0) {
    return <TabEmpty hint="本次会话未产生 Artifact。" icon={Package} />;
  }
  return (
    <>
      {artifacts.map((t) => (
        <div key={t.tool_call_id} className="detail-section">
          <div className="detail-section-title">
            <FileCheck2 size={14} /> {t.name}
          </div>
          <div className="detail-row">
            <span className="detail-key">ID</span>
            <code className="detail-val detail-val-mono">{t.artifact!.artifact_id.slice(0, 16)}</code>
          </div>
          {/* 元数据可空（AC5）：缺了就说"未知"，不拿默认值冒充。
              真后端里 size/mime_type 由 store 决定是否持久化（MinIO 不持久化
              source_tool），编一个 `0 B` / `application/octet-stream` 是在替它撒谎。 */}
          <div className="detail-row">
            <span className="detail-key">大小</span>
            <span className="detail-val">
              {t.artifact!.size === null ? '未知' : formatBytes(t.artifact!.size)}
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-key">类型</span>
            <span className="detail-val detail-val-mono">
              {t.artifact!.mime_type ?? '未知'}
            </span>
          </div>
          {/* 内容按需读取（#186 AC1）——地址是 #185 的只读端点，会话归属由 URL 的
              session_id 决定（artifact_id 是内容哈希，跨会话可重名）。 */}
          <ArtifactViewer
            sessionId={sessionId}
            artifactId={t.artifact!.artifact_id}
            label="查看内容"
          />
        </div>
      ))}
    </>
  );
}

// ── 事件级 Inspector：Overview / Input / Output / Raw 四段（PRD §8.4） ──

/** 事件级 Inspector 主体——只接收已收窄的非 Run 焦点。 */
// 事件级 Inspector 只接受 tool/event——child（委派钻取）有专用面板，
// 永远不会到达这里（Exclude 与主组件的早退分支守卫保持同一形状）。
type EventFocus = Exclude<InspectorFocus, { kind: 'run' } | { kind: 'child' }>;

/** 事件级四段 tab 状态：Overview（元信息）/ Input（data）/ Output（同 data，语义入口）/
 *  Raw（完整事件）。Input 与 Output 对普通事件都是 event.data——Output 作为默认段
 *  保留"看结果优先"的旧习惯；Raw 是完整事件 JSON。 */
type EventIoTab = 'overview' | 'input' | 'output' | 'raw';

function EventInspector({ focus }: { focus: EventFocus }) {
  // hooks 规则：useState 必须在条件 return 之前（tool focus 分支也保持 hook 顺序稳定）
  const [tab, setTab] = useState<EventIoTab>('overview');
  if (focus.kind === 'tool') {
    return <ToolEventSections tool={focus.tool} />;
  }
  const event = focus.event;
  const dataJson = JSON.stringify(event.data, null, 2);
  const rawJson = JSON.stringify(event, null, 2);

  const tabs: readonly { id: EventIoTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'input', label: 'Input' },
    { id: 'output', label: 'Output' },
    { id: 'raw', label: 'Raw' },
  ];

  return (
    <>
      <div className="io-tabs" role="tablist" aria-label="事件详情段">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`io-tab${tab === t.id ? ' sel' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="detail-section">
          <div className="detail-section-title">
            <Clock size={14} /> {event.type}
          </div>
          {event.seq !== null && (
            <div className="detail-row">
              <span className="detail-key">seq</span>
              <span className="detail-val detail-val-mono num">{event.seq}</span>
            </div>
          )}
          {event.time && (
            <div className="detail-row">
              <span className="detail-key">time</span>
              <span className="detail-val detail-val-mono">{event.time}</span>
            </div>
          )}
          {/* 宽松判空（语义见 formatEventTooltip 文档）：缺失/null 都不渲染 step 行。 */}
          {event.step_id != null && (
            <div className="detail-row">
              <span className="detail-key">step</span>
              <span className="detail-val num">{event.step_id}</span>
            </div>
          )}
          {event.run_id && (
            <div className="detail-row">
              <span className="detail-key">run</span>
              <span className="detail-val detail-val-mono">{event.run_id.slice(0, 16)}</span>
            </div>
          )}
          {event.event_id && (
            <div className="detail-row">
              <span className="detail-key">event_id</span>
              <span className="detail-val detail-val-mono">{event.event_id.slice(0, 16)}</span>
            </div>
          )}
        </div>
      )}
      {tab === 'input' && (
        <div className="detail-section">
          <div className="detail-section-title">Input (data)</div>
          <div className="detail-code-wrap">
            <CopyButton text={dataJson} label="复制 JSON" />
            <div className="detail-json">
              <JsonTree value={event.data} />
            </div>
          </div>
        </div>
      )}
      {tab === 'output' && (
        <div className="detail-section">
          <div className="detail-section-title">Output (data)</div>
          <div className="detail-code-wrap">
            <CopyButton text={dataJson} label="复制 JSON" />
            <div className="detail-json">
              <JsonTree value={event.data} />
            </div>
          </div>
        </div>
      )}
      {tab === 'raw' && (
        <div className="detail-section">
          <div className="detail-section-title">Raw</div>
          <div className="detail-code-wrap">
            <CopyButton text={rawJson} label="复制 Raw" />
            <div className="detail-json">
              <JsonTree value={event} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** 工具事件级视图：Overview / Input(args) / Output(result) / Raw(raw_call/raw_result)
 *  四段标签条（PRD §8.4 统一）；默认 Output（运行中的工具回退 Overview）。 */
type IoTab = 'overview' | 'input' | 'output' | 'raw';

export function ToolEventSections({ tool }: { tool: ToolCall }) {
  const argsJson = JSON.stringify(tool.args, null, 2);
  const outputText = stringifyForDisplay(tool.result);
  const resultIsObject = typeof tool.result === 'object' && tool.result !== null;
  const hasOutput = tool.result !== undefined;
  const hasRaw = Boolean(tool.raw_call || tool.raw_result);
  /* #183 AC9（同一数据不得两份独立渲染）：命令输出在 Inspector 里也必须走中心列
     那一个渲染器（`ToolOutputStream`，ToolCard 与「输出」面共用）。此前这里自己
     `<pre>{truncateForDisplay(...)}</pre>` 一份——同一份 stdout 两套渲染，channels
     保真、尾窗预算、换行切换、复制口径全都会各自演化。
     `showCaret=false`（同 #190 AC5 的理由）：Inspector 是复盘面，不是对话流；
     一个闪动光标在这里读起来像"第二条正在跑的流"。 */
  /* 命令的**取数口径**也走那唯一一份（`lib/commandOutput.ts` 的终态优先级：
     有 result 就以 result 为准，没有才回落流式块）。此前这里直接拿 `tool.output`
     ——只要留过流式块就无视已到达的 result，于是同一个 bash 调用在 Inspector 里显示
     分块（大输出还可能被投影合并/重排过）、在中心列与「输出」面显示权威终态文本。
     **只在确有流式块时才需要这次纠正**：没有块的工具维持原有的"结果树"呈现——那棵树
     还带着 `exit_code` / `cancelled` 等字段，而 `ToolOutputStream` 只呈现 stdout/stderr
     文本（把它套到无块的工具上，会把 exit code 从 Inspector 里弄丢）。 */
  const hasChunks = (tool.output?.length ?? 0) > 0;
  const commandChunks = isCommand(tool) && hasChunks
    ? (commandOutputs([tool])[0]?.chunks ?? [])
    : null;
  const outputChunks = commandChunks ?? (tool.output ?? []);
  const [wantTab, setTab] = useState<IoTab>(hasOutput ? 'output' : 'overview');

  const tabs: readonly { id: IoTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'input', label: 'Input' },
    ...(hasOutput ? [{ id: 'output', label: 'Output' } as const] : []),
    ...(hasRaw ? [{ id: 'raw', label: 'Raw' } as const] : []),
  ];
  /* 渲染期收窄到仍然存在的段（同 #182 `resolveActiveTab` 的口径）：选中项在清单里
     移动时这个组件实例**不重建**（AC1），于是 `useState` 的初始值会留在上一个工具
     上——从"有输出"的工具移到"还没结果"的工具，旧 tab 指向一个不存在的段，
     面板就是空白（"详情实时跟随"当场破功）。 */
  const tab: IoTab = tabs.some((t) => t.id === wantTab)
    ? wantTab
    : (hasOutput ? 'output' : 'overview');

  return (
    <div className="detail-section">
      <div className="detail-section-title">
        <TerminalSquare size={14} /> {tool.name}
        <span className={`tool-status-dot tool-status-dot-${tool.status}`} />
        {tool.started_at && tool.completed_at && (
          <span className="io-duration">{formatDuration(tool.started_at, tool.completed_at)}</span>
        )}
      </div>

      <div className="io-tabs" role="tablist" aria-label="工具输入输出">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`io-tab${tab === t.id ? ' sel' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'overview' && (
        <div className="detail-overview">
          <div className="detail-row">
            <span className="detail-key">tool</span>
            <span className="detail-val detail-val-mono">{tool.name}</span>
          </div>
          <div className="detail-row">
            <span className="detail-key">tool_call_id</span>
            <span className="detail-val detail-val-mono">{tool.tool_call_id.slice(0, 16)}</span>
          </div>
          <div className="detail-row">
            <span className="detail-key">status</span>
            <span className="detail-val detail-val-tag">{tool.status}</span>
          </div>
          {tool.started_at && (
            <div className="detail-row">
              <span className="detail-key">started</span>
              <span className="detail-val detail-val-mono">{tool.started_at}</span>
            </div>
          )}
          {tool.started_at && tool.completed_at && (
            <div className="detail-row">
              <span className="detail-key">耗时</span>
              <span className="detail-val num">{formatDuration(tool.started_at, tool.completed_at)}</span>
            </div>
          )}
          {tool.artifact && (
            <div className="detail-row">
              <span className="detail-key">artifact</span>
              <span className="detail-val detail-val-mono">{tool.artifact.artifact_id.slice(0, 16)}</span>
            </div>
          )}
        </div>
      )}
      {tab === 'input' && (
        <div className="detail-code-wrap">
          <CopyButton text={argsJson} label="复制 JSON" />
          <div className="detail-json">
            <JsonTree value={tool.args} />
          </div>
        </div>
      )}
      {tab === 'output' && hasOutput && outputChunks.length > 0 && (
        // 有输出块：中心列同一个渲染器（自带标签条/复制/换行与尾窗预算），
        // 不在外面再套一层 CopyButton——那会出现两个"复制"按钮说同一件事。
        <ToolOutputStream
          chunks={outputChunks}
          streaming={tool.status === 'running'}
          showCaret={false}
        />
      )}
      {tab === 'output' && hasOutput && outputChunks.length === 0 && (
        <div className="detail-code-wrap">
          <CopyButton text={outputText} label="复制输出" />
          {resultIsObject ? (
            <div className="detail-json">
              <JsonTree value={tool.result} />
            </div>
          ) : (
            <pre className="detail-code">{truncateForDisplay(outputText)}</pre>
          )}
        </div>
      )}
      {tab === 'raw' && hasRaw && (
        <div className="io-raw-panes">
          {tool.raw_call && (
            <div className="detail-code-wrap">
              <div className="io-raw-label">tool/call 原始事件</div>
              <CopyButton text={JSON.stringify(tool.raw_call, null, 2)} label="复制 Raw" />
              <div className="detail-json">
                <JsonTree value={tool.raw_call} />
              </div>
            </div>
          )}
          {tool.raw_result && (
            <div className="detail-code-wrap">
              <div className="io-raw-label">tool/result 原始事件</div>
              <CopyButton text={JSON.stringify(tool.raw_result, null, 2)} label="复制 Raw" />
              <div className="detail-json">
                <JsonTree value={tool.raw_result} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Tab 空状态 —— 对应 tab 的 icon + 一句话。
 *  参考 Linear/Vercel dashboard 空状态：轻量图标（非灰黄 emoji）+ 克制文案，
 *  让"没有数据"读起来是预期而非故障。icon 与 tab 条同一图标，视觉呼应。 */
function TabEmpty({ hint, icon: Icon }: { hint: string; icon: typeof ListTree }) {
  return (
    <div className="detail-tab-empty">
      <Icon size={24} className="detail-empty-icon" aria-hidden="true" />
      <div className="detail-empty-hint">{hint}</div>
    </div>
  );
}

function DetailEmpty() {
  return (
    <div className="detail-empty">
      <div className="detail-empty-title">未选择会话</div>
      <div className="detail-empty-hint">从左侧选择，或开始新任务。</div>
    </div>
  );
}

/** Format byte count as human-readable (KB / MB). */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Phase 13 委派钻取：child 会话视图（v2 PRD §10.5）──

/** ChildSessionView — Inspector 内原位展开 child 会话（`GET /api/sessions/{id}/events`
 *  拉取 → projectHistory 同一投影管线，不变量 #22）。只读呈现：Overview 摘要
 *  （ChatTab 复用，工具行静态化）+ child 事件尾窗——child 的完整交互仍在
 *  「打开子会话」主窗管线，这里不做第二套可操作 Inspector。 */
function ChildSessionView({ childSessionId }: { childSessionId: string }) {
  const { conversation, error } = useChildConversation(childSessionId);
  if (error) {
    return <div className="child-view-status">子会话加载失败：{error}</div>;
  }
  if (!conversation) {
    return <div className="child-view-status">正在加载子会话…</div>;
  }
  return (
    <>
      <ChatTab conversation={conversation} tools={allTools(conversation)} />
      <ChildTimeline events={conversation.events} />
    </>
  );
}

/** child 事件只读尾窗（有界 DOM，同 Timeline 尾窗纪律）：verbatim type + 单行
 *  语义摘要。child 会话通常不长，但模型/delta 类事件可能多——tail 200 封顶。 */
const CHILD_TIMELINE_WINDOW = 200;

function ChildTimeline({ events }: { events: AgentEvent[] }) {
  const total = events.length;
  const tail = events.slice(-CHILD_TIMELINE_WINDOW);
  return (
    <div className="detail-section">
      <div className="detail-section-title">
        <ListTree size={14} /> CHILD TIMELINE
      </div>
      {total > CHILD_TIMELINE_WINDOW && (
        <div className="detail-row detail-row-warn">显示最近 {CHILD_TIMELINE_WINDOW} 条 / 共 {total} 条</div>
      )}
      {tail.map((e, i) => (
        <div key={e.event_id ?? `${e.seq ?? 'n'}-${i}`} className="detail-row child-ev-row">
          <span className="detail-key mono">{e.type}</span>
          <span className="detail-val">{summarizeEvent(e) || '—'}</span>
        </div>
      ))}
    </div>
  );
}
