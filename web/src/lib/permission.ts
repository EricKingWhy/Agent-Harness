/** Inspector PERMISSION 段（#184）的派生视图与措辞。
 *
 *  为什么单独一个模块：本仓没有 jsdom，组件测试是 SSR 渲染，交互与**措辞规则**只能靠
 *  "纯函数 + 单测"覆盖。把"无待审批怎么说""拿不到权限档叫什么"这类判断放在这里，
 *  组件就只剩接线（与 `lib/commandOutput`、`lib/capabilities` 同一路数）。
 *
 *  **两条不许违反的规则**（PRD §4 No fake values）：
 *  1. 拿不到的数据渲染 `—`（或如实说明为什么拿不到），**不填 0、不编占位数字**；
 *  2. "没有"要**说出来**（"无待审批"），而不是让整段消失——段消失会被读成"这个会话
 *     没有权限概念"，那是另一回事（AC2）。
 */
import type { ApprovalDecision, ConversationState, PendingApproval } from '../types';

/** 决策词汇 → 人话。只覆盖后端 `PermissionDecision` 今天兑现的两档 + 预留两档；
 *  **未知值原样返回**（见 `decisionLabel`）。 */
const DECISION_LABELS: Record<string, string> = {
  deny: '拒绝',
  approve_once: '批准（一次）',
  approve_session: '批准（会话）',
  approve_policy: '批准（策略）',
};

/** 决策 → 人话。未知值**原样返回**：后端将来新增粒度时，显示原始字符串比显示
 *  "未知"更有信息量，也不会因为前端不认识就丢掉一个真实发生过的裁决。
 *  空串（契约缺字段）→ `—`。 */
export function decisionLabel(decision: string): string {
  const known = Object.prototype.hasOwnProperty.call(DECISION_LABELS, decision)
    ? DECISION_LABELS[decision]
    : undefined;
  return known ?? (decision === '' ? '—' : decision);
}

/** 裁决的语义色档。**绿 = 已批准是一条断言**，所以只有真的 `approve*` 才涂绿；
 *  未知值与缺失值一律 `neutral`——否则一个缺字段的 `permission/resolved` 会被画成
 *  "已批准"的样子（把没发生的事画成发生过）。 */
export type VerdictTone = 'allow' | 'deny' | 'neutral';

export function verdictTone(decision: string): VerdictTone {
  if (decision === 'deny') return 'deny';
  if (decision.startsWith('approve')) return 'allow';
  return 'neutral';
}

export interface PermissionView {
  /** 生效的审批阈值（来自审批请求事件）；整个会话无审批 → null。 */
  policy: string | null;
  pending: PendingApproval[];
  /** 「无待审批」/「N 条」——AC2 要求零待审批时说出来，不让段消失。 */
  pendingLabel: string;
  decisions: {
    approval_id: string;
    /** 配不上对时 `—`（不猜工具名）。 */
    toolName: string;
    decision: string;
    verdict: string;
    tone: VerdictTone;
    reason: string;
  }[];
  /** 「尚无裁决」/「N 条」。 */
  decisionsLabel: string;
}

export function permissionView(state: ConversationState): PermissionView {
  // 三个真相都在投影状态上（`projection.ts` 逐事件折叠）——这里只做**措辞与结构**，
  // 不再多一层纯透传的"派生函数"（review 删掉了那层）。
  const { permission_policy: policy, pending_approvals: pending, approval_decisions: decisions } = state;
  return {
    policy,
    pending,
    pendingLabel: pending.length === 0 ? '无待审批' : `${pending.length} 条`,
    decisions: decisions.map((d: ApprovalDecision) => ({
      approval_id: d.approval_id,
      toolName: d.tool_name || '—',
      decision: d.decision,
      verdict: decisionLabel(d.decision),
      tone: verdictTone(d.decision),
      reason: d.reason,
    })),
    decisionsLabel: decisions.length === 0 ? '尚无裁决' : `${decisions.length} 条`,
  };
}
