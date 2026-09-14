/** 场景 E（spec 01 §22 + 契约 §3）：断连重连——流异常收尾（无终态）→
 *  断线状态条 → GET /stream?after_seq=lastApplied 重放续传 → 终态收尾；
 *  重放帧经 seenSeqs 去重（无缝无重复），显式 cancel 不触发重连（T5）。 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, fulfillSse, submitTask, type FrameSpec } from './fixtures';

test('断连重连：断线条在场 → after_seq 续传 → 文本无重复 → 收尾清条', async ({ page }) => {
  const streamUrls: string[] = [];
  routeApi(page, {
    // 初始流：部分帧后异常收尾（不伪造终态——重连信号）
    onSessionPost: (route) => fulfillSse(route, [
          { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
          { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
          { type: 'user/message', data: { content: '讲个故事' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
          { type: 'text/delta', data: { delta: '从前' }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
        ]),
    // 终态后 viewing 迁移重读历史（#22 对账）——fixture 提供同一真相
    events: [
      { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
      { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
      { type: 'user/message', data: { content: '讲个故事' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
      { type: 'text/delta', data: { delta: '从前' }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
      { type: 'text/delta', data: { delta: '有座山' }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
      { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: RUN, time: T },
    ],
    // 重连：延迟 > 800ms 断线条显示阈值；重放 (after_seq, cursor] 零重叠 + 新帧
    onStreamGet: async (route) => {
      streamUrls.push(route.request().url());
      await new Promise((r) => setTimeout(r, 1500));
      await fulfillSse(route, [
        { type: 'text/delta', data: { delta: '有座山' }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
        { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: RUN, time: T },
      ]);
    },
  });

  await page.goto('/');
  await submitTask(page, '讲个故事');

  // 断线条出现（800ms 延迟阈值后）
  await expect(page.locator('.reconnect-banner')).toBeVisible({ timeout: 5_000 });
  // 续传后终态：条消失，文本完整且 '从前' 只出现一次（重放无重复块）
  await expect(page.locator('.reconnect-banner')).toBeHidden({ timeout: 10_000 });
  const text = await page.locator('.model-output').last().innerText();
  expect(text).toContain('从前');
  expect(text).toContain('有座山');
  expect(text.match(/从前/g)).toHaveLength(1);
  // 重连契约：after_seq = 本地已应用最大 seq（4）——重放自 5 起，零重叠
  expect(streamUrls).toHaveLength(1);
  expect(new URL(streamUrls[0]).searchParams.get('after_seq')).toBe('4');
});
