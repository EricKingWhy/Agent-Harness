/** 场景 V（WS-7 / #170 前端半）：新建项目对话框里的宿主目录浏览器。
 *
 *  契约来源：`docs/PRD_WS6_WS7_DIR_ROOTED_SESSION_AND_DIR_PICKER.md` §4.4（`GET /api/host/dirs`
 *  的形状与错误矩阵）+ §4.5（对话框结构与双向同步）；决策与安全论证见 ADR-0028。
 *  本 spec 覆盖 AC8–AC13 里可在无后端环境确定复现的部分：
 *  - AC8  打开即列**根**（盘符/根），根模式没有"当前目录" → 「向上」「选择此目录」禁用；
 *  - AC9  子目录一层列举 + 排序（大小写不敏感）+ 点选进入 + 「向上」；
 *  - AC10 双向同步：浏览器点选/跳转 → 回填**上方路径输入框**；手改输入框回车 → 浏览器跳转；
 *  - AC11 「选择此目录」回填并用它在 `POST /api/projects` 里注册成功；
 *  - AC12 截断如实提示（truncated）；403/404 就地显示**后端 detail 原文**（不翻译）；
 *  - AC13 以上由本 spec 覆盖（假目录树由 fixtures 按名拼路径，见 ApiMock.hostDirs）。
 *
 *  车道：Playwright e2e + page.route（同 r-project-groups.spec.ts），`--workers=2`。 */

import { expect, test, type Page } from '@playwright/test';
import { routeApi, type ApiMock } from './fixtures';

/** 假目录树：C 盘一个目录；D 盘两个；data 下顺序刻意乱（证明排序由 fixture 按后端
 *  口径做，而不是依赖声明顺序）。 */
const TREE = {
  roots: ['D:\\', 'C:\\'],
  tree: {
    'C:\\': ['Users'],
    'D:\\': ['repos', 'data'],
    'D:\\data': ['logs', 'alpha', 'beta'],
    'D:\\repos': ['my-project'],
    'D:\\repos\\my-project': ['src', 'tests'],
    'D:\\data\\logs': ['a', 'b', 'c'],
  } satisfies Record<string, string[]>,
};

function baseMock(over: Partial<ApiMock> = {}): ApiMock {
  return {
    sessions: [],
    projects: [],
    hostDirs: TREE,
    ...over,
  };
}

const dialog = (page: Page) => page.locator('.project-dialog[aria-label="新建项目"]');
const browser = (page: Page) => page.locator('.dir-browser');
const currentDir = (page: Page) => browser(page).locator('.dir-browser-current');
/** 上方表单的路径输入框（与浏览器路径条是两个控件：AC10 的双向同步就发生在这两者之间）。 */
const formPath = (page: Page) => dialog(page).getByLabel('目录绝对路径', { exact: true });
const browserPath = (page: Page) => browser(page).locator('.dir-browser-path');

async function openCreateDialog(page: Page) {
  await page.goto('/');
  // 侧栏右上角的「新建项目」：真空态下它是**文字**按钮，有会话时是 icon 按钮，
  // 两者可访问名相同——按角色+名字定位才不会随"有没有会话"而失效。
  await page.getByRole('button', { name: '新建项目', exact: true }).click();
  await expect(dialog(page)).toBeVisible();
}

async function enterDir(page: Page, name: string) {
  await browser(page).locator('.dir-browser-item', { hasText: name }).first().click();
}

test('AC8/AC9/AC10 打开即列根（无当前目录 → 两个按钮禁用）；点选进入、向上、回填输入框', async ({
  page,
}) => {
  routeApi(page, baseMock());
  await openCreateDialog(page);

  // AC8：根模式 —— path/parent 都是 null，"当前在根"，没有可选择的目录
  await expect(browserPath(page)).toHaveValue('');
  await expect(currentDir(page)).toHaveAttribute('data-root', 'true');
  const up = browser(page).getByRole('button', { name: '向上一级' });
  await expect(up).toBeDisabled();
  await expect(browser(page).getByRole('button', { name: '选择此目录' })).toBeDisabled();
  // 根列表：盘符，按大小写不敏感排序（fixtures 声明的是 D 在前，列出来必须 C 在前）
  await expect(browser(page).locator('.dir-browser-item-name')).toHaveText(['C:\\', 'D:\\']);

  // AC9/AC10：点选进入 D:\ → 当前目录 + 上方输入框**都被回填**
  await enterDir(page, 'D:\\');
  await expect(currentDir(page)).toHaveText(/D:\\/);
  await expect(formPath(page)).toHaveValue('D:\\');
  await expect(browserPath(page)).toHaveValue('D:\\');

  // 子目录排序（data 在 repos 前，尽管声明顺序相反）+ 一层列举
  await expect(browser(page).locator('.dir-browser-item-name')).toHaveText(['data', 'repos']);

  // 进入 data：条目 = 排序后的 alpha/beta/logs（fixture 声明顺序是 logs/alpha/beta）
  await enterDir(page, 'data');
  await expect(currentDir(page)).toHaveText(/D:\\data$/);
  await expect(browser(page).locator('.dir-browser-item-name')).toHaveText([
    'alpha',
    'beta',
    'logs',
  ]);
  await expect(formPath(page)).toHaveValue('D:\\data');

  // 「向上」回到 D:\ —— 两个输入框跟着一起回退（同一份路径真相）
  await up.click();
  await expect(currentDir(page)).toHaveText(/D:\\$/);
  await expect(formPath(page)).toHaveValue('D:\\');
  await expect(browser(page).locator('.dir-browser-item-name')).toHaveText(['data', 'repos']);
});

test('AC10 手改上方输入框回车 → 浏览器跳到该路径（反方向同步）；浏览器自己的路径条同理', async ({
  page,
}) => {
  routeApi(page, baseMock());
  await openCreateDialog(page);

  await formPath(page).fill('D:\\repos\\my-project');
  await formPath(page).press('Enter');

  await expect(currentDir(page)).toHaveText(/D:\\repos\\my-project$/);
  await expect(browser(page).locator('.dir-browser-item-name')).toHaveText(['src', 'tests']);
  // 跳转成功后的路径条显示当前目录（editing 状态已清掉）
  await expect(browserPath(page)).toHaveValue('D:\\repos\\my-project');

  // 浏览器**自己的**路径条也是同一套语义（两条入口都要能用，不只表单那一侧）
  await browserPath(page).fill('D:\\data');
  await browserPath(page).press('Enter');
  await expect(currentDir(page)).toHaveText(/D:\\data$/);
  await expect(browserPath(page)).toHaveValue('D:\\data');
  await expect(formPath(page)).toHaveValue('D:\\data'); // 反向跳转同样回填表单

  // 回归锁（批次审查 P2）：先跳到 D:\repos，再往条里打字（**不回车**），然后改走
  // "点子目录"这条导航——条不能停留在刚打的旧文本上：条上写 A、下面列 B 自相矛盾。
  await browserPath(page).fill('D:\\repos');
  await browserPath(page).press('Enter');
  await expect(currentDir(page)).toHaveText(/D:\\repos$/);
  await browserPath(page).fill('D:\\data');
  await enterDir(page, 'my-project');
  await expect(currentDir(page)).toHaveText(/D:\\repos\\my-project$/);
  await expect(browserPath(page)).toHaveValue('D:\\repos\\my-project');
});

test('AC11 「选择此目录」回执 + 用它注册项目（POST 体的 path 就是这个目录）', async ({
  page,
}) => {
  routeApi(page, baseMock());
  const bodies: Record<string, unknown>[] = [];
  page.on('request', (req) => {
    if (req.method() !== 'POST') return;
    if (new URL(req.url()).pathname !== '/api/projects') return;
    try {
      bodies.push(req.postDataJSON() as Record<string, unknown>);
    } catch {
      /* 非 JSON：忽略 */
    }
  });
  await openCreateDialog(page);

  await formPath(page).fill('D:\\repos\\my-project');
  await formPath(page).press('Enter');
  await browser(page).getByRole('button', { name: '选择此目录' }).click();

  // 回执：按钮不能看起来"什么都没发生"（路径早在导航时就同步过了）
  await expect(browser(page).locator('.project-notice')).toContainText('D:\\repos\\my-project');
  await expect(formPath(page)).toHaveValue('D:\\repos\\my-project');

  await dialog(page).getByRole('button', { name: '注册项目' }).click();
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0].path).toBe('D:\\repos\\my-project');
  // 注册成功 → 对话框关闭 + 项目出现在侧栏（mock 的 projects 分支真的建了项目）
  await expect(dialog(page)).toHaveCount(0);
  await expect(page.locator('.rail-project').filter({ hasText: 'my-project' })).toBeVisible();
});

test('AC12 截断如实提示：超过上限时列出前 N 条并说明只列了一部分', async ({ page }) => {
  routeApi(page, baseMock({ hostDirs: { ...TREE, maxEntries: 2 } }));
  await openCreateDialog(page);

  // 直接跳进 D:\data\logs（3 个子目录，上限 2）——截断的是**这一层**的列举
  await formPath(page).fill('D:\\data\\logs');
  await formPath(page).press('Enter');

  await expect(currentDir(page)).toHaveText(/D:\\data\\logs$/);
  await expect(browser(page).locator('.dir-browser-item-name')).toHaveText(['a', 'b']);
  // 不说这句，用户会以为"这个目录里就这么多"
  await expect(browser(page).locator('.dir-browser-truncated')).toContainText('只列出了前一部分');
});

test('AC12 403/404/422 就地显示后端 detail 原文（不翻译成"加载失败"）', async ({ page }) => {
  routeApi(
    page,
    baseMock({
      hostDirsErrors: {
        'D:\\secret': { status: 403, detail: '无权限访问：D:\\secret' },
        'D:\\data\\a-file.txt': { status: 422, detail: '不是目录：D:\\data\\a-file.txt' },
      },
    }),
  );
  await openCreateDialog(page);

  // 403：目录存在但读不到 —— 后端 detail 原样出现
  await formPath(page).fill('D:\\secret');
  await formPath(page).press('Enter');
  await expect(browser(page).locator('.dir-browser-error')).toHaveText('无权限访问：D:\\secret');
  // 错误不抹掉已知事实：根列表还在（用户能继续往上/换目录）
  await expect(browser(page).locator('.dir-browser-item-name')).toHaveText(['C:\\', 'D:\\']);

  // 404：不存在的路径（fixture 的假树里没有 → 真后端那句话同形）
  await formPath(page).fill('D:\\nope');
  await formPath(page).press('Enter');
  await expect(browser(page).locator('.dir-browser-error')).toHaveText('目录不存在：D:\\nope');

  // 422：路径存在但是文件（后端矩阵里"是文件"走 422，不是 404——两者别合并）
  await formPath(page).fill('D:\\data\\a-file.txt');
  await formPath(page).press('Enter');
  await expect(browser(page).locator('.dir-browser-error')).toHaveText(
    '不是目录：D:\\data\\a-file.txt',
  );
});
