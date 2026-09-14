/** SessionList — Session Rail of the single-frame shell（Phase 2 Brief §10；WS-5 #155 改版）。
 *
 * 两层结构：
 *   项目（注册表顺序）→ 会话（**账本手工序**，用户拖出来的顺序，不按活动时间重排）
 *   未分组 → 不属于任何项目的会话（保持后端给的活动时间序）
 *
 *  三条不变量：
 *  1. **不丢行**：分组由 `lib/projects.ts` 的 `buildRailModel` 派生，未出现在任何账本
 *     里的会话（含 workspace 引用已失效项目的孤儿行）一律落进未分组区。
 *  2. **不改真相**：顺序与归属都来自后端账本（`GET /api/projects` 的 `session_ids`）；
 *     `GET /api/sessions` 的 `workspace` 只用来解释"自称属于某项目、但该项目不在
 *     当前列表里"的孤儿行（`staleProject`），不参与判定成员资格。本组件不维护影子
 *     成员名单，每次写操作后重新拉取（`ProjectActions` 内部 refresh + `onSessionsChanged`）。
 *  3. **失败要说话**：项目写操作失败时把后端 detail 原样贴在侧栏顶部（`rail-error`），
 *     而不是静默或只留一个禁用的按钮。
 *
 *  时间分组（Running/Today/Yesterday/Older）在 WS-5 后**只保留 Running 的活体语义**：
 *  行上的绿点 + 呼吸仍表示"该会话正在流式"，但不再用时间桶切分列表——侧栏现在有
 *  真实的层级要表达，两套切分叠在一起会让同一行出现在两个不同的分类逻辑下。
 */

import { memo, useMemo, useState } from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import {
  Archive,
  ArrowDown,
  ArrowUp,
  ChevronRight,
  Ellipsis,
  Folder,
  FolderOpen,
  FolderPlus,
  Plus,
  TriangleAlert,
} from 'lucide-react';
import type { Project, SessionDeleted, SessionSummary } from '../types';
import { formatRelativeTime } from '../lib/format';
import { useTickingNow } from '../hooks/useTickingNow';
import { buildRailModel, dropAnchor, moveAnchor } from '../lib/projects';
import { readShowArchived, writeShowArchived } from '../lib/railArchive';
import type { UngroupedRow } from '../lib/projects';
import { describeProjectError } from '../lib/api';
import type { CatalogEntry } from '../lib/api';
import type { ProjectActions } from '../hooks/useProjects';
import {
  AttachToProjectDialog,
  CreateProjectDialog,
  DeleteProjectDialog,
  InlineRename,
} from './ProjectDialogs';
import { DeleteSessionDialog, type DeleteSessionTarget } from './DeleteSessionDialog';
import { StartTaskInProjectDialog } from './StartTaskInProjectDialog';

interface Props {
  sessions: SessionSummary[];
  projects: Project[];
  selectedId: string | null;
  /** The session currently receiving a live stream (live dot). */
  liveSessionId: string | null;
  /** 行标题缓存（Session Model E 轮）：键为 session_id，值为首条 user/message 投影。
   *  无缓存的会话回退到短 ID——不伪造标题。 */
  titlesById: Record<string, string>;
  onSelect: (id: string) => void;
  onNew: () => void;
  projectActions: ProjectActions;
  /** 会话语义发生变化后刷新列表（attach/detach/软删除都会改各行的 `workspace`）。 */
  onSessionsChanged: () => void;
  /** `GET /api/projects` 失败原因（有值时项目区**不隐藏**，只是多一条可重试的错误条：
   *  隐藏项目会把所有会话误显示成未分组，比显示一条错误糟）。 */
  projectsError: string | null;
  onRetryProjects: () => void;
  /** 「在此项目中新建任务」（WS-6 / #169）：以项目目录为 cwd 起一个会话。
   *  resolve `null` = 已开始流式；否则为**给用户看的原因**（留在确认面里）。 */
  onStartTask: (
    project: Project,
    task: string,
    permissionMode: string | null,
  ) => Promise<string | null>;
  /** 权限档清单（GET /api/permission-modes）——确认面三选一的数据源。 */
  permissionModes: CatalogEntry[];
  /** 硬删一个会话（#172 / ADR-0029，**不可恢复**）：失败原因抛给确认面显示，
   *  成功后的状态收敛（清当前视图 / 重拉列表）由 useSession.removeSession 负责
   *  ——本组件不碰会话状态，只把用户点的那一行交出去。 */
  onDeleteSession: (sessionId: string) => Promise<SessionDeleted>;
  /** 归档 / 取消归档一个会话（#171，**可逆**）：resolve `null` = 成功（列表已刷新）；
   *  否则是**给用户看的原因**（后端 detail 原文）——就地显示在本栏顶部，不弹全局横幅
   *  （AC9）。可逆动作因此不需要确认面（AC11）：再点一次「取消归档」就是撤销。 */
  onSetArchived: (sessionId: string, archived: boolean) => Promise<string | null>;
}

// memo：流式期间本组件 props（sessions/projects/selectedId/titlesById/回调）全部引用
// 稳定，跳过每个 delta 的会话栏重渲染；相对时间刷新由内部 useTickingNow 独立驱动。
export const SessionList = memo(function SessionList({
  sessions,
  projects,
  selectedId,
  liveSessionId,
  titlesById,
  onSelect,
  onNew,
  projectActions,
  onSessionsChanged,
  projectsError,
  onRetryProjects,
  onStartTask,
  permissionModes,
  onDeleteSession,
  onSetArchived,
}: Props) {
  const now = useTickingNow();
  /** 「显示已归档」开关（#171 AC10）：**视图状态**，持久化到 localStorage 但**不重拉
   *  列表**——载荷本来就是完整一份（见 `lib/api.ts::listSessions` 的分层说明），
   *  开关只改投影，所以切换是瞬时的、不闪屏。 */
  const [showArchived, setShowArchived] = useState(readShowArchived);
  // 「项目有哪些会话」= 账本投影，不另存一份（不变量 #22）。
  const model = useMemo(
    () => buildRailModel(sessions, projects, { includeArchived: showArchived }),
    [sessions, projects, showArchived],
  );
  const visibleCount =
    model.groups.reduce((n, g) => n + g.sessions.length, 0) + model.ungrouped.length;
  /** 归档条数取**载荷的真值**，不拿 `sessions.length - visibleCount` 推——两者在
   *  "项目账本占用了同一 id"等边界下会不等（见 `buildRailModel` 的 claimed 占用表），
   *  而这句话是在向用户陈述事实。 */
  const archivedCount = sessions.filter((s) => s.archived).length;

  // 折叠状态是**视图**状态（不持久化，与 Inspector 折叠同一立场）。
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [createOpen, setCreateOpen] = useState(false);
  const [deleting, setDeleting] = useState<Project | null>(null);
  /** 待硬删的会话（null = 确认面关闭）——与项目软删分开一个状态：两者的后果与
   *  文案都不同（一个只摘注册记录，一个不可恢复），共用会让"点错了哪一类"没法表达。 */
  const [deletingSession, setDeletingSession] = useState<DeleteSessionTarget | null>(null);
  const [attachFor, setAttachFor] = useState<string | null>(null);
  /** 「在此项目中新建任务」的目标项目（null = 确认面关闭）。 */
  const [startTaskFor, setStartTaskFor] = useState<Project | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [opError, setOpError] = useState<string | null>(null);
  // 拖拽重排（HTML5 DnD）：记**来源项目**而不只是被拖的会话 id——跨项目拖动
  // 不是重排（那是 attach，有 cwd 校验），落点提示只能在来源项目内亮。
  const [drag, setDrag] = useState<{ projectId: string; sessionId: string } | null>(null);
  const [dropTarget, setDropTarget] = useState<{ projectId: string; before: string | null } | null>(
    null,
  );

  /** 选中会话所在的项目永远保持展开：折叠一个"里面有当前会话"的项目等于把用户
   *  正在看的行藏起来——界面不该出现这种自相矛盾的状态。 */
  const isExpanded = (project: Project) =>
    !collapsed.has(project.id) || project.session_ids.includes(selectedId ?? '');

  const toggle = (id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const ledgerOf = (projectId: string) =>
    projects.find((p) => p.id === projectId)?.session_ids ?? [];

  /** 项目写操作的统一出口：失败把后端原因贴到侧栏顶部，绝不静默。
   *  （对话框自己的提交路径不走这里——它们的错误留在对话框里更贴近操作。） */
  const runOp = async (label: string, run: () => Promise<unknown>) => {
    try {
      await run();
      setOpError(null);
      onSessionsChanged();
    } catch (e) {
      setOpError(describeProjectError(e, label));
    }
  };

  const handleMove = (projectId: string, sessionId: string, dir: 'up' | 'down') => {
    const anchor = moveAnchor(ledgerOf(projectId), sessionId, dir);
    if (!anchor) return; // 边界（按钮已禁用，这里是双保险）
    void runOp('调整顺序失败', () => projectActions.reorder(projectId, sessionId, anchor.before));
  };

  const resetDrag = () => {
    setDrag(null);
    setDropTarget(null);
  };

  /** 拖放落定：`before` = 放到这一行前面，null = 放到该项目队尾。 */
  const handleDrop = (projectId: string, before: string | null) => {
    const dragged = drag;
    resetDrag();
    if (!dragged) return;
    // 只支持**项目内**拖动重排：未分组的行拖到项目上等于 attach，而 attach 有
    // cwd 校验（可能 409）——那条路径走"加入项目…"，这里不猜。跨项目同理。
    if (dragged.projectId !== projectId) return;
    const ids = ledgerOf(projectId);
    if (!ids.includes(dragged.sessionId)) return;
    const anchor = dropAnchor(ids, dragged.sessionId, before);
    if (!anchor) return;
    void runOp('调整顺序失败', () =>
      projectActions.reorder(projectId, dragged.sessionId, anchor.before),
    );
  };

  /** 归档 / 取消归档一行：失败原因就地显示（`opError` 那条栏），成功后沿用
   *  `onSetArchived` 里的列表刷新——本组件不碰会话真相，只把用户的意图交出去
   *  （与 `onDeleteSession` 同一分工）。 */
  const handleSetArchived = async (sessionId: string, archived: boolean) => {
    setOpError(await onSetArchived(sessionId, archived));
  };

  const toggleArchived = () => {
    setShowArchived((prev) => {
      const next = !prev;
      writeShowArchived(next);
      return next;
    });
  };

  const showEmpty = sessions.length === 0 && projects.length === 0;

  return (
    <aside className="session-rail">
      <div className="session-list-header">
        <span className="panel-label">会话</span>
        {/* UI-05：真空态下两个 icon 按钮切换为**带文字**的按钮——空态文案引导
            「右上角的『新建项目』」时，用户必须能在右上角看到一个叫这个名字的东西
            （识别而非回忆：全 Rail icon-only 时该文案指涉的文字实体不存在）。 */}
        {showEmpty ? (
          <div className="session-list-actions rail-empty-actions">
            <button className="rail-empty-btn-primary" onClick={() => setCreateOpen(true)}>
              新建项目
            </button>
            <button className="rail-empty-btn-ghost" onClick={onNew}>
              新会话
            </button>
          </div>
        ) : (
          <div className="session-list-actions">
            {/* #171：「显示已归档」——`aria-pressed` 是开关的语义（不是两个动作按钮），
                按下态给 accent 色（CSS）。icon-only 与本栏其余动作一致。 */}
            <button
              className={`icon-btn rail-archived-toggle${showArchived ? ' on' : ''}`}
              aria-pressed={showArchived}
              onClick={toggleArchived}
              aria-label="显示已归档会话"
              title="显示已归档会话（归档只改列表可见性，不删任何东西）"
            >
              <Archive size={14} />
            </button>
            <button
              className="icon-btn"
              onClick={() => setCreateOpen(true)}
              aria-label="新建项目"
              title="新建项目：注册一个已存在的目录"
            >
              <FolderPlus size={14} />
            </button>
            <button className="icon-btn new-session-btn" onClick={onNew} aria-label="新建会话">
              <Plus size={14} />
            </button>
          </div>
        )}
      </div>

      {opError ? (
        <div className="rail-error" role="alert">
          <span className="rail-error-text" title={opError}>
            {opError}
          </span>
          <button
            className="rail-error-close"
            onClick={() => setOpError(null)}
            aria-label="关闭错误提示"
          >
            ×
          </button>
        </div>
      ) : projectsError ? (
        <div className="rail-error" role="alert">
          <span className="rail-error-text" title={projectsError}>
            项目列表加载失败：{projectsError}
          </span>
          <button className="rail-error-retry" onClick={onRetryProjects}>
            重试
          </button>
        </div>
      ) : null}

      <div className="session-items">
        {showEmpty && <div className="empty-hint">暂无会话，提交任务即可开始。</div>}
        {/* 不是真空态，但开关把**每一行**都收起来了——必须说清楚，否则侧栏看起来像坏了
            （且给出去处：顶部那个开关）。
            两个守卫都不能省：
            - `sessions.length > 0`：项目已注册但还没有任何会话时 `visibleCount` 同样是 0，
              不加这条会渲染出「0 条都已归档」——把"没有会话"说成"都归档了"（不变量 #21）。
            - `!showArchived`：开关已经开着还提示"点开关查看"，指向一个已经按下的按钮。
            数字取真正归档的条数而不是 `sessions.length`：后者把未归档但也看不见的行
            （理论上不存在的状态）也算进去，是在替数据说话。 */}
        {!showEmpty && sessions.length > 0 && !showArchived && visibleCount === 0 && (
          <div className="empty-hint">
            没有可见的会话：{archivedCount} 条都已归档。点侧栏顶部的
            <Archive size={12} aria-hidden="true" /> 图标查看。
          </div>
        )}

        <section className="rail-section" aria-label="项目">
          {projects.length > 0 ? (
            <>
              <div className="rail-section-label">项目</div>
              {model.groups.map(({ project, sessions: rows, missing }) => {
                const expanded = isExpanded(project);
                const listId = `rail-project-${project.id}`;
                const renaming = renamingId === project.id;
                // 落点提示只在本项目内亮：跨项目拖动不是重排（见 handleDrop）。
                const dropEnabled = drag?.projectId === project.id;
                return (
                  <section className="rail-project" key={project.id}>
                    <div className="rail-project-head">
                      {renaming ? (
                        // 重命名时不再渲染 toggle 按钮：input 不能嵌在 button 里
                        // （HTML 不允许交互内容嵌套），所以整块换成同布局的 div。
                        <div className="rail-project-toggle rail-project-toggle-static">
                          <ChevronRight size={12} className="rail-project-chevron open" aria-hidden="true" />
                          <FolderOpen size={13} className="rail-project-icon" aria-hidden="true" />
                          <InlineRename
                            initial={project.title}
                            onCommit={(title) => {
                              setRenamingId(null);
                              if (title && title !== project.title) {
                                void runOp('重命名失败', () =>
                                  projectActions.rename(project.id, title),
                                );
                              }
                            }}
                            onCancel={() => setRenamingId(null)}
                          />
                        </div>
                      ) : (
                        <button
                          className="rail-project-toggle"
                          onClick={() => toggle(project.id)}
                          aria-expanded={expanded}
                          aria-controls={expanded ? listId : undefined}
                          // 窄屏（≤820px）标题与计数被 CSS 收起，而 display:none 会把
                          // 它们从可访问性树里摘掉——不补 aria-label 这个按钮在窄屏
                          // 就是无名控件（#179）。
                          aria-label={`${project.title}：${expanded ? '收起项目' : `展开项目（${rows.length} 个会话）`}`}
                          title={expanded ? '收起项目' : `展开项目（${rows.length} 个会话）`}
                        >
                          <ChevronRight
                            size={12}
                            className={`rail-project-chevron${expanded ? ' open' : ''}`}
                            aria-hidden="true"
                          />
                          {expanded ? (
                            <FolderOpen size={13} className="rail-project-icon" aria-hidden="true" />
                          ) : (
                            <Folder size={13} className="rail-project-icon" aria-hidden="true" />
                          )}
                          <span className="rail-project-title" title={project.path}>
                            {project.title}
                          </span>
                          {project.status === 'missing-dir' && (
                            <TriangleAlert
                              size={12}
                              className="rail-project-warn"
                              role="img"
                              aria-label="目录当前不存在"
                            />
                          )}
                          <span className="rail-project-count num">{rows.length}</span>
                        </button>
                      )}
                      <DropdownMenu.Root>
                        <DropdownMenu.Trigger asChild>
                          <button
                            className="icon-btn rail-menu-btn"
                            aria-label={`项目「${project.title}」操作`}
                          >
                            <Ellipsis size={14} />
                          </button>
                        </DropdownMenu.Trigger>
                        <DropdownMenu.Portal>
                          <DropdownMenu.Content className="rail-menu" align="end" sideOffset={4}>
                            {/* 第一项：本票的主入口（AC9）。放在最前是因为它是这个项目
                                行最常用、也最不容易误伤的操作——重命名/删除在它下面。 */}
                            <DropdownMenu.Item
                              className="rail-menu-item"
                              onSelect={() => setStartTaskFor(project)}
                            >
                              在此项目中新建任务
                            </DropdownMenu.Item>
                            <DropdownMenu.Separator className="rail-menu-sep" />
                            <DropdownMenu.Item
                              className="rail-menu-item"
                              onSelect={() => setRenamingId(project.id)}
                            >
                              重命名项目
                            </DropdownMenu.Item>
                            <DropdownMenu.Item
                              className="rail-menu-item rail-menu-item-danger"
                              onSelect={() => setDeleting(project)}
                            >
                              删除项目…
                            </DropdownMenu.Item>
                          </DropdownMenu.Content>
                        </DropdownMenu.Portal>
                      </DropdownMenu.Root>
                    </div>

                    {expanded && (
                      <div className="rail-project-rows" id={listId}>
                        {rows.length === 0 && (
                          // 空项目不再引导用户"去未分组找 cwd 匹配的会话"——WS-6 之后
                          // 在项目里直接开任务就是最短路径，旧文案的语义已被本入口取代
                          // （AC10：占位区替换为该入口按钮）。
                          <div className="rail-project-empty">
                            这个项目还没有会话。
                            <button
                              className="rail-empty-action"
                              onClick={() => setStartTaskFor(project)}
                            >
                              在此项目中新建任务 →
                            </button>
                          </div>
                        )}
                        {rows.map((s) => (
                          <SessionRow
                            key={s.session_id}
                            session={s}
                            title={titlesById[s.session_id] ?? ''}
                            selected={selectedId === s.session_id}
                            live={liveSessionId === s.session_id}
                            now={now}
                            projectId={project.id}
                            ledger={project.session_ids}
                            dragging={drag?.sessionId === s.session_id}
                            dropEnabled={dropEnabled}
                            dropBefore={
                              dropTarget?.projectId === project.id &&
                              dropTarget.before === s.session_id
                            }
                            onSelect={onSelect}
                            onMove={handleMove}
                            onDetach={(sessionId) =>
                              void runOp('移出项目失败', () =>
                                projectActions.detach(project.id, sessionId),
                              )
                            }
                            onAttachPick={setAttachFor}
                            onOpenCreate={() => setCreateOpen(true)}
                            onDragStartRow={(sessionId) =>
                              setDrag({ projectId: project.id, sessionId })
                            }
                            onDragEndRow={resetDrag}
                            onDragOverRow={(before) =>
                              setDropTarget({ projectId: project.id, before })
                            }
                            onDropRow={(before) => handleDrop(project.id, before)}
                            onDelete={setDeletingSession}
                            onSetArchived={(sessionId, archived) =>
                              void handleSetArchived(sessionId, archived)
                            }
                          />
                        ))}
                        {dropEnabled && rows.length > 0 && (
                          <div
                            className={`rail-drop-tail${
                              dropTarget?.projectId === project.id && dropTarget.before === null
                                ? ' active'
                                : ''
                            }`}
                            onDragOver={(e) => {
                              e.preventDefault();
                              e.dataTransfer.dropEffect = 'move';
                              setDropTarget({ projectId: project.id, before: null });
                            }}
                            onDrop={(e) => {
                              e.preventDefault();
                              handleDrop(project.id, null);
                            }}
                          >
                            放到最后
                          </div>
                        )}
                        {missing > 0 && (
                          <div
                            className="rail-project-missing"
                            title="账本里有这些会话 id，但会话日志不存在（已被删除或不属于本机）"
                          >
                            {missing} 条会话日志缺失
                          </div>
                        )}
                      </div>
                    )}
                  </section>
                );
              })}
            </>
          ) : (
            // 「还没有项目」在项目区为空时显示（UI-05 的空态文案 + 行动链接）。
            // projectsError 已单独兜住「列表请求失败」的情形（上方错误条），
            // 这里不再需要第二个条件——此前挂的 `!showEmpty` 恰好把真·空态
            // （sessions 与 projects 都为 0）下的文案整段吞掉，与文字按钮指涉
            // 自相矛盾，正是本票要消灭的断点。
            !projectsError && (
              <div className="rail-project-empty rail-project-empty-first">
                还没有项目。注册一个已存在的目录，同目录的会话就会归到一起。
                <button className="rail-empty-action" onClick={() => setCreateOpen(true)}>
                  注册项目目录 →
                </button>
              </div>
            )
          )}
        </section>

        <section className="rail-section" aria-label="未分组">
          <div className="rail-section-label">
            未分组
            <span className="rail-section-count num">{model.ungrouped.length}</span>
          </div>
          {model.ungrouped.length === 0 && projects.length > 0 && (
            <div className="rail-project-empty">所有会话都已归入项目。</div>
          )}
          <div>
            {model.ungrouped.map((s) => (
              <SessionRow
                key={s.session_id}
                session={s}
                title={titlesById[s.session_id] ?? ''}
                selected={selectedId === s.session_id}
                live={liveSessionId === s.session_id}
                now={now}
                projectId={null}
                ledger={[]}
                dragging={false}
                dropEnabled={false}
                dropBefore={false}
                onSelect={onSelect}
                onMove={handleMove}
                onDetach={() => undefined}
                onAttachPick={setAttachFor}
                onOpenCreate={() => setCreateOpen(true)}
                onDragStartRow={() => undefined}
                onDragEndRow={resetDrag}
                onDragOverRow={() => undefined}
                onDropRow={() => undefined}
                onDelete={setDeletingSession}
                onSetArchived={(sessionId, archived) =>
                  void handleSetArchived(sessionId, archived)
                }
              />
            ))}
          </div>
        </section>
      </div>

      <CreateProjectDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        existing={projects}
        onCreate={async (path, title) => {
          const created = await projectActions.create(path, title);
          onSessionsChanged();
          return created;
        }}
      />
      <DeleteProjectDialog
        project={deleting}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        onConfirm={async (projectId) => {
          const result = await projectActions.remove(projectId);
          onSessionsChanged();
          return result;
        }}
      />
      <DeleteSessionDialog
        target={deletingSession}
        onOpenChange={(open) => {
          if (!open) setDeletingSession(null);
        }}
        onConfirm={onDeleteSession}
      />
      <AttachToProjectDialog
        sessionId={attachFor}
        projects={projects}
        onOpenChange={(open) => {
          if (!open) setAttachFor(null);
        }}
        onPick={async (projectId, sessionId) => {
          await projectActions.attach(projectId, sessionId);
          onSessionsChanged();
        }}
      />
      <StartTaskInProjectDialog
        project={startTaskFor}
        permissionModes={permissionModes}
        onOpenChange={(open) => {
          if (!open) setStartTaskFor(null);
        }}
        onStart={onStartTask}
      />
    </aside>
  );
});

interface RowProps {
  session: UngroupedRow;
  title: string;
  selected: boolean;
  live: boolean;
  now: number;
  /** 所在项目 id；null = 未分组。 */
  projectId: string | null;
  /** 所在项目账本（判边界：首条不能上移、末条不能下移）；未分组传空数组。 */
  ledger: readonly string[];
  dragging: boolean;
  /** 本行是否接受拖放（= 拖拽来源就在本项目）。跨项目拖动不是重排，不接受落点。 */
  dropEnabled: boolean;
  dropBefore: boolean;
  onSelect: (id: string) => void;
  onMove: (projectId: string, sessionId: string, dir: 'up' | 'down') => void;
  onDetach: (sessionId: string) => void;
  onAttachPick: (sessionId: string) => void;
  onOpenCreate: () => void;
  onDragStartRow: (sessionId: string) => void;
  onDragEndRow: () => void;
  /** 悬停到本行 → 落点为「本行之前」。 */
  onDragOverRow: (before: string) => void;
  /** 在本行落下 → 插入到本行之前。 */
  onDropRow: (before: string) => void;
  /** 打开本行的硬删确认面（真正删在前端最上层的 onDeleteSession 里）。 */
  onDelete: (target: DeleteSessionTarget) => void;
  /** 本行归档 / 取消归档（#171）。真正落库在 App 侧的 onSetArchived 里；
   *  本组件只转交意图，不碰会话真相。 */
  onSetArchived: (sessionId: string, archived: boolean) => void;
}

function SessionRow({
  session: s,
  title,
  selected,
  live,
  now,
  projectId,
  ledger,
  dragging,
  dropEnabled,
  dropBefore,
  onSelect,
  onMove,
  onDetach,
  onAttachPick,
  onOpenCreate,
  onDragStartRow,
  onDragEndRow,
  onDragOverRow,
  onDropRow,
  onDelete,
  onSetArchived,
}: RowProps) {
  const inProject = projectId !== null;
  const index = ledger.indexOf(s.session_id);
  return (
    <div
      className={`session-row${inProject ? ' session-row-in-project' : ''}${dragging ? ' dragging' : ''}`}
      draggable={inProject}
      onDragStart={(e) => {
        if (!inProject) return;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', s.session_id);
        onDragStartRow(s.session_id);
      }}
      onDragEnd={onDragEndRow}
      onDragOver={(e) => {
        if (!inProject || !dropEnabled || dragging) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        onDragOverRow(s.session_id);
      }}
      onDrop={(e) => {
        // 落点在行的上半/下半不做区分：统一「放到这一行前面」+ 队尾放置区，
        // 少一个模糊点，也少一类"以为放到后面、结果插到前面"的意外。
        if (!inProject || !dropEnabled) return;
        e.preventDefault();
        e.stopPropagation();
        onDropRow(s.session_id);
      }}
    >
      {dropBefore && <span className="rail-drop-indicator" aria-hidden="true" />}
      <button
        className={`session-item ${selected ? 'selected' : ''}`}
        onClick={() => onSelect(s.session_id)}
        title={`${s.session_id} · ${s.event_count} 事件${inProject ? '' : ' · 未分组'}`}
      >
        <span
          className={`session-item-dot ${live ? 'session-item-dot-live' : ''}`}
          aria-hidden="true"
        />
        <div className="session-item-body">
          {title && <div className="session-item-title">{title.slice(0, 48)}</div>}
          <div className="session-item-id mono">{s.session_id.slice(0, 12)}</div>
          <div className="session-item-meta num">
            {s.event_count} 事件 · {formatRelativeTime(s.last_event_time, now)}
          </div>
          {/* #171：「已归档」徽标。只有打开「显示已归档」时这一行才会被渲染出来
              （默认视图里已归档行整个不渲染，见 buildRailModel），所以徽标是**这一行
              此刻的唯一解释**：它不是被删了、也不是日志丢了，只是收起来了。 */}
          {s.archived && (
            <div
              className="session-item-archived"
              title="已归档：默认从列表收起，事件日志与项目归属都原样保留"
            >
              已归档
            </div>
          )}
          {s.staleProject && (
            <div
              className="session-item-stale"
              title={`这个会话记录的项目 id 是 ${s.staleProject.id}，但它不在当前项目列表里——项目列表可能还没刷新，或该项目已被移除。归属仍以项目账本为准。`}
            >
              所属项目「{s.staleProject.title}」未在列表中
            </div>
          )}
        </div>
      </button>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            className="icon-btn rail-menu-btn"
            aria-label={`会话 ${s.session_id.slice(0, 8)} 操作`}
          >
            <Ellipsis size={14} />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="rail-menu" align="end" sideOffset={4}>
            {inProject ? (
              <>
                <DropdownMenu.Item
                  className="rail-menu-item"
                  disabled={index <= 0}
                  onSelect={() => projectId && onMove(projectId, s.session_id, 'up')}
                >
                  <ArrowUp size={12} aria-hidden="true" /> 上移
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  className="rail-menu-item"
                  disabled={index < 0 || index >= ledger.length - 1}
                  onSelect={() => projectId && onMove(projectId, s.session_id, 'down')}
                >
                  <ArrowDown size={12} aria-hidden="true" /> 下移
                </DropdownMenu.Item>
                <DropdownMenu.Separator className="rail-menu-sep" />
                <DropdownMenu.Item className="rail-menu-item" onSelect={() => onDetach(s.session_id)}>
                  移出项目
                </DropdownMenu.Item>
              </>
            ) : (
              <>
                <DropdownMenu.Item
                  className="rail-menu-item"
                  onSelect={() => onAttachPick(s.session_id)}
                >
                  加入项目…
                </DropdownMenu.Item>
                <DropdownMenu.Item className="rail-menu-item" onSelect={onOpenCreate}>
                  新建项目…
                </DropdownMenu.Item>
              </>
            )}
            <DropdownMenu.Separator className="rail-menu-sep" />
            {/* #171：归档 / 取消归档（**可逆**，不是删除）。位置在项目动作之后、硬删
                之前——两者之间隔着一个分隔符与整整一组动作，是刻意的：点错"收起来"
                只是少看一行，点错"删掉"不可恢复。可逆动作**不做二次确认**（AC11），
                失败就地报错（`opError` 那条栏），撤销 = 再点一次「取消归档」。
                文案随行的真值切换（`s.archived`），不是两个按钮。 */}
            <DropdownMenu.Item
              className="rail-menu-item"
              onSelect={() => onSetArchived(s.session_id, !s.archived)}
            >
              {s.archived ? '取消归档' : '归档'}
            </DropdownMenu.Item>
            <DropdownMenu.Separator className="rail-menu-sep" />
            {/* 硬删（#172 / ADR-0029）——两分支共用、永远最后一项：不可恢复的动作
                不夹在"上移/加入项目"中间，位置本身就是一道缓冲。
                刻意**不**对 live 行禁用：会话是否"忙"（在途 run / 挂起审批）只有
                后端知道，前端据 live 猜一个禁用态就是第二套真相（不变量 #22），
                猜错时留给用户的是一个点了没反应的灰按钮。让后端拒绝并显示它的
                detail（409 的三种原因，见 DeleteSessionDialog）。 */}
            <DropdownMenu.Item
              className="rail-menu-item rail-menu-item-danger"
              onSelect={() => onDelete({ id: s.session_id, title })}
            >
              删除会话…
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}
