/** `lib/permission.ts`（#184 Inspector PERMISSION 段措辞）纯函数测试。
 *
 *  本仓组件测试是 SSR，交互靠 e2e；因此"零待审批怎么说""未知决策怎么显示"这类
 *  措辞规则必须在这里钉死——它们正是 PRD §4「不伪造」最容易失守的地方。 */

import { describe, expect, it } from 'vitest';
import type { ConversationState } from '../types';
import { decisionLabel, permissionView, verdictTone } from './permission';
import { applyEvent, initConversation } from './projection';

const T = '2026-01-01T00:00:00Z';

function withApprovalRequest(
  s: ConversationState,
  approvalId: string,
  seq: number,
  policy = 'read-only',
): ConversationState {
  return applyEvent(s, {
    session_id: 's', time: T, type: 'tool/approval-requested', seq, run_id: 'r', step_id: 1,
    data: {
      approval_id: approvalId, tool_name: 'write', tool_call_id: `tc-${approvalId}`,
      action_type: 'workspace-write', title: 't', description: 'd', arguments_preview: {},
      permission: 'workspace-write', policy, reason: 'r', allowed_decisions: ['deny', 'approve_once'],
    },
  });
}

function withResolved(
  s: ConversationState,
  approvalId: string,
  seq: number,
  decision: string,
  reason = '',
): ConversationState {
  return applyEvent(s, {
    session_id: 's', time: T, type: 'permission/resolved', seq, run_id: 'r',
    data: { approval_id: approvalId, decision, reason },
  });
}

describe('decisionLabel — 决策词汇映射', () => {
  it('已兑现的两档 + 预留两档都给中文；不是英文原样', () => {
    expect(decisionLabel('deny')).toBe('拒绝');
    expect(decisionLabel('approve_once')).toBe('批准（一次）');
    expect(decisionLabel('approve_session')).toBe('批准（会话）');
    expect(decisionLabel('approve_policy')).toBe('批准（策略）');
  });

  it('未知决策**原样返回**——后端加了新粒度时不许显示"未知"把事实丢掉', () => {
    expect(decisionLabel('approve_forever')).toBe('approve_forever');
  });

  it('空串（契约缺字段）→ —，不渲染空标签', () => {
    expect(decisionLabel('')).toBe('—');
  });
});

describe('verdictTone — 语义色档（绿是"已批准"的断言，不许靠猜）', () => {
  it('deny → deny；四种 approve 粒度 → allow', () => {
    expect(verdictTone('deny')).toBe('deny');
    expect(verdictTone('approve_once')).toBe('allow');
    expect(verdictTone('approve_session')).toBe('allow');
    expect(verdictTone('approve_policy')).toBe('allow');
  });

  it('缺失/未知决策 → neutral（缺字段的 permission/resolved 不得被画成"已批准"）', () => {
    expect(verdictTone('')).toBe('neutral');
    expect(verdictTone('maybe')).toBe('neutral');
  });
});

describe('permissionView — 段内措辞（AC2/AC4：说了没有，也不填 0）', () => {
  it('零审批的会话：权限档 null + 「无待审批」「尚无裁决」都**说出来**', () => {
    const view = permissionView(initConversation('p'));
    expect(view.policy).toBeNull();
    expect(view.pendingLabel).toBe('无待审批');
    expect(view.decisionsLabel).toBe('尚无裁决');
    expect(view.pending).toEqual([]);
    expect(view.decisions).toEqual([]);
  });

  it('有待审批：计数如实，条目带工具名与动作类型（供 UI 指认）', () => {
    const view = permissionView(withApprovalRequest(initConversation('p'), 'ap-1', 1));
    expect(view.policy).toBe('read-only');
    expect(view.pendingLabel).toBe('1 条');
    expect(view.pending[0].tool_name).toBe('write');
    expect(view.pending[0].action_type).toBe('workspace-write');
  });

  it('已裁决：译成人话、带工具名与理由；待审批归零但仍明说', () => {
    let s = withApprovalRequest(initConversation('p'), 'ap-1', 1);
    s = withResolved(s, 'ap-1', 2, 'approve_once', '用户批准一次');
    const view = permissionView(s);
    expect(view.pendingLabel).toBe('无待审批');
    expect(view.decisionsLabel).toBe('1 条');
    expect(view.decisions[0]).toEqual({
      approval_id: 'ap-1',
      toolName: 'write',
      decision: 'approve_once',
      verdict: '批准（一次）',
      tone: 'allow',
      reason: '用户批准一次',
    });
  });

  it('配不上对的裁决：工具名 `—`，不编造', () => {
    const view = permissionView(withResolved(initConversation('p'), 'ap-orphan', 1, 'deny'));
    expect(view.decisions[0].toolName).toBe('—');
    expect(view.decisions[0].verdict).toBe('拒绝');
    expect(view.decisions[0].tone).toBe('deny');
  });
});
