/** 场景 S（MEM-5 / #160）：记忆管理 UI——列表 / 分页 / 单条硬删二次确认 / 失败回滚 / 降级态。
 *
 *  契约来源：issue #160 AC1–AC6 + 后端 `src/agent_harness/web/memory.py`。
 *
 *  为什么断言"关掉再打开"：AC3 明确要求"不得只做本地隐藏"（不变量 #22）。只断言
 *  "点了删除行就消失"是**两种实现都能通过**的——本地 filter 一下也能消失。所以
 *  成功路径必须再打开一次面板：那一行不在 = 后端状态真的变了（mock 有状态，
 *  见 fixtures.ts 的 memories 分支）。
 */

import { expect, test, type Page } from '@playwright/test';
import { T, routeApi, type MemoryFixture } from './fixtures';

/** 记忆 fixture（时间戳统一用 fixtures 的 T，方便断言 datetime 原值透传）。 */
const mem = (id: string, content: string, over: Partial<MemoryFixture> = {}): MemoryFixture => ({
  id,
  content,
  scope: 'user',
  metadata: {},
  created_at: T,
  ...over,
});

const SHORT = mem('m-1', '用户偏好简洁的中文回答，不要客套话。');
const OTHER = mem('m-2', '用户的项目在 D:/repos 下。');
/** > 180 字符 → 触发折叠 + 展开按钮（AC1 要求 content 可见：全文必须读得到）。 */
const LONG = mem('m-3', `用户详细偏好：${'细节'.repeat(120)}`);

const panel = (page: Page) => page.locator('.memory-panel');
const row = (page: Page, text: string) => page.locator('.memory-row', { hasText: text });

/** 从顶栏入口打开记忆面板（两次点击之间有请求，等列表稳定由调用方断言）。 */
async function openMemories(page: Page): Promise<void> {
  await page.getByRole('button', { name: '记忆管理' }).click();
  await expect(panel(page)).toBeVisible();
}

/** 关闭面板：底部「关闭」按钮（头部那个 X 的 aria-label 也叫"关闭"，必须限定在
 *  动作区——否则 strict mode 命中两个）。 */
async function closeMemories(page: Page): Promise<void> {
  await panel(page).locator('.project-dialog-actions').getByRole('button', { name: '关闭' }).click();
  await expect(panel(page)).toBeHidden();
}

test('AC1：列表按后端分页渲染 content / scope / 创建时间；"加载更多"真的翻页', async ({ page }) => {
  const requested: string[] = [];
  const many: MemoryFixture[] = Array.from({ length: 55 }, (_, i) =>
    mem(`p-${i}`, `第 ${i} 条记忆`, { scope: i % 10 === 3 ? 'session' : 'user' }),
  );
  routeApi(page, {
    memories: many,
    onMemoriesGet: (route) => {
      requested.push(new URL(route.request().url()).search);
      return false; // 交给 fixtures 的默认分页分支
    },
  });
  await page.goto('/');
  await openMemories(page);

  // 首屏一页（不一次拉全量）：后端默认页大小 50。dev 下 StrictMode 会把挂载
  // effect 跑两遍（第二次只是重复同一页），所以断言"翻页前**没有任何** offset>0
  // 的请求"，而不是给请求编号——编号会随 StrictMode 抖动。
  await expect(page.locator('.memory-row')).toHaveCount(50);
  expect(requested.length).toBeGreaterThan(0);
  expect(requested.every((s) => s.includes('limit=50') && s.includes('offset=0'))).toBe(true);
  expect(await row(page, '第 0 条记忆').count()).toBe(1);

  // AC1：三个字段都在场。时间**原样透传** ISO（展示层格式化由 lib/memory 负责，
  // 这里锁的是契约字段没被改写/丢弃）。
  const first = row(page, '第 0 条记忆');
  await expect(first.locator('.memory-time')).toHaveAttribute('datetime', T);
  await expect(first.locator('.memory-time')).not.toHaveText('');
  // scope 如实渲染（user/session 都有行，未知值不会被当成 user）。
  await expect(first.locator('.memory-scope')).toHaveText('用户');
  await expect(row(page, '第 3 条记忆').locator('.memory-scope')).toHaveText('会话');

  // "加载更多"→ offset = 已显示条数；到底则显示"已全部加载"（不再伪造下一页）。
  await page.getByRole('button', { name: '加载更多' }).click();
  await expect(page.locator('.memory-row')).toHaveCount(55);
  // 第二页真的发去了后端（offset = 已显示条数），不是前端把一份全量切成两半。
  await expect.poll(() => requested.some((s) => s === '?limit=50&offset=50')).toBe(true);
  await expect(panel(page).locator('.memory-more-end')).toHaveText('已全部加载');
  await expect(panel(page).getByRole('button', { name: '加载更多' })).toHaveCount(0);
});

test('AC1：长正文可展开读全文（删除决定前必须读得到完整内容）', async ({ page }) => {
  routeApi(page, { memories: [LONG, SHORT] });
  await page.goto('/');
  await openMemories(page);

  const longRow = row(page, '用户详细偏好');
  await expect(longRow.locator('.memory-content')).toHaveClass(/clamped/);
  await longRow.getByRole('button', { name: '展开全文' }).click();
  await expect(longRow.locator('.memory-content')).not.toHaveClass(/clamped/);
  // 短记忆不给展开按钮（多一个控件是噪音）。
  await expect(row(page, '不要客套话').getByRole('button', { name: '展开全文' })).toHaveCount(0);
});

test('AC2 + AC3：删除必须二次确认且写明"删除不可恢复"；确认后后端状态真的变了', async ({ page }) => {
  routeApi(page, { memories: [SHORT, OTHER] });
  await page.goto('/');
  await openMemories(page);

  // 取消路径：第一次点击只展开确认条，**不发 DELETE**、行不消失。
  const target = row(page, '不要客套话');
  await target.getByRole('button', { name: '删除这条记忆' }).click();
  await expect(target.locator('.memory-confirm')).toContainText('删除不可恢复');
  await expect(target.locator('.memory-confirm')).toContainText('没有回收站');
  await target.getByRole('button', { name: '取消' }).click();
  await expect(target.locator('.memory-confirm')).toHaveCount(0);
  await expect(target).toBeVisible();

  // 确认路径：行消失。
  await target.getByRole('button', { name: '删除这条记忆' }).click();
  await target.getByRole('button', { name: '确认删除' }).click();
  await expect(page.locator('.memory-row', { hasText: '不要客套话' })).toHaveCount(0);
  await expect(row(page, 'D:/repos')).toBeVisible(); // 只删这一条

  // AC3 的**关键**断言：关掉面板再打开（重新 GET 后端）——那条依然不在。
  // 本地隐藏的实现在这里必然变红。
  await closeMemories(page);
  await expect(panel(page)).toBeHidden();
  await openMemories(page);
  await expect(page.locator('.memory-row', { hasText: '不要客套话' })).toHaveCount(0);
  await expect(row(page, 'D:/repos')).toBeVisible();
});

test('AC3：删除失败 → UI 回滚（该行仍在）+ 显示后端拒绝原因', async ({ page }) => {
  routeApi(page, { memories: [SHORT, OTHER], memoryDeniedIds: ['m-1'] });
  await page.goto('/');
  await openMemories(page);

  const target = row(page, '不要客套话');
  await target.getByRole('button', { name: '删除这条记忆' }).click();
  await target.getByRole('button', { name: '确认删除' }).click();

  // 403 = 领域层归属校验：错误留在**这一行**的确认条里（不是整面横幅），
  // 且原文是后端 detail（前端不翻译成自己的话）。断言用真后端那句英文原文
  // （`PermissionError("Memory belongs to a different namespace")`）——mock 的
  // detail 编错会让这条用例变成"前端与我的假后端一致"的自我实现。
  await expect(target.locator('.project-error')).toContainText(
    'Memory belongs to a different namespace',
  );
  await expect(target).toBeVisible(); // 回滚：行没有被隐藏掉
  await expect(target.locator('.memory-confirm')).toBeVisible(); // 确认条留在原地可重试

  // 回滚来自**权威重拉**（不是本地把行塞回来）：关掉再打开，该行仍在后端。
  await closeMemories(page);
  await openMemories(page);
  await expect(row(page, '不要客套话')).toBeVisible();
});

test('AC3：这条在别处已被删（DELETE 404）→ 行随之消失，但失败必须报出来（不能被界面吞掉）', async ({
  page,
}) => {
  routeApi(page, { memories: [SHORT, OTHER], memoryVanishedIds: ['m-1'] });
  await page.goto('/');
  await openMemories(page);

  const target = row(page, '不要客套话');
  await target.getByRole('button', { name: '删除这条记忆' }).click();
  await target.getByRole('button', { name: '确认删除' }).click();

  // 权威列表里它确实没了（别处已删 → 收敛到"不在"），所以行内错误条随行一起消失。
  await expect(page.locator('.memory-row', { hasText: '不要客套话' })).toHaveCount(0);
  // 但**失败本身**必须可见：404 的后端原文出现在面板级错误条里。
  // 少了这条通道，用户点删除就"什么都没发生"（批次审查发现）。
  const panelError = panel(page).locator('.memory-error');
  await expect(panelError).toContainText('记忆不存在：m-1');
  await expect(row(page, 'D:/repos')).toBeVisible(); // 另一条不受影响

  await panelError.getByRole('button', { name: '知道了' }).click();
  await expect(panelError).toHaveCount(0);
});

test('AC4：记忆未装配（503）→ 如实说"记忆未启用"，不伪造空列表、不给无意义的重试', async ({ page }) => {
  const detail = 'memory capability 未启用：请在 CAPABILITIES 中配置 memory。';
  routeApi(page, { memories: [SHORT], memoryDisabled: detail });
  await page.goto('/');
  await openMemories(page);

  const degraded = panel(page).locator('.memory-degraded');
  await expect(degraded).toBeVisible();
  await expect(degraded).toContainText('记忆未启用');
  await expect(degraded).toContainText(detail); // 后端原话
  await expect(degraded).toContainText('CAPABILITIES');
  // 降级态与空态是两件事：不能显示"还没有记忆"，也不能给"重试"（配置状态重试无用）。
  await expect(panel(page).locator('.memory-empty')).toHaveCount(0);
  await expect(panel(page).getByRole('button', { name: '重试' })).toHaveCount(0);
  await expect(panel(page).locator('.memory-loading')).toHaveCount(0);
});

test('AC4：真的没有记忆 → "还没有记忆"（与降级/读取失败都区分开）', async ({ page }) => {
  routeApi(page, { memories: [] });
  await page.goto('/');
  await openMemories(page);
  await expect(panel(page).locator('.memory-empty')).toContainText('还没有记忆');
  await expect(panel(page).locator('.memory-degraded')).toHaveCount(0);
});

test('AC4：读取失败（500）→ 错误条 + 重试可恢复；不得显示成空态', async ({ page }) => {
  // 失败保持到本测试显式关掉（不是"只失败一次"）：dev 下 StrictMode 会把挂载
  // effect 跑两遍，"计数到 1"的写法会让第二个请求立刻把错误覆盖成成功列表。
  let fail = true;
  routeApi(page, {
    memories: [SHORT],
    onMemoriesGet: (route) => {
      if (!fail) return false;
      return route
        .fulfill({ status: 500, body: '{"detail":"boom"}', contentType: 'application/json' })
        .then(() => true);
    },
  });
  await page.goto('/');
  await openMemories(page);
  await expect(panel(page).locator('.memory-error')).toContainText('boom');
  // 真故障**不得**伪装成"没有记忆"（零伪造），也不是配置降级。
  await expect(panel(page).locator('.memory-empty')).toHaveCount(0);
  await expect(panel(page).locator('.memory-degraded')).toHaveCount(0);

  fail = false; // 服务恢复
  await panel(page).getByRole('button', { name: '重试' }).click();
  await expect(row(page, '不要客套话')).toBeVisible();
  await expect(panel(page).locator('.memory-error')).toHaveCount(0);
});

test('入口：命令面板「管理记忆」也能打开（顶栏按钮之外的第二入口）', async ({ page }) => {
  routeApi(page, { memories: [SHORT] });
  await page.goto('/');

  await page.keyboard.press('Control+k');
  await page.locator('.palette-input').fill('管理记忆');
  await page.locator('.palette-item', { hasText: '管理记忆' }).click();

  await expect(panel(page)).toBeVisible();
  await expect(row(page, '不要客套话')).toBeVisible();

  // Esc 关闭（Radix Dialog 语义）：管理面不该只能靠按钮退出。
  await page.keyboard.press('Escape');
  await expect(panel(page)).toBeHidden();
});
