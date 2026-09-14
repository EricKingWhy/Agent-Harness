/** #182 —— 能力声明显隐的语义层（纯函数，无 DOM）。
 *
 *  这一层回答三个问题，每个都有票面 AC 兜着：
 *
 *  1. **后端声明了哪些面、每个面叫什么**（AC4）：`SURFACES` 是"声明键 → 可见名"
 *     的**唯一登记处**。声明键是 `terminal`，界面上叫「输出」——两者只在这里对应
 *     一次，别处再写死字符串就会漂移（PRD §3.5：本项目无 PTY，叫 Terminal 等于
 *     承诺不存在的输入能力）。
 *  2. **能力数据 → 每个面是否可见**（AC2/AC3）：声明为 `true` 的面才可见；数据
 *     拿不到（null / 空目录）→ PRD 缺省语义（chat + timeline）；**Chat 恒存在**。
 *  3. **键盘在 tab 间怎么走**（AC5）：方向键 / Home / End 的目标键由纯函数给出，
 *     组件只负责把事件接上去。没有 DOM 也能把语义钉死——本仓没有 jsdom，交互
 *     层只在 e2e 里测，所以"决策"必须与"接线"分开。
 *
 *  为什么"声明为 true 但尚无实现"的面不渲染：渲染一个没有实现的 tab 就是
 *  "点了没事发生"——#180 已裁定这是最差一档（诚实占位都算退让）。`implemented`
 *  因此是显式的，`changes` / `terminal` 的实现落在 #189 / #190。
 */

import { describe, expect, it } from 'vitest';
import {
  DEFAULT_SURFACES,
  SURFACES,
  SURFACE_KEYS,
  centerTabs,
  deriveSurfaces,
  parseCapabilities,
  resolveActiveTab,
  tabKeyTarget,
  type SurfaceDescriptor,
  type SurfaceKey,
} from './capabilities';

/** 后端 `GET /api/capabilities` 的条目（形状 = `capability/manifest.py::manifest_entry`）。
 *
 *  `surfaces` 这里写成局部字典——真实条目恒带全部五个键（后端统一补齐），但前端解析
 *  必须能扛住缺键（老后端 / 未来裁剪），所以 fixture 刻意保留"只写一部分"这条路径。 */
function capability(surfaces: Partial<Record<SurfaceKey, boolean>>, id = 'coding') {
  return {
    id,
    display_name: id,
    version: '1',
    provider_name: 'builtin',
    surfaces,
    actions: {},
  };
}

describe('#182 AC4：声明键与可见名的登记', () => {
  it('中心列能承载的键都有登记，且只登记一次', () => {
    // 后端 `capability/manifest.py::CORE_SURFACES` 声明的五个键（少登记一个就会有声明被静默丢弃）。
    expect([...SURFACE_KEYS].sort()).toEqual(
      ['artifacts', 'changes', 'chat', 'terminal', 'timeline'].sort(),
    );
    expect(SURFACES.map((s) => s.key).sort()).toEqual(['changes', 'chat', 'terminal']);
    // 另外两个键归 Inspector（`timeline` / `artifacts` 的清单在右栏，PRD §2.1），
    // **故意**不进中心列登记——写进来会让人以为中心列也承载它们。
    for (const inspectorKey of ['timeline', 'artifacts'] as const) {
      expect(SURFACES.some((s) => s.key === inspectorKey)).toBe(false);
    }
  });

  it('`terminal` 的可见名是「输出」，不是 Terminal', () => {
    const terminal = SURFACES.find((s) => s.key === 'terminal');
    expect(terminal?.label).toBe('输出');
    // 反面：任何面的名字都不许叫 Terminal（只读输出不叫终端，PRD §3.5）。
    expect(SURFACES.some((s) => /terminal/i.test(s.label))).toBe(false);
  });

  it('每个面都有非空可见名，且名字互不相同', () => {
    const labels = SURFACES.map((s) => s.label);
    expect(labels.every((l) => l.trim().length > 0)).toBe(true);
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe('#182 AC3：能力数据缺省与降级', () => {
  it('数据拿不到（null）→ PRD 缺省：chat + timeline 为真，其余为假', () => {
    expect(deriveSurfaces(null)).toEqual({
      chat: true,
      timeline: true,
      changes: false,
      terminal: false,
      artifacts: false,
    });
    expect(DEFAULT_SURFACES).toEqual(deriveSurfaces(null));
  });

  it('后端返回空目录（CAPABILITIES=""）→ 同一份缺省，不假装有基础能力', () => {
    expect(deriveSurfaces([])).toEqual(DEFAULT_SURFACES);
  });

  it('声明为 true 的面为真；未声明的键保守取假', () => {
    const surfaces = deriveSurfaces([capability({ changes: true })]);
    expect(surfaces.changes).toBe(true);
    // 后端没写的键不许因为"没写"就当 true（保守默认的方向与后端一致）。
    expect(surfaces.terminal).toBe(false);
    expect(surfaces.artifacts).toBe(false);
  });

  it('多个已装配能力取并集：任一能产出该面即可见', () => {
    const surfaces = deriveSurfaces([
      capability({ changes: false, terminal: false }, 'a'),
      capability({ changes: true }, 'b'),
    ]);
    expect(surfaces.changes).toBe(true);
    expect(surfaces.terminal).toBe(false);
  });

  it('显式 false 压不过另一个能力的 true——但谁都没声明时仍是缺省', () => {
    expect(deriveSurfaces([capability({ chat: false, timeline: false })])).toEqual({
      chat: false, // 声明是什么就是什么；「Chat 恒存在」是**渲染策略**，见下组用例
      timeline: false,
      changes: false,
      terminal: false,
      artifacts: false,
    });
  });
});

describe('#182 AC2/AC3：中心列 tab 集', () => {
  it('全部声明为假 → 恰好只剩 Chat（它恒存在）', () => {
    const tabs = centerTabs(deriveSurfaces([capability({})]));
    expect(tabs.map((t) => t.label)).toEqual(['Chat']);
  });

  it('数据拿不到也只剩 Chat——能力永远拉不到不该让主阅读面消失', () => {
    expect(centerTabs(deriveSurfaces(null)).map((t) => t.key)).toEqual(['chat']);
  });

  it('即使能力把 chat 声明为 false，Chat 也不消失（主阅读面）', () => {
    const tabs = centerTabs(deriveSurfaces([capability({ chat: false, changes: true })]));
    expect(tabs.map((t) => t.key)).toContain('chat');
  });

  it('声明为 true 但尚无实现的面**不渲染**（不给"点了没事发生"的 tab）', () => {
    // 这条规则不依赖"恰好还有一个没实现的面"：#189 落地后中心列三个面全部有实现，
    // 所以用**注入的**未实现面（`artifacts` 属于 Inspector，不在中心列登记表里）证明
    // `centerTabs` 仍然守着它——`registry` 参数存在的理由就是这个。
    const registry: SurfaceDescriptor[] = [
      ...SURFACES,
      { key: 'artifacts', label: 'Artifacts', implemented: false },
    ];
    const surfaces = deriveSurfaces([capability({ changes: true, artifacts: true })]);
    expect(centerTabs(surfaces, registry).map((t) => t.key)).toEqual(['chat', 'changes']);
  });

  it('已实现的面如实跟随声明：为真就出现，为假就消失（#190 的「输出」）', () => {
    expect(centerTabs(deriveSurfaces([capability({ terminal: true })])).map((t) => t.key)).toEqual([
      'chat',
      'terminal',
    ]);
    expect(centerTabs(deriveSurfaces([capability({ terminal: false })])).map((t) => t.key)).toEqual([
      'chat',
    ]);
  });

  it('已实现的面如实跟随声明（#189 的「文件/改动」）：为真就出现，为假就消失', () => {
    expect(centerTabs(deriveSurfaces([capability({ changes: true })])).map((t) => t.key)).toEqual([
      'chat',
      'changes',
    ]);
    expect(centerTabs(deriveSurfaces([capability({ changes: false })])).map((t) => t.key)).toEqual([
      'chat',
    ]);
  });

  it('tab 顺序稳定：登记顺序即渲染顺序，与能力返回顺序无关', () => {
    const surfaces = deriveSurfaces([capability({ terminal: true, changes: true })]);
    expect(centerTabs(surfaces).map((t) => t.key)).toEqual([
      'chat',
      'changes',
      'terminal',
    ]);
  });
});

describe('#182：选中面失效时的落点', () => {
  const tabs = [
    { key: 'chat' as SurfaceKey, label: 'Chat' },
    { key: 'terminal' as SurfaceKey, label: '输出' },
  ];

  it('选中的面还在 → 不动', () => {
    expect(resolveActiveTab(tabs, 'terminal')).toBe('terminal');
  });

  it('选中的面消失（能力翻假）→ 回到第一个可见面，不落在空白上', () => {
    expect(resolveActiveTab([tabs[0]], 'terminal')).toBe('chat');
  });

  it('tab 集为空（理论上不会发生，Chat 恒存在）→ 仍给出确定答案', () => {
    expect(resolveActiveTab([], 'terminal')).toBe('chat');
  });
});

describe('#182 AC5：方向键的目标键（WAI-ARIA tabs 模式）', () => {
  const tabs = [
    { key: 'chat' as SurfaceKey, label: 'Chat' },
    { key: 'changes' as SurfaceKey, label: '文件/改动' },
    { key: 'terminal' as SurfaceKey, label: '输出' },
  ];

  it('← / → 前后移动并环绕', () => {
    expect(tabKeyTarget(tabs, 'chat', 'ArrowRight')).toBe('changes');
    expect(tabKeyTarget(tabs, 'changes', 'ArrowRight')).toBe('terminal');
    expect(tabKeyTarget(tabs, 'terminal', 'ArrowRight')).toBe('chat');
    expect(tabKeyTarget(tabs, 'chat', 'ArrowLeft')).toBe('terminal');
  });

  it('↑ / ↓ 同义（票面只说"方向键"，横排 tab 的上下键不该失效）', () => {
    expect(tabKeyTarget(tabs, 'chat', 'ArrowDown')).toBe('changes');
    expect(tabKeyTarget(tabs, 'changes', 'ArrowUp')).toBe('chat');
  });

  it('Home / End 跳首尾', () => {
    expect(tabKeyTarget(tabs, 'changes', 'Home')).toBe('chat');
    expect(tabKeyTarget(tabs, 'changes', 'End')).toBe('terminal');
  });

  it('与 tab 无关的键 → null（不吞掉别的按键语义）', () => {
    expect(tabKeyTarget(tabs, 'chat', 'Enter')).toBeNull();
    expect(tabKeyTarget(tabs, 'chat', 'Escape')).toBeNull();
    expect(tabKeyTarget(tabs, 'chat', 'a')).toBeNull();
  });

  it('只有一个 tab 时方向键原地不动（不越界、不返回 undefined）', () => {
    const one = [tabs[0]];
    expect(tabKeyTarget(one, 'chat', 'ArrowRight')).toBe('chat');
    expect(tabKeyTarget(one, 'chat', 'End')).toBe('chat');
  });

  it('当前键不在 tab 集里 → 从第一个算起（与 resolveActiveTab 同一口径）', () => {
    expect(tabKeyTarget(tabs, 'artifacts', 'ArrowRight')).toBe('changes');
  });
});

describe('#182：响应体解析（防御式，与 api.ts 既有口径一致）', () => {
  it('正常响应 → 条目列表', () => {
    expect(parseCapabilities({ capabilities: [capability({ changes: true })] })).toHaveLength(1);
  });

  it('形状不符 → 空列表，不抛（能力是可选供给，坏数据不该炸界面）', () => {
    expect(parseCapabilities(null)).toEqual([]);
    expect(parseCapabilities({})).toEqual([]);
    expect(parseCapabilities({ capabilities: 'nope' })).toEqual([]);
    expect(parseCapabilities({ capabilities: [1, 'x', null] })).toEqual([]);
  });

  it('缺 id 的条目被丢弃，其余保留', () => {
    const parsed = parseCapabilities({
      capabilities: [{ surfaces: { changes: true } }, capability({ terminal: true }, 'coding')],
    });
    expect(parsed.map((c) => c.id)).toEqual(['coding']);
  });

  it('surfaces 不是对象的条目按"什么都没声明"处理（缺省由 deriveSurfaces 兜）', () => {
    const parsed = parseCapabilities({ capabilities: [{ id: 'x', surfaces: 'nope' }] });
    expect(parsed).toHaveLength(1);
    expect(parsed[0].surfaces).toEqual({});
  });
});
