/** 场景 H（spec 01 §22）：Trace Density 四档切换 + localStorage 持久化
 *  （冻结决策：四档 + 持久化；key = ahi.traceDensity）。 */

import { expect, test } from '@playwright/test';
import { routeApi } from './fixtures';

test('四档切换：data-density 即时生效，刷新后持久', async ({ page }) => {
  routeApi(page, {});
  await page.goto('/');

  await page.getByRole('radio', { name: '紧凑' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');

  await page.getByRole('radio', { name: 'Raw' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-density', 'raw');
  await expect(page.locator('html')).not.toHaveAttribute('data-density', 'compact');

  // 刷新后持久（localStorage ahi.traceDensity）
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-density', 'raw');
  await page.getByRole('radio', { name: '均衡' }).click(); // 恢复默认档，不污染其它场景
  await expect(page.locator('html')).toHaveAttribute('data-density', 'balanced');
});
