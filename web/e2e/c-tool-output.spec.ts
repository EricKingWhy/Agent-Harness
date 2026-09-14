/** 场景 C（spec 01 §22）：工具输出跟随——tool/call 先于执行（running 态）、
 *  tool/output_delta 按 channel 保真、tool/result 终态校准（契约 §2/§4）。 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, fulfillSse, submitTask, type FrameSpec } from './fixtures';

test('工具输出流：running 行 → stdout/stderr 分块 → result 终态', async ({ page }) => {
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '跑个命令' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/call', data: { tool_call_id: 'tc-1', tool_name: 'bash', args: { command: 'echo hello' } }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/output_delta', data: { tool_call_id: 'tc-1', channel: 'stdout', delta: 'hello\n' }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/output_delta', data: { tool_call_id: 'tc-1', channel: 'stderr', delta: 'warn: deprecated\n' }, seq: 6, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/output_delta', data: { tool_call_id: 'tc-1', channel: 'stdout', delta: 'done\n' }, seq: 7, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/result', data: { tool_call_id: 'tc-1', content: JSON.stringify({ ok: true, message: 'hello done', data: { exit_code: 0 } }) }, seq: 8, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'run/completed', data: {}, seq: 9, session_id: SID, run_id: RUN, time: T },
  ];
  routeApi(page, { onSessionPost: (route) => fulfillSse(route, frames), events: frames });

  await page.goto('/');
  await submitTask(page, '跑个命令');

  // 骨架车道帧一次性到达（终态即现）：tool/call 先于执行落盘（running 行存在
  // 过），终态由 tool/result 校准——chunks 视图被 result 真相替换（T3 设计）。
  // 分色块/跟随浮标等流式中间态断言属联调车道（map 文档）。
  // Balanced 档工具卡是折叠行（name + args 摘要 + 状态 chip；.tool-card-body
  // 只在展开/detailed 档存在）。断言折叠行 + 状态离开 running。
  const card = page.locator('.act-node').first();
  await expect(card).toBeVisible();
  await expect(card).toContainText('bash');
  await expect(card).toContainText('echo hello');
  await expect(page.locator('.act-status').first()).not.toHaveClass(/-running/);
});
