/** BUG-001 回归锁（T7 #137 分叉）：分叉锚点必须是 user/message 的**持久 seq**，
 *  而不是 `turn.step_id`（resolveStep 合成值）。二者只在第 1 轮偶然相等——
 *  第 2 轮起把 step_id 当 from_seq 传会被后端 422 拒绝，且旧代码 `catch {}` 吞掉。
 *
 *  夹具刻意把 user/message 的 seq 与 turn 序号错开（第 1 轮 seq=2、第 2 轮
 *  seq=30，turn_index 分别是 1/2）：若哪天又有人把 turn 序号当锚点，这里会红。 */

import { expect, test, type Page } from '@playwright/test';
import { RUN, SID, T, routeApi, type ApiMock, type FrameSpec } from './fixtures';

const CHILD = `${SID}-child`;

/** 两轮已完成会话。user/message seq：2 / 30；turn 序号 1 / 2。
 *
 *  user/message **刻意不写 step_id**：真实事件信封里它恒为 null（后端
 *  `Session.append(USER_MESSAGE)` 不带 step），step 由随后的 text/delta 携带。
 *  BUG-001 正是「锚点用 turn 序号冒充 seq」，而 turn 序号只有在 user/message
 *  缺席 step_id 时才由 resolveStep 合成——照真实形状造夹具，回归锁才咬得住。 */
function twoTurnEvents(): FrameSpec[] {
  return [
    { type: 'session/started', seq: 1, session_id: SID, time: T },
    { type: 'user/message', data: { content: '第一轮问题' }, seq: 2, session_id: SID, time: T },
    { type: 'run/started', data: { turn_index: 1 }, seq: 3, session_id: SID, run_id: `${RUN}-1`, time: T },
    { type: 'text/delta', data: { delta: '第一轮回答。' }, seq: 4, session_id: SID, step_id: 1, run_id: `${RUN}-1`, time: T },
    { type: 'model/completed', data: { content: '第一轮回答。' }, seq: 5, session_id: SID, step_id: 1, run_id: `${RUN}-1`, time: T },
    { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: `${RUN}-1`, time: T },
    { type: 'user/message', data: { content: '第二轮问题' }, seq: 30, session_id: SID, time: T },
    { type: 'run/started', data: { turn_index: 2 }, seq: 31, session_id: SID, run_id: `${RUN}-2`, time: T },
    { type: 'text/delta', data: { delta: '第二轮回答。' }, seq: 32, session_id: SID, step_id: 2, run_id: `${RUN}-2`, time: T },
    { type: 'model/completed', data: { content: '第二轮回答。' }, seq: 33, session_id: SID, step_id: 2, run_id: `${RUN}-2`, time: T },
    { type: 'run/completed', data: {}, seq: 34, session_id: SID, run_id: `${RUN}-2`, time: T },
  ];
}

const PARENT_ROW = {
  session_id: SID,
  event_count: 11,
  first_event_time: T,
  last_event_time: T,
  first_user_message: '第一轮问题',
  trace_id: null, trace_url: null,
};

/** 进入会话：列表 → 点行 → 等两轮都投影进 DOM。 */
async function openSessionWith(page: Page, mock: ApiMock): Promise<void> {
  routeApi(page, mock);
  await page.goto('/');
  await page.locator('.session-item').first().click();
  await expect(page.locator('.turn')).toHaveCount(2);
}

test('B1 回归锁：第 2 轮分叉传 user/message 的 seq（30），不是 turn 序号（2）', async ({ page }) => {
  let captured: { from_seq?: number } | null = null;
  // 会话列表在每次请求时读取（routeApi 的 handler 内取 mock.sessions），
  // 故 fork 成功后把 child 推进去，refreshSessions 就能看到它。
  const sessions: unknown[] = [PARENT_ROW];
  await openSessionWith(page, {
    sessions,
    events: twoTurnEvents(),
    onForkPost: async (route) => {
      captured = route.request().postDataJSON() as { from_seq?: number };
      sessions.push({
        session_id: CHILD,
        event_count: 2,
        first_event_time: T,
        last_event_time: T,
        first_user_message: null,
        trace_id: null, trace_url: null,
      });
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ session_id: CHILD, from_seq: captured.from_seq ?? 0 }),
        contentType: 'application/json',
      });
    },
  });
  await expect(page.locator('.turn').nth(1)).toContainText('第二轮问题');

  await page.locator('.turn').nth(1).locator('.fork-btn').click();

  await expect.poll(() => captured).not.toBeNull();
  expect(captured!.from_seq).toBe(30);
  // 分叉结果被消费：选中切到 child（证明不是「按钮点了没反应」）。
  // 判等用行上的 `title`（完整 session_id），**不能**用 ContainsText(前 12 字符)：
  // `SessionList` 每行都渲染 `session_id.slice(0, 12)`，而 child id 的前 12 字符与
  // parent 相同（`e2e-session-`）——子串判断在 parent 仍被选中时也通过，等于这个
  // 断言从没验证过导航（把 selectSession 调用删掉它照样绿）。
  await expect(page.locator('.session-item.selected')).toHaveAttribute(
    'title',
    new RegExp(`^${CHILD} `),
  );
  await expect(page.locator('.app-error')).toHaveCount(0);
});

test('B2：分叉被拒绝时展示后端 detail，不再静默吞错', async ({ page }) => {
  await openSessionWith(page, {
    sessions: [PARENT_ROW],
    events: twoTurnEvents(),
    onForkPost: async (route) => {
      await route.fulfill({
        status: 422,
        body: JSON.stringify({ detail: 'from_seq 不是合法分叉锚点；可用边界: [2, 30]' }),
        contentType: 'application/json',
      });
    },
  });

  await page.locator('.turn').nth(1).locator('.fork-btn').click();

  const alert = page.locator('[role="alert"]');
  await expect(alert).toContainText('分叉失败');
  await expect(alert).toContainText('可用边界: [2, 30]');
});

test('B3：第 1 轮按钮提示 child 将是空会话（锚点消息不进 seed）', async ({ page }) => {
  await openSessionWith(page, { sessions: [PARENT_ROW], events: twoTurnEvents() });

  await expect(page.locator('.turn').nth(0).locator('.fork-btn')).toHaveAttribute('title', /空会话/);
  await expect(page.locator('.turn').nth(1).locator('.fork-btn')).toHaveAttribute(
    'title',
    '从此处分叉新会话',
  );
});

test('注入的纠正消息不渲染分叉入口（不是真人说的话，没有可继承的轮次）', async ({ page }) => {
  await openSessionWith(page, {
    sessions: [PARENT_ROW],
    events: [
      { type: 'session/started', seq: 1, session_id: SID, time: T },
      { type: 'user/message', data: { content: '第一轮问题' }, seq: 2, session_id: SID, time: T },
      { type: 'run/started', data: { turn_index: 1 }, seq: 3, session_id: SID, run_id: `${RUN}-1`, time: T },
      { type: 'model/completed', data: { content: '第一轮回答。' }, seq: 4, session_id: SID, step_id: 1, run_id: `${RUN}-1`, time: T },
      { type: 'run/completed', data: {}, seq: 5, session_id: SID, run_id: `${RUN}-1`, time: T },
      {
        type: 'user/message',
        data: { content: '请重试', injected_by: 'failure-guard:soft' },
        seq: 6,
        session_id: SID,
        time: T,
      },
      { type: 'run/started', data: { turn_index: 2 }, seq: 7, session_id: SID, run_id: `${RUN}-2`, time: T },
      { type: 'model/completed', data: { content: '第二轮回答。' }, seq: 8, session_id: SID, step_id: 2, run_id: `${RUN}-2`, time: T },
      { type: 'run/completed', data: {}, seq: 9, session_id: SID, run_id: `${RUN}-2`, time: T },
    ],
  });

  await expect(page.locator('.turn').nth(0).locator('.fork-btn')).toHaveCount(1);
  await expect(page.locator('.turn').nth(1).locator('.system-notice')).toHaveCount(1);
  await expect(page.locator('.turn').nth(1).locator('.fork-btn')).toHaveCount(0);
});
