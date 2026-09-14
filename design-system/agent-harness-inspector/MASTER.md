# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/agent-harness-inspector/pages/[page-name].md`.
> If it exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** Agent Harness Inspector
**Generated:** 2026-09-04 (手工校正版 — 替换 ui-ux-pro-max 自动生成的 luxury/fashion 版本)
**Category:** Developer Tool / Agent Observability Console
**Design Dials:** Motion 7/10 (Standard) | Density 7/10 (Dense, dev tool)
**Visual Anchor:** Apple Liquid Glass × OLED Dark × Real-time Streaming Console

---

## 产品定位（决定下面所有取舍）

这是一个**给开发者用的 agent 运行可观测台**，不是营销落地页。核心场景：
- 用户长时间盯着屏幕看 agent 一步步干活（思考、调工具、被审批拦、给回答）
- 信息密度高（事件流、工具调用、diff、终端输出）
- 实时流式（token 逐字出来、工具状态实时变）
- 要"全透明"——每个决策可追溯

因此：
- **深色 OLED 优先**（护眼 + 玻璃质感需要深色背景才有折射层次）+ 支持浅色切换
- **代码字体是主角**（对话、工具结果、diff 大量是代码）
- **三栏 app shell**（不是滚动营销页）—— 左 sessions / 中 conversation / 右 step detail
- **液态玻璃用在 chrome 层**（面板、卡片、浮层），不用在内容文本块（会糊）

---

## Global Rules

### Color Palette（深色优先，玻璃需要深色背景）

| Role | Hex（Dark） | Hex（Light） | CSS Variable |
|------|------------|-------------|--------------|
| Background | `#0A0A0C` | `#FAFAFA` | `--color-background` |
| Surface 1（面板底） | `#131316` | `#FFFFFF` | `--color-surface-1` |
| Surface 2（卡片/浮层） | `rgba(28,28,32,0.72)` | `rgba(255,255,255,0.72)` | `--color-surface-2` |
| Surface 3（弹窗/模态） | `rgba(38,38,42,0.80)` | `rgba(255,255,255,0.86)` | `--color-surface-3` |
| Foreground（主文本） | `#F5F5F7` | `#1C1C1E` | `--color-foreground` |
| Muted Foreground | `#A1A1A6` | `#6B6B70` | `--color-muted-foreground` |
| Subtle Foreground | `#6E6E73` | `#9A9A9F` | `--color-subtle-foreground` |
| Accent（思考/模型） | `#7C9EFF` | `#5B7CFF` | `--color-accent` |
| Accent Secondary（工具） | `#7FE0B0` | `#3DAA82` | `--color-accent-secondary` |
| Success | `#7FE0B0` | `#3DAA82` | `--color-success` |
| Warning（审批请求） | `#FFD479` | `#C68B00` | `--color-warning` |
| Destructive | `#FF6B6B` | `#D93025` | `--color-destructive` |
| Border（hairline） | `rgba(255,255,255,0.08)` | `rgba(0,0,0,0.08)` | `--color-border` |
| Ring（focus） | `#7C9EFF` | `#5B7CFF` | `--color-ring` |

**配色语义**（重要 — 让用户一眼分清事件类型）：
- 🔵 蓝（accent）= 模型思考 / `model/*` 事件
- 🟢 绿（success/accent-secondary）= 工具成功 / `tool/result` ok
- 🟡 黄（warning）= 审批请求 / `approval/requested`
- 🔴 红（destructive）= 失败 / `tool/result` error / `run/failed`

**Color Notes:**
- Surface 2/3 用半透明 + `backdrop-filter: blur()` 实现 liquid glass。深色模式下 `rgba(28,28,32,0.72)` + blur(40px) saturate(1.6) 是经典组合。
- 文本永远不放在 blur 层正上方读不清的位置——玻璃用在 chrome，不用在文本块背景。
- 对比度 ≥ 4.5:1（主文本 F5F5F7 on 0A0A0C ≈ 18:1，远超）。

### Typography

**原则：UI 字体 + 代码字体，不混用 luxury 衬线。**

- **UI Font（界面）:** `Inter`（无衬线、可变字重、Apple 风的现代感首选）
- **Mono Font（代码 / 工具输出 / diff / 终端）:** `JetBrains Mono` 或 `SF Mono`（系统）
- **Mood:** technical, precise, calm, premium-quiet
- **绝不用:** Cormorant / Playfair / 衬线 luxury 字体（自动生成版的方向，已校正）

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;450;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --font-ui: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', 'Cascadia Code', monospace;
}
```

**字号阶梯**（dev tool 密度，比营销页小一档）：

| Token | Size | Line Height | Use |
|-------|------|-------------|-----|
| `--text-xs` | 11px | 1.4 | 标签、meta、时间戳、badge |
| `--text-sm` | 13px | 1.5 | 侧栏项、工具参数、次要文本 |
| `--text-base` | 14px | 1.6 | 对话流主体、UI 文本（dev tool 默认偏小） |
| `--text-md` | 15px | 1.6 | 强调段落 |
| `--text-lg` | 17px | 1.5 | 面板标题 |
| `--text-xl` | 20px | 1.4 | 空状态大标题 |
| `--text-2xl` | 28px | 1.3 | 仅空状态 hero（少用） |

**字重：** 默认 400；强调用 550（Inter 的可变字重）；标题用 600；不用 700+（太重，不 Apple）。

### Spacing Variables

*Density: 7/10 — Dense（dev tool）*

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` | 图标与文字间隙、紧凑 badge |
| `--space-sm` | `8px` | 卡片内元素间隙、列表行内 |
| `--space-md` | `12px` | 卡片 padding、面板内章节 |
| `--space-lg` | `16px` | 标准面板 padding |
| `--space-xl` | `24px` | 面板之间、主要分区 |
| `--space-2xl` | `32px` | 空状态内边距 |

### Liquid Glass Tokens（核心质感）

```css
:root {
  /* 三档玻璃 —— 用在不同的表面层级 */
  --glass-blur-1: 20px;   /* 面板底（轻） */
  --glass-blur-2: 40px;   /* 卡片 / 浮层（中，默认） */
  --glass-blur-3: 60px;   /* 模态 / 命令面板（重） */
  --glass-saturate: 1.6;  /* 关键 —— 玻璃后面颜色要被提饱和才有"折射"感 */
  --glass-brightness: 1.05;

  /* hairline 描边 —— Apple 标志性 0.5px 边 */
  --glass-border: 0.5px solid rgba(255,255,255,0.10);
  --glass-border-light: 0.5px solid rgba(0,0,0,0.06);

  /* 内层高光 —— 玻璃顶部一道环境光反射 */
  --glass-highlight: inset 0 0.5px 0 rgba(255,255,255,0.12);
}

.glass {
  background: var(--color-surface-2);
  backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-saturate)) brightness(var(--glass-brightness));
  -webkit-backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-saturate)) brightness(var(--glass-brightness));
  border: var(--glass-border);
  box-shadow: var(--glass-highlight), var(--shadow-md);
}

@supports not (backdrop-filter: blur(1px)) {
  .glass { background: var(--color-surface-1); }  /* fallback：无 blur 时退化成实色 */
}

@media (prefers-reduced-transparency: reduce) {
  .glass { backdrop-filter: none; background: var(--color-surface-1); }
}
```

### Shadow Depths（深色模式下阴影要更深）

| Token | Value | Use |
|-------|-------|-----|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.3)` | 微抬升 |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.4)` | 卡片、工具栏 |
| `--shadow-lg` | `0 8px 24px rgba(0,0,0,0.5)` | 浮层、popover |
| `--shadow-xl` | `0 16px 48px rgba(0,0,0,0.6)` | 模态、命令面板 |

### Corner Radii（Apple 式大圆角 + 可选超椭圆）

| Token | Value | Use |
|-------|-------|-----|
| `--radius-sm` | `6px` | badge、tag、小按钮 |
| `--radius-md` | `10px` | 按钮、输入框、小卡片 |
| `--radius-lg` | `14px` | 卡片、面板、对话气泡 |
| `--radius-xl` | `20px` | 模态、大面板、空状态容器 |
| `--radius-full` | `9999px` | pill 按钮、avatar |

可选（高级）：`corner-shape: superellipse(1.5)` + `@supports` 回退到普通圆角（DSH 用法，更显 Apple 质感）。

---

## App Shell Layout（三栏 — 这是 dev tool 不是营销页）

```
┌──────────────────────────────────────────────────────────────────────┐
│  Top Bar（liquid glass，薄）：app name | session meta | 模型 | 主题切换 │
├──────────┬───────────────────────────────────────┬───────────────────┤
│          │                                       │                   │
│ Left     │  Conversation（主区）                  │  Step Detail      │
│ Sessions │   ├─ Turn 1（折叠"Thought for a while"）│  当前选中 step：   │
│  ├ sess1 │   │   ├ tool: bash [终端黑卡]          │  - model 请求元数据 │
│  ├ sess2 │   │   ├ tool: edit [diff 双栏]         │  - tool args/result │
│  └ sess3 │   │   └ tool: read [折叠]              │  - retry / duration │
│          │   ├─ Turn 2（展开思考过程）             │  - checkpoint（空槽）│
│ + new    │   │   ├ model 思考（流式逐 token）      │  - artifact（空槽）  │
│          │   │   └ model 最终回答                 │                   │
│          │   └─ [流式中… ▼ 当前 turn]              │                   │
│          │                                       │                   │
│          ├─ Composer（底部 liquid glass）：        │                   │
│          │   输入任务 + 发送                       │                   │
└──────────┴───────────────────────────────────────┴───────────────────┘
```

**宽度策略**（DSH 式 concession chain）：
- Left: 240px 默认，可拖拽；窗口收窄先塌缩成 56px rail（只显图标）
- Right: 340px 默认，可拖拽；窗口收窄先塌缩成 0（隐藏）
- Middle: 弹性，永远可见，最小 480px

**面板几何是 transient**（刷新即重置，不存 localStorage）—— spec 说前端不维护第二套真相，面板偏好是 UI 状态不是业务真相。

---

## Component Specs

### Cards（工具卡片、对话气泡、面板）

```css
.card-glass {
  background: var(--color-surface-2);
  backdrop-filter: blur(var(--glass-blur-2)) saturate(var(--glass-saturate));
  border: var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-highlight), var(--shadow-md);
  transition: transform 200ms cubic-bezier(0.2,0.8,0.2,1),
              box-shadow 200ms ease;
}
.card-glass:hover { box-shadow: var(--glass-highlight), var(--shadow-lg); }
```

### Tool Cards（Phase 9/10 精简版落地形态：Activity Timeline 节点）

Phase 1 重设计后，工具卡从"左色条卡片"演进为 **act-node 时间轴节点**（更贴 DeepSeek
Harness 式 activity stream，但视觉语言保持本文件 token）：

- **节点行（act-node，默认态）**：`icon · 工具名(mono) · 参数摘要(ellipsis) · duration(tabular-nums) · 状态图标`，
  hover 浮起 `--color-hover`，`aria-expanded` 展开态同色。节点左侧一条 0.5px 极淡时间轴竖线（`--color-border`）。
- **bash**：节点行 + 展开终端内嵌块（`--terminal-bg/--terminal-fg` 跨主题恒定深底浅字，stdout 深色 mono、exit code badge 0 绿非 0 红）。
- **diff（edit/apply_patch/write）**：展开双栏"变更前/变更后"，`+` 行绿 `--color-success`、`-` 行红 `--color-destructive`，行内容 mono。
- **通用工具**：展开看完整参数 + 结果 JSON（深底 mono）。
- **状态表达**：右侧 12px 图标——✓ 绿（success）/ ✗ 红（destructive）/ spinner 黄（running）。不再使用左色条。
- **Progressive Disclosure**：默认只显节点行，点击展开详情（height + fade，240ms apple ease）。

### Approval Card（内联，按 Q14=A）

对话流里原地浮起一张 warning-yellow 玻璃卡：
- 工具名 + 参数（mono，终端深底内嵌）
- 两个按钮：批准（accent 色）、拒绝（subtle outline）
- 决策后左边条转 success 绿 / destructive 红

### Buttons

```css
.btn-primary {
  background: var(--color-accent);
  color: white;
  padding: 8px 16px;
  border-radius: var(--radius-md);
  font: 550 14px var(--font-ui);
  transition: all 180ms cubic-bezier(0.2,0.8,0.2,1);
  cursor: pointer;
}
.btn-primary:hover { filter: brightness(1.1); transform: translateY(-1px); }
.btn-primary:active { transform: translateY(0); }
```

**绝不用**：阴影外扩的 hover（廉价感）、`scale(1.05)`（layout shift）、emoji 图标。

### Inputs / Composer（Phase 1 落地：Floating Command Dock）

Composer 是"悬浮玻璃 dock"而非独立输入框：`--radius-lg` 圆角、`surface-floating`
材质、textarea 透明内嵌（右侧留出按钮位），focus-within 时边框转 accent 45% +
`--shadow-xl` + 3px accent 光晕。发送按钮 32px 圆钮内嵌右下（↑ 图标，accent 底），
运行时切换为 destructive 呼吸态停止钮（Square 图标）。

```css
.composer-dock {
  border-radius: var(--radius-lg);
  transition: box-shadow var(--dur-in) var(--ease-apple), border-color var(--dur-in) var(--ease-apple);
}
.composer-dock:focus-within {
  border-color: color-mix(in srgb, var(--color-accent) 45%, transparent);
  box-shadow: var(--edge-light), var(--shadow-xl),
    0 0 0 3px color-mix(in srgb, var(--color-accent) 16%, transparent);
}
```

---

## Motion（实时流式是核心动效）

### Token 流式逐字

模型回复用 `model/delta` 事件逐 token 追加。新 token 用浅淡 caret 闪烁 + 微 opacity 渐显（120ms）。**不要逐字弹跳**——廉价。

### Turn 折叠 / 展开

默认折叠成 "Thought for a while · 3 tools · 12s"（DSH 式），点击展开内容用 height auto + opacity 双动画（240ms cubic-bezier(0.2,0.8,0.2,1)）。

### Tool Card 状态过渡

running → success：左侧色条由 warning 黄渐变到 success 绿（300ms）。
running → failed：渐变到 destructive 红 + 轻微 shake（一次，120ms，amplitude 2px）。

### Stagger（仅空状态 / session 列表载入）

```js
gsap.from('.session-item', { opacity: 0, y: 8, duration: 0.3, stagger: 0.04, ease: 'power2.out' });
```

**绝不在数据表 / 事件流上 stagger**——用户在等数据，不要让它"表演入场"。

### 通用动效规矩

- 入场 200-300ms，退场 150ms（退场比入场快）
- 用 `cubic-bezier(0.2,0.8,0.2,1)`（Apple 标准 ease），不用 linear、不用 back.out（除列表入场）
- `prefers-reduced-motion: reduce` 时所有动效退化为 opacity-only 或直接跳到终态

---

## Style Guidelines

**Style:** Liquid Glass × OLED Dark Mode × Minimalism

**Keywords:** translucent panels, backdrop-blur, hairline borders, optical depth, system chrome, calm precision

**Key Effects:**
- `backdrop-filter: blur() saturate()` 在面板/卡片/浮层上
- 0.5px hairline borders（不是 1px，太粗）
- 内层 top-highlight（环境光反射）
- layered soft shadows（深色模式下更深）

**Best For:** 这是个长时间盯屏的 dev tool —— 玻璃给层次感和"高级"，但内容区（代码、diff、终端）保持高对比实色，不让 blur 干扰阅读。

### Anti-Patterns (Do NOT Use)

- ❌ Glass 用在正文文本块背景（糊，读不清）
- ❌ 1px 边框（用 0.5px hairline）
- ❌ Cormorant / Playfair 等 luxury 衬线（这是 dev tool，不是时尚品牌 —— 已从自动生成版校正）
- ❌ 金色 accent（自动生成版的 #A16207 —— 改成冷静的蓝 #7C9EFF）
- ❌ Scroll-triggered storytelling（自动生成版的营销 pattern —— 这是 app shell）
- ❌ Emojis as icons（用 SVG：Lucide / Heroicons）
- ❌ 缺 `cursor: pointer`
- ❌ Layout-shifting hovers（`scale(1.05)`）
- ❌ 对比度 < 4.5:1
- ❌ 瞬时状态变化（必须有 150-300ms transition）
- ❌ 看不见的 focus ring

---

## Pre-Delivery Checklist

- [ ] 无 emoji 当图标（用 SVG：Lucide / Heroicons）
- [ ] 图标集统一（不要混 Lucide + Heroicons）
- [ ] 所有可点元素 `cursor: pointer`
- [ ] hover 有 150-300ms 过渡，不 layout shift
- [ ] 文本对比度 ≥ 4.5:1（深色模式主文本 F5F5F7 on 0A0A0C ≈ 18:1 ✓）
- [ ] 键盘 focus 可见（accent 色 ring）
- [ ] `prefers-reduced-motion` 被尊重
- [ ] `prefers-reduced-transparency` 被尊重（玻璃退化成实色）
- [ ] `@supports not (backdrop-filter)` 有 fallback
- [ ] 响应式：1440（默认三栏）/ 1024（右栏隐藏）/ 768（左栏塌成 rail）/ 375（单栏 mobile，但这是 dev tool，mobile 体验降级合理）
- [ ] 三栏拖拽 + concession chain（窄窗先塌右栏、再塌左栏成 rail）
- [ ] 面板几何 transient（不写 localStorage）

---

## 与 ADR-0005 的关系

本设计系统是 ADR-0005「Q5=B 液态玻璃 / Q7=React+Radix+纯CSS」的可视化落地。技术栈、布局、数据契约见 ADR-0005；色彩、字体、动效、玻璃 token 见本文件。两者冲突时以 ADR-0005 为准（架构 > 视觉）。
