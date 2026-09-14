/** 场景 I（spec 01 §22）：键盘可达——Ctrl/Cmd+K 唤起 palette、Esc 关闭、
 *  焦点落输入框；Composer ⌘+Enter 发送路径。 */

import { expect, test } from '@playwright/test';
import { routeApi, fulfillSse } from './fixtures';

test('palette 键盘唤起与关闭；Composer 键盘提交', async ({ page }) => {
  const frames = [
    { type: 'session/started', seq: 1, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
    { type: 'run/started', seq: 2, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
    { type: 'user/message', data: { content: '键盘提交' }, seq: 3, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', step_id: 1, time: '2026-09-07T00:00:00Z' },
    { type: 'run/completed', data: {}, seq: 4, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
  ];
  // 终态后 viewing 迁移重读历史（#22 对账）——sessions/events fixture 提供同一真相
  routeApi(page, {
    sessions: [{ session_id: 'e2e-session-0002', event_count: 4, first_event_time: '2026-09-07T00:00:00Z', last_event_time: '2026-09-07T00:00:00Z', first_user_message: '键盘提交', trace_id: null, trace_url: null }],
    events: frames,
    onSessionPost: (route) => fulfillSse(route, frames),
  });

  await page.goto('/');
  await page.keyboard.press('Control+k');
  await expect(page.locator('.palette-input')).toBeVisible();
  await expect(page.locator('.palette-input')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator('.palette-input')).toBeHidden();

  // Composer ⌘/Ctrl+Enter 发送（键盘路径不依赖鼠标）
  await page.getByLabel('Agent 任务').fill('键盘提交');
  await page.getByLabel('Agent 任务').press('Control+Enter');
  await expect(page.locator('.session-item')).toContainText('键盘提交');
});

test('palette 的 Copy Run ID 复制 run id，而不是 session id', async ({ page, context }) => {  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  // run id 与 session id 刻意不同：两个都是 UUID，抄错了粘出去才发现
  const frames = [
    { type: 'session/started', seq: 1, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
    { type: 'run/started', seq: 2, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
    { type: 'user/message', data: { content: '复制 run id' }, seq: 3, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', step_id: 1, time: '2026-09-07T00:00:00Z' },
    { type: 'model/completed', data: { content: '好。' }, seq: 4, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', step_id: 1, time: '2026-09-07T00:00:00Z' },
    { type: 'run/completed', data: {}, seq: 5, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
  ];
  routeApi(page, {
    sessions: [{ session_id: 'e2e-session-0002', event_count: 5, first_event_time: '2026-09-07T00:00:00Z', last_event_time: '2026-09-07T00:00:00Z', first_user_message: '复制 run id', trace_id: null, trace_url: null }],
    events: frames,
  });
  await page.goto('/');
  await page.locator('.session-item').first().click();
  await expect(page.locator('.turn')).toHaveCount(1);

  await page.keyboard.press('Control+k');
  // 用**英文**查询、点**中文**条目——一条测试锁两件事：label 已本地化（BUG-007），
  // 且英文说法仍经 keywords 命中（老用户的肌肉记忆不作废）。
  await page.locator('.palette-input').fill('Copy Run');
  await page.locator('.palette-item', { hasText: '复制 Run ID' }).click();
  await expect(page.locator('.palette-input')).toBeHidden();

  // copyText 内部是 `void navigator.clipboard.writeText(...)`（不 await）——点击
  // 返回时写可能还没落地，直接读会拿到空/旧值。轮询到写完成再断言。
  // 断言 run id（而非「不是 session id」）：后者在等值断言成立后是同义反复，
  // 且 run id 写错成 session id 时它才会失败——正是被测的那一个 bug。
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe('e2e-run-0002');
});

test('UI-06：palette 密度条目 CJK 间距 + 主题 hint 无箭头（真实渲染断言）', async ({ page }) => {
  const frames = [
    { type: 'session/started', seq: 1, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
    { type: 'run/started', seq: 2, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
    { type: 'user/message', data: { content: '密度' }, seq: 3, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', step_id: 1, time: '2026-09-07T00:00:00Z' },
    { type: 'run/completed', data: {}, seq: 4, session_id: 'e2e-session-0002', run_id: 'e2e-run-0002', time: '2026-09-07T00:00:00Z' },
  ];
  routeApi(page, {
    sessions: [{ session_id: 'e2e-session-0002', event_count: 4, first_event_time: '2026-09-07T00:00:00Z', last_event_time: '2026-09-07T00:00:00Z', first_user_message: '键盘提交', trace_id: null, trace_url: null }],
    events: frames,
  });
  await page.goto('/');
  await page.keyboard.press('Control+k');
  await expect(page.locator('.palette-input')).toBeVisible();

  // 中文查询「切换到」出全部密度档——label 形状是「切换到 + 空格 + 档名」
  await page.locator('.palette-input').fill('切换到');
  await expect(page.locator('.palette-item-label').first()).toContainText('切换到 紧凑');
  const rawLabel = await page.locator('.palette-item-label', { hasText: '切换到 Raw' }).textContent();
  expect(rawLabel).toBe('切换到 Raw');

  // 主题 hint 无方向箭头（UI-06 退役「→」装饰）。e2e 上下文默认 light 主题，
  // hint 是**目标**档位（'暗色'），不断言具体值——箭头消失本身就是本票要锁的形状。
  await page.locator('.palette-input').fill('切换主题');
  const themeHint = await page.locator('.palette-item-hint').first().textContent();
  expect(themeHint).not.toContain('→');
  expect(themeHint).toBe('暗色');
});
