/** 场景 F（spec 01 §22）：历史重放——durable 事件经 projectHistory 重建
 *  （同一投影管线，不变量 #22）；会话行 = 首条用户消息标题。 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, type FrameSpec } from './fixtures';

test('历史重放：会话列表 → 点击行 → projectHistory 重建文本与工具', async ({ page }) => {
  const events: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '历史会话的标题' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'text/delta', data: { delta: '持久化的回答。' }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'model/completed', data: { content: '持久化的回答。' }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: RUN, time: T },
  ];
  routeApi(page, {
    sessions: [{ session_id: SID, event_count: 6, first_event_time: T, last_event_time: T, first_user_message: '历史会话的标题', trace_id: null, trace_url: null }],
    events,
  });

  await page.goto('/');
  await page.locator('.session-item').first().click();
  await expect(page.locator('.model-output').last()).toContainText('持久化的回答。');
  // 会话行标题来自首条 user/message（零额外请求预填）
  await expect(page.locator('.session-item').first()).toContainText('历史会话的标题');
});
