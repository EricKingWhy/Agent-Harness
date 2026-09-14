/** 流式滚动（用户症状：滑轮往下滚被自动滚回顶部，「必须要输出完才能看见」）。
 *
 *  根因是 `Conversation.tsx` 的自动滚动 effect 依赖整个 `conversation` 对象
 *  （每个 delta 都是新引用）→ 每个 delta 重发一次 `scrollIntoView({behavior:
 *  'smooth'})`，动画被反复重启；且它另抄了一份阈值硬编码 120 的 nearBottom，
 *  与 `lib/followLatest`（阈值 48，ReasoningBlock / ToolCard 已在用）并行。
 *
 *  修法：复用 FOLLOW 原语，只在 `followRef.following` 为真时瞬时贴底。
 *
 *  锁什么：浏览器滚动锚定关闭、空闲态无浮标、以及用**真实滚轮**驱动的
 *  脱离→浮标→回底→恢复跟随这一串可观察契约。最后一个用例不需要增量 SSE——
 *  `run_status` 停在 `running`（mock 事件流故意不给终态）即可，而
 *  `page.mouse.wheel` 产生的是浏览器真实 wheel 事件。
 *
 *  **没锁什么（重要）**：用户报的原始症状是「delta 到达时把上滚的视口拽回底部」
 *  这个**竞态**——`scroll` 事件要等下一个渲染时机才派发，而 delta 提交可能先到，
 *  于是自动贴底抢先执行、把脱离意图吞掉。要复现它必须在「wheel 之后、scroll 事件
 *  派发之前」插入一次提交，fixture 的帧是一次性到达的（见 fixtures.ts `fulfillSse`），
 *  没有这个时间控制点；一旦上滚真的发生了（位置越过阈值），scroll 监听单独就会
 *  正确脱离，所以任何确定性用例都无法把这条竞态与「只用 scroll 监听」区分开。
 *  该竞态的证据是真机埋点实测（`docs/FRONTEND_ISSUES_LOG.md` 第 19 项：wheel 同步
 *  脱离后 6×250ms 采样 dTop 恒为 0、期间 0 次贴底），不是本文件的自动化断言。
 *  因此 `setScrollNode` 里的 wheel 监听**不可**因为「测试没覆盖」而删除。
 *  纯状态转移（following / suspended / jump）由 lib/followLatest.test.ts 单元锁。 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, type FrameSpec } from './fixtures';

const EVENTS: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, time: T },
  // user/message 不带 step_id（真实信封形状；步号由后续事件携带）
  { type: 'user/message', data: { content: '滚动验证' }, seq: 2, session_id: SID, time: T },
  { type: 'run/started', data: { turn_index: 1 }, seq: 3, session_id: SID, run_id: RUN, time: T },
  { type: 'text/delta', data: { delta: '回答。' }, seq: 4, session_id: SID, step_id: 1, run_id: RUN, time: T },
  { type: 'model/completed', data: { content: '回答。' }, seq: 5, session_id: SID, step_id: 1, run_id: RUN, time: T },
  { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: RUN, time: T },
];

const ROW = { session_id: SID, event_count: 6, first_event_time: T, last_event_time: T, first_user_message: '滚动验证', trace_id: null, trace_url: null };

test('滚动容器关闭浏览器滚动锚定（虚拟化动态测高会与锚定打架）', async ({ page }) => {
  routeApi(page, { sessions: [ROW], events: EVENTS });
  await page.goto('/');
  await page.locator('.session-item').first().click();
  await expect(page.locator('.turn')).toHaveCount(1);

  const anchor = await page
    .locator('.conversation-scroll')
    .evaluate((el) => getComputedStyle(el).overflowAnchor);
  expect(anchor).toBe('none');
});

test('非流式态不出现「↓ 最新」浮标（没有「最新」可跳，浮标不得残留）', async ({ page }) => {
  routeApi(page, { sessions: [ROW], events: EVENTS });
  await page.goto('/');
  await page.locator('.session-item').first().click();
  await expect(page.locator('.turn')).toHaveCount(1);

  // 上滚到顶（历史已结束，run_status 非 running）
  await page.locator('.conversation-scroll').evaluate((el) => { el.scrollTop = 0; });
  await expect(page.locator('.follow-pill')).toHaveCount(0);
});

/** 长内容 + **不给终态**（run_status 停在 running）→ 自动贴底闸门为真。
 *  这样无需增量 SSE 即可复现「贴底跟随 → 真实滚轮上滚 → 脱离」这条路径：
 *  自动贴底只在 conversation/runActive 变化时跑，帧一次性到达后不再触发，
 *  于是视口位置只可能被用户的手势改变。 */
const LONG_LINES = Array.from({ length: 300 }, (_, i) => `${i} 行内容占位，用来把滚动容器撑高。`).join('\n');

const RUNNING_EVENTS: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, time: T },
  { type: 'user/message', data: { content: '长回答' }, seq: 2, session_id: SID, time: T },
  { type: 'run/started', data: { turn_index: 1 }, seq: 3, session_id: SID, run_id: RUN, time: T },
  { type: 'text/delta', data: { delta: LONG_LINES }, seq: 4, session_id: SID, step_id: 1, run_id: RUN, time: T },
];

test('流式中上滚（真实滚轮）：浮标出现、点浮标回底并恢复跟随', async ({ page }) => {
  routeApi(page, { sessions: [{ ...ROW, event_count: 4 }], events: RUNNING_EVENTS });
  await page.goto('/');
  await page.locator('.session-item').first().click();
  await expect(page.locator('.turn')).toHaveCount(1);

  const scroller = page.locator('.conversation-scroll');
  const gap = () => scroller.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight);
  const top = () => scroller.evaluate((el) => el.scrollTop);
  const range = () => scroller.evaluate((el) => el.scrollHeight - el.clientHeight);

  // 虚拟化要先测高，容器才真的可滚（否则「位置不变」会退化成平凡成立）
  await expect.poll(range).toBeGreaterThan(200);

  // 先到底 = 用户本来就在底部跟随。程序化写 scrollTop 与滚动条拖动同路：
  // 派发 scroll → nearBottom → 跟随态收敛为 FOLLOW_BOTTOM。
  await scroller.evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await expect.poll(gap).toBeLessThan(5);
  const bottomTop = await top();

  // 真实滚轮（浏览器事件，非 JS 合成）落在滚动容器上
  const box = (await scroller.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -800);

  await expect(page.locator('.follow-pill')).toBeVisible({ timeout: 2000 });
  const afterWheel = await top();
  expect(afterWheel).toBeLessThan(bottomTop - 5); // 确实滚上去了

  // 位置保持（本 fixture 的帧一次性到齐，上滚后不再有提交，所以这一步对两种
  // 实现都成立——它锁的是「上滚后视口不自发回弹」这一可观察契约，**不是**
  // 「增量 delta 到达时是否被拽回」那个竞态；见文件头注释）。
  await page.waitForTimeout(500);
  expect(await top()).toBe(afterWheel);
  await expect(page.locator('.follow-pill')).toBeVisible();

  // 点浮标 → 瞬时回底 + 恢复跟随 + 浮标消失
  await page.locator('.follow-pill').click();
  await expect.poll(gap).toBeLessThan(5);
  await expect(page.locator('.follow-pill')).toHaveCount(0);
});
