/** UI-02（R2/R3）对比度与排版地板回归锁 + U-1 review 加固项。
 *
 *  锁（暗/亮两主题各一遍）：
 *  1. 会话元数据（.session-item-meta）≥12px 且对比度 ≥4.5:1
 *  2. 时间线序号（.tl-seq）≥12px 且对比度 ≥4.5:1
 *  3. composer placeholder 对比度 ≥4.5:1
 *  4. 时间线事件类型名（.tl-type）== 解析后的 --color-muted-foreground（R1，等值断言）
 *  5. U-1 review 新增 ink 元素：.approval-chip / .approval-deny .approval-kbd /
 *     .composer-locked-hint 对比度 ≥4.5:1（写 UI 时新立的三处，不许回退）
 *
 *  对比度算法：WCAG 相对亮度；背景取元素到根的祖先 backgroundColor 逐层
 *  alpha 合成（body 的 gradient 不参与——background-color 落在最后一层 canvas）。
 *
 *  ⚠ 已知测量局限（U-1 review 声明）：本 harness 不对 `backdrop-filter`
 *  （玻璃材质的可视底 ≠ backgroundColor）与祖先 `opacity` 建模——被测元素
 *  链上出现这两者时数值会偏离真实观感；当前选择器链均不含。
 *  解析器对未知颜色格式 **throw**（不是回退白底）：Chromium 换计算值格式时
 *  必须显式失败，不许静默量错。 */

import { expect, type Page, test } from '@playwright/test';
import {
  AGENT_PROFILES,
  MODELS,
  PERMISSION_MODES,
  REASONING_EFFORTS,
  routeApi,
  T,
} from './fixtures';

const ROW = {
  session_id: 's-contrast',
  event_count: 5,
  first_event_time: T,
  last_event_time: T,
  first_user_message: '对比度回归',
  trace_id: null,
  trace_url: null,
};

const EVENTS = [
  { type: 'session/started', seq: 1, session_id: ROW.session_id, run_id: 'r1', time: T },
  { type: 'run/started', seq: 2, session_id: ROW.session_id, run_id: 'r1', time: T },
  { type: 'user/message', data: { content: '对比度回归' }, seq: 3, session_id: ROW.session_id, run_id: 'r1', step_id: 1, time: T },
  { type: 'run/completed', data: {}, seq: 4, session_id: ROW.session_id, run_id: 'r1', time: T },
  {
    type: 'tool/approval-requested',
    data: {
      approval_id: 'ap-contrast', tool_name: 'write', tool_call_id: 'tc-1',
      action_type: 'workspace-write', title: 'write (workspace-write)',
      description: '工具授权级别为 workspace-write，但当前策略为只读（read-only）。',
      arguments_preview: { path: 'demo.txt', content: 'HELLO' },
      permission: 'workspace-write', policy: 'read-only',
      reason: '工具授权级别为 workspace-write，但当前策略为只读（read-only）。',
      allowed_decisions: ['deny', 'approve_once'],
    },
    seq: 5, session_id: ROW.session_id, run_id: 'r1', step_id: 1, time: T,
  },
];

async function openWorkspace(page: Page, theme: 'dark' | 'light'): Promise<void> {
  routeApi(page, {
    sessions: [ROW],
    events: EVENTS,
    models: MODELS,
    permissionModes: PERMISSION_MODES,
    agentProfiles: AGENT_PROFILES,
    reasoningEfforts: REASONING_EFFORTS,
  });
  // 主题必须显式引导（localStorage，paint 前生效）：headless 的
  // prefers-color-scheme 是 light，不引导则 [dark] 用例量到的是亮色主题。
  await page.addInitScript((t) => localStorage.setItem('ahi.theme', t), theme);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.locator('.session-item').first().click();
  await page.locator('.turn').first().waitFor();
  // 审批卡在场（提供 chip / deny kbd / locked-hint 三个被测元素）
  await page.locator('.approval-card').waitFor();
}

interface Measure {
  fontSize: string;
  color: [number, number, number, number];
  bg: [number, number, number];
}

/** 页内测量：computed fontSize/color + 祖先 backgroundColor alpha 合成后的有效底色。 */
function measure(page: Page, selector: string): Promise<Measure> {
  return page.evaluate((sel: string) => {
    const el = document.querySelector(sel);
    if (!el) throw new Error(`no element: ${sel}`);
    const parse = (c: string): [number, number, number, number] => {
      const rgb = c.match(/rgba?\(([^)]+)\)/i);
      if (rgb) {
        const p = rgb[1].split(',').map((s) => parseFloat(s.trim()));
        return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
      }
      // color-mix 的计算值在现代 Chromium 可能是 oklab(...)（如选中项的粉色染底）
      const ok = c.match(/oklab\(([^)]+)\)/i);
      if (ok) {
        const parts = ok[1].split('/').map((s) => s.trim());
        const [L, a, b] = parts[0].split(/\s+/).map(parseFloat);
        const alpha = parts.length > 1 ? parseFloat(parts[1]) : 1;
        const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
        const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
        const s_ = L - 0.0894841775 * a - 1.291485548 * b;
        const l = l_ ** 3;
        const m = m_ ** 3;
        const s = s_ ** 3;
        const lin = [
          4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
          -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
          -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
        ];
        const enc = (v: number) => {
          const x = Math.min(1, Math.max(0, v));
          return x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055;
        };
        return [enc(lin[0]) * 255, enc(lin[1]) * 255, enc(lin[2]) * 255, alpha];
      }
      // 同一份 color-mix 在该 Chromium 的另一计算路径是 color(srgb r g b / a)
      // （r/g/b 为 0-1 gamma 编码 sRGB——CSS Color 4 规定 srgb 带 transfer function）。
      const csr = c.match(/color\(srgb\s+([^)]+)\)/i);
      if (csr) {
        const parts = csr[1].split('/');
        const comps = parts[0].trim().split(/\s+/).map(parseFloat);
        const alpha = parts.length > 1 ? parseFloat(parts[1]) : 1;
        return [comps[0] * 255, comps[1] * 255, comps[2] * 255, alpha];
      }
      throw new Error(`unparsed color: ${c}`);
    };
    const cs = getComputedStyle(el);
    const stack: [number, number, number, number][] = [];
    let node: Element | null = el;
    while (node) {
      const c = parse(getComputedStyle(node).backgroundColor);
      stack.push(c);
      if (c[3] >= 1) break;
      node = node.parentElement;
    }
    if (stack[stack.length - 1][3] < 1) throw new Error(`no opaque ancestor bg: ${sel}`);
    let out: [number, number, number] = [
      stack[stack.length - 1][0],
      stack[stack.length - 1][1],
      stack[stack.length - 1][2],
    ];
    for (let i = stack.length - 2; i >= 0; i -= 1) {
      const c = stack[i];
      out = [
        c[0] * c[3] + out[0] * (1 - c[3]),
        c[1] * c[3] + out[1] * (1 - c[3]),
        c[2] * c[3] + out[2] * (1 - c[3]),
      ];
    }
    const color = parse(cs.color);
    return { fontSize: cs.fontSize, color, bg: out };
  }, selector);
}

function contrast(fg: [number, number, number, number], bg: [number, number, number]): number {
  const chan = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const lum = (c: number[]) => 0.2126 * chan(c[0]) + 0.7152 * chan(c[1]) + 0.0722 * chan(c[2]);
  const fgLum = lum([fg[0] * fg[3] + bg[0] * (1 - fg[3]), fg[1] * fg[3] + bg[1] * (1 - fg[3]), fg[2] * fg[3] + bg[2] * (1 - fg[3])]);
  const bgLum = lum(bg);
  const [hi, lo] = fgLum >= bgLum ? [fgLum, bgLum] : [bgLum, fgLum];
  return (hi + 0.05) / (lo + 0.05);
}

for (const theme of ['dark', 'light'] as const) {
  test(`[${theme}] 元数据与时间线序号：12px 地板 + 对比度 ≥4.5（R2/R3）`, async ({ page }) => {
    await openWorkspace(page, theme);
    for (const selector of ['.session-item-meta', '.tl-seq']) {
      const m = await measure(page, selector);
      expect(m.fontSize, `${selector} font-size`).toBe('12px');
      const ratio = contrast(m.color, m.bg);
      expect(ratio, `${selector} contrast`).toBeGreaterThanOrEqual(4.5);
    }
  });

  test(`[${theme}] composer placeholder 对比度 ≥4.5（R3）`, async ({ page }) => {
    await openWorkspace(page, theme);
    const ratio = await page.evaluate(() => {
      const el = document.querySelector('#composer-input');
      if (!el) throw new Error('no composer');
      const cs = getComputedStyle(el, '::placeholder');
      const parse = (c: string): number[] => {
        const m = c.match(/rgba?\(([^)]+)\)/);
        if (!m) throw new Error(`unparsed color: ${c}`);
        return m[1].split(',').map((s) => parseFloat(s.trim()));
      };
      const chan = (v: number) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      const lum = (c: number[]) => 0.2126 * chan(c[0]) + 0.7152 * chan(c[1]) + 0.0722 * chan(c[2]);
      // placeholder 的有效底 = composer dock 的解析底色（两主题 --surface-overlay
      // 均不透明；若未来改成半透明玻璃，这里显式失败而不是拿错误底色量）。
      const dock = el.closest('.composer-dock');
      if (!dock) throw new Error('no composer-dock');
      const bg = parse(getComputedStyle(dock).backgroundColor);
      if ((bg[3] ?? 1) < 1) throw new Error('composer-dock bg translucent — measure invalid');
      const fg = parse(cs.color);
      const a = fg[3] ?? 1;
      const fgMix = fg.slice(0, 3).map((v, k) => v * a + bg[k] * (1 - a));
      const f = lum(fgMix);
      const b = lum(bg.slice(0, 3));
      const [hi, lo] = f >= b ? [f, b] : [b, f];
      return (hi + 0.05) / (lo + 0.05);
    });
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });

  test(`[${theme}] .tl-type == 解析后的 --color-muted-foreground（R1 等值断言）`, async ({ page }) => {
    await openWorkspace(page, theme);
    const [typeColor, expected] = await page.evaluate(() => {
      const el = document.querySelector('.tl-type');
      if (!el) throw new Error('no .tl-type');
      // 用探针元素解析 token 的实际计算值（getPropertyValue 只回 var 引用）
      const probe = document.createElement('div');
      probe.style.color = 'var(--color-muted-foreground)';
      document.body.appendChild(probe);
      const v = getComputedStyle(probe).color;
      probe.remove();
      return [getComputedStyle(el).color, v];
    });
    expect(typeColor).toBe(expected);
  });

  test(`[${theme}] U-1 新增 ink 元素（chip / deny kbd / locked-hint）对比度 ≥4.5`, async ({ page }) => {
    await openWorkspace(page, theme);
    for (const selector of ['.approval-chip', '.approval-deny .approval-kbd', '.composer-locked-hint']) {
      const m = await measure(page, selector);
      const ratio = contrast(m.color, m.bg);
      expect(ratio, `${selector} contrast`).toBeGreaterThanOrEqual(4.5);
    }
  });
}
