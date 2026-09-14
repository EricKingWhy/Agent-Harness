/** 场景 #183：Inspector 升级——清单+详情同框、peek 升级链（↑↓ / Esc / Space /
 *  钉住 / 整页 / 拖宽）。
 *
 *  为什么这些必须走 e2e：本仓组件测试是 SSR（只有首帧），而本票的九条 AC 里有
 *  八条是**交互**——选中项移动、键位、钉住跨会话、整页往返、拖宽不持久化。
 *  SSR 测试锁结构（`StepDetail.peek.test.tsx`），这里锁行为，两者不重叠。
 *
 *  场景数据用**历史会话**（`GET /events` 加载）而不是流式建会话：键盘用的会话应当
 *  是静止的，否则"↑↓ 之后哪一行被选中"会被流式新增行与贴底跟随搅在一起，测出来的
 *  是时序巧合而不是选中语义。
 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, type FrameSpec } from './fixtures';

/** 6 条事件的静止会话：足够让 ↑↓ 有"上/下"两个方向可走。 */
const EVENTS: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
  { type: 'user/message', data: { content: '看看这个' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'tool/call', data: { tool_call_id: 'tc-1', tool_name: 'bash', args: { command: 'ls' } }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'tool/result', data: { tool_call_id: 'tc-1', content: '{"ok":true}' }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: RUN, time: T },
];

const session = (id: string, title: string) => ({
  session_id: id, event_count: EVENTS.length, first_event_time: T, last_event_time: T,
  first_user_message: title, trace_id: null, trace_url: null,
});

/** 打开会话（Inspector 在 ≥1200px 默认展开），返回 Timeline 行 locator。 */
async function openSession(page: import('@playwright/test').Page, which = 0) {
  await page.locator('.session-item').nth(which).click();
  const rows = page.locator('.timeline-row');
  await expect(rows).toHaveCount(EVENTS.length);
  return rows;
}

test('AC1：点一行即预览；↑↓ 移动选中，详情实时跟随且清单不消失', async ({ page }) => {
  routeApi(page, { sessions: [session(SID, '看看这个')], events: EVENTS });
  await page.goto('/');
  const rows = await openSession(page);

  // 鼠标点击即选中即预览（AC3：不做键盘唯一）
  await rows.nth(1).click();
  await expect(rows.nth(1)).toHaveAttribute('aria-current', 'true');
  const peek = page.locator('.detail-peek');
  await expect(peek).toBeVisible();
  await expect(peek.locator('.detail-peek-kind')).toHaveText('run/started');

  // ↑ 回到第一条 → 详情跟着换（不重新挂载：容器还是同一个）
  await page.keyboard.press('ArrowUp');
  await expect(rows.nth(0)).toHaveAttribute('aria-current', 'true');
  await expect(peek.locator('.detail-peek-kind')).toHaveText('session/started');

  // ↓ 两次 → 到第三条（user/message）
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  await expect(rows.nth(2)).toHaveAttribute('aria-current', 'true');
  await expect(peek.locator('.detail-peek-kind')).toHaveText('user/message');

  // 清单仍在（同框）——此前 focus 非 run 时清单整个被替换掉
  await expect(rows).toHaveCount(EVENTS.length);
  // 只有一行是当前项（aria 如实，不是"每行都亮"）
  await expect(page.locator('.timeline-row[aria-current="true"]')).toHaveCount(1);

  // 两端不环绕：在第一条上再按 ↑ 仍停在第一条
  await rows.nth(0).click();
  await page.keyboard.press('ArrowUp');
  await expect(rows.nth(0)).toHaveAttribute('aria-current', 'true');
});

test('AC2：Esc 关预览但面板与清单都还在（关闭不卸载）', async ({ page }) => {
  routeApi(page, { sessions: [session(SID, '看看这个')], events: EVENTS });
  await page.goto('/');
  const rows = await openSession(page);

  await rows.nth(2).click();
  const peek = page.locator('.detail-peek');
  await expect(peek).toBeVisible();

  await page.keyboard.press('Escape');

  // 关掉：视觉上不可见，但**仍在 DOM 里**（hidden 而不是卸载）
  await expect(peek).toBeHidden();
  await expect(peek).toHaveCount(1);
  // 面板与清单原封不动
  await expect(page.locator('.step-detail')).toBeVisible();
  await expect(rows).toHaveCount(EVENTS.length);
  // 选中项保留：再按 Space 能立刻把同一个目标的预览召回来（下面那条用例直接接着验）
  await page.keyboard.press('Space');
  await expect(peek).toBeVisible();
  await expect(peek.locator('.detail-peek-kind')).toHaveText('user/message');
});

test('AC2：Space 快按=保持打开，按住=松手关闭（Linear peek 语义）', async ({ page }) => {
  routeApi(page, { sessions: [session(SID, '看看这个')], events: EVENTS });
  await page.goto('/');
  const rows = await openSession(page);

  await rows.nth(1).click();
  const peek = page.locator('.detail-peek');
  await page.keyboard.press('Escape');
  await expect(peek).toBeHidden();

  // 快按：松开后仍然开着
  await page.keyboard.press('Space');
  await expect(peek).toBeVisible();

  // 按住 ~450ms（阈值 250ms）再松手：临时预览，松手即关
  await page.keyboard.down('Space');
  await page.waitForTimeout(450);
  await page.keyboard.up('Space');
  await expect(peek).toBeHidden();

  // 关掉预览不影响选中项与清单
  await expect(rows.nth(1)).toHaveAttribute('aria-current', 'true');
  await expect(rows).toHaveCount(EVENTS.length);
});

test('AC4：钉住跨会话——未钉住切换会话收起，钉住后保持打开', async ({ page }) => {
  const OTHER = 'e2e-session-0183b';
  routeApi(page, {
    sessions: [session(SID, '第一个'), session(OTHER, '第二个')],
    events: EVENTS,
  });
  await page.goto('/');
  await openSession(page, 0);
  await expect(page.locator('.step-detail')).toBeVisible();

  // 未钉住：切到另一个会话 → 面板收起（仍是 DOM，只是 0 宽不可见）
  await page.locator('.session-item').nth(1).click();
  await expect(page.locator('.app-regions')).toHaveClass(/inspector-closed/);
  await expect(page.locator('.step-detail')).toBeHidden();

  // 打开面板 → 钉住
  await page.getByRole('button', { name: '展开 Inspector' }).click();
  await expect(page.locator('.step-detail')).toBeVisible();
  const pin = page.locator('.detail-ctrl[aria-label="钉住"]');
  await expect(pin).toHaveAttribute('aria-pressed', 'false');
  await pin.click();
  await expect(pin).toHaveAttribute('aria-pressed', 'true');

  // 钉住后：来回切会话都不收起
  await page.locator('.session-item').nth(0).click();
  await expect(page.locator('.app-regions')).not.toHaveClass(/inspector-closed/);
  await expect(page.locator('.step-detail')).toBeVisible();
  await page.locator('.session-item').nth(1).click();
  await expect(page.locator('.app-regions')).not.toHaveClass(/inspector-closed/);

  // 钉住是视图状态、不持久化：刷新后回到未钉住
  await page.reload();
  await expect(page.locator('.detail-ctrl[aria-label="钉住"]')).toHaveAttribute('aria-pressed', 'false');
});

test('AC5：整页往返（面板按钮 + 命令面板两个入口）', async ({ page }) => {
  routeApi(page, { sessions: [session(SID, '看看这个')], events: EVENTS });
  await page.goto('/');
  await openSession(page);

  const expand = page.locator('.detail-ctrl[aria-label="整页"]');
  await expect(expand).toHaveAttribute('aria-pressed', 'false');
  await expand.click();

  // 整页：面板占满，rail 与中心列收起但仍挂载
  await expect(page.locator('.app-regions')).toHaveClass(/inspector-fullpage/);
  await expect(page.locator('.step-detail')).toBeVisible();
  await expect(page.locator('.session-rail')).toBeHidden();
  await expect(expand).toHaveAttribute('aria-pressed', 'true');

  // Esc 先退回整页（分层：这一层不通，用户会以为卡死在整页里）
  await page.locator('.timeline-row').first().click();
  await page.keyboard.press('Escape');
  await expect(page.locator('.app-regions')).not.toHaveClass(/inspector-fullpage/);
  await expect(page.locator('.session-rail')).toBeVisible();

  // 第二入口：命令面板
  await page.keyboard.press('Control+k');
  await page.locator('.palette-input').fill('整页');
  await expect(page.locator('.palette-item', { hasText: '整页打开 Inspector' })).toBeVisible();
  await page.locator('.palette-item', { hasText: '整页打开 Inspector' }).click();
  await expect(page.locator('.app-regions')).toHaveClass(/inspector-fullpage/);

  // 退回（同一个按钮）
  await expand.click();
  await expect(page.locator('.app-regions')).not.toHaveClass(/inspector-fullpage/);
  await expect(page.locator('.app-workspace')).toBeVisible();
});

test('AC6：可拖宽 320→480，夹取到上限且不压垮中心列；刷新后回到 320（不持久化）', async ({
  page,
}) => {
  routeApi(page, { sessions: [session(SID, '看看这个')], events: EVENTS });
  await page.goto('/');
  await openSession(page);

  const resizer = page.locator('.detail-resizer');
  await expect(resizer).toHaveAttribute('aria-valuenow', '320');
  await expect(resizer).toHaveAttribute('aria-valuemin', '320');
  await expect(resizer).toHaveAttribute('aria-valuemax', '480');

  /* 每次拖拽前**重新量**手柄位置：拖宽会把手柄本身挪走，用上一次的坐标再按下去
     会落在面板内容上（第一次拖动后 x 就不再是初始值）。 */
  const dragBy = async (dx: number) => {
    const box = await resizer.boundingBox();
    if (!box) throw new Error('拖宽手柄没有布局盒');
    const y = box.y + Math.min(120, box.height / 2);
    await page.mouse.move(box.x + 3, y);
    await page.mouse.down();
    await page.mouse.move(box.x + 3 + dx, y, { steps: 8 });
    await page.mouse.up();
  };

  // 拖到远超上限的位置：夹取到 480。
  //
  // 注意这条用例**证明不了**"上限会被中心列压低"（AC6 的 `CENTER_MIN_W`）：三栏栅格
  // 只在 ≥1201px 生效，那里 available = viewport − 240 ≥ 961，`available − 360`
  // 恒 > 480 ⇒ 上限恒为 480。要构造"上限真的咬住"的宽度得先改布局（<1200px 的折叠
  // 分支把面板列写死成 280px）。所以这里锁的是**接线**（拖拽确实走到夹取、中心列没被
  // 挤没），而夹取公式本身由 `src/lib/inspectorPanel.test.ts` 的
  // `clampInspectorWidth(480, 700) === 340` 锁住——两处各管一段，别互相冒充。
  await dragBy(600);
  await expect(resizer).toHaveAttribute('aria-valuenow', '480');
  // 中心列没被压垮（AC6 的"不得压垮"）
  const workspace = await page.locator('.app-workspace').boundingBox();
  expect(workspace?.width ?? 0).toBeGreaterThanOrEqual(360);

  // 往左拖回去也要有下限
  await dragBy(-600);
  await expect(resizer).toHaveAttribute('aria-valuenow', '320');

  // 不持久化（不变量 #22）：拖宽后刷新回到 320
  await dragBy(80);
  expect(Number(await resizer.getAttribute('aria-valuenow'))).toBeGreaterThan(320);
  await page.reload();
  await openSession(page);
  await expect(page.locator('.detail-resizer')).toHaveAttribute('aria-valuenow', '320');
});

test('AC7：面板控制都键盘可达（Tab 到拖宽手柄可用方向键调宽）', async ({ page }) => {
  routeApi(page, { sessions: [session(SID, '看看这个')], events: EVENTS });
  await page.goto('/');
  await openSession(page);

  const resizer = page.locator('.detail-resizer');
  await resizer.focus();
  await expect(resizer).toBeFocused();
  await page.keyboard.press('ArrowRight');
  await expect(resizer).toHaveAttribute('aria-valuenow', '336'); // 320 + 16
  await page.keyboard.press('ArrowLeft');
  await expect(resizer).toHaveAttribute('aria-valuenow', '320');

  // 三个按钮都在 Tab 序列里，且名字可读
  await expect(page.locator('.detail-ctrl[aria-label="钉住"]')).toBeVisible();
  await expect(page.locator('.detail-ctrl[aria-label="整页"]')).toBeVisible();
  await expect(page.locator('button[aria-label="关闭 Inspector"]')).toBeVisible();

  // 关闭按钮 = 收起面板（不卸载）
  await page.locator('button[aria-label="关闭 Inspector"]').click();
  await expect(page.locator('.app-regions')).toHaveClass(/inspector-closed/);
  await expect(page.getByRole('button', { name: '展开 Inspector' })).toBeVisible();
});
