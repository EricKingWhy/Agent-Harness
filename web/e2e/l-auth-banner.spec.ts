/** 场景 L：401 引导横幅（后端起身份令牌要求时前端该做什么）。
 *
 * 起因：控制面清点（45 个 `<button>` 逐个核对）发现 `auth-banner-close`
 * （aria-label「关闭提示」）是**全 UI 唯一从未被点过**的按钮。它在本地开发环境
 * **不可达**：后端只在配置了 `jwt_secret` 时才校验并要求令牌
 * （`web/app.py:594` fail-open，`config.py:47` 默认 `None`），故横幅永不出现。
 * 与其重启后端加密钥（改动后端状态、且超出前端范围），这里按后端**已冻结的契约
 * 形状**（`lib/auth.ts` 文档：匿名 → 401 `{"detail":"Missing identity token"}`）造 401。
 *
 * 覆盖分工（两层，别混为一谈）：
 *  - `lib/api.test.ts` 的「401 → UnauthorizedError + onUnauthorized 广播」组：
 *    分类与广播（含 body 非 JSON 的回退文案）；
 *  - 本文件：广播**之后**的 UI——横幅出现、可关、以及再次 401 时的真实反应。 */

import { expect, test } from '@playwright/test';
import { routeApi } from './fixtures';

const UNAUTHORIZED_BODY = '{"detail":"Missing identity token"}';

test('401 → 引导横幅出现；可点「关闭提示」关掉；再有 401 会重新出现', async ({ page }) => {
  // 正常兜底：除会话列表外一律 200 空响应（横幅只由 401 触发）
  routeApi(page, { sessions: [] });
  // 后注册的路由优先：会话列表**始终** 401，复现「后端要求令牌」的持续状态。
  // 不搞「先 401 后 200」的开关——那会让「关闭后不再复现」变成一句空断言
  // （实测横幅出现后到关闭前**没有任何** /api/sessions 请求，200 分支根本不会执行）。
  //
  // 尾部的 `*` 不是可有可无的：Playwright 的 glob 是**整串**匹配，`**/api/sessions`
  // 匹配不了带查询串的 URL。而列表请求自 #171 起恒带 `?include_archived=true`
  // （前端总是要全量、可见性交给投影层），少了这个 `*` 本用例会静默走 routeApi 的
  // 200 分支 → 横幅永不出现、断言红在一个与 401 毫无关系的地方。`*` = `[^/]*`，
  // 所以它只多吃查询串，不会把 `/api/sessions/{id}/…` 这些端点也吞进来。
  await page.route('**/api/sessions*', (route) =>
    route.fulfill({ status: 401, contentType: 'application/json', body: UNAUTHORIZED_BODY }),
  );

  await page.goto('/');
  const banner = page.locator('.auth-banner');
  await expect(banner).toBeVisible();
  // 断言这是**鉴权**横幅（文案是静态的，detail 的传播由 api.test.ts 的单测覆盖）
  await expect(banner).toContainText('身份令牌');

  // 唯一出口：关闭按钮（本用例存在的理由——该按钮此前零覆盖）
  await page.getByRole('button', { name: '关闭提示', exact: true }).click();
  await expect(banner).toBeHidden();
  // 关的是横幅、不是整页：顶栏必须还在（否则「点崩了」也会让 toBeHidden 通过）
  await expect(page.getByRole('button', { name: 'API 身份令牌设置' })).toBeVisible();

  // 真实行为（此前注释把这里说反了）：关闭**不是**永久忽略。
  // 走应用内真实路径「配置令牌」→ `onTokenChange` 先 setAuthRequired(false) 并
  // 立即 refreshSessions()（App.tsx:151-154）；后端仍 401 → 广播 → 横幅回来。
  await page.getByRole('button', { name: 'API 身份令牌设置' }).click();
  await page.locator('.auth-panel input').first().fill('eyJhbGciOiJIUzI1NiJ9.dummy.sig');
  await page.locator('.auth-panel-save').click();
  await expect(banner).toBeVisible();
});
