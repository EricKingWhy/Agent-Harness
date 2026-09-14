/** 场景（#171）：会话**归档**——可逆的列表可见性标记。
 *
 *  契约来源：issue #171 前端半（后端半 `feat/backend 9e4adc0`，
 *  `POST/DELETE /api/sessions/{id}/archive` + `GET /api/sessions?include_archived=`）
 *  与 ADR-0004 R5 Q18。
 *
 *  本 spec 断言的四件事，以及为什么每件都要**真的**考：
 *
 *  1. **默认收起是真收起**（AC8/AC10）：归档行不在默认列表里，开关打开才出现。
 *     mock 的 `GET /api/sessions` 按真后端语义过滤 `include_archived`（见
 *     `fixtures.ts` 那一支）——所以"UI 总是显式要全量、可见性由投影层决定"这条
 *     设计只要**漏掉参数**就会在这里变红（前端本地过滤救不了）。
 *  2. **徽标说的是真值**：行上的「已归档」只在载荷里的 `archived === true` 时渲染，
 *     不是"因为被开关藏起来过"就贴一个。开关关掉再打开，徽标不许自己长出来。
 *  3. **「n 条会话日志缺失」不许把归档算进去**（本票修掉的跨端缺陷）：被开关过滤掉的
 *     行**不是**日志缺失——它就在载荷里，只是没渲染。所以计数必须恰好等于"账本里有、
 *     载荷里压根没有"的条数（本 fixture = 1，只有 `s-gone`）。修之前那句会报 2。
 *  4. **可逆动作不做二次确认**（AC11）、**失败说话**（AC9）：归档 200 就地生效、
 *     没有确认面；409 时原样贴出后端 detail 且列表保持原样。取消归档**永不** 409
 *     （后端守卫是 `archived and get_active(...)` 的连词）——这条不对称也在这里锁住。
 */

import { expect, test, type Page } from '@playwright/test';
import { routeApi, rowOf, sessionRow, type ApiMock } from './fixtures';

const P1 = { id: 'p1', path: 'D:/repos/alpha', title: '项目 alpha', session_ids: [] as string[] };
const PROJECT = { ...P1, session_ids: ['s-keep', 's-arch', 's-gone'] };

/** 一行未归档 + 一行已归档（都在 p1 账本里）+ 一个**只存在于账本**的 id（s-gone）。
 *
 *  `s-gone` 是必需的反向对照：没有它，`missing === 0` 与"根本没算过"同形，第 3 条
 *  断言就会在"前端干脆不显示缺失"的实现下也变绿。 */
function railMock(over: Partial<ApiMock> = {}): ApiMock {
  return {
    projects: [PROJECT],
    sessions: [
      sessionRow('s-keep', { id: 'p1', title: '项目 alpha' }),
      sessionRow('s-arch', { id: 'p1', title: '项目 alpha' }, { archived: true }),
    ],
    ...over,
  };
}

const toggle = (page: Page) => page.locator('.rail-archived-toggle');
/** 打开某行的 kebab 菜单。 */
const openMenu = (page: Page, sessionId: string) =>
  rowOf(page, sessionId).locator('.rail-menu-btn').click();

/** 收集 `/api/sessions`（列表）请求的完整 URL——"UI 总要全量"的形状锁。 */
function collectListUrls(page: Page): string[] {
  const urls: string[] = [];
  page.on('request', (req) => {
    const url = new URL(req.url());
    if (url.pathname === '/api/sessions' && req.method() === 'GET') urls.push(req.url());
  });
  return urls;
}

test('默认收起归档行 + 徽标是真值 + 缺失计数不算归档 + 开关状态跨刷新保留', async ({ page }) => {
  const listUrls = collectListUrls(page);
  await routeApi(page, railMock());
  await page.goto('/');

  // ── 默认：归档行不在列表里，开关未按下 ──
  await expect(rowOf(page, 's-keep')).toBeVisible();
  await expect(rowOf(page, 's-arch')).toHaveCount(0);
  await expect(toggle(page)).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('.session-item-archived')).toHaveCount(0);

  // ── 第 3 条：缺失计数只说真话（1 = 只有 s-gone）。归档行被开关过滤掉，不算缺失 ──
  await expect(page.locator('.rail-project-missing')).toHaveText('1 条会话日志缺失');

  // ── 第 1 条的形状锁：每次列表请求都显式要了全量 ──
  expect(listUrls.length).toBeGreaterThan(0);
  for (const url of listUrls) expect(url).toContain('include_archived=true');

  // ── 打开开关：归档行出现，徽标挂在**它**身上（未归档那行没有） ──
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute('aria-pressed', 'true');
  await expect(rowOf(page, 's-arch')).toBeVisible();
  await expect(rowOf(page, 's-arch').locator('.session-item-archived')).toHaveText('已归档');
  await expect(rowOf(page, 's-keep').locator('.session-item-archived')).toHaveCount(0);
  // 开关只改投影：可见性变了，缺失计数不变（s-gone 是唯一真缺失）。
  await expect(page.locator('.rail-project-missing')).toHaveText('1 条会话日志缺失');

  // ── 再关掉：徽标跟着消失（它不是"曾经藏过"的痕迹） ──
  await toggle(page).click();
  await expect(rowOf(page, 's-arch')).toHaveCount(0);
  await expect(page.locator('.session-item-archived')).toHaveCount(0);

  // ── 开关是持久化的**视图状态**（AC10）：刷新后仍然打开、归档行仍然可见 ──
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute('aria-pressed', 'true');
  await page.reload();
  await expect(toggle(page)).toHaveAttribute('aria-pressed', 'true');
  await expect(rowOf(page, 's-arch')).toBeVisible();
  await expect(rowOf(page, 's-arch').locator('.session-item-archived')).toHaveText('已归档');
});

test('归档 / 取消归档可逆、就地进行、不弹确认面', async ({ page }) => {
  const calls: string[] = [];
  await routeApi(
    page,
    railMock({
      onArchiveRequest: (route, sessionId, archived) => {
        calls.push(`${route.request().method()} ${sessionId} ${String(archived)}`);
        return false; // 交给 fixture 的默认分支（真改状态 + 真回执）
      },
    }),
  );
  await page.goto('/');
  await expect(rowOf(page, 's-keep')).toBeVisible();

  // ── 归档：菜单项说「归档」，点完不弹任何确认面 ──
  await openMenu(page, 's-keep');
  await page.getByRole('menuitem', { name: '归档', exact: true }).click();

  // 行从默认视图里消失——但它**还在载荷里**（下面开关一开就回来），所以这不是删除。
  await expect(rowOf(page, 's-keep')).toHaveCount(0);
  // AC11：可逆动作不要确认面。硬删（#172）走的是 `.project-dialog` 那条路，这里必须没有。
  await expect(page.locator('.project-dialog')).toHaveCount(0);
  await expect(page.locator('[role="alertdialog"]')).toHaveCount(0);
  await expect(page.locator('.rail-error')).toHaveCount(0);

  // ── 开关打开：它带着真徽标回来，菜单项翻成「取消归档」 ──
  await toggle(page).click();
  await expect(rowOf(page, 's-keep').locator('.session-item-archived')).toHaveText('已归档');
  await openMenu(page, 's-keep');
  await page.getByRole('menuitem', { name: '取消归档', exact: true }).click();

  // 取消归档后：徽标没了。
  await expect(rowOf(page, 's-keep').locator('.session-item-archived')).toHaveCount(0);
  // AC12 的"回到默认列表"必须**在默认视图下**断言：把开关关掉再看一眼，
  // 否则"它可见"可能只是开关还开着的结果（两种状态同形）。
  await toggle(page).click();
  await expect(toggle(page)).toHaveAttribute('aria-pressed', 'false');
  await expect(rowOf(page, 's-keep')).toBeVisible();
  await expect(rowOf(page, 's-keep').locator('.session-item-archived')).toHaveCount(0);

  // 两个方向各发了**一次**请求，动词与目标态都对（POST = 归档、DELETE = 取消）。
  expect(calls).toEqual(['POST s-keep true', 'DELETE s-keep false']);
  await expect(page.locator('.rail-error')).toHaveCount(0);
});

test('归档写入成功但列表重拉失败：就地说明「已生效但没刷新出来」，不假装成功', async ({ page }) => {
  // 这个窗口只在真机上偶发（写成功 → 紧接着的 GET 失败）。沉默的代价是具体的：
  // 界面上的行还是旧状态，用户以为没生效、再点一次；而后端其实已经归档了。
  await routeApi(page, railMock({ sessionsListFailAfter: 1 }));
  await page.goto('/');
  await expect(rowOf(page, 's-keep')).toBeVisible();

  await openMenu(page, 's-keep');
  await page.getByRole('menuitem', { name: '归档', exact: true }).click();

  // 就地报错（不是全局横幅），且这句只描述**界面**的处境——不冒充后端 detail。
  const error = page.locator('.rail-error');
  await expect(error).toBeVisible();
  await expect(error).toContainText('归档已生效，但会话列表刷新失败');
  // 行仍在（列表确实是旧的）——界面不自作主张地把它藏掉（不变量 #22）。
  await expect(rowOf(page, 's-keep')).toBeVisible();
});

test('空态提示只说真话：只有归档行时给出归档条数；项目在但无会话时不出声', async ({ page }) => {
  // ① 唯一一行是归档行 → 提示必须出现，并给出**真实**的归档条数（1，不是载荷长度）。
  await routeApi(
    page,
    railMock({
      sessions: [sessionRow('s-arch', { id: 'p1', title: '项目 alpha' }, { archived: true })],
    }),
  );
  await page.goto('/');
  const hint = page.locator('.empty-hint');
  await expect(hint).toContainText('没有可见的会话：1 条都已归档');
  // 指向的入口必须是**屏幕上真的存在**的东西：开关是纯图标按钮（只有 aria-label），
  // 所以文案指的也是"顶部那个图标"，不是一句用户找不到的「显示已归档」。
  await expect(hint).not.toContainText('「显示已归档」');

  // ② 项目已注册但一条会话都没有 → 不许说"0 条都已归档"（"没有会话"≠"都归档了"）。
  await page.route('**/api/sessions*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
  await page.reload();
  await expect(page.locator('.rail-project')).toBeVisible();
  await expect(page.locator('.empty-hint')).toHaveCount(0);
});

test('409：原样显示后端 detail、列表保持原样；取消归档永不被 409 挡', async ({ page }) => {
  await routeApi(page, railMock({ sessionArchiveBusyIds: ['s-keep', 's-arch'] }));
  await page.goto('/');
  await toggle(page).click(); // 让已归档那行也可见（下面要用它验证反向不被挡）
  await expect(rowOf(page, 's-arch')).toBeVisible();

  // ── 归档一个在途运行的会话 → 409，detail 逐字来自后端 ──
  await openMenu(page, 's-keep');
  await page.getByRole('menuitem', { name: '归档', exact: true }).click();

  const error = page.locator('.rail-error');
  await expect(error).toBeVisible();
  await expect(error).toContainText(
    "session 's-keep' has a run in flight; archive it after it finishes",
  );
  // 拒绝之后**列表保持原样**（没有乐观隐藏、也没有贴上一个假徽标）。
  await expect(rowOf(page, 's-keep')).toBeVisible();
  await expect(rowOf(page, 's-keep').locator('.session-item-archived')).toHaveCount(0);

  // ── 反向（取消归档）**不受** 409 守卫：同一个"忙"标记下它必须成功 ──
  await error.locator('.rail-error-close').click();
  await expect(error).toHaveCount(0);
  await openMenu(page, 's-arch');
  await page.getByRole('menuitem', { name: '取消归档', exact: true }).click();
  await expect(rowOf(page, 's-arch').locator('.session-item-archived')).toHaveCount(0);
  await expect(page.locator('.rail-error')).toHaveCount(0);
});

test('归档不影响正在阅读的会话：视野不被拽走（归档 ≠ 删除）', async ({ page }) => {
  // 硬删（#172）在会话被删时清空视图；归档只是列表可见性标记，事件日志与
  // resume 都还在（#171 AC5 的跨端对应），所以主区内容与选中态都不许动。
  await routeApi(
    page,
    railMock({
      events: [
        { type: 'session/started', seq: 1, session_id: 's-keep', run_id: null, time: null },
        {
          type: 'user/message',
          data: { content: '归档我，但别动我的对话' },
          seq: 2,
          session_id: 's-keep',
          run_id: null,
          step_id: 1,
          time: null,
        },
        {
          type: 'text/delta',
          data: { delta: '这条回答在归档之后仍然可见。' },
          seq: 3,
          session_id: 's-keep',
          run_id: null,
          step_id: 1,
          time: null,
        },
      ],
    }),
  );
  await page.goto('/');
  await rowOf(page, 's-keep').locator('.session-item').click();
  await expect(page.getByText('这条回答在归档之后仍然可见。')).toBeVisible();

  await openMenu(page, 's-keep');
  await page.getByRole('menuitem', { name: '归档', exact: true }).click();

  // 行从侧栏收起（默认视图），但对话区**逐字不变**——没有"被删了"的空态。
  await expect(rowOf(page, 's-keep')).toHaveCount(0);
  await expect(page.getByText('这条回答在归档之后仍然可见。')).toBeVisible();
});
