/** 场景 U（WS-6 / #169 前端半）：项目内新建任务——入口 → 确认面 → cwd 提交 → 落组。
 *
 *  契约来源：`docs/PRD_WS6_WS7_DIR_ROOTED_SESSION_AND_DIR_PICKER.md` §4.3（后端契约
 *  矩阵在 §4.1；ADR-0027 是决策与安全论证）。本 spec 锁 AC9–AC13 里可在无后端环境
 *  确定复现的部分：
 *  - AC9 项目行 kebab 第一项 =「在此项目中新建任务」；空项目占位区替换为该入口按钮；
 *  - AC10 确认面逐字出现「Agent 将直接读写该目录：<路径>」+ 权限档三选 + 空任务禁用；
 *  - AC11 提交体带 `cwd`，会话真的落进该项目分组；**默认档不发 `permission_mode`**
 *    （这是本票最容易踩的坑：后端"显式传非 danger 档 → 切交互式审批"，把默认档也
 *    塞进 payload 会让每次工具调用都弹审批卡）；
 *  - AC12 422 留在确认面：不关对话框、不打全局横幅、后端 detail 原样可见、可重试；
 *  - AC13 以上全部由本 spec 覆盖（mock 语义按真后端，见 fixtures 的 cwd 分支）。
 *
 *  权限档夹具用**真后端的三个 id/显示名**（`tooling/contract.py::PERMISSION_MODE_DESCRIPTIONS`）
 *  ——fixtures 里共享的 `PERMISSION_MODES`（auto/ask/deny）是另一批 spec 的历史夹具，
 *  与本票的真实契约不一致（已知漂移，另记，不在本票范围内顺手改）。
 *
 *  车道：Playwright e2e + page.route（同 r-project-groups.spec.ts 约定），`--workers=2`。
 */

import { expect, test, type Page } from '@playwright/test';
import { routeApi, sessionRow, type ApiMock } from './fixtures';

const ALPHA = 'D:/repos/alpha';
const BETA = 'D:/repos/beta';

/** 真后端 GET /api/permission-modes 的三档（id 是封闭枚举，未知值 → 422）。 */
const REAL_PERMISSION_MODES = [
  { id: 'read-only', display_name: '只读', description: '可读文件和运行只读工具，不可写入。' },
  {
    id: 'workspace-write',
    display_name: '工作区写入',
    description: '可读写工作区内文件；高危工具仍需审批。',
  },
  {
    id: 'danger-full-access',
    display_name: '完全访问',
    description: '所有工具无需审批，含网络/系统副作用。仅在可信环境使用。',
  },
];

/** 每个用例一份数组（fixture 的 cwd 分支会 unshift 新行——共享数组会串味）。 */
function baseSessions() {
  return [sessionRow('s3', { id: 'p2', title: '项目 beta' })];
}

/** alpha 是**空项目**（AC9 的空态入口），beta 有一条会话。 */
function baseMock(over: Partial<ApiMock> = {}): ApiMock {
  return {
    sessions: baseSessions(),
    projects: [
      { id: 'p1', path: ALPHA, title: '项目 alpha', session_ids: [] },
      { id: 'p2', path: BETA, title: '项目 beta', session_ids: ['s3'] },
    ],
    permissionModes: REAL_PERMISSION_MODES,
    ...over,
  };
}

const project = (page: Page, title: string) =>
  page.locator('.rail-project').filter({ hasText: title });
const dialog = (page: Page) => page.locator('.project-dialog[aria-label="在此项目中新建任务"]');

/** 打开某项目行的 kebab 菜单（限定在 `.rail-project-head` 里：项目块**包含**它的
 *  会话行，不加限定会同时命中每个会话行的菜单 → strict mode violation）。 */
async function openProjectMenu(page: Page, title: string) {
  await project(page, title).locator('.rail-project-head .rail-menu-btn').click();
}

/** AC9 主入口：菜单第一项 → 确认面在场。 */
async function openStartDialog(page: Page, title: string) {
  await openProjectMenu(page, title);
  await page.getByRole('menuitem', { name: '在此项目中新建任务' }).click();
  await expect(dialog(page)).toBeVisible();
}

/** 捕获 POST /api/sessions 的请求体（AC13 的请求体断言）。
 *  用 page 级 request 事件而不是 fixture 回调：请求体是"前端发了什么"的事实，
 *  与被 mock 的响应语义无关，两者分开观察才不会互相掩盖。 */
function captureSessionPosts(page: Page): Record<string, unknown>[] {
  const bodies: Record<string, unknown>[] = [];
  page.on('request', (req) => {
    if (req.method() !== 'POST') return;
    if (new URL(req.url()).pathname !== '/api/sessions') return;
    try {
      bodies.push(req.postDataJSON() as Record<string, unknown>);
    } catch {
      /* 非 JSON 体（本 spec 不该出现）：忽略而不是让监听器抛错 */
    }
  });
  return bodies;
}

test('AC9/AC10 菜单第一项是入口；确认面逐字明示路径、权限档默认工作区写入、空任务禁用', async ({
  page,
}) => {
  routeApi(page, baseMock());
  await page.goto('/');

  await openProjectMenu(page, '项目 alpha');
  // 第一项就是这个入口（重命名/删除在它下面——顺序是 AC 的一部分）
  await expect(page.getByRole('menuitem').first()).toHaveText('在此项目中新建任务');
  await page.getByRole('menuitem', { name: '在此项目中新建任务' }).click();

  const box = dialog(page);
  await expect(box).toBeVisible();
  // AC10①：路径明示行**逐字**出现——标签与路径必须连续（拆成两条断言的话，
  // "把路径挪到别的元素里、两段之间插入别的话"也能通过，那就不叫逐字了）
  const callout = box.locator('.project-path-callout');
  await expect(callout).toContainText(`Agent 将直接读写该目录：${ALPHA}`);
  // AC10②：权限档是**三选**（默认档之外两档也必须真的可选，否则"三选"只是文案）
  // FE-R11-05 之后单选 picker 多了一个首项「默认（未选）」（提交 `null` = 用默认档），
  // 所以这里是 1 + 3。三档**逐档**断言存在，不靠总数——总数只是"多了一项"的护栏。
  await box.locator('.composer-control[aria-label="权限模式"]').click();
  const listbox = page.locator('[role="listbox"]:visible').last();
  await expect(listbox.getByRole('option')).toHaveCount(4);
  for (const mode of ['只读', '工作区写入', '完全访问']) {
    await expect(listbox.getByRole('option', { name: mode })).toBeVisible();
  }
  await page.keyboard.press('Escape');
  await expect(box.locator('.composer-control[aria-label="权限模式"]')).toContainText('工作区写入');
  // AC10③：空任务禁用 → 填了才可提交
  const start = box.getByRole('button', { name: '开始任务' });
  await expect(start).toBeDisabled();
  await box.getByLabel('任务内容').fill('看看这个目录');
  await expect(start).toBeEnabled();
});

test('AC11 默认档提交：请求体带 cwd、不带 permission_mode，会话落进该项目分组', async ({
  page,
}) => {
  routeApi(page, baseMock());
  const bodies = captureSessionPosts(page);
  await page.goto('/');

  await openStartDialog(page, '项目 alpha');
  await dialog(page).getByLabel('任务内容').fill('读一下 README，总结项目结构');
  await dialog(page).getByRole('button', { name: '开始任务' }).click();

  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0].task).toBe('读一下 README，总结项目结构');
  expect(bodies[0].cwd).toBe(ALPHA);
  // 坑点锁（PRD §4.3）：默认档必须"不发键"——发了就是切交互式审批，
  // 每次工具调用都会弹审批卡。这条断言红了不要改 mock，要改的是那段提交逻辑。
  expect('permission_mode' in bodies[0]).toBe(false);

  // AC11 落组：新会话出现在「项目 alpha」下（mock 按真语义改了账本 + 行的 workspace）
  await expect(project(page, '项目 alpha').locator('.session-item-id')).toHaveCount(1);
  // AC11「选中该会话、跟随流」：这一行处于选中态，且流里的回答已渲染出来
  // （只断言"落组"会漏掉"提交完还得用户自己点一下才看到"的实现）
  await expect(project(page, '项目 alpha').locator('.session-item.selected')).toHaveCount(1);
  await expect(page.getByText('好，我先看看这个目录。')).toBeVisible();
  // 确认面关闭：用户接下来要看着那条流（不是停在浮层里）
  await expect(dialog(page)).toHaveCount(0);
});

test('AC11 主动改档才发 permission_mode（改档 = 要逐次审批）', async ({ page }) => {
  routeApi(page, baseMock());
  const bodies = captureSessionPosts(page);
  await page.goto('/');

  await openStartDialog(page, '项目 alpha');
  const box = dialog(page);
  await box.locator('.composer-control[aria-label="权限模式"]').click();
  // `:visible` 限定当前打开的浮层：关闭动画期间上一层 listbox 仍在 DOM 里。
  const listbox = page.locator('[role="listbox"]:visible').last();
  await expect(listbox).toBeVisible();
  await listbox.getByRole('option', { name: /只读/ }).click();
  await expect(box.locator('.composer-control[aria-label="权限模式"]')).toContainText('只读');

  await box.getByLabel('任务内容').fill('只做只读检查');
  await box.getByRole('button', { name: '开始任务' }).click();

  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0].permission_mode).toBe('read-only'); // 改档 → 显式发键（切交互式审批）
  expect(bodies[0].cwd).toBe(ALPHA);
});

test('AC12 422 留在确认面：后端 detail 原样可见、不关对话框、无全局横幅、重试即成功', async ({
  page,
}) => {
  const mock = baseMock({
    cwdSessionError: { status: 422, detail: `目录不存在：${ALPHA}` },
  });
  routeApi(page, mock);
  await page.goto('/');

  await openStartDialog(page, '项目 alpha');
  const box = dialog(page);
  await box.getByLabel('任务内容').fill('做点什么');
  await box.getByRole('button', { name: '开始任务' }).click();

  // 后端 detail 原样出现在浮层里——而且**不是** Composer 那条 422 旧语义
  // （「模型不可用（422）」），cwd 校验失败必须让后端那句话说话。
  // 用 toHaveText（整串相等）而不是 toContainText：前缀是「提交失败：」+ 后端原文，
  // 后半段一旦被改写（哪怕改成更"友好"的话）这条断言必须变红。
  await expect(box.locator('.project-error')).toHaveText(`提交失败：目录不存在：${ALPHA}`);
  await expect(box).toBeVisible();
  await expect(page.locator('.app-error')).toHaveCount(0); // 不弹全局横幅

  // 可重试：失败原因解除后同一条路径成功 → 落组 + 关闭
  mock.cwdSessionError = undefined;
  await box.getByRole('button', { name: '开始任务' }).click();
  await expect(project(page, '项目 alpha').locator('.session-item-id')).toHaveCount(1);
  await expect(box).toHaveCount(0);
});

test('AC9 空项目占位区替换为入口按钮（旧的"去未分组找 cwd 匹配会话"文案不再出现）', async ({
  page,
}) => {
  routeApi(page, baseMock());
  await page.goto('/');

  const alpha = project(page, '项目 alpha');
  await expect(alpha).not.toContainText('从未分组会话的');
  const entry = alpha.locator('.rail-empty-action');
  await expect(entry).toHaveText('在此项目中新建任务 →');

  await entry.click();
  await expect(dialog(page)).toBeVisible();
  await expect(dialog(page).locator('.project-path-callout')).toContainText(ALPHA);
});
