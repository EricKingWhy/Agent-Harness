/** 联调车道：审批卡「批准」「拒绝」两键的真机证据（真后端 + 真模型 + 真浏览器
 *  点击，**无任何 `page.route` mock**）。
 *
 * 运行：`npx playwright test --config playwright.live.config.ts`（需后端已启动）。
 * 不入标准门禁——主车道（`playwright.config.ts`）只扫 `./e2e`，本目录不被其收录。
 *
 * 机制：`session/service.py:348` `interactive = permission_mode_explicit and
 * permission_mode != danger-full-access`——显式选一个权限档位即开启交互式审批；
 * 叠加 policy=read-only 时任何 WORKSPACE_WRITE 工具都会走 `_check_approval`
 * （`tooling/executor.py:659`）→ 发 `tool/approval-requested` → ApprovalCard 渲染。
 * 这把此前「`auto_approve` 硬编码 → 审批卡不可达」的登记**证伪**了。
 *
 * 确定性：模型是否真调工具、调哪个工具由模型决定，故本车道结果非确定——只作
 * 真机取证；**回归锁**是 hermetic 的 `e2e/n-approval-card.spec.ts`。
 *
 * 本地可能复用到「别的 worktree 起在 5173 的 dev server」（`reuseExistingServer`），
 * 那会测到错的构建——跑之前确认端口上的 server 就是本 worktree 的。 */

import { expect, test } from '@playwright/test';
import { pickControl } from '../e2e/fixtures';

const TASK_APPROVE = '必须调用工具：在工作区创建文件 live-approve.txt，内容写 APPROVED。不要只在回复里说。';
const TASK_DENY = '必须调用工具：在工作区创建文件 live-deny.txt，内容写 DENIED。不要只在回复里说。';

async function runUntilCard(page: import('@playwright/test').Page, task: string) {
  const approvals: { path: string; body: unknown }[] = [];
  page.on('request', (r) => {
    if (/\/approve$/.test(new URL(r.url()).pathname)) {
      approvals.push({ path: new URL(r.url()).pathname, body: r.postDataJSON() });
    }
  });
  await page.goto('/');
  // 显式选权限档位：read-only（真目录第一项）——这一步是「交互式审批」的开关。
  // 目录若重排，这里会因文案断言不符而**明确变红**（不会静默选错档位）。
  await pickControl(page, '权限模式', 0, '只读');
  await page.getByLabel('Agent 任务').fill(task);
  await page.getByLabel('发送').click();
  const card = page.locator('.approval-card');
  // 真模型往返 + 工具调用，给足时间（后端审批超时 300s，fail-closed）
  await expect(card).toBeVisible({ timeout: 240_000 });
  await expect(card.locator('.approval-title')).toHaveText('需要审批');
  await expect(card.locator('code')).toContainText(/\w/); // 工具名真实渲染
  return { card, approvals };
}

/** 读后端 durable 事件里的已决决策。
 *
 *  为什么必须查后端：`ApprovalCard` 的 `catch` 对**任何**错误都会把标题翻成
 *  已批准/已拒绝（`ApprovalCard.tsx:29-31`），所以「标题变了」**不能**证明决策
 *  真的落库——POST 失败时 UI 也会看起来成功。只有 JSONL 里的
 *  `permission/resolved` 才是判决书。 */
function resolvedDecisions(page: import('@playwright/test').Page, approvePath: string) {
  const sid = approvePath.split('/')[3]; // /api/sessions/{sid}/approve
  return async (): Promise<string[]> => {
    const res = await page.request.get(`/api/sessions/${sid}/events`);
    const evs = (await res.json()) as { type?: string; data?: { decision?: string } }[];
    return evs.filter((e) => e.type === 'permission/resolved').map((e) => String(e.data?.decision ?? ''));
  };
}

test('LIVE 批准：审批卡渲染 → 点「批准」→ 已批准 + 后端落库 approve_once', async ({ page }) => {
  const { card, approvals } = await runUntilCard(page, TASK_APPROVE);
  await card.screenshot({ path: 'test-results/live-approval-before.png' });

  await card.locator('.approval-approve').click();
  await expect(card.locator('.approval-title')).toHaveText('已批准');
  await expect(card.locator('.approval-actions')).toHaveCount(0); // 决后按钮消失

  expect(approvals).toHaveLength(1);
  expect(approvals[0].body).toMatchObject({ approved: true, decision: 'approve_once' });
  // 关键断言：决策真落库（POST 失败时 `catch` 也会把 UI 翻成「已批准」，故上面几条不足以证明）
  await expect
    .poll(resolvedDecisions(page, approvals[0].path), { timeout: 30_000 })
    .toContain('approve_once');
  await page.screenshot({ path: 'test-results/live-approval-approved.png' });
});

test('LIVE 拒绝：审批卡渲染 → 点「拒绝」→ 已拒绝 + 后端落库 deny', async ({ page }) => {
  const { card, approvals } = await runUntilCard(page, TASK_DENY);

  await card.locator('.approval-deny').click();
  await expect(card.locator('.approval-title')).toHaveText('已拒绝');
  await expect(card.locator('.approval-actions')).toHaveCount(0);

  expect(approvals).toHaveLength(1);
  expect(approvals[0].body).toMatchObject({ approved: false, decision: 'deny' });
  await expect
    .poll(resolvedDecisions(page, approvals[0].path), { timeout: 30_000 })
    .toContain('deny');
  await page.screenshot({ path: 'test-results/live-approval-denied.png' });
});
