/** 场景 M：流式容器里的三个「跟随/换行」按钮——此前**唯一没能真机点过**的三个控件。
 *
 * 三个控件的挂载条件并不相同，别混为一谈：
 * - `tool-out-wrap-btn`：只要输出尾窗存在就在（`ToolOutputStream.tsx` 的 `.tool-out-bar`，
 *   自身无 streaming 条件），而尾窗的挂载条件是 `tool.output.length > 0 &&
 *   (status === 'running' || !tool.result)`（`ToolCard.tsx` 里的 `ToolOutputStream` 调用点）；
 * - `tool-out-jump` / `reasoning-jump`：在上一行基础上**再**要求 `suspended`，即
 *   「流式中 + 容器被上滚离开底部」（`lib/followLatest.ts:33-38`，渲染于
 *   `ToolCard.tsx:322` / `ReasoningBlock.tsx:255`）。
 *
 * 真实后端里这个窗口只有毫秒级——cmd.exe 缓冲输出，整段输出以**单个终态 delta** 到达、
 * `tool/result` 紧随其后；叠加 bash 工具 10s 硬超时，六次真机尝试都只能看到窗口、点不进去
 * （见登记簿第三轮「缺口 2」；**该「不可达」结论已在第四轮作废并补齐**）。
 *
 * 这里用**可控 mock 流**把窗口钉住：**不发 `tool/result` / `reasoning/completed`**，
 * 于是 `tool.status === 'running'`、`block.status === 'streaming'` 恒成立，窗口常驻。
 * 点击仍是**真实浏览器里的真实点击**（Playwright 真鼠标事件），只是网络被替换成 fixture
 * ——这是「可复现」与「真机」的折中，覆盖账目按此口径单独记。
 *
 * 没锁什么（如实划界）：上滚由 `scrollTop = 0` + 合成 `scroll` 事件诱发，不是真实滚轮；
 * 且 fixture 一次性铺完，**没有**「suspended 期间文本仍在持续增量」这一更难的时序场景。 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, fulfillSse, submitTask, type FrameSpec } from './fixtures';

/** 造一段足够长的文本，保证容器可滚动（否则 suspended 永远不会触发）。 */
function longText(lines: number, prefix: string): string {
  return Array.from({ length: lines }, (_, i) => `${prefix}-${String(i + 1).padStart(3, '0')} ${'x'.repeat(40)}`).join('\n');
}

test('工具输出尾窗：自动换行可切换；上滚出「↓ 最新」，点击回底并消失', async ({ page }) => {
  const out = longText(120, 'LINE');
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '跑个长命令' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/call', data: { tool_call_id: 'tc-1', tool_name: 'bash', args: { command: 'seq 1 120' } }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    // 只给输出、**不给 tool/result** → 工具恒为 running → 尾窗常驻
    { type: 'tool/output_delta', data: { tool_call_id: 'tc-1', channel: 'stdout', delta: out.slice(0, 2000) }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/output_delta', data: { tool_call_id: 'tc-1', channel: 'stdout', delta: out.slice(2000) }, seq: 6, session_id: SID, run_id: RUN, step_id: 1, time: T },
  ];
  routeApi(page, { onSessionPost: (route) => fulfillSse(route, frames), events: frames });

  await page.goto('/');
  await submitTask(page, '跑个长命令');

  /* 三条 locator 都必须**限定在对话面里**（#193）：`ToolOutputStream` 是对话卡与中心列
     「输出」面共用的那一个渲染器（#190 AC9），而 `#193` 让「输出」面在真实默认载荷下
     真的存在了——它还带着同一个工具的一份输出（`hidden` 面板，不卸载，见 `App.tsx:889`）。
     于是裸类名 `.tool-out-body` / `.tool-out-wrap-btn` 会同时命中两处（strict mode 直接报
     两个元素），而且**藏起来那份**参与不了滚动（`scrollHeight === 0`），下面的可滚动前置
     断言会假失败。本用例要验的是对话里那张工具卡（`ToolCard` 调用的实例），所以按面板 id
     收窄——这也让"测的是哪一处"从偶然变得确定。 */
  const chat = page.locator('#workspace-panel-chat');
  const body = chat.locator('.tool-out-body');
  await expect(body).toBeVisible();
  // 窗口里确实是 fixture 的增量内容（否则「窗口存在」可能来自别处，断言会变得空洞）
  await expect(body).toContainText('LINE-001');
  await expect(body).toContainText('LINE-120');

  // ── 按钮 1：自动换行 / 不换行（初始 wrap=true → 按钮文案是「不换行」，即「点了就换行」）──
  const wrap = chat.locator('.tool-out-wrap-btn');
  await expect(wrap).toBeVisible();
  await expect(wrap).toHaveText('不换行');
  await expect(body).toHaveCSS('white-space', 'pre-wrap');
  await wrap.click();
  await expect(wrap).toHaveText('自动换行');
  await expect(body).toHaveClass(/tool-out-nowrap/);
  await expect(body).not.toHaveClass(/tool-out-wrap\b/);
  await expect(body).toHaveCSS('white-space', 'pre'); // 断到真实生效的样式，而非仅 class 名
  await wrap.click();
  await expect(wrap).toHaveText('不换行');
  await expect(body).toHaveClass(/tool-out-wrap/);
  await expect(body).toHaveCSS('white-space', 'pre-wrap');

  // ── 按钮 2：↓ 最新（上滚 suspended 才出现）──
  await expect(chat.locator('.tool-out-jump')).toHaveCount(0);
  // 前置条件：容器确实可滚动，否则下面 scrollTop=0 是空操作、jump 断言会**假通过**
  const gaps = await body.evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
  expect(gaps.scroll, '容器必须可滚动（scrollHeight 应显著大于 clientHeight）').toBeGreaterThan(gaps.client + 5);
  await body.evaluate((el) => {
    el.scrollTop = 0;
    el.dispatchEvent(new Event('scroll', { bubbles: true }));
  });
  const jump = chat.locator('.tool-out-jump');
  await expect(jump).toBeVisible();

  await jump.click();
  await expect(jump).toHaveCount(0); // 回底即复位（followOnJump 置回底 + 清 suspended）
  await expect
    .poll(() => body.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight))
    .toBeLessThan(8);
});

test('推理块：上滚出「↓ 最新」，点击回底并消失', async ({ page }) => {
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '想个长问题' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'reasoning/started', data: { source: 'model' }, block_id: 'rsn-1-1', seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    // 只给思考增量、**不给 reasoning/completed** → block 恒为 streaming → 浮标可达
    { type: 'reasoning/delta', data: { delta: longText(80, 'THINK'), source: 'model' }, block_id: 'rsn-1-1', seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
  ];
  routeApi(page, { onSessionPost: (route) => fulfillSse(route, frames), events: frames });

  await page.goto('/');
  await submitTask(page, '想个长问题');

  const block = page.locator('.reasoning-block');
  await expect(block).toBeVisible();
  // 展开态是流式块的自动规则（`disclosure.ts:109`：streaming && density !== 'compact'）——
  // 这是点击 jump 的前置条件，直接锁住；正文只在展开时渲染，所以它同时是断言而非分支
  const header = block.locator('.reasoning-header');
  await expect(header).toHaveAttribute('aria-expanded', 'true');
  const text = block.locator('.reasoning-text');
  await expect(text).toBeVisible();
  await expect(text).toContainText('THINK-080'); // fixture 增量确实进了正文

  await expect(page.locator('.reasoning-jump')).toHaveCount(0);
  const gaps = await text.evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
  expect(gaps.scroll, '思考正文必须可滚动（scrollHeight 应显著大于 clientHeight）').toBeGreaterThan(gaps.client + 5);
  await text.evaluate((el) => {
    el.scrollTop = 0;
    el.dispatchEvent(new Event('scroll', { bubbles: true }));
  });
  const jump = page.locator('.reasoning-jump');
  await expect(jump).toBeVisible();

  await jump.click();
  await expect(jump).toHaveCount(0);
  await expect
    .poll(() => text.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight))
    .toBeLessThan(8);
});
