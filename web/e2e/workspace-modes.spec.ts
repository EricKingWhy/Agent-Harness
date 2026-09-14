/** 场景：#182 —— 中心列的面由**能力声明**决定；Split / Preview 已删除。
 *
 *  历史（#180 路线 A）：那条"Workspace 模式"条上，Split/Preview 是 `disabled` 的诚实
 *  占位。本票按 Brief 与 `BENCHMARK_SYNTHESIS` 的取舍把它们**删掉**（要的是 tabs 不是
 *  分屏），换成真正由 `GET /api/capabilities` 驱动的 tab 集：
 *
 *  - AC1：Split / Preview / 预留位字样**全部不存在**（删干净，不留"点了没事发生"）；
 *  - AC2/AC3：tab 集 = `Chat`（恒存在）+ 能力声明为真的面；数据拿不到时落 PRD 缺省
 *    语义（chat + timeline），**Chat 永不因此消失**；
 *  - AC4：声明为真**但尚无实现**的面不渲染——渲染一个没有实现的 tab 就是"看着像
 *    功能、点了没反应"，比不渲染更差；
 *  - AC5：`role="tablist"` / `aria-selected` 如实 / roving tabindex（方向键语义的
 *    纯函数单测在 `src/lib/capabilities.test.ts`，这里锁真实 DOM 接线）；
 *  - AC7：三区几何不变、Chat 面板照常渲染。
 */

import { expect, test } from '@playwright/test';
import { CORE_CAPABILITY, capabilityFixture, routeApi } from './fixtures';

const tabs = (page: import('@playwright/test').Page) =>
  page.getByRole('tablist', { name: '工作区面' });
const tabLabels = (page: import('@playwright/test').Page) => tabs(page).getByRole('tab').allTextContents();

test('AC1：Split / Preview 与预留位残留已全部删除', async ({ page }) => {
  routeApi(page, {});
  await page.goto('/');

  // 旧的那条"模式"工具条不再存在（它被能力驱动的 tab 条取代）。
  await expect(page.getByRole('toolbar', { name: 'Workspace 模式' })).toHaveCount(0);
  await expect(page.locator('.workspace-mode, .workspace-mode-bar')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Split|Preview/ })).toHaveCount(0);
  // 占位说明文案也一并消失——留着它等于留着"这里本来该有功能"的暗示。
  await expect(page.getByText('Phase 1d 预留，尚未实现')).toHaveCount(0);
  await expect(page.getByText('未来升级点')).toHaveCount(0);
  // 取而代之的是 tab 条（`role="tablist"`，不是一个 button 工具栏）。
  await expect(tabs(page)).toBeVisible();
});

test('AC2/AC3 + #193：**真实后端默认**（`CAPABILITIES=""`，只有 core）→ 三个面都出现', async ({
  page,
}) => {
  /* 这条锁的是**前端消费侧**：#193 之后端点在默认部署下发的就是"只有 core 一条"，
     前端必须据此渲染出三个面。载荷由 `routeApi` 缺省给（`[CORE_CAPABILITY]`，逐值镜像
     `capability/manifest.py`）——**请求不出网**，所以它证明不了"后端真的发 core"，
     只证明"后端发这个形状时，前端不把两个面滤掉"。后端那一半由
     `tests/web/test_web_phase2_endpoints.py::TestCapabilities` 锁（那条真走 HTTP 端点）。
     两侧镜像会漂移：后端改值时这里不会自动跟，改声明请同时看这两个文件。 */
  routeApi(page, {});
  await page.goto('/');

  expect(await tabLabels(page)).toEqual(['Chat', '文件/改动', '输出']);
  const chat = tabs(page).getByRole('tab', { name: 'Chat' });
  await expect(chat).toHaveAttribute('aria-selected', 'true');
  // roving tabindex：整条只占一个 Tab 停靠点（选中项 0，其余 -1）。
  await expect(chat).toHaveAttribute('tabindex', '0');
});

test('AC2/AC3：能力目录**真的为空**（老后端/无 core）→ 恰好只剩 Chat，且它被选中', async ({
  page,
}) => {
  // "空就是空"这条语义仍在：没有声明为真的条目时不留任何多余面。
  // 真实后端现在恒发 core，所以要覆盖这条路径必须显式 mock 空列表
  //（老后端部署 / 端点被裁剪的部署都可能这么返回）。
  routeApi(page, { capabilities: [] });
  await page.goto('/');

  expect(await tabLabels(page)).toEqual(['Chat']);
  const chat = tabs(page).getByRole('tab', { name: 'Chat' });
  await expect(chat).toHaveAttribute('aria-selected', 'true');
  await expect(chat).toHaveAttribute('tabindex', '0');
});

test('AC4 + 端点真被消费：面跟着**真实默认载荷**出现（`changes` #189 / `terminal` #190）', async ({
  page,
}) => {
  // 这条用例同时回答一个**不能只靠 Chat 回答**的问题：前端到底有没有调这个端点？
  // `changes`（「文件/改动」）与 `terminal`（「输出」）都已落地实现，所以真实默认载荷下
  // **必须**出现——这正是 #182 骨架期守卫翻转后的形态（当时本用例断言两个面都不出现，
  // 因为那时它们还没有实现）。"声明为真但没有实现 → 不渲染"这条守卫仍在：见 AC6。
  let calls = 0;
  routeApi(page, {
    onCapabilitiesGet: () => {
      calls += 1;
      return false; // 交回默认分支（回真实默认载荷）
    },
  });
  await page.goto('/');

  expect(await tabLabels(page)).toEqual(['Chat', '文件/改动', '输出']);
  // StrictMode 在 dev 下会双调用 effect（React 既定行为），所以**不锁精确次数**；
  // 锁两件真事：(a) 端点确实被消费了；(b) 消费完之后没有继续重拉——依赖写错会变成
  // 请求循环，而那种 bug 靠 tab 集看不出来。
  await expect.poll(() => calls).toBeGreaterThanOrEqual(1);
  const settled = calls;
  await page.waitForTimeout(400);
  expect(calls).toBe(settled);
});

test('AC6：tab 集恰好等于"声明为真 **且有实现**"的面（逐面独立）', async ({ page }) => {
  // 票面 AC6 要求"各组 mock（真/假）各断言 tab 集**恰好**符合声明"。
  // 这里**不挂 core 条目**（`capabilities` 显式给出时就完全替换缺省载荷），
  // 于是三组之间只差一个布尔值，能验"changes 与 terminal 互不牵连"。
  // "真实默认载荷（含 core）→ 三个面"由上面 AC2/AC3 那条覆盖。
  routeApi(page, {
    capabilities: [capabilityFixture({ chat: true, timeline: true, changes: false, terminal: false })],
  });
  await page.goto('/');
  const declaredFalse = await tabLabels(page);

  await page.unroute('**/api/**');
  routeApi(page, {
    capabilities: [capabilityFixture({ chat: true, timeline: true, changes: false, terminal: true })],
  });
  await page.goto('/');
  const declaredTrue = await tabLabels(page);

  await page.unroute('**/api/**');
  routeApi(page, {
    capabilities: [capabilityFixture({ chat: true, timeline: true, changes: true, terminal: false })],
  });
  await page.goto('/');
  const changesOnly = await tabLabels(page);

  expect(declaredFalse).toEqual(['Chat']);
  expect(declaredTrue).toEqual(['Chat', '输出']);
  // changes 单独声明为真 → 恰好只有它出现（与 terminal 互不牵连）
  expect(changesOnly).toEqual(['Chat', '文件/改动']);
});

test('#193：前端取**并集**——插件声明 false 不能关掉 core 已声明的面', async ({ page }) => {
  // 如实记录当前语义（不变量 #22 的"单一真相"落在声明上）：`deriveSurfaces` 对多条取并集
  // ——"只要有一个能力能产出该面，这个会话就能产出它"。core 声明 changes/terminal 为真，
  // 所以插件写 false 不会让面消失（`centerTabs` 的"声明为真"判据由 core 满足）。
  // 要让某个面消失，只能在**声明侧**去掉它（core 不再声明）——这正是 #193 把两个面的
  // 可见性交还给"内置工具集真的存在"这件事的原因。
  routeApi(page, {
    capabilities: [
      CORE_CAPABILITY,
      capabilityFixture({ chat: false, timeline: false, changes: false, terminal: false }),
    ],
  });
  await page.goto('/');

  expect(await tabLabels(page)).toEqual(['Chat', '文件/改动', '输出']);
});

test('AC3：能力接口不可用 → 降级为缺省语义，Chat 永不消失', async ({ page }) => {
  // 老后端没有这个端点（404）——降级不阻塞主流程，也不该让主阅读面消失。
  routeApi(page, { capabilitiesError: { status: 404, detail: 'Not Found' } });
  await page.goto('/');

  expect(await tabLabels(page)).toEqual(['Chat']);
  await expect(tabs(page).getByRole('tab', { name: 'Chat' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
});

test('AC5：方向键在只有一个面时原地不动，不把焦点丢出 tab 条', async ({ page }) => {
  // 单 tab 是**显式构造**的：真实后端默认载荷（含 core）会给出三个面，
  // 而"单 tab 环绕回自己"这条边界仍要有用例守着（空目录 / 只有 Chat 可用的部署）。
  routeApi(page, { capabilities: [] });
  await page.goto('/');

  const chat = tabs(page).getByRole('tab', { name: 'Chat' });
  await chat.focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowLeft');
  // 单 tab 时环绕回到自己：仍选中、仍持有焦点（焦点被吞会让键盘用户直接掉出这条）。
  await expect(chat).toHaveAttribute('aria-selected', 'true');
  await expect(chat).toBeFocused();
});

test('AC7：三区几何不变，Chat 的对话与输入框照常渲染', async ({ page }) => {
  routeApi(page, {});
  await page.goto('/');

  // 中心列多出的那一层（tabpanel 容器）不得改动三区几何：仍是 240 | 1fr | 320。
  const columns = await page
    .locator('.app-regions')
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  const tracks = columns.split(' ').filter((t) => t.endsWith('px'));
  expect(tracks).toHaveLength(3);
  expect(tracks[0]).toBe('240px');
  expect(tracks[2]).toBe('320px');

  // Conversation 与 Composer 都还在（新容器必须把 flex 纵向布局原样传给它们）。
  await expect(page.getByLabel('Agent 任务')).toBeVisible();
  await expect(page.locator('.conversation')).toBeVisible();
});
