/** 项目相关的三个浮层（WS-5 / #155）：新建 / 删除（软删除确认）/ 加入项目。
 *
 *  都用 Radix Dialog（与 CommandPalette 同一套语义：焦点陷阱 / Esc / backdrop）——
 *  **不是**为了好看，而是这三个动作都可能改宿主侧状态（注册目录、摘注册记录、
 *  改账本），必须有一个用户明确按下确认的边界，且失败原因要留在原地可见。
 *
 *  结构纪律：表单状态放在**只在打开时挂载**的内层组件里（`{open && <Form/>}`），
 *  而不是"常驻组件 + useEffect 里 setState 清空"——后者每次打开都会多一轮渲染，
 *  也是 react-hooks 的 set-state-in-effect 告警来源。挂载即初始化，关闭即丢弃，
 *  上一次的输入与错误不会漏到下一次。 */

import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { FolderPlus, TriangleAlert, X } from 'lucide-react';
import { describeProjectError } from '../lib/api';
import { useDirectoryListing } from '../hooks/useDirectoryListing';
import { DirectoryBrowser } from './DirectoryBrowser';
import type { Project, ProjectDeleted } from '../types';

interface CreateProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 注册成功 → 返回实体（调用方负责刷新）。失败时抛出（错误留在此处显示）。 */
  onCreate: (path: string, title: string | null) => Promise<Project>;
  /** 当前已知项目：提交前用于判断"这个目录已经是项目了吗"——命中则就地提示，
   *  **不发**重复注册请求（后端虽然是幂等的，但"你点的这个已经在列表里"更该在
   *  发请求前说清楚）。 */
  existing: Project[];
}

export function CreateProjectDialog(props: CreateProps) {
  const { open, onOpenChange } = props;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="palette-overlay" />
        {open && <CreateProjectForm {...props} />}
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function CreateProjectForm({ onOpenChange, onCreate, existing }: CreateProps) {
  const [path, setPath] = useState('');
  const [title, setTitle] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // WS-7 / #170：内嵌目录浏览器。它的列举结果**回填** path（浏览 → 输入框），
  // 于是"浏览到哪"与"要注册哪个目录"永远是同一个值（不维护第二份路径真相）。
  const browser = useDirectoryListing({ onPathChange: setPath });

  const submit = async () => {
    const value = path.trim();
    if (!value) {
      setError('请填写目录的绝对路径。');
      return;
    }
    // 幂等提示：同路径已在列表里 → 不重复注册，直接告诉用户它在哪。
    // 尾部分隔符归一（D:\x\ 与 D:\x 是同一个目录）后再比。
    const strip = (p: string) => p.replace(/[\\/]+$/, '');
    const hit = existing.find((p) => strip(p.path) === strip(value));
    if (hit) {
      setNotice(
        hit.status === 'missing-dir'
          ? `该目录已经是项目「${hit.title}」——没有重复注册，它就在侧栏里（后端当前报告该目录不存在）。`
          : `该目录已经是项目「${hit.title}」——没有重复注册，它就在侧栏里。`,
      );
      setError(null);
      return;
    }
    if (pending) return;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      await onCreate(value, title.trim() || null);
      onOpenChange(false);
    } catch (e) {
      setError(describeProjectError(e, '注册项目失败'));
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog.Content className="project-dialog" aria-label="新建项目">
      <div className="project-dialog-head">
        <Dialog.Title className="project-dialog-title">
          <FolderPlus size={14} aria-hidden="true" /> 新建项目
        </Dialog.Title>
        <Dialog.Close asChild>
          <button className="icon-btn project-dialog-close" aria-label="关闭">
            <X size={14} />
          </button>
        </Dialog.Close>
      </div>
      <Dialog.Description className="project-dialog-desc">
        把一个<strong>已存在</strong>的目录注册为项目。项目只是这个目录在侧栏里的名字——
        目录不会被复制、移动或创建，同目录下的会话可以归到一起。
      </Dialog.Description>

      <label className="project-field">
        <span className="project-field-label">目录绝对路径</span>
        <input
          className="project-input mono"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="D:\repos\my-project"
          aria-label="目录绝对路径"
          maxLength={4096}
          autoFocus
          onKeyDown={(e) => {
            // Enter = 在下方浏览器里打开这个路径（PRD §4.5 的双向同步：手改输入框
            // 回车 → 浏览器跳转）。注册动作由「注册项目」按钮明确触发——先看见目录
            // 里有什么，再决定注册它，这条路径本来就不该一个回车就走完。
            if (e.key === 'Enter' && !pending) browser.goto(path.trim() || null);
          }}
        />
        <span className="project-field-hint">
          必须是绝对路径；目录需要已经存在（不会替你创建，路径不存在会明确报错）。
          回车 = 在下方浏览该目录；确认无误后点「注册项目」。
        </span>
      </label>

      <label className="project-field">
        <span className="project-field-label">项目名（可选）</span>
        <input
          className="project-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="缺省取目录名"
          aria-label="项目名"
          maxLength={200}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !pending) void submit();
          }}
        />
      </label>

      {/* WS-7 / #170：内嵌浏览器（浏览 → 回填上面的路径输入框；上面回车 → 跳到这里）。
          放在表单下方而不是替换输入框：手写路径与点选目录两条路都要留着——熟练用户
          粘贴一个长路径比逐层点快得多。 */}
      <DirectoryBrowser
        listing={browser.listing}
        loading={browser.loading}
        error={browser.error}
        onGoto={browser.goto}
        onPick={setPath}
      />

      {notice && (
        <div className="project-notice" role="status">
          {notice}
        </div>
      )}

      {error && (
        <div className="project-error" role="alert">
          {error}
        </div>
      )}

      <div className="project-dialog-actions">
        <Dialog.Close asChild>
          <button className="project-btn">取消</button>
        </Dialog.Close>
        <button
          className="project-btn project-btn-primary"
          onClick={() => void submit()}
          disabled={pending}
        >
          {pending ? '注册中…' : '注册项目'}
        </button>
      </div>
    </Dialog.Content>
  );
}

interface DeleteProps {
  /** 待删除项目；null = 关闭。 */
  project: Project | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (projectId: string) => Promise<ProjectDeleted>;
}

export function DeleteProjectDialog({ project, onOpenChange, onConfirm }: DeleteProps) {
  return (
    <Dialog.Root
      open={project !== null}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="palette-overlay" />
        {project && (
          <DeleteProjectForm project={project} onOpenChange={onOpenChange} onConfirm={onConfirm} />
        )}
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** 删除确认：必须让用户在按下按钮**之前**就看到"会话不会被删"（AC5）。 */
function DeleteProjectForm({
  project,
  onConfirm,
}: DeleteProps & { project: Project }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const confirm = async () => {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const result = await onConfirm(project.id);
      // 后端写好的那句话在这里原样出现——它明确说了「会话与目录都没删」（AC5）。
      // 兜底句也把「什么都没删」说全：软删除的确认如果只留在后端文案里，后端哪天
      // 简化了那句话，界面就会退回"项目没了但不知道文件还在不在"。
      setDone(
        result.detail ||
          '项目已从注册表移除，会话回到未分组。目录、用户文件与会话日志均未删除。',
      );
    } catch (e) {
      setError(describeProjectError(e, '删除项目失败'));
    } finally {
      setPending(false);
    }
  };

  const count = project.session_ids.length;

  return (
    <Dialog.Content className="project-dialog" aria-label="删除项目">
      <div className="project-dialog-head">
        <Dialog.Title className="project-dialog-title project-dialog-title-danger">
          <TriangleAlert size={14} aria-hidden="true" /> 删除项目「{project.title}」
        </Dialog.Title>
        <Dialog.Close asChild>
          <button className="icon-btn project-dialog-close" aria-label="关闭">
            <X size={14} />
          </button>
        </Dialog.Close>
      </div>

      {done ? (
        <div className="project-dialog-done" role="status">
          {done}
        </div>
      ) : (
        // asChild + div：Radix 的 Description 默认渲染 <p>，而下面是一个列表——
        // <p> 里放 <ul> 是非法 HTML（浏览器会把 <p> 提前闭合，DOM 与代码不一致）。
        <Dialog.Description asChild>
          <div className="project-dialog-desc">
            这是<strong>软删除</strong>：只把项目从注册表移除。
            <ul className="project-dialog-list">
              <li>
                {count > 0
                  ? `${count} 个会话回到「未分组」，仍可打开与继续对话`
                  : '当前项目内没有会话'}
              </li>
              <li>目录与其中的文件<strong>不会</strong>被删除</li>
              <li>会话日志<strong>不会</strong>被删除，历史一条不少</li>
            </ul>
            之后可以重新注册同一个目录。
          </div>
        </Dialog.Description>
      )}

      {error && (
        <div className="project-error" role="alert">
          {error}
        </div>
      )}

      <div className="project-dialog-actions">
        {done ? (
          <Dialog.Close asChild>
            <button className="project-btn project-btn-primary">完成</button>
          </Dialog.Close>
        ) : (
          <>
            <Dialog.Close asChild>
              <button className="project-btn">取消</button>
            </Dialog.Close>
            <button
              className="project-btn project-btn-danger"
              onClick={() => void confirm()}
              disabled={pending}
            >
              {pending ? '正在移除…' : '只移除项目（不删会话）'}
            </button>
          </>
        )}
      </div>
    </Dialog.Content>
  );
}

interface AttachProps {
  /** 待加入项目的会话 id；null = 关闭。 */
  sessionId: string | null;
  projects: Project[];
  onOpenChange: (open: boolean) => void;
  onPick: (projectId: string, sessionId: string) => Promise<void>;
}

export function AttachToProjectDialog({ sessionId, projects, onOpenChange, onPick }: AttachProps) {
  return (
    <Dialog.Root
      open={sessionId !== null}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="palette-overlay" />
        {sessionId !== null && (
          <AttachForm
            sessionId={sessionId}
            projects={projects}
            onOpenChange={onOpenChange}
            onPick={onPick}
          />
        )}
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function AttachForm({
  sessionId,
  projects,
  onOpenChange,
  onPick,
}: AttachProps & { sessionId: string }) {
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const pick = async (projectId: string) => {
    if (pendingId !== null) return;
    setPendingId(projectId);
    setError(null);
    try {
      await onPick(projectId, sessionId);
      onOpenChange(false);
    } catch (e) {
      setError(describeProjectError(e, '加入项目失败'));
    } finally {
      setPendingId(null);
    }
  };

  return (
    <Dialog.Content className="project-dialog" aria-label="加入项目">
      <div className="project-dialog-head">
        <Dialog.Title className="project-dialog-title">把会话加入项目</Dialog.Title>
        <Dialog.Close asChild>
          <button className="icon-btn project-dialog-close" aria-label="关闭">
            <X size={14} />
          </button>
        </Dialog.Close>
      </div>
      <Dialog.Description className="project-dialog-desc">
        选择要加入的项目。会话的工作目录必须与项目路径一致，否则后端会拒绝
        （原因会显示在这里）——归属由会话自己的 cwd 决定，不由界面决定。
      </Dialog.Description>

      {projects.length === 0 ? (
        <div className="project-notice" role="status">
          还没有项目。先用侧栏右上角的「新建项目」注册一个目录，再回来把会话加进去。
        </div>
      ) : (
        // 不用 role="list"/"listitem"：这些是按钮，把 button 标成 listitem 会让
        // 读屏丢掉"可按"的语义——这里的信息层级靠标题与顺序表达就够了。
        <div className="project-pick-list">
          {projects.map((p) => (
            <button
              key={p.id}
              className="project-pick-item"
              onClick={() => void pick(p.id)}
              disabled={pendingId !== null}
            >
              <span className="project-pick-title">{p.title}</span>
              <span className="project-pick-path mono">{p.path}</span>
              {pendingId === p.id && <span className="project-pick-pending">加入中…</span>}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="project-error" role="alert">
          {error}
        </div>
      )}

      <div className="project-dialog-actions">
        <Dialog.Close asChild>
          <button className="project-btn">取消</button>
        </Dialog.Close>
      </div>
    </Dialog.Content>
  );
}

/** 行内重命名输入（不起浮层：项目标题就在侧栏里，就地改名最短路径）。
 *  Enter 提交 / Esc 取消 / 失焦提交——三条路径都由调用方传入的回调收口。
 *
 *  FE-R11-08：空白标题此前被**静默丢弃**——Enter 直接把 `''` 交给调用方，
 *  调用方的 `if (title)` 一过滤，编辑态关闭、没有请求、也没有任何提示，
 *  用户以为改名成功了。现在 Enter 遇到空白就地拦下：给可见提示 + 保持编辑态
 *  （输入框里还是那串空白，用户可以直接补字或按 Esc 走人）。
 *  失焦仍按取消处理——用户已经离开这块界面，名字原样留在那里本身就是反馈。 */
export function InlineRename({
  initial,
  onCommit,
  onCancel,
}: {
  initial: string;
  onCommit: (title: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const errorId = 'rename-error';
  return (
    <>
      <input
        className="project-rename-input"
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          if (error) setError(null); // 一动手就撤提示，不用等提交
        }}
        aria-label="项目名"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        maxLength={200}
        autoFocus
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === 'Enter') {
            const next = value.trim();
            if (!next) {
              setError('项目名不能为空');
              return;
            }
            onCommit(next);
          } else if (e.key === 'Escape') onCancel();
        }}
        onBlur={() => {
          const next = value.trim();
          if (next && next !== initial) onCommit(next);
          else onCancel();
        }}
      />
      {error && (
        <span className="project-rename-error" id={errorId} role="alert">
          不能为空
        </span>
      )}
    </>
  );
}
