/** 场景 K：刷新一致性（BUG-005 / BUG-006）。
 *
 * 用户要求：刷新后的会话必须和刷新前一致。拆成两件事验证——
 *  - **BUG-005**：选中的会话要能恢复（localStorage `ahi.selectedSession`），
 *    刷新后零点击就能看到同一个会话与它的全部已落盘内容；
 *  - **BUG-006**：刷新时 run 若仍在服务端跑（ADR-0016 detached-run），要以
 *    `?after_seq=<已加载最大 seq>` 接回实时流——**刷新之后才产生的事件必须继续到达**，
 *    否则用户看到的是一个停在半截、看起来已完成的假快照。
 * 外加两条兜底：零帧空流（run 其实已在刷新窗口内收口）不得弹假重连横幅；
 * 记住的会话已被删（404）要静默回空态并清键。
 *
 * 注：`localStorage` 预置 + 直接进站 === 刷新后的那条代码路径——mode 由
 * `readStoredSessionId()` 惰性初始化，与 F5 完全同形，故无需先"造一段历史"。 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, fulfillSse, routeApi, type FrameSpec } from './fixtures';

const KEY = 'ahi.selectedSession';

/** 会话行 fixture（同一份，避免各用例复制漂移）。 */
const SESSIONS = [
  { session_id: SID, event_count: 4, first_event_time: T, last_event_time: T, first_user_message: '刷新前就发出的任务', trace_id: null, trace_url: null },
];

/** run 已开始但**未收口**（末尾无 run 终态）→ `hasUnterminatedRun` 为真 → 触发接流。 */
const IN_FLIGHT: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
  { type: 'user/message', data: { content: '刷新前就发出的任务' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'text/delta', data: { delta: '刷新前已有的内容。' }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
];

test('BUG-005：刷新后零点击恢复同一个会话与全部内容', async ({ page }) => {
  const events: FrameSpec[] = [
    ...IN_FLIGHT,
    { type: 'run/completed', data: {}, seq: 5, session_id: SID, run_id: RUN, time: T },
  ];
  routeApi(page, { sessions: SESSIONS, events });
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [KEY, SID]);

  await page.goto('/');
  // 零点击：进站即选中该会话并渲染内容（不再是「暂无对话」空态）
  await expect(page.locator('.session-item.selected')).toHaveCount(1);
  await expect(page.locator('.session-item.selected')).toHaveAttribute('title', new RegExp(SID));
  await expect(page.locator('.model-output').last()).toContainText('刷新前已有的内容。');
  await expect(page.locator('.empty-hero')).toBeHidden();

  // F5：选中与内容逐项不变
  await page.reload();
  await expect(page.locator('.session-item.selected')).toHaveAttribute('title', new RegExp(SID));
  await expect(page.locator('.model-output').last()).toContainText('刷新前已有的内容。');
  await expect(page.locator('.empty-hero')).toBeHidden();
});

test('BUG-005 写入路径：真实点击会话行 → 写键 → 不带种子刷新仍恢复', async ({ page }) => {
  // 这条**不用 addInitScript 播种**：addInitScript 会在每次导航（含 reload）重跑，
  // 于是「刷新后还在」只能证明读路径。这里从未选中状态出发，靠真实点击产生写入，
  // 再刷新一次——只有 persist 写路径真的存在才可能通过（删掉写入 effect 这条会红）。
  routeApi(page, {
    sessions: [
      ...SESSIONS,
      { session_id: `${SID}-B`, event_count: 5, first_event_time: T, last_event_time: T, first_user_message: '另一个会话', trace_id: null, trace_url: null },
    ],
    events: [
      ...IN_FLIGHT,
      { type: 'run/completed', data: {}, seq: 5, session_id: SID, run_id: RUN, time: T },
    ],
  });

  await page.goto('/');
  // 起始是空态 + 无键（persist effect 在 idle 下会主动删键）
  await expect(page.locator('.empty-hero')).toBeVisible();
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBeNull();

  // 真实点击会话行 → 选中
  await page.locator('.session-item').first().click();
  await expect(page.locator('.model-output').last()).toContainText('刷新前已有的内容。');
  // 写入路径断言：点了就该记住
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBe(SID);

  // 刷新（**不重新播种**）：恢复只能来自上一步写下的键
  await page.reload();
  await expect(page.locator('.session-item.selected')).toHaveAttribute('title', new RegExp(SID));
  await expect(page.locator('.model-output').last()).toContainText('刷新前已有的内容。');
  await expect(page.locator('.empty-hero')).toBeHidden();
});

test('子会话 id 与普通会话同一持久化/恢复路径：非首行真实点击 → 写键 → 刷新恢复', async ({ page }) => {
  // 意图边界：child id 不特殊，与普通会话共用同一条 persist/restore 路径。若后人
  // 认为「子会话 id 不该持久化」而在 persist effect 里按 child 过滤 → 本用例变红
  // （变异验证：写入过滤 `-child` → 两个视口都报
  //  Expected: "e2e-session-0001-child" / Received: null）。
  //
  // 与兄弟用例 `BUG-005 写入路径` 的差别（两者都有存在价值）：
  //  ① 点**非首行**——兄弟用例点 `.first()`，发现不了「总是持久化第 0 行」；
  //  ② id 是首行 id 的**严格前缀**（SID vs SID-child），刷新断言因此真的能区分
  //     「恢复了错的会话」（`new RegExp(SID)` 同时匹配 SID-child，无鉴别力）。
  //
  // 本用例是**合成 fixture**，不含真的委派/分叉事件；真机验证（委派 child 经列表
  // 与「打开子会话」两条入口、410 事件的分叉 child，刷新后正文 fingerprint 逐字节
  // 一致）记在 docs/FRONTEND_ISSUES_LOG.md——勿把本用例当成那次的自动化复现。
  //
  // 必须走**真实点击的写入路径**，不能 addInitScript 播种：播种在每次导航（含
  // reload）都会重跑，「刷新后还在」便只能证明读路径（实测：播种版在写入被过滤时
  // 依然全绿）。
  const CHILD = `${SID}-child`;
  const CHILD_EVENTS: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: CHILD, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: CHILD, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '委派给 research_review 的子任务' }, seq: 3, session_id: CHILD, run_id: RUN, step_id: 1, time: T },
    { type: 'text/delta', data: { delta: '子会话结论。' }, seq: 4, session_id: CHILD, run_id: RUN, step_id: 1, time: T },
    { type: 'run/completed', data: {}, seq: 5, session_id: CHILD, run_id: RUN, time: T },
  ];
  // 父会话给**不同正文**：routeApi 对任意 id 都返回同一份 events，那样的
  // `toContainText` 在「恢复了父会话」时也会通过，等于没锁内容一致性。
  const PARENT_EVENTS: FrameSpec[] = [
    { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
    { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
    { type: 'user/message', data: { content: '刷新前就发出的任务' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'text/delta', data: { delta: '父会话正文。' }, seq: 4, session_id: SID, run_id: RUN, step_id: 1, time: T },
    { type: 'run/completed', data: {}, seq: 5, session_id: SID, run_id: RUN, time: T },
  ];
  routeApi(page, {
    sessions: [
      ...SESSIONS,
      { session_id: CHILD, event_count: 5, first_event_time: T, last_event_time: T, first_user_message: '委派给 research_review 的子任务', trace_id: null, trace_url: null },
    ],
  });
  // 后注册的路由优先：按请求的 session id 返回**各自**的事件，内容一致性才有鉴别力
  await page.route('**/api/sessions/*/events', (route) => {
    const id = new URL(route.request().url()).pathname.split('/')[3];
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(id === CHILD ? CHILD_EVENTS : PARENT_EVENTS),
    });
  });

  await page.goto('/');
  // 前置条件：空态、且本（全新）上下文里没有键
  await expect(page.locator('.empty-hero')).toBeVisible();
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBeNull();

  // 真实点击 **child** 行（非首行）；按 title 属性定位（稳定身份），不按业务文案
  await page.locator(`.session-item[title^="${CHILD} "]`).click();
  await expect(page.locator('.model-output').last()).toContainText('子会话结论。');
  await expect(page.locator('.model-output').last()).not.toContainText('父会话正文。');
  // 写入路径断言：child id 与普通会话一样被记住
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBe(CHILD);

  // 刷新（**不重新播种**）：恢复只能来自上一步写下的键
  await page.reload();
  await expect(page.locator('.session-item.selected')).toHaveAttribute('title', new RegExp(`${CHILD} `));
  await expect(page.locator('.model-output').last()).toContainText('子会话结论。');
  await expect(page.locator('.model-output').last()).not.toContainText('父会话正文。');
  await expect(page.locator('.empty-hero')).toBeHidden();
});

test('BUG-006：刷新时 run 在途 → 以 after_seq 接回流，刷新后的事件继续到达', async ({ page }) => {
  let streamCalls = 0;
  const afterReloadReqs: string[] = [];
  routeApi(page, {
    sessions: SESSIONS,
    events: IN_FLIGHT,
    onStreamGet: async (route) => {
      streamCalls += 1;
      if (streamCalls > 1) afterReloadReqs.push(route.request().url());
      // 两次接流给不同标记：只有「刷新之后」那一次才能证明事件是接流送到的
      const marker = streamCalls === 1 ? 'FIRST-LOAD-增量。' : 'RELOAD-AFTER-增量。';
      await fulfillSse(route, [
        { type: 'text/delta', data: { delta: marker }, seq: 5, session_id: SID, run_id: RUN, step_id: 1, time: T },
        { type: 'run/completed', data: {}, seq: 6, session_id: SID, run_id: RUN, time: T },
      ]);
    },
  });
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [KEY, SID]);

  await page.goto('/');
  await expect(page.locator('.model-output').last()).toContainText('FIRST-LOAD-增量。');
  await expect(page.locator('.model-output').last()).not.toContainText('RELOAD-AFTER-增量。');

  await page.reload();

  // 零交互：刷新后新增的文本由接流送达
  await expect(page.locator('.model-output').last()).toContainText('RELOAD-AFTER-增量。', { timeout: 10_000 });
  // 接流游标 = 已加载事件的最大持久 seq（4）——重放区间 (4, cursor] 与已加载内容不重不漏
  expect(afterReloadReqs).toHaveLength(1);
  expect(new URL(afterReloadReqs[0]).searchParams.get('after_seq')).toBe('4');
  // 正常接流不是「断线重连」，不得出现重连横幅
  await expect(page.locator('.reconnect-banner')).toBeHidden();
});

test('BUG-006 兜底：接流零帧空流（run 已在刷新窗口内收口）→ 静默停在历史，且不再重试', async ({ page }) => {
  const streamReqs: string[] = [];
  routeApi(page, {
    sessions: SESSIONS,
    events: IN_FLIGHT,
    // 服务端已无在跑的 run：与真实后端一致，立即 200 + 空 body
    onStreamGet: async (route) => {
      streamReqs.push(route.request().url());
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    },
  });
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [KEY, SID]);

  await page.goto('/');
  // 历史照旧渲染，不因空流而清屏
  await expect(page.locator('.model-output').last()).toContainText('刷新前已有的内容。');
  await expect(page.locator('.reconnect-banner')).toBeHidden();
  await expect(page.locator('.session-item.selected')).toHaveCount(1);

  // 死循环断点：零帧 → 退回 viewing → 历史重装 → 游标不变 → 不得再发起第二次接流
  await page.waitForTimeout(600);
  expect(streamReqs).toHaveLength(1);
});

test('BUG-005 自愈：记住的会话已不存在（404）→ 清键 + 静默回空态，不弹错误', async ({ page }) => {
  routeApi(page, { sessions: [], events: [] });
  // Playwright 后注册的路由优先匹配：这条把上面 fixtures 的 /events 200 覆盖成 404
  await page.route('**/api/sessions/*/events', (route) =>
    route.fulfill({ status: 404, body: '{"detail":"session not found"}', contentType: 'application/json' }),
  );
  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [KEY, 'deleted-session']);

  await page.goto('/');
  await expect(page.locator('.empty-hero')).toBeVisible();
  await expect(page.locator('.reconnect-banner')).toBeHidden();
  // 陈旧 id 不得留在存储里被下次刷新复活
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBeNull();
});
