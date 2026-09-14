/** 场景 W（#172 / ADR-0029）：会话**硬删**——不可逆二次确认 + 删除后的状态收敛。
 *
 *  契约来源：issue #172 前端半（后端半 `4109b08`，`DELETE /api/sessions/{id}`）+
 *  ADR-0029。ADR-0029 把"误删不可逆"的风险明确压在**入口层**，所以本 spec 的断言
 *  重点不是"能删掉"，而是**删除之前说清了什么**与**删除之后界面收敛到什么状态**：
 *
 *  - 确认面必须写明不可恢复（只说"删除"不算）+ 显示会话标识（标题 + id 片段）；
 *  - 取消 = 零请求、零变化（第一次点击不许发 DELETE）；
 *  - 成功后：行消失（后端状态真的变了，不是本地隐藏）、项目计数跟着掉、回执带真实
 *    计数、当前打开的会话被清空且记住的 id 被清掉（刷新不会被拉回死会话）；
 *  - 409（有在途 run / 挂起审批 / fork 父会话，状态码相同）→ 原样显示后端 detail，
 *    列表**保持原样**——不做乐观删除；
 *  - 404（这个会话本就不在了）→ 显示后端 detail，并让本地这行过期行收敛消失。
 *
 *  为什么"删掉之后再看一次列表"是必需的：只断言"点了行就没了"是**两种实现都能过**的
 *  ——本地 filter 一下也能没（不变量 #22 的老陷阱）。mock 的 DELETE 分支真的把行与
 *  项目账本摘掉，所以这里的绿灯只有"界面跟着后端走"才拿得到。
 */

import { expect, test, type Page } from '@playwright/test';
import { RUN, T, routeApi, rowOf, sessionRow, type FrameSpec } from './fixtures';

/** `lib/sessionRestore.ts::SELECTED_SESSION_KEY`（记住选中的会话，BUG-005）。 */
const KEY = 'ahi.selectedSession';

const P1 = { id: 'p1', path: 'D:/repos/alpha', title: '项目 alpha', session_ids: ['s2'] };

/** 被打开那个会话的历史：确认"删除前对话区真的有内容"才有得比较。 */
const HISTORY: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: 's2', run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: 's2', run_id: RUN, time: T },
  { type: 'user/message', data: { content: '要被删掉的那条任务的提问' }, seq: 3, session_id: 's2', run_id: RUN, step_id: 1, time: T },
  { type: 'text/delta', data: { delta: '要被删掉的那条任务的回答。' }, seq: 4, session_id: 's2', run_id: RUN, step_id: 1, time: T },
  { type: 'run/completed', data: {}, seq: 5, session_id: 's2', run_id: RUN, time: T },
];

/** 一条会话行。`event_count` 取与 fixture 默认值（3）不同的数，回执那句里的数字
 *  就只能是这一处来的。
 *
 *  边界说明（别把这条断言说过头）：mock 的 DELETE 回执 `events` 也是从这行的
 *  `event_count` 算的（真后端同理——两边都数同一份日志），所以本 spec **区分不了**
 *  "回执读了响应"与"前端偷读了行上的计数"。区分它们靠的是另外两层：类型上
 *  `DeleteSessionTarget` 根本不含事件数（对话框拿不到行上的值），以及
 *  `api.test.ts` 对回执的透传断言。这里锁的是"这句话以正确的数字出现"。 */
const projectSession = () => sessionRow('s2', { id: 'p1', title: '项目 alpha' }, { event_count: 42 });
const freeSession = () => sessionRow('s1', null, { event_count: 7 });

const dialog = (page: Page) => page.locator('.project-dialog');
const project = (page: Page) => page.locator('.rail-project').filter({ hasText: '项目 alpha' });

/** 打开某会话行的 kebab 菜单并进入硬删确认面。 */
async function openDeleteConfirm(page: Page, sessionId: string): Promise<void> {
  await rowOf(page, sessionId).locator('.rail-menu-btn').click();
  await page.getByRole('menuitem', { name: '删除会话…' }).click();
  await expect(dialog(page)).toBeVisible();
}

/** 收集真正发出去的会话硬删请求（"取消不发请求"这条 AC 的判据）。 */
function countSessionDeletes(page: Page): { urls: string[] } {
  const urls: string[] = [];
  page.on('request', (req) => {
    if (req.method() !== 'DELETE') return;
    const path = new URL(req.url()).pathname;
    if (/^\/api\/sessions\/[^/]+$/.test(path)) urls.push(path);
  });
  return { urls };
}

/** FE-R11-09 回归锁：≤820px 的 56px 图标轨里，删除入口必须仍然可达。
 *
 *  窄屏下每行只剩一个 24px 槽位（`.session-item-body` 收起），行菜单是到达
 *  「重命名 / 移出项目 / 删除会话」的唯一路径；此前 `.rail-menu-btn` 与项目头
 *  一起 `display:none`，这些操作在窄屏彻底消失且没有替代入口。
 *  同一条规则还误伤了 `.session-item-dot`（那块注释声称"只留下点"，实际把点也藏了
 *  → 行是空条），现在点与 ⋯ 共用槽位：空闲显示点，hover/聚焦换成 ⋯ 且不挤占
 *  会话的可点面积（⋯ 绝对定位，不参与布局）。 */
test.describe('窄屏（≤820px）删除入口', () => {
  test.use({ viewport: { width: 800, height: 900 } });

  test('窄屏：槽位默认是会话点，聚焦后换成 ⋯，且能走完删除确认流程', async ({ page }) => {
    routeApi(page, { sessions: [projectSession(), freeSession()], projects: [P1], events: HISTORY });
    await page.goto('/');

    const row = rowOf(page, 's2');
    const dot = row.locator('.session-item-dot');
    const btn = row.locator('.rail-menu-btn');

    // 指针挪开侧栏 → 真·空闲态：点必须在场（否则这一行什么也看不见）
    await page.mouse.move(0, 0);
    await expect(dot).toBeVisible();
    await expect(dot).toHaveCSS('opacity', '1');
    // ⋯ 默认安静，键盘聚焦必须让它现身（:focus-visible 那条规则不能在窄屏失效）
    await btn.focus();
    await expect(btn).toBeVisible();
    await expect.poll(() => btn.evaluate((el) => getComputedStyle(el).opacity)).toBe('1');
    // 同槽位不叠两团东西：⋯ 浮现时点让位
    await expect(dot).toHaveCSS('opacity', '0');

    // 会话的可点面积没被 ⋯ 挤掉（⋯ 绝对定位，不参与布局）
    const itemW = await row
      .locator('.session-item')
      .evaluate((el) => Math.round(el.getBoundingClientRect().width));
    expect(itemW).toBeGreaterThanOrEqual(24);

    await btn.click();
    await page.getByRole('menuitem', { name: '删除会话…' }).click();
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toContainText('不可恢复');
  });
});

/** FE-R11-10 回归锁：确认面的初始焦点落在「取消」，不是右上「关闭(X)」。
 *  一次不可逆删除的确认面上，键盘用户落地第一眼看到的控件应该是安全的出口。 */
test('删除确认弹窗：初始焦点在「取消」，Enter 即安全取消', async ({ page }) => {
  routeApi(page, { sessions: [projectSession(), freeSession()], projects: [P1], events: HISTORY });
  const deletes = countSessionDeletes(page);
  await page.goto('/');

  await openDeleteConfirm(page, 's2');
  const cancel = dialog(page).getByRole('button', { name: '取消' });
  await expect(cancel).toBeFocused();
  await expect(dialog(page).getByRole('button', { name: '关闭' })).not.toBeFocused();

  // 初焦在取消 → 直接回车 = 取消（零请求），而不是落在危险的「永久删除」上
  await page.keyboard.press('Enter');
  await expect(dialog(page)).toBeHidden();
  expect(deletes.urls).toEqual([]);
});

test('确认面说清不可恢复 + 取消零请求 + 确认后行消失/项目计数掉/当前会话被清空', async ({ page }) => {
  routeApi(page, { sessions: [projectSession(), freeSession()], projects: [P1], events: HISTORY });
  const deletes = countSessionDeletes(page);
  await page.goto('/');

  // 打开项目里的那条会话：对话区有内容、记住的 id = s2（删除前后要有得比较）。
  await rowOf(page, 's2').locator('.session-item').click();
  await expect(page.locator('.model-output').last()).toContainText('要被删掉的那条任务的回答。');
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBe('s2');
  await expect(project(page).locator('.rail-project-count')).toHaveText('1');

  await openDeleteConfirm(page, 's2');

  // AC：不可逆必须写在**按下之前**——"删除"两个字单独出现不算。
  await expect(dialog(page)).toContainText('硬删除');
  await expect(dialog(page)).toContainText('不可恢复');
  await expect(dialog(page)).toContainText('没有回收站');
  // AC：会话标识（标题 / 首条消息 + id 片段）——用户据此确认点的是哪一条。
  // 标题取的是**侧栏那一行显示的**那个（打开会话后由事件派生覆盖列表预填值），
  // 所以这里与行上的字逐字一致：确认面认的就是用户刚点的那一行。
  await expect(dialog(page).locator('.project-dialog-target-title')).toHaveText(
    '要被删掉的那条任务的提问',
  );
  await expect(dialog(page).locator('.project-dialog-target-id')).toHaveText('id s2');
  // 按钮也不许只写"删除"。
  await expect(dialog(page).getByRole('button', { name: '永久删除（不可恢复）' })).toBeVisible();

  // 取消路径：零请求、行还在、视图与记住的 id 一个都没动。
  await dialog(page).getByRole('button', { name: '取消' }).click();
  await expect(dialog(page)).toBeHidden();
  expect(deletes.urls).toEqual([]);
  await expect(rowOf(page, 's2')).toBeVisible();
  await expect(page.locator('.model-output').last()).toContainText('要被删掉的那条任务的回答。');
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBe('s2');

  // 确认路径：回执的两个计数都来自后端响应（events=42 是行上的 event_count，
  // detached=1 是它真的进过一个项目账本）。
  await openDeleteConfirm(page, 's2');
  await dialog(page).getByRole('button', { name: '永久删除（不可恢复）' }).click();
  await expect(dialog(page).locator('.project-dialog-done')).toHaveText(
    '已永久删除 42 条事件记录（不可恢复），并从 1 个项目里解除。',
  );
  await dialog(page).getByRole('button', { name: '完成' }).click();
  await expect(dialog(page)).toBeHidden();

  expect(deletes.urls).toEqual(['/api/sessions/s2']);
  // ① 行真的没了（后端状态变了；本地隐藏的实现拿不到这一条——重拉也不会有）
  await expect(rowOf(page, 's2')).toHaveCount(0);
  await expect(rowOf(page, 's1')).toBeVisible(); // 只删它，别的一行不少
  // ② 项目账本也摘掉了它（计数 1 → 0 + 空项目占位）
  await expect(project(page).locator('.rail-project-count')).toHaveText('0');
  await expect(project(page).locator('.rail-project-empty')).toContainText('这个项目还没有会话');
  // ③ 被删的正是当前打开的会话 → 对话区清空、记住的 id 清掉（刷新不会被拉回死会话）
  await expect(page.locator('.empty-hero')).toBeVisible();
  await expect(page.locator('.model-output')).toHaveCount(0);
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBeNull();
  // 刷新一次也不会复活它（后端状态是真删，不是视图层过滤）
  await page.reload();
  await expect(rowOf(page, 's2')).toHaveCount(0);
  await expect(page.locator('.empty-hero')).toBeVisible();
});

test('409（fork 父会话 / 在途 run）：原样显示后端 detail，列表保持原样', async ({ page }) => {
  const forkDetail = "session 's2' is the fork parent of 2 session(s): delete the child session(s) first";
  const busyDetail = "session 's1' has a run in flight; cancel it first";
  routeApi(page, {
    sessions: [projectSession(), freeSession()],
    projects: [P1],
    // 两种 409 原因：状态码相同、只有 detail 能区分——所以两条都锁，且都要求逐字显示。
    sessionDeleteErrors: {
      s2: { status: 409, detail: forkDetail },
      s1: { status: 409, detail: busyDetail },
    },
  });
  const deletes = countSessionDeletes(page);
  await page.goto('/');
  await expect(project(page).locator('.rail-project-count')).toHaveText('1');

  await openDeleteConfirm(page, 's2');
  await dialog(page).getByRole('button', { name: '永久删除（不可恢复）' }).click();
  // 后端拒绝原因**原样**出现（含那条 detail 自带的子会话数量 2——盖掉它就是把
  // 唯一可行动的信息说糊了）。
  await expect(dialog(page).locator('.project-error')).toHaveText(forkDetail);
  // 失败时不给成功回执（"删了还看得见"的反面：凭空少一行同样是假象）。
  await expect(dialog(page).locator('.project-dialog-done')).toHaveCount(0);

  // 列表**保持原样**：两行都在、项目计数没变、没有乐观删除。
  await expect(rowOf(page, 's2')).toBeVisible();
  await expect(rowOf(page, 's1')).toBeVisible();
  await expect(project(page).locator('.rail-project-count')).toHaveText('1');

  // 换另一条 409（在途 run）走一遍：同一状态码、不同 detail，同样逐字。
  await dialog(page).getByRole('button', { name: '取消' }).click();
  await openDeleteConfirm(page, 's1');
  await dialog(page).getByRole('button', { name: '永久删除（不可恢复）' }).click();
  await expect(dialog(page).locator('.project-error')).toHaveText(busyDetail);
  await expect(rowOf(page, 's1')).toBeVisible();

  expect(deletes.urls).toEqual(['/api/sessions/s2', '/api/sessions/s1']);
});

test('404（会话本就不在了）：显示后端 detail，并让这条过期行收敛消失', async ({ page }) => {
  routeApi(page, {
    sessions: [projectSession(), freeSession()],
    projects: [P1],
    // 真机上这是个并发窗口（别处已删 / 另一个标签页删过）；mock 里 404 的条目也会
    // 把它从状态里摘掉——真后端在那一刻它确实不在。
    sessionDeleteErrors: { s2: { status: 404, detail: "session 's2' not found" } },
  });
  await page.goto('/');
  await openDeleteConfirm(page, 's2');
  await dialog(page).getByRole('button', { name: '永久删除（不可恢复）' }).click();
  // 后端刻意不把第二次删除伪装成"又删了一次"，所以这句话要如实显示。
  await expect(dialog(page).locator('.project-error')).toHaveText("session 's2' not found");

  // 但它说明**本地这行已过期**——收敛掉，否则用户对着一个永远删不掉的幽灵行反复重试。
  await dialog(page).getByRole('button', { name: '取消' }).click();
  await expect(rowOf(page, 's2')).toHaveCount(0);
  await expect(rowOf(page, 's1')).toBeVisible();
});

test('删的不是当前会话：视图与记住的 id 都不被拽走（只收敛被删的那一行）', async ({ page }) => {
  // s1 在项目里（被删的那个），s2 未分组（当前打开的）——删 s1 不该动 s2 的视图。
  routeApi(page, {
    sessions: [
      sessionRow('s1', { id: 'p1', title: '项目 alpha' }, { event_count: 7 }),
      sessionRow('s2', null, { event_count: 5 }),
    ],
    projects: [{ ...P1, session_ids: ['s1'] }],
    events: HISTORY,
  });
  await page.goto('/');

  await rowOf(page, 's2').locator('.session-item').click();
  await expect(page.locator('.model-output').last()).toContainText('要被删掉的那条任务的回答。');
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBe('s2');

  await openDeleteConfirm(page, 's1');
  await dialog(page).getByRole('button', { name: '永久删除（不可恢复）' }).click();
  // s1 是项目成员 → 回执带"从 1 个项目里解除"（计数来自后端响应，不是本地推断）。
  await expect(dialog(page).locator('.project-dialog-done')).toHaveText(
    '已永久删除 7 条事件记录（不可恢复），并从 1 个项目里解除。',
  );
  await dialog(page).getByRole('button', { name: '完成' }).click();

  await expect(rowOf(page, 's1')).toHaveCount(0);
  // 当前视图原封不动：对话内容还在、"暂无对话"空态没出现、记住的 id 仍是 s2
  // （把别人的删除当成"当前会话也没了"会把用户从他正在看的地方拽走）。
  await expect(page.locator('.model-output').last()).toContainText('要被删掉的那条任务的回答。');
  await expect(page.locator('.empty-hero')).toBeHidden();
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBe('s2');
  // 刷新后照常回到 s2：它没被删，记住的 id 不该被另一次删除清掉。
  await page.reload();
  await expect(page.locator('.model-output').last()).toContainText('要被删掉的那条任务的回答。');
});

