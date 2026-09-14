/** F1-Fix3: 6 档宽度 GUI QA 回归。
 *  验证 composer-controls 在不同宽度下不溢出、不破坏响应式布局。
 *  B1 spec 要求：6 档宽度（1440/1280/1024/820/768/浅色）回归。 */

import { expect, test } from '@playwright/test';
import {
  AGENT_PROFILES,
  PERMISSION_MODES,
  REASONING_EFFORTS,
  fulfillSse,
  routeApi,
} from './fixtures';

const frames = [
  { type: 'session/started', seq: 1, session_id: 'e2e-vqa', run_id: 'e2e-vqa-run', time: '2026-09-08T00:00:00Z' },
  { type: 'run/started', seq: 2, session_id: 'e2e-vqa', run_id: 'e2e-vqa-run', time: '2026-09-08T00:00:00Z' },
  { type: 'user/message', data: { content: 'GUI QA' }, seq: 3, session_id: 'e2e-vqa', run_id: 'e2e-vqa-run', step_id: 1, time: '2026-09-08T00:00:00Z' },
  { type: 'run/completed', data: {}, seq: 4, session_id: 'e2e-vqa', run_id: 'e2e-vqa-run', time: '2026-09-08T00:00:00Z' },
];

const WIDTHS = [1440, 1280, 1024, 820, 768];

for (const width of WIDTHS) {
  test(`Composer control row 在 ${width}px 宽度下不溢出`, async ({ page }) => {
    routeApi(page, {
      sessions: [],
      events: [],
      permissionModes: PERMISSION_MODES,
      agentProfiles: AGENT_PROFILES,
      reasoningEfforts: REASONING_EFFORTS,
      onSessionPost: (route) => fulfillSse(route, frames),
    });

    await page.setViewportSize({ width, height: 800 });
    await page.goto('/');

    // 控件行在场
    const controls = page.locator('.composer-controls');
    await expect(controls).toBeVisible();

    // 控件行不超出 composer-dock 边界
    const dockBox = await page.locator('.composer-dock').boundingBox();
    const controlsBox = await controls.boundingBox();
    expect(controlsBox).not.toBeNull();
    expect(dockBox).not.toBeNull();
    expect(controlsBox!.x).toBeGreaterThanOrEqual(dockBox!.x);
    expect(controlsBox!.x + controlsBox!.width).toBeLessThanOrEqual(dockBox!.x + dockBox!.width + 1);

    // 四个控件 trigger 在场（ModelPicker 空 → 不渲染；三个 ControlPicker 在场）
    await expect(page.locator('.composer-control')).toHaveCount(3);
  });
}

test('Composer control row 在浅色模式下可见', async ({ page }) => {
  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: PERMISSION_MODES,
    agentProfiles: AGENT_PROFILES,
    reasoningEfforts: REASONING_EFFORTS,
    onSessionPost: (route) => fulfillSse(route, frames),
  });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/');

  // 切换到浅色模式
  await page.evaluate(() => {
    document.documentElement.setAttribute('data-theme', 'light');
  });

  // 控件行仍然可见
  const controls = page.locator('.composer-controls');
  await expect(controls).toBeVisible();

  // trigger 文本可读（非透明）
  const trigger = page.locator('.composer-control').first();
  const color = await trigger.evaluate((el) => window.getComputedStyle(el).color);
  expect(color).not.toBe('rgba(0, 0, 0, 0)');
});

test('Inspector 时间线 run 分组头 + 头标对齐（UI-03）', async ({ page }) => {
  const T0 = '2026-09-12T00:00:00Z';
  const ROW2 = {
    session_id: 'e2e-two-run', event_count: 7, first_event_time: T0, last_event_time: T0,
    first_user_message: '两轮任务', trace_id: null, trace_url: null,
  };
  const EVENTS2 = [
    { type: 'session/started', seq: 1, session_id: 'e2e-two-run', run_id: 'r1', time: T0 },
    { type: 'run/started', seq: 2, session_id: 'e2e-two-run', run_id: 'r1', time: T0 },
    { type: 'user/message', data: { content: '第一轮' }, seq: 3, session_id: 'e2e-two-run', run_id: 'r1', step_id: 1, time: T0 },
    { type: 'run/completed', data: {}, seq: 4, session_id: 'e2e-two-run', run_id: 'r1', time: T0 },
    { type: 'run/started', seq: 5, session_id: 'e2e-two-run', run_id: 'r2', time: T0 },
    { type: 'user/message', data: { content: '第二轮' }, seq: 6, session_id: 'e2e-two-run', run_id: 'r2', step_id: 2, time: T0 },
    { type: 'text/delta', data: { delta: '完成' }, seq: 7, session_id: 'e2e-two-run', run_id: 'r2', step_id: 2, time: T0 },
  ];
  routeApi(page, {
    sessions: [ROW2],
    events: EVENTS2,
    permissionModes: PERMISSION_MODES,
    agentProfiles: AGENT_PROFILES,
    reasoningEfforts: REASONING_EFFORTS,
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.locator('.session-item').first().click();

  // Timeline tab → 两个分组头：序数、状态徽章、计数
  await page.locator('.detail-tab[title="Timeline"]').click();
  const headers = page.locator('.tl-run-header');
  await expect(headers).toHaveCount(2);
  await expect(headers.first()).toContainText('Run 1');
  await expect(headers.first()).toContainText('已完成');
  await expect(headers.first()).toContainText('4 事件');
  await expect(headers.nth(1)).toContainText('Run 2');
  await expect(headers.nth(1)).toContainText('进行中');

  // 头标对齐：描述全会话范围，不再显示单个 run_id 短码
  await expect(page.locator('.detail-run-id')).toHaveText('2 runs · 7 事件');

  // tab 计数徽章（识别而非回忆）
  await expect(page.locator('.detail-tab[title="Timeline"] .detail-tab-count')).toHaveText('7');
});
