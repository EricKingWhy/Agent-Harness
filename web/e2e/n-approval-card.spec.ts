/** 场景 N：交互式审批卡（#37, PRD §2.2）——「批准」「拒绝」两键的确定性点击回归锁。
 *
 * 可达性（此前登记为「产品不可达」，**已证伪**）：审批卡由 `tool/approval-requested`
 * 事件驱动（`projection.ts:514` → `pending_approvals` → `Conversation.tsx:348`），
 * 与 `auto_approve` 无关。真后端路径：显式选一个权限档位且非 danger-full-access
 * 时 `interactive=True`（`session/service.py:348`），policy=read-only 下任何
 * workspace-write 工具都会走 `_check_approval` 发该事件（`tooling/executor.py:659`）。
 * 真机证据见 `docs/FRONTEND_ISSUES_LOG.md` OBS-006 订正条（含 JSONL seq 与 decision）。
 *
 * 本 spec 用同一形状的 fixture 锁**前端契约**（事件 → 卡片 → POST /approve 请求体
 * → 决后 UI），与网络真实与否解耦，故可进标准门禁。
 *
 * OBS-015 回归锁：POST 500 → 卡片保持 pending + 按钮仍可用 + 出现错误提示；
 * POST 409 → 视为幂等成功，翻「已批准」。 */

import { expect, test } from '@playwright/test';
import { RUN, SID, T, routeApi, fulfillSse, submitTask, type FrameSpec } from './fixtures';

/** 一条与后端 `session/approval.py:56-72` 同形状的审批请求帧。 */
function approvalRequestedFrame(approvalId: string, seq: number): FrameSpec {
  return {
    type: 'tool/approval-requested',
    data: {
      approval_id: approvalId,
      tool_name: 'write',
      tool_call_id: 'tc-1',
      action_type: 'workspace-write',
      title: 'write (workspace-write)',
      description: '工具授权级别为 workspace-write，但当前策略为只读（read-only）。',
      arguments_preview: { path: 'demo.txt', content: 'HELLO' },
      permission: 'workspace-write',
      policy: 'read-only',
      reason: '工具授权级别为 workspace-write，但当前策略为只读（read-only）。',
      allowed_decisions: ['deny', 'approve_once'],
    },
    seq,
    session_id: SID,
    run_id: RUN,
    step_id: 1,
    time: T,
  };
}

/** 「决后再按快捷键无第二个请求」的静默观察窗（对齐 q-model-dedupe 的写法）：
 *  absence 断言没法 poll，只能等一个有限窗口确认没有新调用。 */
const NO_SECOND_REQUEST_WAIT_MS = 300;

const HEAD: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
  { type: 'user/message', data: { content: '写个文件' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
];

async function openCard(page: import('@playwright/test').Page, frames: FrameSpec[], sent: unknown[]) {
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, frames),
    onApprovePost: async (route) => {
      // 同时记 URL 路径：只断请求体会漏掉「打到别的会话」的回归（本 spec 的 route 正则
      // 是 `[^/]+`，任何 id 都匹配，故必须显式断路径）。
      sent.push({
        path: new URL(route.request().url()).pathname,
        body: route.request().postDataJSON(),
      });
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ status: 'resolved', approval_id: 'ap-1', decision: 'approve_once' }),
        contentType: 'application/json',
      });
    },
    events: frames,
  });
  await page.goto('/');
  await submitTask(page, '写个文件');
}

test('审批请求 → 卡片渲染工具名与参数预览', async ({ page }) => {
  const sent: unknown[] = [];
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4)], sent);

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();
  await expect(card.locator('.approval-title')).toHaveText('需要审批');
  // UI-01：工具名 + permission/policy 徽章；路径结构化置顶（不再是 .approval-args 转义串）。
  await expect(card.locator('.approval-tool code')).toHaveText('write');
  await expect(card.locator('.approval-chip')).toHaveCount(2);
  await expect(card.locator('.approval-path code')).toHaveText('demo.txt');
  await expect(card.locator('.approval-content')).toContainText('HELLO');
  // UI-01：description 渲染（后端下发、此前未渲染的决策上下文）。
  await expect(card.locator('.approval-desc')).toContainText('workspace-write');
  await expect(card.locator('.approval-approve')).toBeEnabled();
  await expect(card.locator('.approval-deny')).toBeEnabled();
});

/** UI-01 ①：多行 content 以**真实换行**呈现（R7——转义串 `\n` 字面量是旧病）。 */
test('多行 content → 原文块真实换行，不再出现字面 \\n', async ({ page }) => {
  const sent: unknown[] = [];
  const rich = approvalRequestedFrame('ap-1', 4);
  rich.data = {
    ...rich.data,
    arguments_preview: { path: 'deploy.sh', content: '#!/usr/bin/env bash\nrsync -av dist/ server:/srv/app' },
  };
  await openCard(page, [...HEAD, rich], sent);

  const content = page.locator('.approval-content');
  await expect(content).toBeVisible();
  const text = (await content.textContent()) ?? '';
  expect(text).toContain('#!/usr/bin/env bash\nrsync -av dist/ server:/srv/app');
  expect(text).not.toContain('\\n');
  // 命令形状的旧断言面：未知键才走 .approval-args 兜底（此处已被结构化消费 → 不渲染）。
  await expect(page.locator('.approval-args')).toHaveCount(0);
});

/** UI-01 ②③：挂载焦点落卡 + Ctrl+Enter 批准。 */
test('焦点落卡 + Ctrl+Enter → POST decision=approve_once', async ({ page }) => {
  const sent: unknown[] = [];
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4)], sent);

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();
  await expect(card).toBeFocused(); // alertdialog 挂载焦点（多卡只有第一张）

  await page.keyboard.press('Control+Enter');
  await expect(card.locator('.approval-title')).toHaveText('已批准');
  await expect(card.locator('.approval-actions')).toHaveCount(0);
  expect(sent).toEqual([
    { path: `/api/sessions/${SID}/approve`, body: { approval_id: 'ap-1', approved: true, decision: 'approve_once' } },
  ]);
});

/** UI-01 ③：Ctrl+Backspace 拒绝；决后快捷键失效（不再发第二个请求）。 */
test('Ctrl+Backspace → POST decision=deny；决后快捷键失效', async ({ page }) => {
  const sent: unknown[] = [];
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4)], sent);

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();
  await page.keyboard.press('Control+Backspace');
  await expect(card.locator('.approval-title')).toHaveText('已拒绝');

  // 决后再按快捷键：监听已卸载 → 无新请求
  await page.keyboard.press('Control+Enter');
  await page.waitForTimeout(NO_SECOND_REQUEST_WAIT_MS);
  expect(sent).toEqual([
    { path: `/api/sessions/${SID}/approve`, body: { approval_id: 'ap-1', approved: false, decision: 'deny' } },
  ]);
});

/** U-1 review P1 回归锁：多卡并存时快捷键**只决第一张**——
 *  每张卡各自挂 document 监听的话，一次 Ctrl+Enter 会向 N 个 approval_id
 *  各发一 POST = 一次按键批量批准多个危险操作。门控：仅 autoFocus 卡挂监听。 */
test('双卡并存 → Ctrl+Enter 只 POST 第一张（不批量批准）', async ({ page }) => {
  const sent: unknown[] = [];
  const second = approvalRequestedFrame('ap-2', 5);
  second.data = { ...second.data, approval_id: 'ap-2', title: 'write (workspace-write) #2' };
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4), second], sent);

  const cards = page.locator('.approval-card');
  await expect(cards).toHaveCount(2);
  await expect(cards.first()).toBeFocused();

  await page.keyboard.press('Control+Enter');
  await expect(cards.first().locator('.approval-title')).toHaveText('已批准');
  await page.waitForTimeout(NO_SECOND_REQUEST_WAIT_MS);
  expect(sent).toHaveLength(1);
  expect(sent[0]).toEqual({
    path: `/api/sessions/${SID}/approve`,
    body: { approval_id: 'ap-1', approved: true, decision: 'approve_once' },
  });
  // 第二张保持 pending，可继续决策
  await expect(cards.nth(1).locator('.approval-title')).toHaveText('需要审批');
});

/** APR-01（第十一轮真机）：run 终结后仍 pending 的审批 = 孤儿（后端队列随 run GC，
 *  决策永不可能提交）。此前这种卡既点不动（点了只有 404）又把 composer 一起锁死 →
 *  **会话永久发不出消息**，且刷新多少次都重演。现在：卡转只读失效态，composer 解锁。
 *
 *  fixture 补 run/completed 同时让 streaming=false，于是「composer 可用」这条断言
 *  只能来自「失效审批不参与锁定」——变异验证不会假绿。 */
test('run 终结仍 pending（孤儿审批）→ 卡片只读失效 + composer 不再锁死', async ({ page }) => {
  const sent: unknown[] = [];
  const done: FrameSpec = {
    type: 'run/completed',
    data: {},
    seq: 5,
    session_id: SID,
    run_id: RUN,
    time: T,
  };
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4), done], sent);

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();
  await expect(card.locator('.approval-title')).toHaveText('审批已失效');
  await expect(card.locator('.approval-invalid-note')).toContainText('决策无法再提交');
  await expect(card.locator('.approval-approve')).toBeDisabled();
  await expect(card.locator('.approval-deny')).toBeDisabled();

  // 关键：失效审批不该继续锁 composer（否则这个会话再也发不出话）
  const textarea = page.locator('#composer-input');
  await expect(textarea).toBeEnabled();
  await expect(page.locator('.composer-locked-hint')).toHaveCount(0);
  // 空输入框的发送键本来就是禁用的——打上字才证明真的能用（不是被锁住）
  await textarea.fill('还能继续发消息');
  await expect(page.locator('.composer-send')).toBeEnabled();

  // 失效卡不可点 → 一个请求都不该发出
  await card.locator('.approval-approve').click({ force: true }).catch(() => {});
  await page.waitForTimeout(NO_SECOND_REQUEST_WAIT_MS);
  expect(sent).toHaveLength(0);
});

/** UI-01 ⑤：permission/resolved 清空队列 → composer 解锁（同一 projection 状态驱动，
 *  无第二真相源）。真待决审批的锁定断言在「POST 500」票里（那里卡必须保持可决策）。 */
test('permission/resolved 后卡片消失 + composer 解锁', async ({ page }) => {
  const sent: unknown[] = [];
  const resolved: FrameSpec = {
    type: 'permission/resolved',
    data: { approval_id: 'ap-1', decision: 'approve_once', reason: '' },
    seq: 5,
    session_id: SID,
    run_id: RUN,
    step_id: 1,
    time: T,
  };
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4), resolved], sent);
  await expect(page.locator('.approval-card')).toHaveCount(0);
  await expect(page.locator('#composer-input')).toBeEnabled();
  await expect(page.locator('.composer-locked-hint')).toHaveCount(0);
});

test('点「批准」→ 已批准 + 按钮消失 + POST decision=approve_once', async ({ page }) => {
  const sent: unknown[] = [];
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4)], sent);

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();
  await card.locator('.approval-approve').click();

  await expect(card.locator('.approval-title')).toHaveText('已批准');
  await expect(card.locator('.approval-actions')).toHaveCount(0);
  expect(sent).toEqual([
    { path: `/api/sessions/${SID}/approve`, body: { approval_id: 'ap-1', approved: true, decision: 'approve_once' } },
  ]);
});

test('点「拒绝」→ 已拒绝 + 按钮消失 + POST decision=deny', async ({ page }) => {
  const sent: unknown[] = [];
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4)], sent);

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();
  await card.locator('.approval-deny').click();

  await expect(card.locator('.approval-title')).toHaveText('已拒绝');
  await expect(card.locator('.approval-actions')).toHaveCount(0);
  expect(sent).toEqual([
    { path: `/api/sessions/${SID}/approve`, body: { approval_id: 'ap-1', approved: false, decision: 'deny' } },
  ]);
});

test('permission/resolved 把卡片从待决队列移除（不渲染）', async ({ page }) => {
  const sent: unknown[] = [];
  const resolved: FrameSpec = {
    type: 'permission/resolved',
    data: { approval_id: 'ap-1', decision: 'approve_once', reason: '' },
    seq: 5,
    session_id: SID,
    run_id: RUN,
    step_id: 1,
    time: T,
  };
  await openCard(page, [...HEAD, approvalRequestedFrame('ap-1', 4), resolved], sent);

  await expect(page.locator('.approval-card')).toHaveCount(0);
  expect(sent).toEqual([]); // 无待决项 → 不该有决策请求
});

// ── OBS-015 回归锁：错误处理 ──────────────────────────────────────

/** POST /approve 返回 500 → 卡片保持 pending + 按钮仍可用 + 出现错误提示。
 *  这是 OBS-015 的核心断言：真失败时不能翻成「已批准」。 */
test('POST 500 → 卡片保持「需要审批」+ 按钮仍可用 + 出现错误提示', async ({ page }) => {
  const approveCalls: unknown[] = [];
  const frames = [...HEAD, approvalRequestedFrame('ap-1', 4)];
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, frames),
    onApprovePost: async (route) => {
      approveCalls.push(route.request().postDataJSON());
      await route.fulfill({
        status: 500,
        body: JSON.stringify({ detail: 'Internal Server Error' }),
        contentType: 'application/json',
      });
    },
    events: frames,
  });
  await page.goto('/');
  await submitTask(page, '写个文件');

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();
  await expect(card.locator('.approval-title')).toHaveText('需要审批');

  // 点批准 → 500 → 保持 pending
  await card.locator('.approval-approve').click();
  await expect(card.locator('.approval-title')).toHaveText('需要审批');
  await expect(card.locator('.approval-error')).toBeVisible();
  await expect(card.locator('.approval-approve')).toBeEnabled();
  await expect(card.locator('.approval-deny')).toBeEnabled();
  expect(approveCalls).toHaveLength(1);
  // UI-01：仍 pending → composer 仍锁定
  await expect(page.locator('#composer-input')).toBeDisabled();
  await expect(page.locator('.composer-locked-hint')).toBeVisible();

  // 重试：第二次点批准 → 仍然 500 → 仍然 pending
  await card.locator('.approval-approve').click();
  await expect(card.locator('.approval-title')).toHaveText('需要审批');
  await expect(card.locator('.approval-error')).toBeVisible();
  expect(approveCalls).toHaveLength(2);
});

/** POST /approve 返回 409 → 幂等成功，翻「已批准」。
 *  后端对同一 approval_id 的第二次决策返回 409。 */
test('POST 409 → 幂等成功，卡片翻「已批准」', async ({ page }) => {
  const approveCalls: unknown[] = [];
  const frames = [...HEAD, approvalRequestedFrame('ap-1', 4)];
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, frames),
    onApprovePost: async (route) => {
      approveCalls.push(route.request().postDataJSON());
      await route.fulfill({
        status: 409,
        body: JSON.stringify({ detail: 'Approval already resolved' }),
        contentType: 'application/json',
      });
    },
    events: frames,
  });
  await page.goto('/');
  await submitTask(page, '写个文件');

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();

  // 点批准 → 409 → 幂等成功
  await card.locator('.approval-approve').click();
  await expect(card.locator('.approval-title')).toHaveText('已批准');
  await expect(card.locator('.approval-actions')).toHaveCount(0);
  expect(approveCalls).toHaveLength(1);
});

/** POST /approve 返回 404 → 只读失效态（**不是**幂等成功，也不再提示重试）。
 *
 *  与最初交接提示词的期望**相反**，此处按后端真实语义钉死：404 有四个来源
 *  （session 不存在 / 审批队列缺失 / `approval_id` 不在队列 / 事件过期，
 *  `web/app.py:1157-1166`）。它们在当前实现下都不可能再变回可提交——审批队列是
 *  纯内存的，进程重启或 run 终结即 GC（`session/service.py:1233-1241`），没有任何
 *  路径把它放回来。所以 404 既不能当成功（「决策其实没生效、UI 却显示已批准」
 *  正是 OBS-015 本身），也不该提示重试（重试多少次都是 404）。
 *  **「不是已批准」这条不变量仍然锁在这里**；真已决由 `permission/resolved`
 *  投影事件移除卡片（上一用例已锁），不靠 404。 */
test('POST 404 → 只读失效态（404 不是幂等已决，也不是可重试错误）', async ({ page }) => {
  const approveCalls: unknown[] = [];
  const frames = [...HEAD, approvalRequestedFrame('ap-1', 4)];
  routeApi(page, {
    onSessionPost: (route) => fulfillSse(route, frames),
    onApprovePost: async (route) => {
      approveCalls.push(route.request().postDataJSON());
      await route.fulfill({
        status: 404,
        body: JSON.stringify({ detail: 'approval not found' }),
        contentType: 'application/json',
      });
    },
    events: frames,
  });
  await page.goto('/');
  await submitTask(page, '写个文件');

  const card = page.locator('.approval-card');
  await expect(card).toBeVisible();

  await card.locator('.approval-approve').click();
  // 关键不变量：404 ≠ 成功，绝不能翻「已批准」
  await expect(card.locator('.approval-title')).toHaveText('审批已失效');
  await expect(card.locator('.approval-invalid-note')).toBeVisible();
  await expect(card.locator('.approval-approve')).toBeDisabled();
  await expect(card.locator('.approval-deny')).toBeDisabled();
  await expect(card.locator('.approval-error')).toHaveCount(0); // 不走可重试错误通道
  expect(approveCalls).toHaveLength(1);

  // 失效即不再阻塞会话；快捷键已撤 → 不会发出第二个请求
  await expect(page.locator('#composer-input')).toBeEnabled();
  await page.keyboard.press('Control+Enter');
  await page.waitForTimeout(NO_SECOND_REQUEST_WAIT_MS);
  expect(approveCalls).toHaveLength(1);
});
