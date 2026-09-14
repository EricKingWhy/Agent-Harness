/** #186：artifact 内容可见 + 就地展开。
 *
 *  票面 AC6 明说"e2e 对 artifact/diff 目前零覆盖，至少新增一条'外置 diff → 就地展开
 *  → 可见'"。这里给四条：
 *  - **清单 → 打开内容**（AC1 的正路，走 #185 的真实端点形状）；
 *  - **归档 diff → 就地展开 → 可见**（AC2 的正路，且与清单**同一渲染器**）；
 *  - **503 与 404 两种拿不到**（AC1 的三态：失败原因必须分开说，detail 照显原文）。
 *
 *  为什么必须走真网络（route 拦截）而不是断言组件内部状态：取数那一层在 SSR 测试里
 *  不会 resolve（本仓无 jsdom），所以"端点真的被调了、参数对不对、失败怎么显示"
 *  只有在这里能证明。
 */

import { expect, test } from '@playwright/test';
import { SID, T, capabilityFixture, fulfillSse, routeApi, submitTask, type FrameSpec } from './fixtures';

const AID = '0123456789abcdef';

/** 会话外壳 + 一次 write 的工具对 + 外置事件（形状照后端 `tooling/overflow.py`）。 */
function framesWithArtifact(over: { marker?: string } = {}): FrameSpec[] {
  const marker = over.marker ?? `use read_artifact(${AID}) to view]`;
  return [
    { type: 'session/started', seq: 1, session_id: SID, run_id: 'run-186', time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: 'run-186', time: T },
    { type: 'user/message', data: { content: '写一个大文件' }, seq: 3, session_id: SID, run_id: 'run-186', step_id: 1, time: T },
    {
      type: 'tool/call',
      data: { tool_call_id: 'tc-1', tool_name: 'write', args: { path: 'big.txt' } },
      seq: 4, session_id: SID, run_id: 'run-186', step_id: 1, time: T,
    },
    {
      type: 'tool/result',
      data: {
        tool_call_id: 'tc-1',
        content: JSON.stringify({
          ok: true,
          message: 'ok',
          artifact_ref: AID,
          /* before/after 被换成"摘要 + marker"（>2000 字符的实际形态）——保留一行真内容
             好让归档占位之外的东西也能被认出来。 */
          data: {
            path: 'big.txt',
            before: '',
            after: `... [truncated, 5000 lines total, ${marker}`,
            truncated: true,
          },
        }),
      },
      seq: 5, session_id: SID, run_id: 'run-186', step_id: 1, time: T,
    },
    {
      type: 'artifact/externalized',
      data: {
        artifact_id: AID, session_id: SID, source_tool: 'write',
        tool_call_id: 'tc-1', size: 4096, mime_type: 'text/plain',
      },
      seq: 6, session_id: SID, run_id: 'run-186', step_id: 1, time: T,
    },
    { type: 'run/completed', data: {}, seq: 7, session_id: SID, run_id: 'run-186', time: T },
  ];
}

const SLICE = {
  artifact_id: AID,
  lines: [
    { line_number: 1, text: 'CONTENT_LINE_ONE' },
    { line_number: 2, text: 'CONTENT_LINE_TWO' },
  ],
  total_lines: 2,
  returned_lines: 2,
  truncated: false,
};

async function openSession(page: import('@playwright/test').Page, frames: FrameSpec[], extra = {}) {
  routeApi(page, {
    capabilities: [capabilityFixture({ chat: true, timeline: true, changes: true, artifacts: true })],
    sessions: [{
      session_id: SID, event_count: frames.length, first_event_time: T, last_event_time: T,
      first_user_message: '写一个大文件', trace_id: null, trace_url: null,
    }],
    events: frames,
    onSessionPost: (route) => fulfillSse(route, frames),
    ...extra,
  });
  await page.goto('/');
  await submitTask(page, '写一个大文件');
}

/** 把中心列的工具卡展开到 L2（`DiffBlock` 只在 L2 渲染——L1 是折叠行，
 *  `tool-card-body` 不存在）。行本身是 L0→L1→L2 的循环按钮，所以点到 `aria-level=2`
 *  为止（不写死点击次数：默认档位不同会差一次）。
 *
 *  `tool-card-body` 是 `.act-node-wrap` 的**兄弟**（工具卡返回的是 fragment，没有共同
 *  父元素），所以不要把它挂在 wrap 下面找——那条选择器永远匹配不到。本 spec 的 fixture
 *  只有一个工具，直接用页面级选择器，读起来也更直白。 */
async function expandToolToL2(page: import('@playwright/test').Page) {
  const row = page.locator('.act-node').first();
  for (let i = 0; i < 3; i++) {
    if ((await row.getAttribute('aria-level')) === '2') break;
    await row.click();
  }
  await expect(row).toHaveAttribute('aria-level', '2');
  await expect(page.locator('.tool-card-body')).toBeVisible();
}

/** 打开 Inspector 的 Artifacts 面。 */
async function openArtifactsTab(page: import('@playwright/test').Page) {
  const aside = page.locator('.step-detail');
  await aside.getByRole('tab', { name: /Artifacts/ }).click();
}

test('AC1：Artifacts 清单 → 点"查看内容" → 内容真的可见（走 #185 端点）', async ({ page }) => {
  const frames = framesWithArtifact();
  await openSession(page, frames, { artifactContent: SLICE });
  await openArtifactsTab(page);

  // 清单本身在（票面要求"保留并可读"，不是被内容面板取代）
  await expect(page.locator('.step-detail')).toContainText(AID.slice(0, 16));
  await expect(page.locator('.step-detail')).toContainText('text/plain');

  // 内容**未**展开时不请求（组件只在展开后取数）
  await expect(page.locator('.artifact-content')).toHaveCount(0);

  await page.getByRole('button', { name: '查看内容' }).click();

  const content = page.locator('.artifact-content');
  await expect(content).toBeVisible();
  await expect(content).toContainText('CONTENT_LINE_ONE');
  await expect(content).toContainText('CONTENT_LINE_TWO');
  await expect(content).toContainText('共 2 行');
  // 行号在场（左列）
  await expect(page.locator('.artifact-line-no').first()).toHaveText('1');
});

test('AC2/AC6：外置 diff → 就地展开 → 可见（与清单同一渲染器）', async ({ page }) => {
  const frames = framesWithArtifact();
  await openSession(page, frames, { artifactContent: SLICE });

  // 中心列里那张工具卡：diff 已归档 → 占位 + 展开入口
  await expandToolToL2(page);
  /* 中心列与 Inspector 各有一份 `.diff-archived`（同一份 diff 的两个视图，共用
     `DiffBlock`——这正是 #183 AC9 要的"同一渲染器"）。断言落在中心列这一份上。 */
  const center = page.locator('.conversation-scroll');
  await expect(center.locator('.diff-archived')).toBeVisible();
  await center.getByRole('button', { name: '查看完整内容' }).click();

  const content = center.locator('.artifact-content');
  await expect(content).toBeVisible();
  await expect(content).toContainText('CONTENT_LINE_ONE');

  // 就地展开：没有新开浮层/新页面（票面 AC2 的"不新开导航面"）
  await expect(page.locator('.palette-overlay')).toHaveCount(0);
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('AC4：read_artifact marker（默认部署）也被认出来，且工具名原样回显', async ({ page }) => {
  const frames = framesWithArtifact({ marker: `use read_artifact(${AID}) to view]` });
  await openSession(page, frames, { artifactContent: SLICE });

  await expandToolToL2(page);
  const center = page.locator('.conversation-scroll');
  await expect(center.locator('.diff-archived')).toBeVisible();
  // 工具名照 marker 显示——默认部署配的是 read_artifact，写死 inspect_artifact 会让
  // 用户照着复制一句调不通的提示
  await expect(center.locator('.diff-archived-hint')).toContainText('read_artifact');
  await expect(center.locator('.diff-archived-hint')).not.toContainText('inspect_artifact');
});

test('AC2：命令输出被外置时，工具卡也给同一个就地展开（判据是投影的 artifact）', async ({ page }) => {
  const AID2 = 'fedcba9876543210';
  const frames: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: 'run-186b', time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: 'run-186b', time: T },
    { type: 'user/message', data: { content: '看看大日志' }, seq: 3, session_id: SID, run_id: 'run-186b', step_id: 1, time: T },
    {
      type: 'tool/call',
      data: { tool_call_id: 'tc-b', tool_name: 'bash', args: { command: 'cat big.log' } },
      seq: 4, session_id: SID, run_id: 'run-186b', step_id: 1, time: T,
    },
    {
      type: 'tool/result',
      data: {
        tool_call_id: 'tc-b',
        content: JSON.stringify({
          ok: true,
          message: 'ok',
          artifact_ref: AID2,
          data: {
            exit_code: 0,
            stdout: `head of log
... [truncated, 9000 lines total, use read_artifact(${AID2}) to view]
tail of log`,
          },
        }),
      },
      seq: 5, session_id: SID, run_id: 'run-186b', step_id: 1, time: T,
    },
    {
      type: 'artifact/externalized',
      data: {
        artifact_id: AID2, session_id: SID, source_tool: 'bash',
        tool_call_id: 'tc-b', size: 90000, mime_type: 'text/plain',
      },
      seq: 6, session_id: SID, run_id: 'run-186b', step_id: 1, time: T,
    },
    { type: 'run/completed', data: {}, seq: 7, session_id: SID, run_id: 'run-186b', time: T },
  ];
  await openSession(page, frames, {
    artifactContent: {
      artifact_id: AID2,
      lines: [{ line_number: 1, text: 'FULL_LOG_LINE' }],
      total_lines: 1,
      returned_lines: 1,
      truncated: false,
    },
  });
  await expandToolToL2(page);

  const center = page.locator('.conversation-scroll');
  // 命令输出这一条路径不是 diff——判据必须是投影挂上的 artifact，不是 marker 文本
  await expect(center.locator('.bash-output')).toContainText('head of log');
  await center.getByRole('button', { name: '查看完整内容' }).click();
  await expect(center.locator('.artifact-content')).toContainText('FULL_LOG_LINE');
});

test('AC1：拿不到时分因说明——503"部署没配存储"与 404"不在本会话"不是同一句话', async ({ page }) => {
  const frames = framesWithArtifact();
  // 503：本部署没有可读存储
  await openSession(page, frames, {
    artifactContentError: { status: 503, detail: '本部署没有可读取的 artifact 存储：artifact_dir 为空' },
  });
  await openArtifactsTab(page);
  await page.getByRole('button', { name: '查看内容' }).click();
  const err = page.locator('.artifact-content-error');
  await expect(err).toBeVisible();
  await expect(err).toContainText('本部署没有可读取的 artifact 存储');
  // 后端 detail 原文照显
  await expect(page.locator('.artifact-content-detail')).toContainText('artifact_dir 为空');
  // 不是"不存在"——这两件事对用户不同
  await expect(err).not.toContainText('不在本会话里');
  // 可重试（503 是配置/瞬时问题）
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible();

  // 404：不在本会话
  await page.unroute('**/api/**');
  await openSession(page, frames, {
    artifactContentError: { status: 404, detail: `artifact '${AID}' 不在会话 's1' 的命名空间里` },
  });
  await openArtifactsTab(page);
  await page.getByRole('button', { name: '查看内容' }).click();
  const gone = page.locator('.artifact-content-error');
  await expect(gone).toContainText('不在本会话里');
  await expect(gone).not.toContainText('本部署没有可读取的 artifact 存储');
});
