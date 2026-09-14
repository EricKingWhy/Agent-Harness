/** DiffBlock — before/after 双栏 diff 视图。
 *
 *  UI-01 从 ToolCard.tsx **原样抽出**复用（审批卡的 old/new 预览与工具卡的
 *  diff 走同一渲染）；搬运不改逻辑不改样式，出处见 ToolCard 历史注释。
 *
 *  #186 AC2：归档态给一个**真实可用**的「就地展开」——内容走 #185 的只读端点，
 *  与 Artifacts 清单**同一个** `ArtifactViewer`。`sessionId` 缺席时不渲染展开入口
 *  （审批卡的 old/new 预览不是 artifact，没有会话可读，也不该伪造一个）。 */
import { Archive } from 'lucide-react';
import type { ToolCall } from '../types';
import { ArtifactViewer } from './ArtifactViewer';
import { CopyButton } from './CopyButton';

export function DiffBlock({
  diff,
  sessionId,
}: {
  diff: NonNullable<ToolCall['diff']>;
  /** 内容接口需要的会话归属；缺席 = 这一处不提供展开（见文件头）。 */
  sessionId?: string;
}) {
  // before/after 已归档（>2000 字符截断摘要内嵌 "use <读回工具>(<id>)" marker）
  // → 占位态而非把 marker 原文当 diff 渲染。
  if (diff.archived && diff.artifactId) {
    // 工具名照抄 marker（S3 → inspect_artifact，MinIO / Local → read_artifact）。
    // 前端不知道也不该猜这个部署用的哪个 store；写死一个名字，S3 部署上复制出来的
    // 就是一句调不通的提示（#186 AC4）。
    const tool = diff.artifactTool ?? 'inspect_artifact';
    return (
      <div className="diff-block">
        <div className="diff-archived">
          <Archive size={14} />
          <div className="diff-archived-text">
            <div className="diff-archived-title">Diff 内容已归档（超过 2000 字符）</div>
            <div className="diff-archived-hint">
              原始变更已存为 artifact；模型侧可用 <code>{tool}</code> 读取
            </div>
          </div>
          <code className="diff-archived-id">{diff.artifactId.slice(0, 16)}…</code>
          <CopyButton text={`${tool}(${diff.artifactId})`} label={`复制 ${tool} 引用`} />
        </div>
        {/* 就地展开（AC2）：与 Artifacts 清单同一个渲染器，不新开导航面。 */}
        {sessionId && (
          <ArtifactViewer
            sessionId={sessionId}
            artifactId={diff.artifactId}
            label="查看完整内容"
          />
        )}
      </div>
    );
  }
  return (
    <div className="diff-block">
      {diff.truncated && <div className="diff-truncated">内容过长，已截断显示</div>}
      <div className="diff-cols">
        <div className="diff-col diff-before">
          <div className="diff-col-label">变更前</div>
          <pre>{diff.before || '（空）'}</pre>
        </div>
        <div className="diff-col diff-after">
          <div className="diff-col-label">变更后</div>
          <pre>{diff.after || '（空）'}</pre>
        </div>
      </div>
    </div>
  );
}
