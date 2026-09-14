/** 会话硬删的二次确认浮层（#172 / ADR-0029）。
 *
 *  为什么必须是浮层，而不是行内两段式（记忆面板那种就地确认条）：ADR-0029 的
 *  Consequences 逐字写着「误删不可逆，且没有任何技术兜底（无墓碑 / 无回收站）。风险
 *  全部由**入口层**的显式确认承担」。一次不可恢复的删除，代价必须与动作本身分离
 *  ——行内确认条在快速滚动 / 连点里太容易被"下一步"顺手点掉，而它赔不起。
 *
 *  结构纪律照抄 ProjectDialogs：表单状态放在**只在打开时挂载**的内层组件里
 *  （`{target && <Form/>}`），关闭即丢弃——上一次的错误与回执不会漏到下一次。
 *
 *  分工：本组件只管"确认 + 回执 + 失败原因留在原地"，**不碰列表状态**。删除成功后
 *  的状态收敛（清掉当前视图 / 重拉会话列表）由调用方负责，与 DeleteProjectDialog
 *  同一分工（那边也是 onConfirm 抛出、调用方刷新）。 */

import { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { TriangleAlert, X } from 'lucide-react';
import { describeSessionError } from '../lib/api';
import { sessionDeletedMessage } from '../lib/sessionDelete';
import type { SessionDeleted } from '../types';

/** 确认面上要显示的会话标识：标题（首条用户消息投影，可能为空）+ id。
 *
 *  刻意用这个小形状而不是 `SessionSummary`：确认面的职责只有一个——让用户认出自己
 *  点的是哪一条。它需要的字段比会话行少得多，传整条 summary 会让人以为这里还能读
 *  别的字段。
 *
 *  **刻意不带事件数**：列表里的 `event_count` 是上次拉取时的快照，删除发生在之后
 *  （这中间可能又跑过 run）。把可能过期的数字放进"确认要删掉多少"的位置，就是拿一个
 *  二手值当事实陈述——真值只在回执里（后端**删除前**现取，见 SessionDeleted）。 */
export interface DeleteSessionTarget {
  id: string;
  /** 行标题（首条用户消息）；空串 = 没有可用标题，届时只显示 id 片段。 */
  title: string;
}

interface Props {
  /** 待删除会话；null = 关闭。 */
  target: DeleteSessionTarget | null;
  onOpenChange: (open: boolean) => void;
  /** 硬删（不可恢复）。resolve = 后端回执；reject = **留在浮层里**的原因。 */
  onConfirm: (sessionId: string) => Promise<SessionDeleted>;
}

export function DeleteSessionDialog({ target, onOpenChange, onConfirm }: Props) {
  return (
    <Dialog.Root
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="palette-overlay" />
        {target && <DeleteSessionForm target={target} onConfirm={onConfirm} />}
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DeleteSessionForm({
  target,
  onConfirm,
}: {
  target: DeleteSessionTarget;
  onConfirm: Props['onConfirm'];
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  /** 成功回执：浮层**不自动关**——回执要留在原地被读到，用户点「完成」才走
   *  （与 DeleteProjectDialog 的成功态同一约定）。 */
  const [done, setDone] = useState<string | null>(null);
  /** FE-R11-10：初焦落在「取消」而不是右上「关闭(X)」。 */
  const cancelRef = useRef<HTMLButtonElement>(null);

  const confirm = async () => {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      setDone(sessionDeletedMessage(await onConfirm(target.id)));
    } catch (e) {
      // 409 的三种原因（有在途 run / 有挂起审批 / 是 fork 父会话）**状态码相同**，
      // 只有 detail 能区分——所以这里原样显示后端那句话，绝不自己编一套文案：编了
      // 就会把"有 2 个 fork 子会话"说成一个泛泛的失败，把唯一可行动的信息抹掉。
      setError(describeSessionError(e, '删除会话失败'));
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog.Content
      className="project-dialog"
      /* FE-R11-10：Radix 默认把初焦给 Content 里第一个可聚焦元素——本弹窗里那是
         右上角的「关闭(X)」图标按钮：读屏只念得出"关闭"，回车即退出，而键盘用户
         落地第一眼看到的是全场最不该先碰的控件。一次不可逆删除的确认面，初焦应该
         落在安全的出口上：「取消」（回车 = 安全取消）。回执态没有「取消」按钮，
         交回 Radix 默认处理。 */
      onOpenAutoFocus={(e) => {
        if (!cancelRef.current) return;
        e.preventDefault();
        cancelRef.current.focus();
      }}
    >
      <div className="project-dialog-head">
        <Dialog.Title className="project-dialog-title project-dialog-title-danger">
          <TriangleAlert size={14} aria-hidden="true" /> 删除会话
        </Dialog.Title>
        <Dialog.Close asChild>
          <button className="icon-btn project-dialog-close" aria-label="关闭">
            <X size={14} />
          </button>
        </Dialog.Close>
      </div>

      {/* 会话标识块（AC：确认面必须显示标题 / 首条消息 + id 片段）——它是"认出自己
          点的是哪一条"的唯一依据，所以**无论在确认态还是回执态都显示**。（不像
          DeleteProjectDialog 那样在 Content 上再挂一个 aria-label：Radix 用 Title
          作 aria-labelledby，多加一个只会与它打架。） */}
      <div className="project-dialog-target">
        <div className="project-dialog-target-title" title={target.title || target.id}>
          {target.title || '（这条会话没有标题）'}
        </div>
        <div className="project-dialog-target-id">id {target.id.slice(0, 12)}</div>
      </div>

      {done ? (
        <div className="project-dialog-done" role="status">
          {done}
        </div>
      ) : (
        // asChild + div：Radix 的 Description 默认渲染 <p>，而下面是一个列表——
        // <p> 里放 <ul> 是非法 HTML（浏览器会提前闭合 <p>，DOM 与代码不一致）。
        <Dialog.Description asChild>
          <div className="project-dialog-desc">
            这是<strong>硬删除</strong>，<strong>不可恢复</strong>：
            <ul className="project-dialog-list">
              <li>该会话的事件记录会被永久删除，没有回收站、没有撤销</li>
              <li>
                你的项目目录与其中的文件<strong>不会</strong>被删除
              </li>
              <li>若它属于某个项目，只会从项目里解除——项目本身与目录不动</li>
            </ul>
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
              <button className="project-btn" ref={cancelRef}>
                取消
              </button>
            </Dialog.Close>
            {/* 按钮文字不写「删除」两个字就完事：这是本票唯一的不可逆动作，
                「永久」「不可恢复」必须出现在**按下之前**（ADR-0029 入口层责任）。 */}
            <button
              className="project-btn project-btn-danger"
              onClick={() => void confirm()}
              disabled={pending}
            >
              {pending ? '正在删除…' : '永久删除（不可恢复）'}
            </button>
          </>
        )}
      </div>
    </Dialog.Content>
  );
}
