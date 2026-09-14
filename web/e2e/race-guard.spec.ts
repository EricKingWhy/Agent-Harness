/** FE-04 e2e：useSession 竞态守卫在 catch 分支缺失。
 *
 * 缺陷模式：用户在旧请求（超时/失败）之后立即发起新请求，
 * 旧请求的 catch 可能在 gen 已被新请求自增后才触发，
 * 把新会话正在跑的 UI 态污染成 idle + 报错。
 *
 * 场景（真正交错竞态）：
 *   1. 发任务 A → mock 延迟 1500ms 后返回 500
 *   2. 在任务 A 尚在途时（不等 500 返回）立即发任务 B
 *   3. 任务 B 的 mock 立即返回成功 SSE 流
 *   4. ~1500ms 后任务 A 的 500 迟到 → catch 触发
 *   5. 修复前：setError('提交失败...') 污染任务 B → 红灯
 *      修复后：gen 守卫 return，不污染 → 绿灯
 *
 * 车道归属：Playwright e2e（同 continuation.spec.ts 约定）。 */

import { expect, test } from '@playwright/test';
import { fulfillSse, routeApi } from './fixtures';

const SUCCESS_FRAMES = [
  { type: 'session/started', seq: 1, session_id: 'race-session-b', run_id: 'race-run-b', time: '2026-09-08T00:00:00Z' },
  { type: 'run/started', seq: 2, session_id: 'race-session-b', run_id: 'race-run-b', time: '2026-09-08T00:00:00Z' },
  { type: 'user/message', data: { content: '任务B' }, seq: 3, session_id: 'race-session-b', run_id: 'race-run-b', step_id: 1, time: '2026-09-08T00:00:00Z' },
  { type: 'run/completed', data: {}, seq: 4, session_id: 'race-session-b', run_id: 'race-run-b', time: '2026-09-08T00:00:00Z' },
];

test('竞态守卫：旧请求迟到失败不污染新会话', async ({ page }) => {
  let postCount = 0;
  let secondPostHit = false;

  routeApi(page, {
    sessions: [],
    events: [],
    onSessionPost: async (route) => {
      postCount++;
      if (postCount === 1) {
        // 任务 A：延迟 1500ms 后返回 500——制造迟到失败
        await new Promise((r) => setTimeout(r, 1500));
        return route.fulfill({ status: 500, body: '{"detail":"server error"}', contentType: 'application/json' });
      }
      // 任务 B：立即返回成功 SSE 流
      secondPostHit = true;
      return fulfillSse(route, SUCCESS_FRAMES);
    },
  });

  await page.goto('/');

  // 发任务 A（将延迟失败）
  await page.getByLabel('Agent 任务').fill('任务A');
  await page.getByLabel('发送').click();

  // 不等任务 A 失败——立即发任务 B（制造交错竞态）
  await page.getByLabel('Agent 任务').fill('任务B');
  await page.getByLabel('发送').click();

  // 等待任务 B 的 POST 被拦截
  await expect.poll(() => secondPostHit).toBe(true);

  // 等任务 A 的迟到 500 返回（1500ms + 余量）
  await page.waitForTimeout(2500);

  // 关键断言：UI 不应显示任务 A 的 setError 污染
  // 修复前：旧请求的 catch 会 setError('提交失败：Start failed: 500')
  // 修复后：gen 守卫丢弃旧请求的迟到失败
  const errorText = page.locator('[role="alert"], .error, [data-testid="error-message"]');
  await expect(errorText).toHaveCount(0);
});
