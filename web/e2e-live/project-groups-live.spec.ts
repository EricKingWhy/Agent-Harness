/** 联调车道（真后端 + 真盘 + 真浏览器，**无任何 `page.route` mock**）：
 *  WS-5 / #155 项目分组 UI 的真机证据。
 *
 *  运行前提（`playwright.live.config.ts` 的约定）：
 *   1. 后端：`D:\intelligence-agent-backend` 起 web app 于 127.0.0.1:8000（真 .env / 真 harness.db）；
 *   2. 前端：本目录 `npm run dev`（5173，proxy /api → 8000）；
 *   3. `npx playwright test --config playwright.live.config.ts --workers=1`。
 *
 *  用到的真实目录（都是**已存在**的目录，测试不创建也不删除任何目录）：
 *   - `.scratch/ws5-live-project`：空的临时目录 → 注册/改名/删除（0 会话的软删除路径）；
 *   - `.agent/workspace/workspaces/ws-delete-me`：盘上真实存在、内含 1 个真实会话的目录
 *     → 注册 → attach（cwd 相等，后端放行）→ detach → 再 attach → **软删除**
 *     （sessions_detached=1，会话与目录都还在）→ 回到测试前状态。
 *
 *  结束时把项目/会话两份 JSON 快照与开始时**逐字段比对**：真机验收必须证明"测完
 *  状态回到基线"，否则一次验收就污染了用户的真实分组。 */

import { expect, test, type Page } from '@playwright/test';
import { existsSync, mkdirSync } from 'node:fs';

const SHOT_DIR = 'gui-test-screenshots/ws5';
const SCRATCH = 'D:\\intelligence-agent-backend\\.scratch\\ws5-live-project';
const WS_DELETE_ME =
  'D:\\intelligence-agent-backend\\.agent\\workspace\\workspaces\\ws-delete-me';
/** ws-delete-me 目录里那个真实会话（读盘上的 session/started.cwd 得到的）。 */
const SESSION_ID = '43e7b46e-2a00-4cbe-bae7-64cfbf284b6e';

interface ProjectRow {
  id: string;
  path: string;
  title: string;
  status: string;
  session_ids: string[];
}
interface SessionRow {
  session_id: string;
  workspace: { id: string; title: string } | null;
}

/** 从前端同源 fetch 读真实后端（本地信任模式，无 token）——比 curl 更贴近被测路径。 */
async function snapshot(page: Page): Promise<{ projects: ProjectRow[]; sessions: SessionRow[] }> {
  return page.evaluate(async () => {
    const [projects, sessions] = await Promise.all([
      fetch('/api/projects').then((r) => r.json()),
      fetch('/api/sessions').then((r) => r.json()),
    ]);
    return { projects, sessions };
  });
}

/** 只保留与"分组状态"有关的字段：时间戳/事件数这类必然会变的不进比对。 */
function comparable(snap: { projects: ProjectRow[]; sessions: SessionRow[] }) {
  return {
    projects: snap.projects.map((p) => ({
      id: p.id,
      path: p.path,
      title: p.title,
      session_ids: p.session_ids,
    })),
    sessions: snap.sessions.map((s) => ({
      session_id: s.session_id,
      workspace: s.workspace ? s.workspace.id : null,
    })),
  };
}

const project = (page: Page, title: string) =>
  page.locator('.rail-project').filter({ hasText: title });
const ungrouped = (page: Page) => page.locator('.rail-section[aria-label="未分组"]');
const row = (page: Page, prefix: string) =>
  page.locator('.session-row').filter({ has: page.locator('.session-item-id', { hasText: prefix }) });

async function openProjectMenu(page: Page, title: string) {
  await project(page, title).locator('.rail-project-head .rail-menu-btn').click();
}

async function registerProject(page: Page, path: string) {
  await page.getByLabel('新建项目').click();
  const dialog = page.locator('.project-dialog');
  await dialog.getByLabel('目录绝对路径').fill(path);
  await dialog.getByRole('button', { name: '注册项目' }).click();
  await expect(dialog).toBeHidden();
}

test('真机：项目分组 / 新建 / 重命名 / attach / detach / 重排 / 软删除（无 mock）', async ({
  page,
}) => {
  test.setTimeout(300_000);
  const calls: string[] = [];
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/api/projects')) {
      calls.push(`${r.request().method()} ${u.pathname} → ${r.status()}`);
    }
  });
  mkdirSync(SHOT_DIR, { recursive: true });

  await page.goto('/');
  await expect(page.locator('.rail-section[aria-label="项目"] .rail-project')).toHaveCount(2);
  const before = await snapshot(page);
  // 真实项目按注册表顺序渲染：ws2-e2e 在前（bootstrap 时最新在前）
  expect(await page.locator('.rail-project-title').allTextContents()).toEqual([
    'ws2-e2e',
    'ws1-e2e',
  ]);
  // 项目内会话数 = 账本长度（真实 3 / 5）
  expect(await project(page, 'ws2-e2e').locator('.session-item-id').count()).toBe(
    before.projects[0].session_ids.length,
  );
  expect(await project(page, 'ws1-e2e').locator('.session-item-id').count()).toBe(
    before.projects[1].session_ids.length,
  );
  expect(await ungrouped(page).locator('.session-item-id').count()).toBeGreaterThan(10);
  await page.screenshot({ path: `${SHOT_DIR}/01-real-overview.png`, fullPage: false });

  // ① 注册临时目录 → 默认标题取目录名；改名 → 改名生效
  await registerProject(page, SCRATCH);
  await expect(page.locator('.rail-project-title').first()).toHaveText('ws5-live-project');
  await openProjectMenu(page, 'ws5-live-project');
  await page.getByRole('menuitem', { name: '重命名项目' }).click();
  const rename = page.getByLabel('项目名');
  await rename.fill('WS5 真机项目');
  await rename.press('Enter');
  await expect(project(page, 'WS5 真机项目')).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/02-created-and-renamed.png` });

  // ② 软删除它（0 会话）：确认文案必须说明不删会话，成功提示用后端原文
  await openProjectMenu(page, 'WS5 真机项目');
  await page.getByRole('menuitem', { name: '删除项目…' }).click();
  const delDialog = page.locator('.project-dialog');
  await expect(delDialog).toContainText('不会');
  await expect(delDialog).toContainText('会话日志');
  await page.screenshot({ path: `${SHOT_DIR}/03-soft-delete-confirm.png` });
  await delDialog.getByRole('button', { name: '只移除项目（不删会话）' }).click();
  await expect(delDialog.locator('.project-dialog-done')).toContainText('可重新注册同一目录');
  await delDialog.getByRole('button', { name: '完成' }).click();
  await expect(page.locator('.rail-project-title')).toHaveCount(2);

  // ③ 注册盘上真实存在、内含 1 个真实会话的目录 → attach（cwd 相等，后端放行）
  await registerProject(page, WS_DELETE_ME);
  await expect(project(page, 'ws-delete-me')).toBeVisible();
  await expect(ungrouped(page).locator('.session-item-id', { hasText: SESSION_ID.slice(0, 12) }))
    .toHaveCount(1);
  await row(page, SESSION_ID.slice(0, 12)).locator('.rail-menu-btn').click();
  await page.getByRole('menuitem', { name: '加入项目…' }).click();
  await page.locator('.project-pick-item').filter({ hasText: 'ws-delete-me' }).click();
  await expect
    .poll(() => project(page, 'ws-delete-me').locator('.session-item-id').count())
    .toBe(1);
  await page.screenshot({ path: `${SHOT_DIR}/04-attached-under-project.png` });

  // ④ detach → 回到未分组（会话与日志都不动）
  await row(page, SESSION_ID.slice(0, 12)).locator('.rail-menu-btn').click();
  await page.getByRole('menuitem', { name: '移出项目' }).click();
  await expect
    .poll(() => project(page, 'ws-delete-me').locator('.session-item-id').count())
    .toBe(0);
  await expect(row(page, SESSION_ID.slice(0, 12))).toHaveCount(1);

  // ⑤ 再 attach → 软删除这个**有会话**的项目：会话回到未分组，目录与日志不动
  await row(page, SESSION_ID.slice(0, 12)).locator('.rail-menu-btn').click();
  await page.getByRole('menuitem', { name: '加入项目…' }).click();
  await page.locator('.project-pick-item').filter({ hasText: 'ws-delete-me' }).click();
  await expect
    .poll(() => project(page, 'ws-delete-me').locator('.session-item-id').count())
    .toBe(1);
  await openProjectMenu(page, 'ws-delete-me');
  await page.getByRole('menuitem', { name: '删除项目…' }).click();
  await expect(page.locator('.project-dialog')).toContainText('1 个会话回到「未分组」');
  await page.locator('.project-dialog').getByRole('button', { name: '只移除项目（不删会话）' }).click();
  await expect(page.locator('.project-dialog-done')).toContainText('1 个会话回到未分组');
  await page.locator('.project-dialog').getByRole('button', { name: '完成' }).click();
  await expect(project(page, 'ws-delete-me')).toHaveCount(0);
  await expect(row(page, SESSION_ID.slice(0, 12))).toHaveCount(1); // 会话还在（未分组区）
  expect(existsSync(WS_DELETE_ME)).toBe(true); // 目录还在盘上
  await page.screenshot({ path: `${SHOT_DIR}/05-after-soft-delete.png` });

  // ⑥ 真项目内重排：把第 2 行上移再下移 → 账本序**精确还原**（读后端验证，不只看界面）
  const ledgerBefore = before.projects[0].session_ids;
  const moved = ledgerBefore[1];
  await row(page, moved.slice(0, 12)).locator('.rail-menu-btn').click();
  await page.getByRole('menuitem', { name: '上移' }).click();
  await expect
    .poll(async () =>
      (await (await page.request.get('/api/projects')).json()).find(
        (p: ProjectRow) => p.id === before.projects[0].id,
      ).session_ids,
    )
    .toEqual([ledgerBefore[1], ledgerBefore[0], ...ledgerBefore.slice(2)]);
  await page.screenshot({ path: `${SHOT_DIR}/06-reordered.png` });
  await row(page, moved.slice(0, 12)).locator('.rail-menu-btn').click();
  await page.getByRole('menuitem', { name: '下移' }).click();
  await expect
    .poll(async () =>
      (await (await page.request.get('/api/projects')).json()).find(
        (p: ProjectRow) => p.id === before.projects[0].id,
      ).session_ids,
    )
    .toEqual(ledgerBefore);

  // ⑦ 基线比对：项目（含账本序）与会话归属必须与开测前**逐字段相等**
  const after = await snapshot(page);
  expect(comparable(after)).toEqual(comparable(before));

  // 真机证据留档（请求流水 + 结果）
  // eslint-disable-next-line no-console
  console.log(`[WS5 真机] /api/projects 调用流水：\n${calls.join('\n')}`);
  console.log(
    `[WS5 真机] 项目数 ${before.projects.length}→${after.projects.length}；` +
      `会话 ${before.sessions.length} 条，归属逐字段一致=${JSON.stringify(comparable(before)) === JSON.stringify(comparable(after))}`,
  );
});
