/** #181（AC1–AC3）：≤820px **触摸**设备上 ⋯ 菜单的可达性。
 *
 *  已有的窄屏用例（`w-session-delete.spec.ts` / `r-project-groups.spec.ts`）全是
 *  「800px + 鼠标 + 键盘」：它们点得开 ⋯，因为 `hover` / `focus-within` 在桌面输入下
 *  成立。而窄屏的槽位交换（默认显示会话点 / 文件夹图标，hover 时让位给 ⋯）恰恰由这
 *  两条伪类驱动，触摸设备上它们**都可能不成立**：触摸没有 hover；iOS Safari 上点
 *  `button` 也不进入 `:focus-within`。于是 FE-R11-09（会话级）与 #179（项目级）担保
 *  的入口在手机上可能压根不显形——桌面输入的脚本验证覆盖不到这一档。
 *
 *  AC1 的"无需 hover 即可触发"在本文件按 **可见性** 验（`opacity`）：`opacity: 0` 的
 *  元素本来就能被 `tap()` 命中（Playwright 的可见性判据不看 opacity），所以"点得到"
 *  从来不是缺口，"看不见"才是。修复前本文件红在 `opacity` 那一条上，正是这个意思。
 *
 *  第三层断言（`状态信号`）：本票的取舍是「⋯ 常显、点 / 图标退到背景」，但槽位里原本
 *  还有两个**状态**信号——"这个会话在跑"与"项目目录不见了"。它们在触摸档修复前是
 *  **可见**的，跟着槽位一起消失就是一次信息丢失，所以改挂在 ⋯ 上。断言方式是与状态
 *  元素**同源比色**（`getComputedStyle` 比字符串 / 解析 token），而不是写死色值——
 *  改 token 或换明暗主题不该让这条用例假红。
 */

import { expect, test, type Locator, type Page } from '@playwright/test';
import {
  RUN,
  T,
  fulfillSse,
  routeApi,
  rowOf,
  sessionRow,
  submitTask,
  type FrameSpec,
  type ProjectFixture,
} from './fixtures';

/** 跑着流的那条会话。行里的 id 是 `session_id.slice(0, 12)`，所以这里用短 id
 *  （长 id 会被截断，`rowOf` 的 hasText 就匹配不上——w-session-delete 同款约定）。 */
const LIVE = 's9';
const P1: ProjectFixture = { id: 'p1', path: 'D:/repos/alpha', title: '项目 alpha', session_ids: ['s2'] };
/** 目录已不在的项目：`.rail-project-warn` 只在 `status === 'missing-dir'` 时渲染。 */
const MISSING: ProjectFixture = { id: 'p9', path: 'D:/repos/gone', title: '项目 gone', session_ids: [], status: 'missing-dir' };

const projectSession = () => sessionRow('s2', { id: 'p1', title: '项目 alpha' });
const freeSession = () => sessionRow('s1', null);

/** 读计算样式。`getPropertyValue` 收的是**连字符**属性名（驼峰会静默返回空串，
 *  断言就变成拿 "" 去比——白红一场）。 */
const computedStyle = (locator: Locator, prop: 'opacity' | 'color') =>
  locator.evaluate((el, p) => getComputedStyle(el).getPropertyValue(p), prop);

/** 把一段 CSS 值在**当前主题**下解析成计算值——用来比对 token（明暗主题各有一套
 *  色值，写死 rgb 会在另一个主题下假红；token 改名同理）。 */
const resolveToken = (page: Page, value: string) =>
  page.evaluate((v) => {
    const probe = document.createElement('span');
    probe.style.color = v;
    document.body.appendChild(probe);
    const resolved = getComputedStyle(probe).color;
    probe.remove();
    return resolved;
  }, value);

test.describe('#181 窄屏触摸：⋯ 菜单不依赖 hover', () => {
  test.use({ viewport: { width: 800, height: 900 }, hasTouch: true, isMobile: true });

  test('AC1/AC2：空闲态 ⋯ 即可见，且会话级 / 项目级同款地 tap 得开', async ({ page }) => {
    await routeApi(page, { sessions: [projectSession(), freeSession()], projects: [P1] });
    await page.goto('/');

    // 前置（AC3 的关键）：这个上下文必须真的是「无 hover」。若某个 Playwright 版本下
    // `hasTouch` 不带媒体特性，下面的绿灯就来自桌面输入——本用例当场红在这里，
    // 而不是悄悄测了另一台设备。
    const noHover = await page.evaluate(() => matchMedia('(hover: none)').matches);
    expect(noHover, 'hasTouch 上下文必须是 (hover: none)，否则本 spec 没测到触摸档').toBe(true);

    // 指针挪到左上角：排除任何残留 hover（触摸设备本来也没有指针）
    await page.mouse.move(0, 0);

    const sessionRow = rowOf(page, 's2');
    const sessionBtn = sessionRow.locator('.rail-menu-btn');
    const projectHead = page.locator('.rail-project-head').filter({ hasText: '项目 alpha' });
    const projectBtn = projectHead.locator('.rail-menu-btn');

    // ── AC1（会话行）──
    // 没有任何 hover / 聚焦，⋯ 就得在场。修复前这里是 0（`toBeVisible` 拦不住）。
    await expect.poll(() => computedStyle(sessionBtn, 'opacity')).toBe('1');
    // 槽位确实让出来了：点退到背景，而不是和 ⋯ 叠在同一槽心
    await expect.poll(() => computedStyle(sessionRow.locator('.session-item-dot'), 'opacity')).toBe('0');

    // ── AC2（项目行）：同款行为，不因为是另一层就退回 hover ──
    await expect.poll(() => computedStyle(projectBtn, 'opacity')).toBe('1');
    await expect.poll(() => computedStyle(projectHead.locator('.rail-project-icon'), 'opacity')).toBe('0');

    // 槽位交换不该把整行的可点面积吃掉——用 opacity 让位（而不是 display:none）就是为了
    // 让内容仍占着布局。判据分两条：点**仍在流里**（`display:none` 时 boundingBox() 返回
    // null），以及行的盒子仍然够点（实测 800px 档：项目内某行 29×23；既有注释记录过
    // 收掉 padding 会把可点区域"24px → 9px"）。
    const dotBox = await sessionRow.locator('.session-item-dot').boundingBox();
    expect(dotBox, '会话点必须仍在布局里：display:none 会让行塌成 0 高').not.toBeNull();
    const box = await sessionRow.locator('.session-item').boundingBox();
    expect(Math.round(box?.width ?? 0), '会话行的可点宽度').toBeGreaterThanOrEqual(20);
    expect(Math.round(box?.height ?? 0), '会话行的可点高度').toBeGreaterThanOrEqual(20);
    /* 这里**不**断言"点行内空白处能选会话"：实测 ⋯ 芯片（20px）居中压在行中央，行相对
       x∈[4,24) 命中的是它——而且它在 `opacity: 0` 时**照样接收指针事件**（`elementFromPoint`
       验证过）。也就是说"点行中央 = 打开菜单"是这条窄轨**修复前就有**的既成事实（未显形的
       ⋯ 也会拦下这一击，反而更怪）；本票把它变成看得见的入口，没有引入这个重叠。要让
       "点行中央选会话"成立得改槽位模型（例如窄屏行不再收缩成内容宽 29px），issue 明确说
       这类改动要一次性定案，不在可达性票里顺手做。 */

    await sessionBtn.tap();
    await expect(page.getByRole('menuitem', { name: '移出项目' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: '删除会话…' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('menuitem', { name: '移出项目' })).toHaveCount(0);

    await projectBtn.tap();
    await expect(page.getByRole('menuitem', { name: '在此项目中新建任务' })).toBeVisible();
    await expect(page.getByRole('menuitem', { name: '重命名项目' })).toBeVisible();
  });

  test('槽位让给 ⋯ 后，两个状态信号（在跑 / 目录缺失）仍挂在 ⋯ 上', async ({ page }) => {
    // 两个状态都得**真的发生**：live 来自一条不结束的流（不给 run/completed），
    // 目录缺失来自项目 fixture 的 status。
    const frames: FrameSpec[] = [
      { type: 'session/started', seq: 1, session_id: LIVE, run_id: RUN, time: T },
      { type: 'run/started', seq: 2, session_id: LIVE, run_id: RUN, time: T },
      { type: 'user/message', data: { content: '跑个长任务' }, seq: 3, session_id: LIVE, run_id: RUN, step_id: 1, time: T },
    ];
    await routeApi(page, {
      sessions: [sessionRow(LIVE)],
      projects: [MISSING],
      onSessionPost: (route) => fulfillSse(route, frames),
    });
    await page.goto('/');
    await submitTask(page, '跑个长任务');

    // 前置：这一行真的在跑（否则下面断言的是"没在跑时长什么样"）
    const row = rowOf(page, LIVE);
    await expect(row.locator('.session-item-dot')).toHaveClass(/session-item-dot-live/);
    /* 参照物是 `var(--success)`——`.session-item-dot-live` 自己声明的那个颜色，而不是
       点的**实际**背景色：跑着流的那条会话同时是选中行，而
       `.session-item.selected .session-item-dot`（更高优先级）把点染成 accent，绿色只在
       未选中时才露出来。呼吸动画刻意不搬到 ⋯ 上（会把槽里唯一的入口周期性淡到 .55），
       所以这里断言的是颜色这一半。 */
    const live = row.locator('.rail-menu-btn');
    await expect.poll(() => computedStyle(live, 'color')).toBe(await resolveToken(page, 'var(--success)'));

    // 项目行同理：黄三角退到背景，颜色改由 ⋯ 承担
    const warn = page.locator('.rail-project-warn');
    await expect(warn).toHaveCount(1); // fixture 真的造出了 missing-dir，否则下一条会假绿
    await expect
      .poll(() => computedStyle(page.locator('.rail-project-head .rail-menu-btn'), 'color'))
      .toBe(await computedStyle(warn, 'color'));
  });
});
