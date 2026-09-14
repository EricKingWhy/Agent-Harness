/** 场景 A（spec 01 §22）：reasoning 流——思考块聚合 + 完成态 + 最终文本。
 *  零伪造边界：fixture 有思考才有块（envelope block_id 聚合，契约 §2）。 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, fulfillSse, submitTask, type FrameSpec } from './fixtures';

test('reasoning 流：思考块聚合、完成后展开可见、最终文本呈现', async ({ page }) => {
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '思考一下 1+1' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'reasoning/started', data: { source: 'model' }, block_id: 'rsn-1-1', seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'reasoning/delta', data: { delta: '用户问 1+1，答案是 2。', source: 'model' }, block_id: 'rsn-1-1', seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'reasoning/completed', data: {}, block_id: 'rsn-1-1', seq: 6, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'text/delta', data: { delta: '1+1 = 2。' }, seq: 7, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'model/completed', data: { content: '1+1 = 2。' }, seq: 8, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'run/completed', data: {}, seq: 9, session_id: SID, run_id: RUN, time: T },
  ];
  // events fixture：终态后 viewing 迁移重读历史（#22 对账），fixture 提供同一真相
  routeApi(page, { onSessionPost: (route) => fulfillSse(route, frames), events: frames });

  await page.goto('/');
  await submitTask(page, '思考一下 1+1');

  // 思考块在场且终态（streaming → completed）
  const block = page.locator('.reasoning-block');
  await expect(block).toBeVisible();
  await expect(block).toHaveClass(/reasoning-completed/);
  // 完成态默认折叠 → 展开后思考文本可见（envelope block_id 聚合单块）
  await block.locator('.reasoning-header').click();
  await expect(page.getByText('用户问 1+1，答案是 2。')).toBeVisible();
  // 最终文本（text/delta + model/completed 校准）呈现一次
  await expect(page.locator('.model-output').last()).toContainText('1+1 = 2。');
  const text = await page.locator('.model-output').last().innerText();
  expect(text.match(/1\+1 = 2。/g)).toHaveLength(1); // 重放/合帧不得产生重复块
});
