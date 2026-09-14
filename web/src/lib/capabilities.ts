/** 能力声明显隐的**语义层**（#182 / PRD §3.2）。
 *
 *  数据来源：`GET /api/capabilities`（条目形状在后端 `capability/manifest.py` 定义
 *  一次，由 `web/app.py::list_capabilities` 投影）——本前端此前**零消费**，所以
 *  "能力为真的面才出现"一直是 PRD 里的一句空话。
 *
 *  **不写后端的行号**：那个端点 #193 刚被重写，行号引用当场就过期了。后端函数名 /
 *  模块名才是稳定坐标（本仓其余跨仓引用同理）。
 *
 *  分工：
 *  - 本文件是纯函数层（无 DOM、无 React）：解析响应、把声明折成"每个面是否可见"、
 *    给键盘算出目标 tab。**没有 jsdom 也能把语义钉死**。
 *  - `components/WorkspaceTabs.tsx` 只负责把 DOM 事件接到这里的决策函数上。
 */

/** 后端会声明的五个面（`capability/manifest.py::CORE_SURFACES` 的键集，**一个都不能少**）。 */
export const SURFACE_KEYS = [
  'chat',
  'timeline',
  'changes',
  'terminal',
  'artifacts',
] as const;

export type SurfaceKey = (typeof SURFACE_KEYS)[number];

export interface SurfaceDescriptor {
  key: SurfaceKey;
  /** 用户可见名。**声明键 → 名字的唯一登记处**：键是 `terminal`、名字是「输出」，
   *  两者只在这里对应一次（别处再写死字符串就会漂移）。 */
  label: string;
  /** 声明为 true 时是否已有**真实实现**。
   *
   *  未实现的面**不渲染**：渲染一个没有实现的 tab 就是"点了没事发生"——#180 已
   *  裁定这是最差一档（连"诚实占位"都算退让）。`changes` / `terminal` 的实现分别
   *  落在 #189 / #190。
   *
   *  ⚠ 接口这里改成 true **不足以**让面出现：`App.tsx` 里还要为它渲染面板内容
   *  （每个面一个 `workspace-panel-<key>`）。只改本标记会得到一个空白面板——
   *  正是这条标记想避免的形状。 */
  implemented: boolean;
  /** 与能力声明无关、恒存在的面（Chat 是主阅读面，见 `centerTabs`）。 */
  always?: boolean;
}

/** 中心列的面（登记顺序 = 渲染顺序，与后端返回顺序无关）。 */
export const SURFACES: readonly SurfaceDescriptor[] = [
  { key: 'chat', label: 'Chat', implemented: true, always: true },
  // 「文件/改动」面（#189 已实现）：`implemented: true` 与 App.tsx 里 `changes` 分支的
  // `<ChangesPanel>` 是**成对**的——少任何一半都会得到一个空面板。
  { key: 'changes', label: '文件/改动', implemented: true },
  // 「输出」面（#190 已实现）：`implemented: true` 与 App.tsx 里 `terminal` 分支的
  // `<OutputPanel>` 是**成对**的——少任何一半都会得到一个空面板。
  { key: 'terminal', label: '输出', implemented: true },
];

/** 保守缺省（PRD §3.2，与后端 `capability/manifest.py` 里未声明 `surfaces` 的条目
 *  取同一份缺省）：能力数据拿不到时用。
 *  `timeline` 是 Inspector 的面，这里保留它是为了**如实反映声明全集**——
 *  本批中心列只消费其中的 `chat` / `changes` / `terminal`。 */
export const DEFAULT_SURFACES: Readonly<Record<SurfaceKey, boolean>> = {
  chat: true,
  timeline: true,
  changes: false,
  terminal: false,
  artifacts: false,
};

/** `GET /api/capabilities` 的条目（解析后形态）。
 *
 *  只保留**真的会被消费**的字段：`surfaces` 是显隐的唯一依据，`id` 是条目身份
 *  （单测与排错用）。后端的 `display_name` / `version` / `provider_name` / `actions`
 *  本批一律不读——解析进来当摆设只会让人以为它们在某处生效。 */
export interface CapabilityDescriptor {
  id: string;
  surfaces: Partial<Record<SurfaceKey, boolean>>;
}

/** 响应体解析：**防御式**，坏数据一律降级成空列表（能力是可选供给，不该炸界面）。
 *  与 `api.ts` 的 `getModels` 同一口径：只认得出形状的字段，其余丢弃。 */
export function parseCapabilities(body: unknown): CapabilityDescriptor[] {
  const raw =
    typeof body === 'object' && body !== null
      ? (body as { capabilities?: unknown }).capabilities
      : undefined;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    if (typeof entry !== 'object' || entry === null) return [];
    const r = entry as Record<string, unknown>;
    if (typeof r.id !== 'string' || !r.id) return [];
    const surfaces: Partial<Record<SurfaceKey, boolean>> = {};
    if (typeof r.surfaces === 'object' && r.surfaces !== null) {
      const s = r.surfaces as Record<string, unknown>;
      for (const key of SURFACE_KEYS) {
        // 只认布尔：字符串 "true" / 1 之类都不是契约（保守取假）。
        if (typeof s[key] === 'boolean') surfaces[key] = s[key];
      }
    }
    return [{ id: r.id, surfaces }];
  });
}

/** 能力列表 → 每个面是否可见。
 *
 *  - 列表为空 / 拿不到 → PRD 缺省语义（chat + timeline），**不假装有基础能力**；
 *  - 多能力 → **并集**：只要装配进来的某个能力能产出该面，这个会话就能产出它
 *    （PRD §6.3 "Visible when the active capability/session can produce …"）。
 *    前端没有"当前能力"这一概念（后端不暴露），所以不做挑一个能力再读它的声明——
 *    那会凭空发明一个后端没有的语义；
 *  - 未声明的键 → false（缺省**只用于整份数据不可得**，不用于补齐单个条目）。

 *  注意本函数如实反映声明本身：能力若显式声明 `chat:false`，这里就是 false。
 *  「Chat 恒存在」是**渲染策略**，只写在 `centerTabs` 里（单一事实源）。
 */
export function deriveSurfaces(
  capabilities: readonly CapabilityDescriptor[] | null | undefined,
): Record<SurfaceKey, boolean> {
  if (!capabilities || capabilities.length === 0) return { ...DEFAULT_SURFACES };
  const out = { chat: false, timeline: false, changes: false, terminal: false, artifacts: false };
  for (const capability of capabilities) {
    for (const key of SURFACE_KEYS) {
      if (capability.surfaces[key] === true) out[key] = true;
    }
  }
  return out;
}

/** 中心列的 tab 集：登记顺序即渲染顺序。
 *
 *  规则（AC2/AC3）：`always` 的面恒在；其余面要么被声明为 true **且**已有实现，
 *  要么不出现。`registry` 可注入只是为了单测能验证"实现落地后立刻出现"这条形状，
 *  生产调用不传。
 */
export function centerTabs(
  surfaces: Readonly<Record<SurfaceKey, boolean>>,
  registry: readonly SurfaceDescriptor[] = SURFACES,
): SurfaceDescriptor[] {
  return registry.filter((s) => (s.always === true || surfaces[s.key] === true) && s.implemented);
}

/** 选中的面若已不可见（能力翻假），落回**第一个可见面**——绝不留在空白面板上。
 *  tab 集理论上有 Chat 就非空；空集仍给确定答案，免得调用方多写一层兜底。 */
export function resolveActiveTab(
  tabs: readonly { key: SurfaceKey }[],
  active: SurfaceKey,
): SurfaceKey {
  return tabs.some((t) => t.key === active) ? active : (tabs[0]?.key ?? 'chat');
}

/** 键盘事件 → 应当激活的 tab 键（WAI-ARIA tabs 的 roving focus 语义）。
 *
 *  `←/→` 是横排 tab 的标准键；`↑/↓` 一并支持（票面只说"方向键"，横排下不该失效）。
 *  与 tab 无关的键返回 `null`——组件据此**不 preventDefault**，不吞掉别的按键语义。
 */
export function tabKeyTarget(
  tabs: readonly { key: SurfaceKey }[],
  active: SurfaceKey,
  key: string,
): SurfaceKey | null {
  if (tabs.length === 0) return null;
  const at = Math.max(
    0,
    tabs.findIndex((t) => t.key === active),
  );
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return tabs[(at + 1) % tabs.length].key;
    case 'ArrowLeft':
    case 'ArrowUp':
      return tabs[(at - 1 + tabs.length) % tabs.length].key;
    case 'Home':
      return tabs[0].key;
    case 'End':
      return tabs[tabs.length - 1].key;
    default:
      return null;
  }
}
