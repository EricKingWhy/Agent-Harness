/** F3 e2e：Context Providers 多选控件交互。
 *
 * 验收项：
 *   - 目录非空 → ContextProviderPicker 渲染
 *   - 目录空 → 不渲染（return null）
 *   - 键盘 toggle 选中/取消
 *   - trigger 显示选中数量
 *   - POST body 的 context_providers 是 string[]
 *
 * 车道归属：Playwright e2e（同 control-row.spec.ts 约定）。 */

import { expect, test } from '@playwright/test';
import { CONTEXT_PROVIDERS, PERMISSION_MODES, fulfillSse, routeApi } from './fixtures';

const frames = [
  { type: 'session/started', seq: 1, session_id: 'e2e-cp-session', run_id: 'e2e-cp-run', time: '2026-09-08T00:00:00Z' },
  { type: 'run/started', seq: 2, session_id: 'e2e-cp-session', run_id: 'e2e-cp-run', time: '2026-09-08T00:00:00Z' },
  { type: 'user/message', data: { content: 'context providers 测试' }, seq: 3, session_id: 'e2e-cp-session', run_id: 'e2e-cp-run', step_id: 1, time: '2026-09-08T00:00:00Z' },
  { type: 'run/completed', data: {}, seq: 4, session_id: 'e2e-cp-session', run_id: 'e2e-cp-run', time: '2026-09-08T00:00:00Z' },
];

test('ContextProviderPicker：目录非空 → 渲染；键盘 toggle + POST string[]', async ({ page }) => {
  let capturedBody: string | null = null;

  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: PERMISSION_MODES,
    contextProviders: CONTEXT_PROVIDERS,
    onSessionPost: (route) => {
      const req = route.request();
      capturedBody = req.postData() ?? '';
      return fulfillSse(route, frames);
    },
  });

  await page.goto('/');

  // ContextProviderPicker 在场
  const ctxTrigger = page.locator('.composer-control[aria-label="Context Providers"]');
  await expect(ctxTrigger).toBeVisible();
  // 初始 placeholder——未选
  await expect(ctxTrigger).toContainText('Context');

  // 键盘打开浮层
  await ctxTrigger.focus();
  await page.keyboard.press('Enter');
  // 浮层已开——用 listbox 判定（CONTEXT_PROVIDERS 仅 2 条 → 搜索框隐藏 → combobox 不可见，F-DEFER-1）
  const listbox = page.locator('[role="listbox"]:visible').last();
  await expect(listbox).toBeVisible();
  // 两个 option 在场
  await expect(page.locator('[role="option"]')).toHaveCount(2);
  // FE-R11-06：多选列表要自报多选语义，否则 AT 会把 aria-selected 当单选高亮读
  await expect(listbox).toHaveAttribute('aria-multiselectable', 'true');
  // FE-R11-04 修复后开箱即落在 cmdk root 内（旧代码这里需要手动 focus 兜底）。
  // 仍显式 focus 一次：本用例后续连按 Enter/ArrowDown，多一层保险不亏。
  await expect
    .poll(() =>
      page.evaluate(() => !!document.activeElement?.closest('[cmdk-root]')),
    )
    .toBe(true);
  await listbox.focus();

  // 勾选态对 AT 可见（FE-R11-06）：画在 aria-hidden checkbox 上的 ☑ 读不到，
  // 状态必须落在 role="option" 的 aria-checked 上——cmdk 只硬写 aria-selected。
  const firstOption = page.locator('[role="option"]').first();
  await expect(firstOption).toHaveAttribute('aria-checked', 'false');

  // Enter 选中第一项（memory）——多选模式不关闭 popover
  await page.keyboard.press('Enter');
  // trigger 显示选中数量
  await expect(ctxTrigger).toContainText('Context · 1');
  await expect(firstOption).toHaveAttribute('aria-checked', 'true');

  // ArrowDown 移到第二项（skills），Enter 选中
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(ctxTrigger).toContainText('Context · 2');
  await expect(page.locator('[role="option"]').nth(1)).toHaveAttribute('aria-checked', 'true');

  // Esc 关闭浮层
  await page.keyboard.press('Escape');
  await expect(page.locator('[role="listbox"]')).toBeHidden();

  // 提交任务
  await page.getByLabel('Agent 任务').fill('cp 测试');
  await page.getByLabel('发送').click();

  // 等待 POST 被拦截
  await expect.poll(() => capturedBody).not.toBeNull();

  const body = JSON.parse(capturedBody!);
  // context_providers 是 string[]，包含 memory 和 skills
  expect(body.context_providers).toEqual(['memory', 'skills']);
});

test('ContextProviderPicker：目录空 → 不渲染', async ({ page }) => {
  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: PERMISSION_MODES,
    // contextProviders 不传 → mock 返 [] → 空目录降级
    onSessionPost: (route) => fulfillSse(route, frames),
  });

  await page.goto('/');

  // ContextProviderPicker 不在场——空目录 return null
  const ctxTrigger = page.locator('.composer-control[aria-label="Context Providers"]');
  await expect(ctxTrigger).toHaveCount(0);
});
