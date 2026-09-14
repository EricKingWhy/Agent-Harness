/** 中心列「文件/改动」面（#189 / PRD §3.3）。
 *
 *  要回答的问题："**这次 agent 动了哪些文件、每个文件改成了什么样**"——不是"看工具调用
 *  流水"（那是中心列的对话流与 Inspector 的 Timeline）。
 *
 *  三条纪律：
 *  - **一个文件一行**（AC2）：按路径聚合，同一文件改三次仍是一行，右侧按时间序列出
 *    各次改动。形态对齐 Claude Code 桌面版 / VS Code Changes panel（左侧文件列表 +
 *    右侧逐文件 diff，PRD §3.0）。
 *  - **diff 只有一份渲染器**（AC5 / #190 AC9 同族）：右栏复用 `DiffBlock`——不是
 *    在面板里再写一套 `<pre>` 双栏。截断/归档的"查看完整内容"入口属 #186，本票**不**
 *    另造一个（造了就是第二套渲染与第二套 marker 解析）。
 *  - **只读**（AC4）：不提供任何编辑入口；也没有输入类元素（与「输出」面同一条纪律）。
 *
 *  范围（AC3）：**只显示本次会话改动过的文件**。不做工作区浏览、不读当前文件内容、
 *  不做 git 状态——那是 #191。
 */
import { FileDiff } from 'lucide-react';
import { useState } from 'react';
import type { ToolCall } from '../types';
import { changedFiles, type FileChange } from '../lib/changedFiles';
import { DiffBlock } from './DiffBlock';

/** 统计徽标：`+N` / `-M` 只显示非零的一侧，净零显示 `±0`。
 *  `±0` 是一条真事实（改完又改回去）——隐藏它会让这个文件看起来"没被改过"，
 *  而它确实被改过两次。 */
function StatBadge({ file }: { file: FileChange }) {
  if (file.added === null || file.removed === null) {
    return (
      <span
        className="changes-stat changes-stat-limited"
        title={`统计不可得：${file.limited === 'archived' ? '内容已归档为 artifact（超过 2000 字符）' : '内容过长已被截断（>50KB）'}`}
      >
        —
      </span>
    );
  }
  if (file.added === 0 && file.removed === 0) {
    return (
      <span className="changes-stat" title="净变化为 0（改动被后续改动抵消）">
        ±0
      </span>
    );
  }
  return (
    <span className="changes-stat">
      {file.added > 0 && <span className="changes-added">+{file.added}</span>}
      {file.removed > 0 && <span className="changes-removed">-{file.removed}</span>}
    </span>
  );
}

/** 归属不了文件的改动次数：空态与有文件两种版式下都要说同一句话，所以只有一份。 */
function UnattributedFootnote({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <div className="changes-footnote">
      另有 {count} 次改动无法归属到文件（事件里没有路径）。
    </div>
  );
}

export function ChangesPanel({
  tools,
  sessionId,
}: {
  tools: readonly ToolCall[];
  /** #186 AC2：归档 diff 的「就地展开」要按会话读 artifact 内容。 */
  sessionId?: string;
}) {
  const { files, unattributed } = changedFiles(tools);
  const [wanted, setWanted] = useState<string | null>(null);
  /* 渲染期收窄（同 #182 `resolveActiveTab` / #183 的 peek 口径）：选中的文件可能已经
   * 不在清单里（会话切换、或那次改动被后续事件改写），此时落回第一个文件——绝不留在
   * 一个指向不存在文件的选择上。 */
  const selected = files.find((f) => f.path === wanted) ?? files[0] ?? null;

  return (
    <div className="changes-panel" role="region" aria-label="文件/改动">
      {files.length === 0 ? (
        <div className="detail-tab-empty">
          <FileDiff size={24} className="detail-empty-icon" aria-hidden="true" />
          <div className="detail-empty-hint">本次会话未改动任何文件。</div>
          <UnattributedFootnote count={unattributed} />
        </div>
      ) : (
        <>
          <div className="changes-split">
            {/* 左侧：改动文件列表（路径 + 统计）。行是按钮——点击即选中（AC8 的
                "点文件名 → diff 可见"），键盘也能 Tab 到达。 */}
            <ul className="changes-files" aria-label="改动文件">
              {files.map((file) => {
                const active = selected?.path === file.path;
                return (
                  <li key={file.path}>
                    <button
                      type="button"
                      className={`changes-file-row${active ? ' sel' : ''}`}
                      aria-current={active ? 'true' : undefined}
                      onClick={() => setWanted(file.path)}
                      title={file.path}
                    >
                      <span className="changes-file-path">{file.path}</span>
                      <StatBadge file={file} />
                      {/* 改多次时把次数说出来：行只有一行，但"改了几次"是用户会问的下一问。 */}
                      {file.edits.length > 1 && (
                        <span className="changes-file-count">{file.edits.length} 次</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>

            {/* 右侧：选中文件的逐次改动（时间序）。diff 渲染复用 `DiffBlock`（AC5）。 */}
            <div className="changes-detail">
              {selected && (
                <>
                  <div className="changes-detail-head">
                    <code className="changes-detail-path">{selected.path}</code>
                    <StatBadge file={selected} />
                  </div>
                  {selected.edits.map((edit, i) => (
                    <div className="changes-edit" key={edit.toolCallId}>
                      {selected.edits.length > 1 && (
                        <div className="changes-edit-head">
                          第 {i + 1} 次改动（{edit.toolName}）
                        </div>
                      )}
                      <DiffBlock
                        sessionId={sessionId}
                        diff={{
                          before: edit.before,
                          after: edit.after,
                          truncated: edit.truncated,
                          ...(edit.archived ? { archived: true as const } : {}),
                          ...(edit.artifactId !== undefined ? { artifactId: edit.artifactId } : {}),
                          ...(edit.artifactTool !== undefined
                            ? { artifactTool: edit.artifactTool }
                            : {}),
                        }}
                      />
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
          <UnattributedFootnote count={unattributed} />
        </>
      )}
    </div>
  );
}
