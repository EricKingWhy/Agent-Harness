/** 恢复会话（T8 #138）——用户的原始症状是「点了恢复，什么反应也没有」。
 *
 *  根因不是后端不干活（崩溃会话往往已被启动扫描修完，POST /recover 是幂等
 *  no-op），而是前端把「修好了」与「按钮坏了」渲染成了同一个画面：
 *  `recoverState` 修好后回 `idle`、投影逐字不变、入口还在。
 *
 *  这里锁两件事：
 *  ① 成功后有**明确可见**的反馈，且该反馈不能挂在 `canRecover` 门内——
 *     修好后 dangling 归零、入口消失，挂在门内的提示会立刻被卸载；
 *  ② `repaired === 0` 不能笼统报「已恢复」：事件已完整（真 no-op）与后端也没能
 *     回填（仍缺终态，可重试）是两种不同状态，混报会让用户以为修好了。 */

import { expect, test, type Page } from '@playwright/test';
import { RUN, SID, T, routeApi, type ApiMock, type FrameSpec } from './fixtures';

const ROW = {
  session_id: SID,
  event_count: 5,
  first_event_time: T,
  last_event_time: T,
  first_user_message: '崩溃前的问题',
  trace_id: null, trace_url: null,
};

/** 崩溃会话：run 无终态 + 一条未配对 tool/call → isRecoverableRun 为真。
 *  `user/message` **不带 `step_id`**：这是真实信封形状（步号由其后的
 *  `model/completed` / `tool/call` 携带），伪造一个 step_id 会掩盖
 *  `resolveStep` 相关的回归。 */
function crashedEvents(): FrameSpec[] {
  return [
    { type: 'session/started', seq: 1, session_id: SID, time: T },
    { type: 'user/message', data: { content: '崩溃前的问题' }, seq: 2, session_id: SID, time: T },
    { type: 'run/started', data: { turn_index: 1 }, seq: 3, session_id: SID, run_id: RUN, time: T },
    { type: 'model/completed', data: { content: '开始执行。' }, seq: 4, session_id: SID, step_id: 1, run_id: RUN, time: T },
    {
      type: 'tool/call',
      data: { tool_call_id: 'call-1', tool_name: 'bash', args: { command: 'ls' } },
      seq: 5,
      session_id: SID,
      step_id: 1,
      run_id: RUN,
      time: T,
    },
  ];
}

/** 后端修复后的事件流：补 tool/result + 补 run 终态（真实 /recover 的语义）。 */
function repairedEvents(): FrameSpec[] {
  return [
    ...crashedEvents(),
    {
      type: 'tool/result',
      data: { tool_call_id: 'call-1', content: JSON.stringify({ ok: true, message: 'done', data: {} }) },
      seq: 6,
      session_id: SID,
      step_id: 1,
      run_id: RUN,
      time: T,
    },
    { type: 'run/interrupted', data: { reason: 'process_restart' }, seq: 7, session_id: SID, step_id: 1, run_id: RUN, time: T },
  ];
}

async function openCrashedSession(page: Page, mock: ApiMock): Promise<void> {
  routeApi(page, mock);
  await page.goto('/');
  await page.locator('.session-item').first().click();
  await expect(page.locator('.recover-btn')).toBeVisible();
}

test('恢复成功：提示明确可见，且入口消失后提示不跟着消失', async ({ page }) => {
  await openCrashedSession(page, {
    sessions: [ROW],
    events: crashedEvents(),
    onRecoverPost: async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify(repairedEvents()), contentType: 'application/json' });
    },
  });
  await expect(page.locator('.recover-hint')).toContainText('未配对');

  await page.locator('.recover-btn').click();

  const done = page.locator('.recover-done');
  await expect(done).toContainText('已恢复');
  await expect(done).toContainText('回填 1 条工具结果');
  // 关键：修好后事件已完整 → canRecover 转假、入口卸载，提示必须仍在场
  await expect(page.locator('.recover-btn')).toHaveCount(0);
  await expect(page.locator('.recover-hint')).toHaveCount(0);
});

test('后端未能回填时不谎报「已完整」——如实说明仍缺终态、可重试', async ({ page }) => {
  await openCrashedSession(page, {
    sessions: [ROW],
    events: crashedEvents(),
    // 幂等 no-op：响应与当前事件同构（既没配对 tool，也没补终态）
    onRecoverPost: async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify(crashedEvents()), contentType: 'application/json' });
    },
  });

  await page.locator('.recover-btn').click();

  const done = page.locator('.recover-done');
  await expect(done).toContainText('仍缺 run 终态');
  await expect(done).not.toContainText('已完整');
  // 仍是可恢复态 → 入口保留，用户可重试（不是死路）
  await expect(page.locator('.recover-btn')).toBeVisible();
});

/** 只缺 run 终态、无 dangling 的崩溃会话：isRecoverableRun 走「缺终态」这一支。 */
function unterminatedOnly(): FrameSpec[] {
  return [
    { type: 'session/started', seq: 1, session_id: SID, time: T },
    { type: 'user/message', data: { content: '崩溃前的问题' }, seq: 2, session_id: SID, time: T },
    { type: 'run/started', data: { turn_index: 1 }, seq: 3, session_id: SID, run_id: RUN, time: T },
    { type: 'model/completed', data: { content: '先想一下。' }, seq: 4, session_id: SID, step_id: 1, run_id: RUN, time: T },
  ];
}

test('只补上 run 终态（无工具回填）时如实说「补齐 run 终态」，不谎报「无可修复项」', async ({ page }) => {
  await openCrashedSession(page, {
    sessions: [{ ...ROW, event_count: 4 }],
    events: unterminatedOnly(),
    onRecoverPost: async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify([
          ...unterminatedOnly(),
          { type: 'run/interrupted', data: { reason: 'process_restart' }, seq: 5, session_id: SID, run_id: RUN, time: T },
        ]),
        contentType: 'application/json',
      });
    },
  });

  await page.locator('.recover-btn').click();

  const done = page.locator('.recover-done');
  await expect(done).toContainText('补齐 run 终态');
  // 「无可修复项」会把一次真实的修复说成没修——这正是要防的谎报
  await expect(done).not.toContainText('无可修复项');
  await expect(done).not.toContainText('已完整');
  // 终态补上后事件完整 → 入口消失
  await expect(page.locator('.recover-btn')).toHaveCount(0);
});

test('恢复遇 409：需人工裁决单独成形，不混同普通失败', async ({ page }) => {  await openCrashedSession(page, {
    sessions: [ROW],
    events: crashedEvents(),
    onRecoverPost: async (route) => {
      await route.fulfill({
        status: 409,
        body: JSON.stringify({ detail: '存在 UNKNOWN 状态的高风险工具调用，需人工裁决' }),
        contentType: 'application/json',
      });
    },
  });

  await page.locator('.recover-btn').click();

  const conflict = page.locator('.recover-conflict');
  await expect(conflict).toContainText('需人工裁决');
  await expect(conflict).toContainText('高风险工具调用');
  await expect(page.locator('.recover-done')).toHaveCount(0);
});

/** 中断横幅的 step_id **缺失**是**真值**，不是缺失——实测扫 71 个真实会话：
 *  4 条 run/interrupted 里有 2 条信封整个不带 step_id（`run/started` 之后紧接
 *  `run/interrupted`，进程在该 run 的首个带步号事件之前就死了；run/started 信封
 *  不带 step，检测器无从沿用），例如 c63ce4d3-3b26-40bb-8e8c-e3af8dd33035。
 *  渲染成「第 ? 步」等于把「还没开始就断了」说成一个未知数字。 */

/** 在首个带步号事件前中断：run/started(seq 2) → run/interrupted(seq 3, step null)。 */
function interruptedBeforeFirstStep(): FrameSpec[] {
  return [
    { type: 'session/started', seq: 1, session_id: SID, time: T },
    { type: 'user/message', data: { content: '刚发出去就崩了' }, seq: 2, session_id: SID, time: T },
    { type: 'run/started', data: { turn_index: 1 }, seq: 3, session_id: SID, run_id: RUN, time: T },
    {
      type: 'run/interrupted',
      data: { interrupted_seq: 3, reason: 'process_restart' },
      seq: 4,
      session_id: SID,
      run_id: RUN,
      time: T,
    },
  ];
}

test('中断在首个步骤之前：横幅说「首个步骤开始前中断」而不是「第 ? 步」', async ({ page }) => {
  routeApi(page, { sessions: [ROW], events: interruptedBeforeFirstStep() });
  await page.goto('/');
  await page.locator('.session-item').first().click();

  const banner = page.locator('.interrupt-banner');
  await expect(banner).toContainText('首个步骤开始前中断');
  await expect(banner).not.toContainText('第 ? 步');
  await expect(banner).toContainText('process_restart');
});

test('中断在某个步骤：横幅仍报具体步号', async ({ page }) => {
  routeApi(page, {
    sessions: [ROW],
    events: [
      ...crashedEvents(),
      {
        type: 'run/interrupted',
        data: { interrupted_seq: 5, reason: 'process_restart' },
        seq: 6,
        session_id: SID,
        step_id: 1,
        run_id: RUN,
        time: T,
      },
    ],
  });
  await page.goto('/');
  await page.locator('.session-item').first().click();

  await expect(page.locator('.interrupt-banner')).toContainText('上次运行在第 1 步中断');
});
