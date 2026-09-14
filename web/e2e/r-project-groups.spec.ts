/** 场景 R（WS-5 / #155）：项目分组 UI——项目 → 会话层级 + 未分组区 + 项目 CRUD。
 *
 * 契约来源：`docs/…/WS-5` 验收标准 AC1–AC7。本 spec 锁住其中可在无后端环境
 *  确定复现的部分：
 *  - AC1 项目层级 + **账本手工序**（用例刻意把活动时间序做成账本序的**反序**，
 *    任何"按活动时间重排"的实现都会在这里变红）；
 *  - AC2 未分组区存在、可点开、**可继续对话**（真的发出 POST /messages）；
 *  - AC3 新建项目（含"路径不存在"的清晰错误）——不测目录浏览器（不做）；
 *  - AC4 重命名 / 加入项目 / 移出项目 / 项目内重排（键盘可达的"上移/下移"路径）；
 *  - AC5 删除项目必须明示「只解除分组、不删会话」，且删除后会话仍在该处、落到未分组。
 *
 *  不含真实拖拽：HTML5 DnD 在并行车道里有已知抖动（§16.6 要求 --workers=2），
 *  而"调整顺序"这条 AC 已由确定性的菜单路径覆盖；拖拽只在真机人工验收里点。
 *  非目标（不做）：上传/导入、目录浏览式选择器、跨项目归属。
 */

import { expect, test, type Page } from '@playwright/test';
import { RUN, T, fulfillSse, routeApi, sessionRow, type FrameSpec } from './fixtures';

const P1 = { id: 'p1', path: 'D:/repos/alpha', title: '项目 alpha', session_ids: ['s2', 's1'] };
const P2 = { id: 'p2', path: 'D:/repos/beta', title: '项目 beta', session_ids: ['s3'] };

/** 未分组会话的历史（点开要能看到内容，才谈得上"可继续对话"）。 */
const FREE_EVENTS: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: 'free-1', run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: 'free-1', run_id: RUN, time: T },
  { type: 'user/message', data: { content: '未分组的旧任务' }, seq: 3, session_id: 'free-1', run_id: RUN, step_id: 1, time: T },
  { type: 'text/delta', data: { delta: '未分组会话的历史回答。' }, seq: 4, session_id: 'free-1', run_id: RUN, step_id: 1, time: T },
  { type: 'run/completed', data: {}, seq: 5, session_id: 'free-1', run_id: RUN, time: T },
];

/** 活动时间序 = [s1(最新), s2(较旧), s3]；账本序 = [s2, s1]。反序是刻意的。 */
function baseSessions() {
  return [
    sessionRow('s1', { id: 'p1', title: '项目 alpha' }, { last_event_time: '2026-09-11T10:00:00Z' }),
    sessionRow('s2', { id: 'p1', title: '项目 alpha' }, { last_event_time: '2026-09-11T09:00:00Z' }),
    sessionRow('s3', { id: 'p2', title: '项目 beta' }),
    sessionRow('free-1', null, { first_user_message: '未分组的旧任务' }),
  ];
}

const project = (page: Page, title: string) =>
  page.locator('.rail-project').filter({ hasText: title });
const ungrouped = (page: Page) => page.locator('.rail-section[aria-label="未分组"]');

/** 某个项目块里会话行的渲染顺序（用短 id 断言——会话 id 短，slice(0,12) 不改写）。 */
async function railOrder(page: Page, title: string): Promise<string[]> {
  return project(page, title).locator('.session-item-id').allTextContents();
}

/** 打开某项目行的操作菜单（kebab 默认透明，但可点——Playwright 判定可见性看
 *  的是布局而非 opacity）。
 *
 *  必须限定在 `.rail-project-head` 里：项目块**包含**它的会话行，不加限定的
 *  `.rail-menu-btn` 会同时命中每个会话行的菜单（strict mode violation）。 */
async function openProjectMenu(page: Page, title: string) {
  await project(page, title).locator('.rail-project-head .rail-menu-btn').click();
}

/** 打开某个会话行的操作菜单（按短 id 定位行）。 */
async function openSessionMenu(page: Page, sessionId: string) {
  await page
    .locator('.session-row')
    .filter({ has: page.locator('.session-item-id', { hasText: sessionId }) })
    .locator('.rail-menu-btn')
    .click();
}

test('AC1/AC2：项目 → 会话层级按账本手工序渲染；未分组区可点开、可继续对话', async ({ page }) => {
  let sent: Record<string, unknown> | null = null;
  routeApi(page, {
    sessions: baseSessions(),
    projects: [P1, P2],
    events: FREE_EVENTS,
    onMessagesPost: async (route) => {
      sent = route.request().postDataJSON() as Record<string, unknown>;
      await fulfillSse(route, [
        { type: 'run/started', seq: 6, session_id: 'free-1', run_id: RUN, time: T },
        { type: 'text/delta', data: { delta: '继续对话的回答。' }, seq: 7, session_id: 'free-1', run_id: RUN, step_id: 1, time: T },
        { type: 'run/completed', data: {}, seq: 8, session_id: 'free-1', run_id: RUN, time: T },
      ]);
    },
  });

  await page.goto('/');

  // 项目块存在且顺序 = 注册表顺序（新项目前插 → p1 在 p2 前）
  const headers = await page.locator('.rail-project-title').allTextContents();
  expect(headers).toEqual(['项目 alpha', '项目 beta']);

  // AC1：项目内顺序 = 账本手工序（活动时间序是它的反序）
  expect(await railOrder(page, '项目 alpha')).toEqual(['s2', 's1']);
  expect(await railOrder(page, '项目 beta')).toEqual(['s3']);

  // AC2：未分组区存在，只装未分组会话，计数正确
  await expect(ungrouped(page)).toContainText('未分组');
  expect(await ungrouped(page).locator('.session-item-id').allTextContents()).toEqual(['free-1']);

  // AC2：未分组的会话可点开——历史重建出来
  await ungrouped(page).locator('.session-item').click();
  await expect(page.locator('.model-output').last()).toContainText('未分组会话的历史回答。');

  // AC2：可**继续对话**——真的发出续聊请求（不是只打开看看）
  await page.getByLabel('Agent 任务').fill('继续这条会话');
  await page.getByLabel('发送').click();
  await expect.poll(() => sent).not.toBeNull();
  expect(sent!.content).toBe('继续这条会话');
});

test('AC3：新建项目输入绝对路径；路径不存在 → 就地给出清晰错误', async ({ page }) => {
  routeApi(page, {
    sessions: baseSessions(),
    projects: [P1],
    projectMissingPaths: ['D:/nope/missing'],
  });
  await page.goto('/');

  await page.getByLabel('新建项目').click();
  const dialog = page.locator('.project-dialog');
  await expect(dialog).toBeVisible();

  // 路径不存在：错误留在对话框里，对话框不关（用户能改完再试）。
  // 断言打在**后端原始串**上（WinError 3 + 路径）——AC3 要的是"后端说了什么就显示
  // 什么"，把原因翻译成"操作失败"或换成自己的措辞都会让这条变红。
  await dialog.getByLabel('目录绝对路径').fill('D:/nope/missing');
  await dialog.getByRole('button', { name: '注册项目' }).click();
  await expect(dialog.locator('.project-error')).toContainText('WinError 3');
  await expect(dialog.locator('.project-error')).toContainText('D:/nope/missing');
  await expect(dialog).toBeVisible();

  // 合法路径 + 自定义标题 → 注册成功，关闭并出现在侧栏（新项目前插）
  await dialog.getByLabel('目录绝对路径').fill('D:/repos/gamma');
  await dialog.getByLabel('项目名').fill('项目 gamma');
  await dialog.getByRole('button', { name: '注册项目' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator('.rail-project-title').first()).toHaveText('项目 gamma');
});

test('AC4：重命名项目 / 加入项目 / 移出项目 / 项目内重排', async ({ page }) => {
  routeApi(page, {
    sessions: baseSessions(),
    projects: [{ id: 'p1', path: 'D:/repos/alpha', title: '项目 alpha', session_ids: ['s1', 's2', 's3'] }],
  });
  await page.goto('/');
  expect(await railOrder(page, '项目 alpha')).toEqual(['s1', 's2', 's3']);

  // 重命名：行内输入，Enter 提交
  //
  // ⚠ Enter 一律走 `page.keyboard.press`，不用 `locator.press`：行内输入的 Enter
  // 处理器会立刻提交并**卸载自己**，而 `locator.press` 在 keydown 之后还要对同一个
  // 定位符补发 keyup——元素已不在，它就会重新解析定位符并一直等下去（本用例曾在
  // 全量并行下偶发 30s 超时，页面快照却显示改名已经成功）。键盘按下不持有元素引用，
  // 因此对"提交即卸载"的输入是稳定的。
  await openProjectMenu(page, '项目 alpha');
  await page.getByRole('menuitem', { name: '重命名项目' }).click();
  const rename = page.getByLabel('项目名');
  await rename.fill('改名后的项目');
  await page.keyboard.press('Enter');
  await expect(project(page, '改名后的项目')).toBeVisible();

  // FE-R11-08：纯空白标题按 Enter 不许静默丢弃——之前编辑态直接关掉、没有请求、
  // 也没有任何提示，用户以为改名成功了。现在就地拦下：留下编辑态 + 可见提示。
  await openProjectMenu(page, '改名后的项目');
  await page.getByRole('menuitem', { name: '重命名项目' }).click();
  const rename2 = page.getByLabel('项目名');
  await rename2.fill('   ');
  await page.keyboard.press('Enter');
  await expect(page.locator('.project-rename-error')).toBeVisible();
  await expect(rename2).toBeVisible(); // 编辑态还在，用户能直接补字
  await expect(rename2).toHaveAttribute('aria-invalid', 'true');
  // 补上字再提交 → 正常改名（提示消失、Enter 这次真的提交）
  await rename2.fill('改名后的项目');
  await expect(page.locator('.project-rename-error')).toHaveCount(0);
  await page.keyboard.press('Enter');
  await expect(project(page, '改名后的项目')).toBeVisible();

  // 重排：s3 上移一格 → [s1, s3, s2]
  await openSessionMenu(page, 's3');
  await page.getByRole('menuitem', { name: '上移' }).click();
  await expect
    .poll(() => railOrder(page, '改名后的项目'))
    .toEqual(['s1', 's3', 's2']);

  // 边界：首条的「上移」不可用、末条的「下移」不可用
  await openSessionMenu(page, 's1');
  await expect(page.getByRole('menuitem', { name: '上移' })).toHaveAttribute('data-disabled', '');
  await page.keyboard.press('Escape');

  // 移出项目：s3 回到未分组
  await openSessionMenu(page, 's3');
  await page.getByRole('menuitem', { name: '移出项目' }).click();
  await expect.poll(() => railOrder(page, '改名后的项目')).toEqual(['s1', 's2']);
  await expect.poll(() => ungrouped(page).locator('.session-item-id').allTextContents()).toContain('s3');

  // 加入项目：s3 再从对话框选回来。落点在账本**头部**——真实后端 attach 写的是
  // `[session_id, *kept]`（前插），不是追加队尾（`tests/web/test_projects_api.py`
  // 锁住了这个顺序；mock 与本断言都必须跟它一致，否则真机上会红）。
  await openSessionMenu(page, 's3');
  await page.getByRole('menuitem', { name: '加入项目…' }).click();
  await page.locator('.project-pick-item').filter({ hasText: '改名后的项目' }).click();
  await expect.poll(() => railOrder(page, '改名后的项目')).toEqual(['s3', 's1', 's2']);
});

test('加入项目被后端拒绝时（409 会话 cwd 与项目路径不一致）就地显示后端原因，归属不变', async ({
  page,
}) => {
  // 这条是"归属由 cwd 决定"的证明：会话不能靠界面被塞进一个它不属于的项目。
  // 真机上 409 由后端给出（自由会话的 cwd 与项目路径不同），e2e 用拦截口伪造。
  const detail = "会话 'free-1' 的工作目录与项目「项目 alpha」不一致（账本按会话 cwd 判定成员资格）";
  routeApi(page, {
    sessions: baseSessions(),
    projects: [P1],
    onAttachPost: async (route) => {
      await route.fulfill({
        status: 409,
        body: JSON.stringify({ detail }),
        contentType: 'application/json',
      });
      return true;
    },
  });
  await page.goto('/');

  await openSessionMenu(page, 'free-1');
  await page.getByRole('menuitem', { name: '加入项目…' }).click();
  await page.locator('.project-pick-item').filter({ hasText: '项目 alpha' }).click();

  // 后端 detail 原样留在对话框里（不翻译成"操作失败"），对话框不关
  const dialog = page.locator('.project-dialog');
  await expect(dialog.locator('.project-error')).toContainText('工作目录与项目');
  await expect(dialog).toBeVisible();

  // 归属不变：free-1 仍在未分组（s3 本来就不属于 P1，也仍在未分组——它的项目
  // p2 不在本用例的项目列表里，所以还带一条"未在列表中"的注解）。
  await dialog.getByRole('button', { name: '取消' }).click();
  await expect.poll(() => railOrder(page, '项目 alpha')).toEqual(['s2', 's1']);
  expect(await ungrouped(page).locator('.session-item-id').allTextContents()).toEqual([
    's3',
    'free-1',
  ]);
});

test('AC5：删除项目明示"只解除分组"，删除后会话仍在且落到未分组', async ({ page }) => {
  routeApi(page, {
    sessions: baseSessions(),
    projects: [P1, P2],
  });
  await page.goto('/');
  await expect(ungrouped(page).locator('.session-item-id')).toHaveCount(1);

  await openProjectMenu(page, '项目 alpha');
  await page.getByRole('menuitem', { name: '删除项目…' }).click();

  // AC5 的文案底线：删除确认里必须明确说出**不会**删掉什么
  const dialog = page.locator('.project-dialog');
  await expect(dialog).toContainText('软删除');
  await expect(dialog).toContainText('不会');
  await expect(dialog).toContainText('会话日志');
  await expect(dialog).toContainText('2 个会话回到「未分组」');

  await dialog.getByRole('button', { name: '只移除项目（不删会话）' }).click();
  // 后端写好的软删除说明原样展示（含"可重新注册同一目录"）
  await expect(dialog.locator('.project-dialog-done')).toContainText('可重新注册同一目录');
  await dialog.getByRole('button', { name: '完成' }).click();
  await expect(dialog).toBeHidden();

  // 项目消失，它的两个会话一个不少地出现在未分组区
  await expect(page.locator('.rail-project-title')).toHaveCount(1);
  expect(await ungrouped(page).locator('.session-item-id').allTextContents()).toEqual([
    's1',
    's2',
    'free-1',
  ]);
});

test('项目列表端点失败时不隐藏会话：全部落到未分组 + 一条可重试的错误条', async ({ page }) => {
  // 后端不可用/契约失效时的降级：项目区消失但**一行都不丢**（比"项目也看不见、会话
  // 也看不见"好）；错误条给出重试入口。这条是 buildRailModel「绝不丢行」的 e2e 证据。
  routeApi(page, { sessions: baseSessions(), events: FREE_EVENTS });
  // 注意注册顺序：Playwright 后注册的路由优先，所以这条 502 必须**在 routeApi 之后**
  // 注册才能盖住 `**/api/**` 里的默认实现。
  await page.route('**/api/projects', (route) =>
    route.fulfill({ status: 502, body: '{"detail":"gateway"}', contentType: 'application/json' }),
  );

  await page.goto('/');
  await expect(page.locator('.rail-error')).toContainText('项目列表加载失败');
  expect(await ungrouped(page).locator('.session-item-id').allTextContents()).toEqual([
    's1',
    's2',
    's3',
    'free-1',
  ]);
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible();

  // AC6：`SessionSummary.workspace` 的唯一运行时用途就在这里——解释"自称属于某项目、
  // 但那个项目不在当前列表里"的行。三条（s1/s2→alpha、s3→beta）带注解，未分组的
  // free-1（workspace=null）**不带**：不是所有未分组行都该被标成"孤儿"。
  await expect(ungrouped(page).locator('.session-item-stale')).toHaveCount(3);
  await expect(ungrouped(page).locator('.session-item-stale').first()).toContainText('项目 alpha');
  await expect(
    ungrouped(page).locator('.session-row').filter({ hasText: 'free-1' }).locator('.session-item-stale'),
  ).toHaveCount(0);
});

test('会话行不因进入项目而看到假的"已分组"：行 tooltip 区分未分组', async ({ page }) => {
  routeApi(page, { sessions: baseSessions(), projects: [P1, P2] });
  await page.goto('/');
  // 未分组行的 title 带「· 未分组」；项目内行不带——同一份列表里两种状态可区分。
  await expect(ungrouped(page).locator('.session-item')).toHaveAttribute('title', /未分组/);
  await expect(project(page, '项目 alpha').locator('.session-item').first()).not.toHaveAttribute(
    'title',
    /未分组/,
  );
});

test('UI-05：真空态 → Rail 头部是文字按钮 + 空态文案带行动链接（不再指路到不存在的实体）', async ({ page }) => {
  // 真·空态：无会话、无项目（与空态文案自洽，不复现「请求失败也算空」的矛盾）
  routeApi(page, { sessions: [], projects: [] });
  await page.goto('/');
  await page.setViewportSize({ width: 1440, height: 900 });

  // 头部出现的是**带文字**的按钮（可见文本，不是 icon-only + aria-label）
  const createBtn = page.locator('.rail-empty-btn-primary', { hasText: '新建项目' });
  const newBtn = page.locator('.rail-empty-btn-ghost', { hasText: '新会话' });
  await expect(createBtn).toBeVisible();
  await expect(newBtn).toBeVisible();

  // 空态文案 + 行动链接
  await expect(page.locator('.rail-project-empty')).toContainText('还没有项目');
  const link = page.locator('.rail-empty-action', { hasText: '注册项目目录' });
  await expect(link).toBeVisible();

  // 「新建项目」文字按钮与链接都打开创建对话框
  await createBtn.click();
  await expect(page.locator('.project-dialog')).toBeVisible();
  await page.locator('.project-dialog-close').click();
  await expect(page.locator('.project-dialog')).toHaveCount(0);
  await link.click();
  await expect(page.locator('.project-dialog')).toBeVisible();

  // 非空态回退 icon 按钮（文字按钮不残留）
  await page.locator('.project-dialog-close').click();
});

test('UI-05：有会话或项目时回退 icon-only 按钮（aria-label 定位）', async ({ page }) => {
  routeApi(page, { sessions: baseSessions(), projects: [P1] });
  await page.goto('/');
  await expect(page.locator('.rail-empty-btn-primary')).toHaveCount(0);
  await expect(page.locator('button[aria-label="新建项目"]')).toBeVisible();
  await expect(page.locator('.rail-empty-action')).toHaveCount(0);
});

/** #179：窄屏（≤820px）项目级操作可达性。
 *
 *  背景：WS-5 #155 的窄屏降级把 `.rail-project-head` 整块 `display:none`——层级信息
 *  丢失是刻意的取舍，但"**项目级操作**（重命名 / 删除项目 / 在此项目中新建任务）只在
 *  那一行的菜单里"意味着它们在窄屏彻底不可达（FE-R11-09 修的是会话级的同源问题）。
 *  本 describe 锁住修复后的两条底线：菜单**能打开**，且**菜单项与宽屏一致**。
 *
 *  为什么用真窄视口而不是只断言 CSS：菜单在窄屏是"文件夹图标 ↔ ⋯"的槽位交换，
 *  只要 `.rail-project-head` 仍被收起（或 ⋯ 被一起藏掉），`click` 就会因为元素不可
 *  交互而失败——这条断言只有"真的可达"才拿得到。 */
test.describe('窄屏 ≤820px：项目级操作（#179）', () => {
  test.use({ viewport: { width: 800, height: 900 } });

  test('项目头不再整块收起：⋯ 菜单可达且菜单项与宽屏一致', async ({ page }) => {
    routeApi(page, { sessions: baseSessions(), projects: [P1] });
    await page.goto('/');

    const head = project(page, '项目 alpha').locator('.rail-project-head');
    await expect(head).toBeVisible();
    // 窄屏收起的是标题/计数/箭头，不是整行——标题在可访问性树里换成 aria-label
    // （display:none 会把它摘掉，无名控件等于没有入口）。
    await expect(head.locator('.rail-project-title')).toBeHidden();
    await expect(head.locator('.rail-project-count')).toBeHidden();
    await expect(head.locator('.rail-project-toggle')).toHaveAttribute(
      'aria-label',
      /项目 alpha：/,
    );

    await openProjectMenu(page, '项目 alpha');
    // AC2：与宽屏同一套动作、同一个确认面（三个菜单项逐字一致）。
    await expect(page.getByRole('menuitem', { name: '在此项目中新建任务' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: '重命名项目' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: '删除项目…' })).toBeVisible();
    // 破坏性动作仍走自己的确认面（不是"窄屏简化成直接删"）。
    await page.getByRole('menuitem', { name: '删除项目…' }).click();
    await expect(page.getByRole('dialog', { name: /删除项目/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /只移除项目（不删会话）/ })).toBeVisible();
  });

  test('窄屏重命名真的落到后端（PATCH 后重取仍在，不是本地改名）', async ({ page }) => {
    routeApi(page, { sessions: baseSessions(), projects: [P1] });
    await page.goto('/');

    await openProjectMenu(page, '项目 alpha');
    await page.getByRole('menuitem', { name: '重命名项目' }).click();
    // 窄屏没有横向空间，输入框向右溢出（CSS）——这里**量宽度**而不是只 `fill`：
    // Playwright 对"布局存在但被裁掉"的元素照样能 fill，只断言能输入等于没锁住可用性。
    const rename = page.getByLabel('项目名');
    const box = await rename.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThan(100);
    await rename.fill('窄屏改的名');
    await page.keyboard.press('Enter');

    // 刷新后重取 `/api/projects`：mock 只有在真的走过 PATCH 分支时才会返回新标题
    // （fixtures 的 projects 是**有状态**的），所以这条断言排除了"界面本地改了个名"。
    await page.reload();
    await expect(project(page, '窄屏改的名')).toBeVisible();
  });
});
