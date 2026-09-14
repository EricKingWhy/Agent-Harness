/** highlight 管线契约（#99，D18）——真实 shiki（dependencies，node 可跑）。
 *  锁定：双主题 token 结构一致、内容 verbatim、无标注/未知语言不猜、空码降级。
 *
 *  ⚠ 首次调用要现加载 shiki 的 grammar/theme（实测 4.7–5.2s），正好压在 vitest 默认
 *  5s 超时上——机器一忙就随机变红（第十一轮集成时真红过一次，重跑又绿）。这是**加载
 *  成本**不是逻辑问题，所以给加载类的用例放宽超时，而不是把断言削弱或把 shiki 换掉。 */

import { describe, expect, it } from 'vitest';
import { highlightCode } from './highlight';

/** shiki 冷启动（首次 import grammar/theme）的余量，非产物性能预算。 */
const SHIKI_LOAD_TIMEOUT = 30_000;

describe('highlightCode — 完成态代码高亮管线', () => {
  it('js 代码：token 色 non-empty（恒深底单主题）、内容 verbatim', async () => {
    const r = await highlightCode('const a = 1;', 'js');
    expect(r).not.toBeNull();
    const flat = r!.lines.flat();
    expect(flat.map((t) => t.content).join('')).toBe('const a = 1;');
    expect(flat.filter((t) => t.content.trim()).every((t) => t.color)).toBe(true);
  }, SHIKI_LOAD_TIMEOUT);

  it('python 多行：行结构保留', async () => {
    const r = await highlightCode('def f():\n    return 1', 'python');
    expect(r).not.toBeNull();
    expect(r!.lines.length).toBe(2);
  }, SHIKI_LOAD_TIMEOUT);

  it('无标注语言不猜（票面硬约束：语言从围栏 info string 取）', async () => {
    expect(await highlightCode('SELECT 1;', null)).toBeNull();
  });

  it('未知语言不猜', async () => {
    expect(await highlightCode('x', 'definitely-not-a-lang')).toBeNull();
  });

  it('空代码降级 null', async () => {
    expect(await highlightCode('   ', 'js')).toBeNull();
  });
});
