/** 场景：#190 —— 中心列「输出」面（只读如实）。
 *
 *  锁三件事：
 *  - **只读边界**（AC1/AC5）：面内明示"无交互终端"，且**不存在任何暗示可输入的元素**
 *    （输入框 / `contenteditable` / "运行"按钮 / 流式光标）——一个看起来能敲命令的面板
 *    就是在骗人，本项目没有 PTY；
 *  - **聚合如实**（AC2）：按工具调用分组，命令原文、exit code、stdout 与 stderr 都在；
 *  - **能力显隐**（AC4）：声明为假时整面不渲染（Agent 能力为假的会话不该看到它）。
 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, capabilityFixture, fulfillSse, routeApi, submitTask, type FrameSpec } from './fixtures';

/** 换行符改用 `String.fromCharCode`：转义序列要经过 shell → 生成脚本 → TS 三道转义，
 *  写坏一次就得到一个跨行的非法字面量；显式构造只有一种解释。 */
const NL = String.fromCharCode(10);

/** 两条命令：一条成功（stdout）、一条失败（有 stderr）——`tool/result.content` 是后端
 *  `ToolResult.model_dump_json()` 的字符串（契约：结构化字段在 `.data` 里）。 */
const FRAMES: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
  { type: 'user/message', data: { content: '跑两条命令' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'tool/call', data: { tool_call_id: 'tc-1', tool_name: 'bash', args: { command: 'echo hello' } }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'tool/output_delta', data: { tool_call_id: 'tc-1', channel: 'stdout', delta: 'hello\n' }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'tool/result', data: { tool_call_id: 'tc-1', content: JSON.stringify({ ok: true, message: 'ok', data: { exit_code: 0, stdout: 'hello\n', stderr: '' } }) }, seq: 6, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'tool/call', data: { tool_call_id: 'tc-2', tool_name: 'bash', args: { command: 'pytest -q' } }, seq: 7, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'tool/result', data: { tool_call_id: 'tc-2', content: JSON.stringify({ ok: true, message: 'exit 1', data: { exit_code: 1, stdout: 'collected 3 items\n', stderr: 'E 一个断言失败\n' } }) }, seq: 8, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'run/completed', data: {}, seq: 9, session_id: SID, run_id: RUN, time: T },
];

/** 声明为假 → 整面不渲染（AC4）：显式换掉缺省载荷（**故意不含 core**）。
 *  若只把插件的 `terminal` 写成 false、又挂着 core，面照样会出现——那是"取并集"语义
 *  （见 `workspace-modes.spec.ts` 的同名用例）。
 *  其余用例**不注入声明**：`routeApi` 的缺省载荷就是真实后端那份（`[CORE_CAPABILITY]`）。 */
const DISABLED = [capabilityFixture({ chat: true, timeline: true, terminal: false })];

const outputTab = (page: import('@playwright/test').Page) =>
  page.getByRole('tablist', { name: '工作区面' }).getByRole('tab', { name: '输出' });

test('AC1/AC2：面内明示只读；命令按工具调用分组，stdout/stderr 与 exit code 都在', async ({
  page,
}) => {
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, FRAMES),
    events: FRAMES,
  });
  await page.goto('/');
  await submitTask(page, '跑两条命令');

  await outputTab(page).click();
  const panel = page.locator('.output-panel');
  await expect(panel).toBeVisible();

  // AC1：只读说明**逐字**在场（不是靠 title，读屏与键盘用户都要看得到）。
  await expect(panel.getByRole('note')).toHaveText(
    '只读：本项目命令为一次性执行，无交互终端（不能在此输入或重跑）。',
  );

  // AC2：两条命令各成一组，顺序 = 调用顺序。
  await expect(panel.locator('.output-item')).toHaveCount(2);
  await expect(panel.locator('.output-item').nth(0)).toContainText('echo hello');
  await expect(panel.locator('.output-item').nth(1)).toContainText('pytest -q');

  // 输出内容（终态以 result 为准）：成功那条 stdout 在，失败那条 stdout + stderr 都在。
  await expect(panel.locator('.output-item').nth(0)).toContainText('hello');
  await expect(panel.locator('.output-item').nth(1)).toContainText('collected 3 items');
  await expect(panel.locator('.output-item').nth(1)).toContainText('一个断言失败');
  await expect(panel.locator('.output-item').nth(1).locator('.tool-out-stderr')).toHaveCount(1);

  // exit code 如实（0 与 1 分色）。
  await expect(panel.locator('.exit-badge').nth(0)).toHaveText('exit 0');
  await expect(panel.locator('.exit-badge').nth(1)).toHaveText('exit 1');

  // 复制是**按工具调用**给的（AC2 的"分组 + 复制"）——每个输出块自己的工具条上，
  // 头部不再重复放一个（同一段文本两个复制按钮只会让人犹豫点哪个）。
  await expect(panel.getByRole('button', { name: '复制全部输出' })).toHaveCount(2);
});

test('AC5：面内不存在任何暗示可输入的元素（无输入框 / 无"运行"按钮 / 无光标）', async ({
  page,
}) => {
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, FRAMES),
    events: FRAMES,
  });
  await page.goto('/');
  await submitTask(page, '跑两条命令');
  await outputTab(page).click();

  const panel = page.locator('.output-panel');
  await expect(panel).toBeVisible();

  // 输入类元素一个都不许有——这是本面的核心约束（本项目没有 PTY）。
  await expect(panel.locator('input, textarea, [contenteditable="true"], [role="textbox"]')).toHaveCount(0);
  // 也不许有"点了会执行什么"的按钮（复制/换行/回到底部是视图动作，不算）。
  await expect(
    panel.getByRole('button', { name: /运行|执行|重跑|输入|发送/ }),
  ).toHaveCount(0);
  // 流式光标只在真流式时出现；这里的命令都已终态。
  await expect(panel.locator('.stream-caret')).toHaveCount(0);
});

test('AC4：能力声明为假 → 整面不渲染（连 tab 都不出现）', async ({ page }) => {
  routeApi(page, {
    capabilities: DISABLED,
    onSessionPost: (route) => fulfillSse(route, FRAMES),
    events: FRAMES,
  });
  await page.goto('/');
  await submitTask(page, '跑两条命令');

  await expect(outputTab(page)).toHaveCount(0);
  await expect(page.locator('.output-panel')).toHaveCount(0);
  // 主阅读面不受影响（Chat 恒存在）。
  await expect(
    page.getByRole('tablist', { name: '工作区面' }).getByRole('tab', { name: 'Chat' }),
  ).toHaveAttribute('aria-selected', 'true');
});

test('空态如实：能力为真但本会话没跑过命令 → 说明原因，不留空白', async ({ page }) => {
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '只聊两句' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'run/completed', data: {}, seq: 4, session_id: SID, run_id: RUN, time: T },
  ];
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, frames),
    events: frames,
  });
  await page.goto('/');
  await submitTask(page, '只聊两句');

  await outputTab(page).click();
  await expect(page.locator('.output-panel')).toContainText(
    '本次会话未执行命令——没有输出可显示。',
  );
});

test('AC3：长输出就地折叠，点开即得全文（不新开导航面）', async ({ page }) => {
  // 尾窗预算是 8000 字符：把标记放在头尾，就能证明"展开前头部没渲染、展开后渲染了"。
  const stdout = 'HEAD_MARKER' + NL + 'x'.repeat(9000) + NL + 'TAIL_MARKER' + NL;
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '输出很长' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/call', data: { tool_call_id: 'tc-1', tool_name: 'bash', args: { command: 'cat big.log' } }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/result', data: { tool_call_id: 'tc-1', content: JSON.stringify({ ok: true, message: 'ok', data: { exit_code: 0, stdout, stderr: '' } }) }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: RUN, time: T },
  ];
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, frames),
    events: frames,
  });
  await page.goto('/');
  await submitTask(page, '输出很长');
  await outputTab(page).click();

  const panel = page.locator('.output-panel');
  // 折叠态：只渲染尾窗，头部标记不在 DOM 里（就地截断，不新开面）。
  await expect(panel).toContainText('TAIL_MARKER');
  await expect(panel).not.toContainText('HEAD_MARKER');

  await panel.getByRole('button', { name: /展开全部/ }).click();
  await expect(panel).toContainText('HEAD_MARKER');
  await expect(panel.getByRole('button', { name: '收起' })).toBeVisible();
});

test('AC5：运行中的命令也不画光标——"还在跑"用文字说，不用终端提示符的样子说', async ({
  page,
}) => {
  // 只有 tool/call 与流式输出、**没有** tool/result → status 停在 running。
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '跑个长命令' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/call', data: { tool_call_id: 'tc-1', tool_name: 'bash', args: { command: 'pytest -q' } }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/output_delta', data: { tool_call_id: 'tc-1', channel: 'stdout', delta: 'collected 3 items' + NL }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
  ];
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, frames),
    events: frames,
  });
  await page.goto('/');
  await submitTask(page, '跑个长命令');
  await outputTab(page).click();

  const panel = page.locator('.output-panel');
  // 流式内容照常显示 + 状态如实，但**没有**光标（那是终端提示符的样子）。
  await expect(panel).toContainText('collected 3 items');
  await expect(panel).toContainText('运行中…');
  await expect(panel.locator('.stream-caret')).toHaveCount(0);
});

test('运行中但还没有输出 → 说"等待输出…"，不说"没有输出"', async ({ page }) => {
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '跑个慢命令' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'tool/call', data: { tool_call_id: 'tc-1', tool_name: 'bash', args: { command: 'sleep 30' } }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
  ];
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, frames),
    events: frames,
  });
  await page.goto('/');
  await submitTask(page, '跑个慢命令');
  await outputTab(page).click();

  const panel = page.locator('.output-panel');
  await expect(panel).toContainText('等待输出…');
  await expect(panel).not.toContainText('这次命令没有输出');
});
