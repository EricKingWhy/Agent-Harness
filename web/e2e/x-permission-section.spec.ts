/** 场景：#184 Inspector PERMISSION 段（权限档 / 待审批 / 裁决结果）。
 *
 *  锁三件事：
 *  - **权限档如实**：唯一带运行时证据的来源是审批请求里的 `policy`；没有审批事件时
 *    显示 `—` 并说明原因（AC4：拿不到就说拿不到，不填 0、不拿 composer 的选择冒充）；
 *  - **"没有"要说出来**（AC2）：零待审批显示「无待审批」、零裁决显示「尚无裁决」，
 *    整段不消失——段消失会被读成"这个会话没有权限概念"；
 *  - **能进审批面**（AC5）：点待审批行 → 中间主区的审批卡被脉冲高亮（反向联动）。
 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, fulfillSse, routeApi, submitTask, type FrameSpec } from './fixtures';

/** 与后端 `session/approval.py:56-72` 同形状的审批请求帧。 */
function approvalRequested(approvalId: string, seq: number, policy = 'read-only'): FrameSpec {
  return {
    type: 'tool/approval-requested',
    data: {
      approval_id: approvalId,
      tool_name: 'write',
      tool_call_id: 'tc-1',
      action_type: 'workspace-write',
      title: 'write (workspace-write)',
      description: '工具授权级别为 workspace-write，但当前策略为只读（read-only）。',
      arguments_preview: { path: 'demo.txt', content: 'HELLO' },
      permission: 'workspace-write',
      policy,
      reason: '工具授权级别为 workspace-write，但当前策略为只读（read-only）。',
      allowed_decisions: ['deny', 'approve_once'],
    },
    seq,
    session_id: SID,
    run_id: RUN,
    step_id: 1,
    time: T,
  };
}

const HEAD: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
  { type: 'user/message', data: { content: '写个文件' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
];

/** PERMISSION 段在 Inspector 的 Overview（= `chat`）tab 里，默认 tab 是 Timeline。 */
const permissionSection = (page: import('@playwright/test').Page) =>
  page.locator('[data-section="permission"]');

async function openInspectorOverview(page: import('@playwright/test').Page, frames: FrameSpec[]) {
  routeApi(page, { onSessionPost: (route) => fulfillSse(route, frames), events: frames });
  await page.goto('/');
  await submitTask(page, '写个文件');
  await page
    .getByRole('tablist', { name: 'Inspector 视图' })
    .getByRole('tab', { name: 'Overview' })
    .click();
  await expect(permissionSection(page)).toBeVisible();
}

test('AC1/AC5：有待审批 → 段内出现权限档 + 待审批行；点它进入审批面（脉冲 + 卡片可见）', async ({
  page,
}) => {
  await openInspectorOverview(page, [...HEAD, approvalRequested('ap-1', 4)]);

  const section = permissionSection(page);
  // 权限档 = 审批请求携带的生效阈值（不是 composer 里"下次运行"的选择）。
  await expect(section).toContainText('权限档');
  await expect(section).toContainText('read-only');
  await expect(section).toContainText('1 条');

  const row = section.locator('.detail-permission-row');
  await expect(row).toHaveCount(1);
  await expect(row).toContainText('write');
  await expect(row).toContainText('workspace-write');

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();
  await row.click();
  // 「能进审批面」的可观测形式：跳转落点被脉冲高亮（复用 Timeline→主区的反向联动）。
  // 落点是包住卡片的 `[data-approval-key]` 容器（卡片本身不在虚拟化列表里，
  // 所以它由外层容器承担滚动定位与高亮——脉冲类加在容器上，不是 `.approval-card`）。
  await expect(page.locator('[data-approval-key="ap-1"]')).toHaveClass(/stream-jump-pulse/);
  await expect(card).toBeVisible();
});

test('AC2/AC4：零审批的会话段不消失——权限档 `—` 并说明原因，两项"没有"都说出来', async ({
  page,
}) => {
  const frames: FrameSpec[] = [
    ...HEAD,
    { type: 'model/completed', data: { text: '好了' }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'run/completed', data: {}, seq: 5, session_id: SID, run_id: RUN, time: T },
  ];
  await openInspectorOverview(page, frames);

  const section = permissionSection(page);
  await expect(section).toContainText('无待审批');
  await expect(section).toContainText('尚无裁决');
  // AC4：权限档拿不到 → `—`（**不是** 0、不是任何占位档位名），并说明为什么拿不到。
  // 按行取（`.detail-val-muted` 在段内还有"无待审批/尚无裁决"两处，不能整段模糊匹配）。
  await expect(section.locator('.detail-row', { hasText: '权限档' })).toContainText('—');
  await expect(section).toContainText('本会话无审批事件，生效阈值无从得知');
  // 零待审批 → 没有可点的行（不画假按钮）。
  await expect(section.locator('.detail-permission-row')).toHaveCount(0);
});

test('AC1：决议后 → 移出待审批并留痕到"已裁决"（工具名 + 人话裁决 + 理由）', async ({ page }) => {
  const frames: FrameSpec[] = [
    ...HEAD,
    approvalRequested('ap-1', 4),
    {
      type: 'permission/resolved',
      data: { approval_id: 'ap-1', decision: 'deny', reason: '用户拒绝' },
      seq: 5,
      session_id: SID,
      run_id: RUN,
      step_id: 1,
      time: T,
    },
  ];
  await openInspectorOverview(page, frames);

  const section = permissionSection(page);
  await expect(section).toContainText('无待审批');
  await expect(section).toContainText('1 条');
  const decision = section.locator('.detail-permission-decision');
  await expect(decision).toHaveCount(1);
  await expect(decision).toContainText('拒绝');
  await expect(decision).toContainText('write');
  await expect(decision).toContainText('用户拒绝');
  // 出队后权限档仍可得（从事件流读，不是从队列读）——这正是"决议即出队"的坑。
  await expect(section).toContainText('read-only');
});
