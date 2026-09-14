/** 场景 P：Inspector 时间线的「加载更早 N 条」——**唯一零自动化覆盖的控件**。
 *
 * 背景（第六轮覆盖账目）：`StepDetail.tsx` 的 `timeline-earlier` 此前只有 SSR 契约
 * （`StepDetail.test.tsx` 锁了尾窗裁剪的**读**路径），而 `setWindowSize` 这条**写**路径
 * 没有任何自动化点击。SSR 车道点不了（本仓单测不用 Testing Library），所以锁在 e2e。
 *
 * 常量与源码同步：`TIMELINE_WINDOW_DEFAULT = 200`（初始窗口）、
 * `TIMELINE_WINDOW_STEP = 500`（每次展开）。它们已由 `StepDetail.test.tsx` 单测钉住；
 * 这里硬编码 200/60 是有意的——真改了常量，这条用例会红，提醒同步。
 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, type FrameSpec } from './fixtures';

const TOTAL = 260; // → 初始只显示最近 200 条，折叠 60 条

const EVENTS: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
  { type: 'user/message', data: { content: '长会话' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
  ...Array.from({ length: TOTAL - 3 }, (_, i) => ({
    type: 'text/delta',
    data: { delta: `块${i} ` },
    seq: 4 + i,
    session_id: SID,
    run_id: RUN,
    step_id: 1,
    time: T,
  })) as FrameSpec[],
];

test('时间线「加载更早 N 条」：真实点击展开折叠的前段，折叠条随之消失', async ({ page }) => {
  routeApi(page, {
    sessions: [{
      session_id: SID, event_count: EVENTS.length, first_event_time: T, last_event_time: T,
      first_user_message: '长会话', trace_id: null, trace_url: null,
    }],
    events: EVENTS,
  });

  await page.goto('/');
  await page.locator('.session-item').first().click();
  await expect(page.locator('.session-item').first()).toContainText('长会话');

  // 默认 tab 就是 Timeline（`useState<Tab>('timeline')`）；Inspector 在 ≥1200px 默认展开
  await expect(page.getByRole('tab', { name: 'Timeline' })).toHaveAttribute('aria-selected', 'true');

  const rows = page.locator('.timeline-row');
  await expect(page.locator('.timeline-window-bar')).toContainText(`共 ${TOTAL} 条`);
  await expect(page.locator('.timeline-window-bar')).toContainText('显示最近 200');
  // 窗口是**最近** 200 条：第一行是 seq 61（1..60 被折叠）
  await expect(rows).toHaveCount(200);
  await expect(rows.first().locator('.tl-seq')).toHaveText('61');

  const earlier = page.locator('.timeline-earlier');
  await expect(earlier).toHaveText('加载更早 60 条'); // min(STEP=500, hidden=60)

  await earlier.click();

  // 展开后：全部 260 行、最早一行露出来（seq 1）、折叠条消失
  await expect(rows).toHaveCount(TOTAL);
  await expect(rows.first().locator('.tl-seq')).toHaveText('1');
  await expect(page.locator('.timeline-window-bar')).toHaveCount(0);
});
