/** F1（Phase 2b）Composer control row e2e 交互测试。
 *
 * 验收项：
 *   - 四个控件 trigger 在场（ModelPicker + Permission/Agent/Reasoning）
 *   - 空目录隐藏入口（context-providers 返 [] → 控件不渲染）
 *   - 键盘打开浮层 + 方向键导航 + Enter 选档 → trigger 文本更新
 *   - Esc 关闭浮层（§19）
 *
 * 车道归属：Playwright e2e（同 model-picker.spec.ts 约定）。 */

import { expect, test } from '@playwright/test';
import {
  AGENT_PROFILES,
  PERMISSION_MODES,
  REASONING_EFFORTS,
  fulfillSse,
  longCatalog,
  pickControl,
  routeApi,
} from './fixtures';

test('Composer control row：四控件渲染 + 键盘选档 + Esc 关闭', async ({ page }) => {
  const frames = [
    { type: 'session/started', seq: 1, session_id: 'e2e-session-0001', run_id: 'e2e-run-0001', time: '2026-09-08T00:00:00Z' },
    { type: 'run/started', seq: 2, session_id: 'e2e-session-0001', run_id: 'e2e-run-0001', time: '2026-09-08T00:00:00Z' },
    { type: 'user/message', data: { content: '测试 control row' }, seq: 3, session_id: 'e2e-session-0001', run_id: 'e2e-run-0001', step_id: 1, time: '2026-09-08T00:00:00Z' },
    { type: 'run/completed', data: {}, seq: 4, session_id: 'e2e-session-0001', run_id: 'e2e-run-0001', time: '2026-09-08T00:00:00Z' },
  ];

  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: PERMISSION_MODES,
    agentProfiles: AGENT_PROFILES,
    reasoningEfforts: REASONING_EFFORTS,
    onSessionPost: (route) => fulfillSse(route, frames),
  });

  await page.goto('/');

  // 四个控件 trigger 在场
  const modelTrigger = page.locator('.composer-model[aria-label="模型选择"]');
  const permTrigger = page.locator('.composer-control[aria-label="权限模式"]');
  const agentTrigger = page.locator('.composer-control[aria-label="Agent Profile"]');
  const effortTrigger = page.locator('.composer-control[aria-label="Reasoning Effort"]');

  // ModelPicker 目录空时不渲染——这里没 mock models，所以 model-picker 不在场
  await expect(modelTrigger).toHaveCount(0);
  // 三个 ControlPicker 在场
  await expect(permTrigger).toBeVisible();
  await expect(agentTrigger).toBeVisible();
  await expect(effortTrigger).toBeVisible();

  // 键盘打开 Permission Mode 浮层
  await permTrigger.focus();
  await page.keyboard.press('Enter');
  // 浮层已开——listbox 恒可见（combobox 在短目录下会随搜索框隐藏，见 F-DEFER-1）
  await expect(page.locator('[role="listbox"]')).toBeVisible();
  // option 角色在场——默认（未选）+ auto/ask/deny = 4（FE-R11-05 加的回到未选入口）
  await expect(page.locator('[role="option"]')).toHaveCount(4);

  // Esc 关闭浮层（§19）
  await page.keyboard.press('Escape');
  await expect(page.locator('[role="listbox"]')).toBeHidden();

  // 再次打开 + Enter 选第一个真实档位（ArrowDown 1 次越过「默认（未选）」）
  await pickControl(page, '权限模式', 1, 'Auto Approve');
});

test('Composer control row：长目录搜索过滤 + 短目录隐藏搜索框', async ({ page }) => {
  // 权限模式 3 条 ≤ 5 → 搜索框隐藏；要测搜索需换长目录（F-DEFER-1）。
  // 长目录来自 fixtures 公共构造，避免内联后与其它 spec 漂移。
  const LONG_MODES = longCatalog('mode', 6, { index: 2, label: 'Ask Each Time' });

  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: LONG_MODES,
  });

  await page.goto('/');

  const permTrigger = page.locator('.composer-control[aria-label="权限模式"]');
  await expect(permTrigger).toBeVisible();
  await permTrigger.focus();
  await page.keyboard.press('Enter');

  // 长目录（6 > 5）→ 搜索框可见、可交互
  const combo = page.getByRole('combobox', { name: '权限模式' });
  await expect(combo).toBeVisible();
  // 6 条目录 + 「默认（未选）」= 7
  await expect(page.locator('[role="option"]')).toHaveCount(7);

  // 搜索过滤：键入「ask」只剩匹配项（「默认（未选）」的 keywords 不含 ask）
  await page.keyboard.type('ask');
  await expect(page.locator('[role="option"]')).toHaveCount(1);
  await expect(page.locator('[role="option"]')).toContainText('Ask Each Time');
});

/** FE-R11-05 回归锁：单选控件选了之后必须能回到「未选」。
 *  此前只能整页 reload——目录里没有任何表达"没选"的条目，触发文本却显示 placeholder。 */
test('Composer control row：单选档位可以选回「默认（未选）」', async ({ page }) => {
  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: PERMISSION_MODES,
    agentProfiles: AGENT_PROFILES,
    reasoningEfforts: REASONING_EFFORTS,
  });
  await page.goto('/');

  const trigger = page.locator('.composer-control[aria-label="权限模式"]');
  await expect(trigger).toContainText('权限'); // 未选 → placeholder（文案是「权限」）

  // 先选一个真实档位
  await pickControl(page, '权限模式', 1, 'Auto Approve');
  await expect(trigger).toContainText('Auto Approve');

  // 再选回「默认（未选）」——首项，Enter 零次下压即命中
  await pickControl(page, '权限模式', 0, '权限');
  await expect(trigger).not.toContainText('Auto Approve');
});

/** FE-R11-04 回归锁：短目录（搜索框 display:none）下**纯键盘**必须能选档。
 *
 *  此前的洞：cmdk 把方向键/Enter 的处理挂在 `[cmdk-root]` 上，只能靠冒泡到达；
 *  搜索框一藏，root 里没有可聚焦元素 → Radix 把焦点放到 Content（在 root 之外）
 *  → 方向键无反应、Enter 不提交。鼠标路径正常，所以只有键盘用户会撞上。
 *  本用例**不手动 focus listbox**（那是旧 helper 的绕行），只依赖打开时的初焦——
 *  修复前这里必然失败。 */
test('Composer control row：短目录键盘导航（不手动聚焦 listbox）', async ({ page }) => {
  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: PERMISSION_MODES, // 3 条 ≤ 5 → 搜索框隐藏
  });
  await page.goto('/');

  const trigger = page.locator('.composer-control[aria-label="权限模式"]');
  await trigger.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('[role="listbox"]')).toBeVisible();

  // 焦点必须在 cmdk 的 root 内，否则按键根本到不了承接者
  const focusInCmdkRoot = await page.evaluate(() => {
    const a = document.activeElement as HTMLElement | null;
    return !!a?.closest('[cmdk-root]');
  });
  expect(focusInCmdkRoot).toBe(true);

  // 零下压 = 首项「默认（未选）」；下压一次 → 第一个真实档位
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(trigger).toContainText('Auto Approve');
});

test('Composer control row：提交 payload 字段名对齐后端契约', async ({ page }) => {
  const frames = [
    { type: 'session/started', seq: 1, session_id: 'e2e-session-payload', run_id: 'e2e-run-payload', time: '2026-09-08T00:00:00Z' },
    { type: 'run/started', seq: 2, session_id: 'e2e-session-payload', run_id: 'e2e-run-payload', time: '2026-09-08T00:00:00Z' },
    { type: 'user/message', data: { content: 'payload 测试' }, seq: 3, session_id: 'e2e-session-payload', run_id: 'e2e-run-payload', step_id: 1, time: '2026-09-08T00:00:00Z' },
    { type: 'run/completed', data: {}, seq: 4, session_id: 'e2e-session-payload', run_id: 'e2e-run-payload', time: '2026-09-08T00:00:00Z' },
  ];

  let capturedBody: string | null = null;

  routeApi(page, {
    sessions: [],
    events: [],
    permissionModes: PERMISSION_MODES,
    agentProfiles: AGENT_PROFILES,
    reasoningEfforts: REASONING_EFFORTS,
    onSessionPost: (route) => {
      const req = route.request();
      capturedBody = req.postData() ?? '';
      return fulfillSse(route, frames);
    },
  });

  await page.goto('/');

  // 选 Permission Mode → auto / Agent Profile → coding / Reasoning Effort → deep
  // （每个控件首项都是「默认（未选）」，故下压次数 = 条目下标 + 1）
  await pickControl(page, '权限模式', 1, 'Auto Approve');
  await pickControl(page, 'Agent Profile', 2, 'Coding');
  await pickControl(page, 'Reasoning Effort', 3, 'Deep');

  // 提交任务
  await page.getByLabel('Agent 任务').fill('payload 测试');
  await page.getByLabel('发送').click();

  // 等待 POST 被拦截
  await expect.poll(() => capturedBody).not.toBeNull();

  const body = JSON.parse(capturedBody!);
  // 字段名对齐后端 B1 契约
  expect(body.permission_mode).toBe('auto');
  expect(body.agent_profile).toBe('coding');
  expect(body.reasoning_effort).toBe('deep');
  // 未选 context_providers → 不传该字段
  expect(body.context_providers).toBeUndefined();
});
