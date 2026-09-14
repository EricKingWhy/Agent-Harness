/** BUG-011 回归锁（前端侧）：**同一个模型目标不得发出第二个 `POST /model`**。
 *
 * 真机现场（会话 `dd983104`）：模型项被双击 → 两个并发 `POST /model` → 后端两个请求
 * 各自基于同一份快照取号 → 两条 seq=5 落盘 → 该会话此后任何续聊恒 404
 * （`续聊失败：Send failed: 404`）。后端已加 seq 守卫 + 冲突重试兜底；前端这一侧的
 * 契约是**一次用户意图只对应一个请求**：弹层在第一次选中后关闭，但节点在退出动画
 * （`--dur-out` 150ms）期间仍在 DOM 中可被命中，第二次 click 会再触发一次 `onSelect`。
 *
 * 拦截点是选档入口 `ModelPicker.commitSelection` 的「弹层已关即忽略选中」——
 * **单层，实测足够**（探针实测，见下）：`dblclick()`（一次手势两下点击）与
 * `page.mouse.click` ×2 都只产生 1 个请求。曾试过在 `useSession.changeModel` 再加
 * 「同目标在途复用 Promise」，探针显示该层**永不生效**（两次 click 之间 React 已提交
 * `open=false`，第二个请求根本到不了那层）→ 已删除：测不到的死层不留在代码里。
 *
 * 三条锁：
 * 1. **在途重复点击**：首个请求未回来时再点一次（用延迟响应撑开在途窗口，否则本地
 *    mock 毫秒级返回覆盖不到该窗口）→ 只发一个；
 * 2. **已关即忽略**：首个请求已回来后再双击同一项（人类双击 ~120ms，真机现场就是
 *    这个形状）→ 只有首下那一个请求，第二下被丢弃；
 * 3. **不误吞正常切换**：换一个目标必须照常发。
 *
 * 第 2、3 条用两次**原始鼠标点击**（`page.mouse.click`，不经 Playwright 的可操作性
 * 等待）——真机上正是这种「弹层已关但节点仍命中」的第二次点击造成重复请求。
 *
 * **敏感性（反「假绿」）**：去掉 `commitSelection` 的 `!open` 守卫 → 本文件两条测试
 * 全部转红（第二下点击确实命中目标项并被计数）。所以绿不是「第二次点击根本没落到
 * 节点上」造成的。 */

import { expect, test } from '@playwright/test';
import { MODELS, RUN, SID, T, routeApi, type FrameSpec } from './fixtures';

const EVENTS: FrameSpec[] = [
  { type: 'session/started', seq: 1, session_id: SID, run_id: RUN, time: T },
  { type: 'run/started', seq: 2, session_id: SID, run_id: RUN, time: T },
  { type: 'user/message', data: { content: '模型切换去重' }, seq: 3, session_id: SID, run_id: RUN, step_id: 1, time: T },
  { type: 'run/completed', data: {}, seq: 4, session_id: SID, run_id: RUN, time: T },
];

const SESSION_ROW = {
  session_id: SID, event_count: 4, first_event_time: T, last_event_time: T,
  first_user_message: '模型切换去重', trace_id: null, trace_url: null,
};

/** 撑开在途窗口的响应延迟；等待「没有迟到的请求」比它更长。 */
const MODEL_RESPONSE_DELAY_MS = 800;
const SETTLE_WAIT_MS = MODEL_RESPONSE_DELAY_MS + 200;

/** 收集 `POST /api/sessions/{id}/model` 的请求体——响应交给 fixtures 的缺省处理器
 *  （不在这里重写响应体：去重与响应内容无关，重写只会让断言耦合到假形状）。 */
function countModelPosts(page: import('@playwright/test').Page): string[] {
  const posts: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/sessions\/[^/]+\/model$/.test(new URL(req.url()).pathname)) {
      posts.push(req.postData() ?? '');
    }
  });
  return posts;
}

/** 打开模型浮层，返回目标任务项（`.model-picker-item`）。 */
async function openPicker(page: import('@playwright/test').Page, name: string) {
  await page.locator('.composer-model[aria-label="模型选择"]').first().click();
  const item = page.locator('.model-picker-item', { hasText: name }).first();
  await item.waitFor();
  return item;
}

/** 原始鼠标点击目标项（两次）——**不做可操作性等待**，模拟真实双击的第二次点击
 *  （弹层已开始关闭、节点仍可命中）。 */
async function rawClickItem(page: import('@playwright/test').Page, item: import('@playwright/test').Locator, gapMs = 0) {
  const box = await item.boundingBox();
  if (!box) throw new Error('模型项无 boundingBox');
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.click(cx, cy);
  if (gapMs > 0) await page.waitForTimeout(gapMs);
  await page.mouse.click(cx, cy);
}

test.describe('模型切换去重（BUG-011）', () => {
  test('在途重复点击：延迟响应窗口内只发一个 POST /model', async ({ page }) => {
    const posts = countModelPosts(page);
    routeApi(page, {
      sessions: [SESSION_ROW],
      events: EVENTS,
      models: MODELS,
      onModelPost: async (route) => {
        await new Promise((r) => setTimeout(r, MODEL_RESPONSE_DELAY_MS)); // 撑开在途窗口
        await route.fulfill({ status: 200, body: JSON.stringify({ status: 'changed' }), contentType: 'application/json' });
      },
    });

    await page.goto('/');
    await page.locator('.session-item').first().click();
    expect(posts, '会话打开阶段不应自己发 POST /model').toHaveLength(0);
    const item = await openPicker(page, 'qwen-max');
    await rawClickItem(page, item, 0); // 首次点击 + 在途期间的第二次点击

    await expect.poll(() => posts.length, { timeout: 5000 }).toBe(1);
    await page.waitForTimeout(SETTLE_WAIT_MS); // 等响应落地，确认没有迟到的第二个请求
    expect(posts, '在途窗口内的重复点击发出了第二个请求').toHaveLength(1);
  });

  test('关闭态下的第二次点击：仍是 1 个请求；换目标照常发', async ({ page }) => {
    const posts = countModelPosts(page);
    routeApi(page, { sessions: [SESSION_ROW], events: EVENTS, models: MODELS });

    await page.goto('/');
    await page.locator('.session-item').first().click();
    expect(posts, '会话打开阶段不应自己发 POST /model').toHaveLength(0);

    // ① 单击切换 → 恰一个请求
    const first = await openPicker(page, 'qwen-max');
    await first.click();
    await expect.poll(() => posts.length).toBe(1);

    // ② 人类尺度双击同一项 → 首下照常发一个（未在途、无永久幂等缓存），
    //    第二下落在「弹层已关、节点仍命中」的窗口 → 必须被丢弃（真机现场就是这个形状）
    const again = await openPicker(page, 'qwen-max');
    await rawClickItem(page, again, 120);
    await page.waitForTimeout(400);
    expect(posts, '双击模型项发出了第二个请求').toHaveLength(2);

    // ③ 去重不得吞掉正常切换：换个目标照常发
    const other = await openPicker(page, 'claude-sonnet-4');
    await other.click();
    await expect.poll(() => posts.length).toBe(3);
  });
});
