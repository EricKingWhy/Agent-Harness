/** 「在此项目中新建任务」确认面（WS-6 / #169 AC9–AC14）。
 *
 *  为什么必须有一个确认面，而不是点菜单项就直接跑：这个入口会以**项目目录**为
 *  cwd 起一个会话，而 cwd 在 ADR-0027 里就是会话的 workspace root——agent 会直接
 *  读写那个目录。误点一个菜单项不该等于把某个仓库交给 agent，所以路径必须在按下
 *  「开始任务」之前被肉眼看到（Q2=C 的硬要求，文案逐字为 AC）。
 *
 *  权限档的默认档**不写进请求体**（这是本票最容易踩的坑）：后端
 *  `service.create_and_launch` 的语义是「显式传了非 danger-full-access 的档 →
 *  切交互式审批」（`permission_mode_explicit`）。所以"默认 = workspace-write +
 *  自动执行"只能靠**不发这个键**来表达；一旦把默认档也塞进 payload，每次工具调用
 *  都会弹审批卡。只有用户主动改档才发 `permission_mode`，而改档的语义恰恰就是
 *  "我要逐次审批"。
 *
 *  失败留在本浮层（AC12）：项目目录被移走 → 后端 422「目录不存在：…」，这句话
 *  必须出现在用户目光所在的位置（浮层里），而不是被打到 Workspace 区的全局横幅上
 *  让用户去别处找。表单状态放只在打开时挂载的内层组件（与 ProjectDialogs 同一条
 *  结构纪律：挂载即初始化，关闭即丢弃）。 */

import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Shield, TriangleAlert, X } from 'lucide-react';
import type { CatalogEntry } from '../lib/api';
import type { Project } from '../types';
import { ControlPicker } from './ControlPicker';

/** 默认权限档——与后端 `web/app.py::CreateSessionRequest.permission_mode` 的默认值
 *  同名同义（workspace-write + auto-approve）。它只作为**本地选中态**，不发进请求体：
 *  见文件头注释。 */
const DEFAULT_PERMISSION_MODE = 'workspace-write';

interface Props {
  /** 待开任务的项目；null = 关闭。 */
  project: Project | null;
  /** 权限档清单（GET /api/permission-modes）。空数组 = 端点缺席 → 不渲染选择器，
   *  用默认档（与 Composer 的降级立场一致：不伪造列表）。 */
  permissionModes: CatalogEntry[];
  onOpenChange: (open: boolean) => void;
  /** 提交任务。resolve `null` = 已被接受（流已接上，调用方关闭浮层）；
   *  否则 resolve 一句**给用户看的原因**（浮层就地显示，不抛异常）。 */
  onStart: (
    project: Project,
    task: string,
    permissionMode: string | null,
  ) => Promise<string | null>;
}

export function StartTaskInProjectDialog({
  project,
  permissionModes,
  onOpenChange,
  onStart,
}: Props) {
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
          <StartTaskForm
            project={project}
            permissionModes={permissionModes}
            onOpenChange={onOpenChange}
            onStart={onStart}
          />
        )}
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function StartTaskForm({
  project,
  permissionModes,
  onOpenChange,
  onStart,
}: Props & { project: Project }) {
  const [task, setTask] = useState('');
  const [mode, setMode] = useState<string>(DEFAULT_PERMISSION_MODE);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const text = task.trim();
  const submit = async () => {
    if (!text || pending) return;
    setPending(true);
    setError(null);
    // 默认档 → null → api 层不发 permission_mode 键（见文件头注释）。
    const chosen = mode === DEFAULT_PERMISSION_MODE ? null : mode;
    const failure = await onStart(project, text, chosen);
    if (failure) {
      setError(failure);
      setPending(false);
      return;
    }
    onOpenChange(false); // 成功即关闭：用户接下来要看着那条流
  };

  return (
    <Dialog.Content className="project-dialog" aria-label="在此项目中新建任务">
      <div className="project-dialog-head">
        <Dialog.Title className="project-dialog-title">
          <Shield size={14} aria-hidden="true" /> 在此项目中新建任务
        </Dialog.Title>
        <Dialog.Close asChild>
          <button className="icon-btn project-dialog-close" aria-label="关闭">
            <X size={14} />
          </button>
        </Dialog.Close>
      </div>

      <Dialog.Description className="project-dialog-desc">
        在项目「{project.title}」里开一个新会话。它把这个目录作为工作目录——agent
        的文件操作都相对它解析，创建后自动归入本项目（同一目录，无需再「加入项目」）。
      </Dialog.Description>

      {/* AC10：路径明示行（逐字文案，e2e 断言）。强视觉是因为它承担的是
          "你正在把哪个目录交给 agent"这个确认责任。 */}
      <div className="project-path-callout" role="note">
        <TriangleAlert size={13} aria-hidden="true" />
        <span>
          Agent 将直接读写该目录：
          <span className="project-path-callout-path mono">{project.path}</span>
        </span>
      </div>

      {permissionModes.length > 0 ? (
        <div className="project-field">
          <span className="project-field-label">权限模式</span>
          <ControlPicker
            ariaLabel="权限模式"
            entries={permissionModes}
            selectedId={mode}
            onChange={(id) => setMode(id ?? DEFAULT_PERMISSION_MODE)}
            icon={Shield}
            placeholder="默认（工作区写入，自动执行）"
            disabled={pending}
          />
          <span className="project-field-hint">
            默认档 = 工作区写入 + 自动执行，工具调用不会逐次询问；改档后每次工具调用都需要你审批。
          </span>
        </div>
      ) : (
        // 清单端点缺席：不伪造三档，说清"用的是默认档"（选择器降级隐藏）。
        <div className="project-notice" role="status">
          权限档清单未加载，将使用默认档：工作区写入 + 自动执行。
        </div>
      )}

      <label className="project-field">
        <span className="project-field-label">任务内容</span>
        <textarea
          className="project-textarea"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="例如：读一下 README 和 src 目录，总结这个项目的结构。"
          aria-label="任务内容"
          rows={4}
          maxLength={8000}
          autoFocus
        />
      </label>

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
          disabled={!text || pending}
        >
          {pending ? '正在开始…' : '开始任务'}
        </button>
      </div>
    </Dialog.Content>
  );
}
