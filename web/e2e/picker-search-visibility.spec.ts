/** F-DEFER-1 e2e：搜索框按目录长度显示/隐藏。
 *
 * 背景：三个 picker（ModelPicker / ControlPicker / ContextProviderPicker）都挂了
 * `model-picker-search-wrap${长目录 ? '' : ' hidden'}`，但 CSS 里从来没有
 * `.model-picker-search-wrap.hidden { display: none }` 规则——class 挂了等于没挂，
 * 短目录下搜索框一直显示。本 spec 锁死修复后的行为：
 *
 *   - 短目录（≤5 条）→ `.model-picker-search-wrap` 不可见（display:none）；
 *   - 长目录（>5 条）→ 可见。
 *
 * ⚠️ 两条实测陷阱（探针验证，见下方注释）：
 *   1. cmdk 把 `role="combobox"` 放在 CommandInput 本身。搜索框隐藏 = 该 role
 *      也从 a11y 树里消失。**不能用 combobox 当「浮层已开」的信号**，否则短目录
 *      用例必然假失败。正确信号是 `[role="listbox"]`（CommandList）或
 *      `[role="dialog"]`（Radix popover），二者恒可见。
 *   2. cmdk 要求 CommandInput 始终留在 DOM（不能条件卸载），所以断言用
 *      toBeHidden() 而非 toHaveCount(0)——元素必须在场，只是不可见。
 *
 * 阈值速查（源码）：
 *   ModelPicker:  models.length + 1 > 5   → 默认链算 1 条
 *   ControlPicker / ContextProviderPicker: entries.length > 5
 *
 * 车道归属：Playwright e2e（浮层内内容在关闭态不渲染，SSR/单测断不到）。 */

import { expect, test } from '@playwright/test';
import { CONTEXT_PROVIDERS, LONG_MODELS, MODELS, PERMISSION_MODES, longCatalog, routeApi } from './fixtures';

// 长目录统一来自 fixtures（避免三处内联后静默漂移，见 fixtures.ts「长目录 fixture」段）。
const LONG_MODES = longCatalog('mode', 6);

const searchWrap = (page: import('@playwright/test').Page) => page.locator('.model-picker-search-wrap');

test('短目录：ModelPicker 搜索框不可见（F-DEFER-1 修复回归）', async ({ page }) => {
  routeApi(page, { sessions: [], events: [], models: MODELS }); // 3 条 → +1 = 4 ≤ 5
  await page.goto('/');

  const trigger = page.locator('.composer-model[aria-label="模型选择"]');
  await expect(trigger).toBeVisible();
  await trigger.focus();
  await page.keyboard.press('Enter');

  // 浮层已开——listbox/dialog 恒可见（combobox 会随输入框一起隐藏，不能用作信号）
  await expect(page.locator('[role="listbox"]')).toBeVisible();
  // 搜索框必须在场但不可见——修复前此处会失败（display:flex 一直显示）
  await expect(searchWrap(page)).toHaveCount(1);
  await expect(searchWrap(page)).toBeHidden();
});

test('长目录：ModelPicker 搜索框可见（+combobox 可交互）', async ({ page }) => {
  routeApi(page, { sessions: [], events: [], models: LONG_MODELS }); // 7 条 → +1 = 8 > 5
  await page.goto('/');

  const trigger = page.locator('.composer-model[aria-label="模型选择"]');
  await trigger.focus();
  await page.keyboard.press('Enter');

  await expect(page.locator('[role="listbox"]')).toBeVisible();
  await expect(searchWrap(page)).toHaveCount(1);
  await expect(searchWrap(page)).toBeVisible();
  // 长目录下输入框真的能用（反证 hidden 是显示而非卸载）
  await page.locator('.model-picker-search').fill('claude');
  await expect(page.locator('[role="option"]')).toHaveCount(1);
});

test('短目录：ControlPicker（权限模式）搜索框不可见', async ({ page }) => {
  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: PERMISSION_MODES, // 3 条 ≤ 5 → 隐藏
  });
  await page.goto('/');

  const trigger = page.locator('.composer-control[aria-label="权限模式"]');
  await expect(trigger).toBeVisible();
  await trigger.focus();
  await page.keyboard.press('Enter');

  await expect(page.locator('[role="listbox"]')).toBeVisible();
  await expect(searchWrap(page)).toHaveCount(1);
  await expect(searchWrap(page)).toBeHidden();
});

test('长目录：ControlPicker（权限模式）搜索框可见', async ({ page }) => {
  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: LONG_MODES, // 6 > 5
  });
  await page.goto('/');

  const trigger = page.locator('.composer-control[aria-label="权限模式"]');
  await trigger.focus();
  await page.keyboard.press('Enter');

  await expect(page.locator('[role="listbox"]')).toBeVisible();
  await expect(searchWrap(page)).toHaveCount(1);
  await expect(searchWrap(page)).toBeVisible();
});

test('短目录：ContextProviderPicker 搜索框不可见', async ({ page }) => {
  routeApi(page, {
    sessions: [],
    events: [],
    contextProviders: CONTEXT_PROVIDERS, // 2 条 ≤ 5
  });
  await page.goto('/');

  const trigger = page.locator('.composer-control[aria-label="Context Providers"]');
  await expect(trigger).toBeVisible();
  await trigger.focus();
  await page.keyboard.press('Enter');

  await expect(page.locator('[role="listbox"]')).toBeVisible();
  await expect(searchWrap(page)).toHaveCount(1);
  await expect(searchWrap(page)).toBeHidden();
});
