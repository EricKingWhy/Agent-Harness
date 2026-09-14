/** ApprovalCard 失效态渲染（APR-01，第十一轮真机）。
 *
 *  静态渲染（renderToStaticMarkup，同 Conversation.test.tsx 的口径）：本文件锁的是
 *  「被判为失效的审批长什么样」。**失效判定不在卡内**——`invalid` 由 App 统一计算
 *  （投影的 `stale` ∪ 后端 404 实证），同一事实同时驱动 composer 解锁；
 *  404 → ApprovalGoneError 的归类由 api.test.ts 覆盖，端到端由
 *  `e2e/n-approval-card.spec.ts` 覆盖。 */
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApprovalCard } from './ApprovalCard';
import type { PendingApproval } from '../types';

function approval(): PendingApproval {
  return {
    approval_id: 'ap-1',
    tool_name: 'bash',
    tool_call_id: 'tc-1',
    action_type: 'danger',
    title: '执行命令',
    description: 'rm -rf 之类',
    arguments_preview: { command: 'ls' },
    permission: 'bash',
    policy: 'ask',
    reason: '危险操作',
    allowed_decisions: ['approve_once', 'deny'],
  };
}

function buttonTag(html: string, cls: string): string {
  const m = html.match(new RegExp(`<button[^>]*class="${cls}"[^>]*>`));
  if (!m) throw new Error(`找不到按钮 ${cls}`);
  return m[0];
}

describe('ApprovalCard — 失效态（APR-01）', () => {
  it('invalid 优先于「需要审批」：标题说失效，不再说需要审批', () => {
    const html = renderToStaticMarkup(
      <ApprovalCard sessionId="s" approval={approval()} invalid />,
    );
    expect(html).toContain('审批已失效');
    expect(html).not.toContain('需要审批');
  });

  it('invalid：批准/拒绝都 disabled（点了必然 404 的按钮不该可点）', () => {
    const html = renderToStaticMarkup(
      <ApprovalCard sessionId="s" approval={approval()} invalid />,
    );
    expect(buttonTag(html, 'btn-primary approval-approve')).toContain('disabled');
    expect(buttonTag(html, 'btn-ghost approval-deny')).toContain('disabled');
  });

  it('invalid：给出原因说明，且不再标注快捷键（键盘路径已撤）', () => {
    const html = renderToStaticMarkup(
      <ApprovalCard sessionId="s" approval={approval()} invalid />,
    );
    expect(html).toContain('决策无法再提交');
    expect(html).not.toContain('approval-kbd');
    expect(html).toContain('approval-card pending invalid');
  });

  it('非 invalid：仍是可提交的正常卡（防误伤——run 活着时审批就该能点）', () => {
    const html = renderToStaticMarkup(<ApprovalCard sessionId="s" approval={approval()} />);
    expect(html).toContain('需要审批');
    expect(html).not.toContain('审批已失效');
    expect(buttonTag(html, 'btn-primary approval-approve')).not.toContain('disabled');
    expect(html).toContain('approval-kbd'); // 快捷键提示保留
    expect(html).not.toContain('invalid');
  });
});
