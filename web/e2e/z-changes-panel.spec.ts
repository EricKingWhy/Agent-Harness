/** 场景 #189：中心列「文件/改动」面（本会话改动文件 + 逐文件 diff）。
 *
 *  锁三件事（AC8 逐条）：
 *  - **两次改动同一文件 → 只有一行**，统计是"相对首次改动前的原文"的净变化；
 *  - **点文件名 → 右侧 diff 可见**（并在同一文件改多次时按时间序全列出）；
 *  - **无改动 → 空态文案逐字**（不是空列表、不是"加载中"）。
 *
 *  另外锁两条本票的诚实纪律：内容归档（>2000 字符转 artifact）时**不给假统计**，
 *  以及面内没有任何编辑入口（AC4）。
 */

import { expect, test } from '@playwright/test';
import { SID, T, fulfillSse, routeApi, submitTask, type FrameSpec } from './fixtures';

/** 一次 write/edit 的 tool/call + tool/result 对（data 形状同后端 `_diff_data`）。 */
function writePair(
  seq: number,
  callId: string,
  name: string,
  path: string,
  before: string,
  after: string,
  over: Record<string, unknown> = {},
): FrameSpec[] {
  return [
    {
      type: 'tool/call',
      /* 字段名照后端真形状：`data.tool_name`（不是 `name`）。投影层读的是
         `event.data.tool_name`——写错名字会静默变成工具名 'unknown'，于是写工具的
         白名单不命中、清单恒空（这条 e2e 第一版就踩了，正是它该抓的类）。 */
      data: { tool_call_id: callId, tool_name: name, args: { path } },
      seq, session_id: SID, run_id: 'run-189', step_id: 1, time: T,
    },
    {
      type: 'tool/result',
      data: {
        tool_call_id: callId,
        content: JSON.stringify({
          ok: true, message: 'ok',
          data: { path, before, after, truncated: false, ...over },
        }),
      },
      seq: seq + 1, session_id: SID, run_id: 'run-189', step_id: 1, time: T,
    },
  ];
}

const HEAD: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, run_id: 'run-189', time: T },
  { type: 'run/started', seq: 2, session_id: SID, run_id: 'run-189', time: T },
  { type: 'user/message', data: { content: '改两个文件' }, seq: 3, session_id: SID, run_id: 'run-189', step_id: 1, time: T },
];

/** 打开「文件/改动」面。
 *
 *  **不注入能力声明**：用 `routeApi` 的缺省载荷（`[CORE_CAPABILITY]`——逐值镜像
 *  `capability/manifest.py`，即后端 `CAPABILITIES=""` 时恒发的 core 条目）。#193 起 core
 *  就声明了 `changes`，所以"面出现"由真实载荷驱动，不再靠用例自己造声明。
 *  镜像不等于同源：后端改值这里不会自动跟（后端侧由
 *  `tests/web/test_web_phase2_endpoints.py::TestCapabilities` 锁）。 */
async function openChanges(page: import('@playwright/test').Page, frames: FrameSpec[]) {
  routeApi(page, {
    sessions: [{
      session_id: SID, event_count: frames.length, first_event_time: T, last_event_time: T,
      first_user_message: '改两个文件', trace_id: null, trace_url: null,
    }],
    events: frames,
    onSessionPost: (route) => fulfillSse(route, frames),
  });
  await page.goto('/');
  await submitTask(page, '改两个文件');
  await page.getByRole('tablist', { name: '工作区面' }).getByRole('tab', { name: '文件/改动' }).click();
  await expect(page.locator('.changes-panel')).toBeVisible();
}

test('AC1/AC2/AC8：两次改动同一文件只有一行；点文件名 → diff 可见且按时间序列出各次改动', async ({
  page,
}) => {
  // a.ts 两次（净 '' → 'l1\nl2\nl3\nl4\n' = +4）、b.ts 一次（替换一行：+1 −1）
  const frames: FrameSpec[] = [
    ...HEAD,
    ...writePair(4, 'tc-a1', 'write', 'src/a.ts', '', 'l1\nl2\n'),
    ...writePair(6, 'tc-b1', 'edit', 'src/b.ts', 'old\n', 'new\n'),
    ...writePair(8, 'tc-a2', 'edit', 'src/a.ts', 'l1\nl2\n', 'l1\nl2\nl3\nl4\n'),
    { type: 'run/completed', data: {}, seq: 10, session_id: SID, run_id: 'run-189', time: T },
  ];
  await openChanges(page, frames);

  const rows = page.locator('.changes-file-row');
  await expect(rows).toHaveCount(2);
  // 一个文件一行：a.ts 出现**恰好一次**
  await expect(page.locator('.changes-file-row', { hasText: 'src/a.ts' })).toHaveCount(1);
  await expect(page.locator('.changes-file-row', { hasText: 'src/b.ts' })).toHaveCount(1);

  // 统计是净变化：a.ts 空 → 4 行 = +4（不是 +2 +4 = +6）；b.ts = +1 −1
  const aRow = page.locator('.changes-file-row', { hasText: 'src/a.ts' });
  await expect(aRow.locator('.changes-added')).toHaveText('+4');
  await expect(aRow.locator('.changes-file-count')).toHaveText('2 次');
  const bRow = page.locator('.changes-file-row', { hasText: 'src/b.ts' });
  await expect(bRow.locator('.changes-added')).toHaveText('+1');
  await expect(bRow.locator('.changes-removed')).toHaveText('-1');

  // 默认选中第一个文件 → 右栏是它的 diff；同一文件两次改动都按时间序列出
  await expect(page.locator('.changes-detail-path')).toHaveText('src/a.ts');
  await expect(page.locator('.changes-edit')).toHaveCount(2);
  await expect(page.locator('.changes-edit-head').first()).toContainText('第 1 次改动');

  // 点 b.ts → 右侧换成 b.ts 的 diff（可见 + 内容对得上）
  await bRow.click();
  await expect(page.locator('.changes-detail-path')).toHaveText('src/b.ts');
  await expect(page.locator('.changes-detail')).toContainText('new');
  await expect(page.locator('.changes-edit')).toHaveCount(1);
  // 选中态如实（aria-current，不是只靠颜色）
  await expect(bRow).toHaveAttribute('aria-current', 'true');
  await expect(aRow).not.toHaveAttribute('aria-current', 'true');

  // 只读（AC4）：面内没有输入类元素，也没有编辑/撤销类按钮
  await expect(page.locator('.changes-panel input, .changes-panel textarea')).toHaveCount(0);
  await expect(
    page.locator('.changes-panel').getByRole('button', { name: /保存|应用|撤销|编辑/ }),
  ).toHaveCount(0);
});

test('AC5：内容归档（>2000 字符转 artifact）→ 统计说"不可得"，不给假数字', async ({ page }) => {
  const marker = 'use inspect_artifact(0123456789abcdef)';
  const frames: FrameSpec[] = [
    ...HEAD,
    ...writePair(4, 'tc-a1', 'write', 'big.ts', marker, marker),
    { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: 'run-189', time: T },
  ];
  await openChanges(page, frames);

  const row = page.locator('.changes-file-row', { hasText: 'big.ts' });
  await expect(row).toHaveCount(1);
  // 文件确实被改过（在清单里），但统计如实不可得
  await expect(row.locator('.changes-stat')).toHaveText('—');
  await expect(row.locator('.changes-stat')).toHaveAttribute('title', /归档/);
  // 归档占位由 DiffBlock 承担（同一渲染器；可点的"查看完整内容"入口属 #186）
  await expect(page.locator('.diff-archived')).toBeVisible();
});

test('AC6/AC8：无改动 → 空态文案逐字', async ({ page }) => {
  const frames: FrameSpec[] = [
    ...HEAD,
    {
      type: 'tool/call',
      data: { tool_call_id: 'tc-sh', tool_name: 'bash', args: { command: 'echo hi' } },
      seq: 4, session_id: SID, run_id: 'run-189', step_id: 1, time: T,
    },
    {
      type: 'tool/result',
      data: {
        tool_call_id: 'tc-sh',
        content: JSON.stringify({ ok: true, message: 'ok', data: { exit_code: 0, stdout: 'hi\n' } }),
      },
      seq: 5, session_id: SID, run_id: 'run-189', step_id: 1, time: T,
    },
    { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: 'run-189', time: T },
  ];
  await openChanges(page, frames);

  // 跑过命令但没改文件 ≠ 有改动：空态文案逐字（AC6）
  await expect(page.locator('.changes-files')).toHaveCount(0);
  await expect(page.locator('.changes-panel')).toContainText('本次会话未改动任何文件。');
});
