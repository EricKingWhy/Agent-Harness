---
name: Agent Harness Inspector
description: 暗色优先的 agent 运行观察仪——三栏工作台、粉色签名、克制密度
colors:
  blossom: "#f1b3ca"
  blossom-strong: "#f4a5c4"
  blossom-deep: "#c96990"
  canvas: "#0c0c0f"
  chrome: "#101014"
  workspace: "#121217"
  elevated: "#17171d"
  overlay: "#262b34"
  text-primary: "rgba(255, 255, 255, 0.92)"
  text-secondary: "rgba(255, 255, 255, 0.64)"
  text-tertiary: "rgba(255, 255, 255, 0.52)"
  success: "#6fce9e"
  warning: "#e3b565"
  danger: "#e5726f"
  info: "#7c9eff"
  terminal-bg: "#0d0d0f"
  terminal-fg: "#d4d4d4"
typography:
  display:
    fontFamily: "Inter Variable, Inter, -apple-system, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.3
  title:
    fontFamily: "Inter Variable, Inter, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.45
  body:
    fontFamily: "Inter Variable, Inter, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: "Inter Variable, Inter, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.5
  data:
    fontFamily: "JetBrains Mono Variable, JetBrains Mono, monospace"
    fontSize: "12px"
    fontWeight: 450
    lineHeight: 1.55
    fontVariantNumeric: "tabular-nums"
  micro-label:
    fontFamily: "Inter Variable, Inter, sans-serif"
    fontSize: "10px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.08em"
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "20px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  lg2: "20px"
  xl: "24px"
  2xl: "32px"
  3xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.blossom}"
    textColor: "#0c0c0f"
    rounded: "{rounded.full}"
    size: "32px"
  button-approve:
    backgroundColor: "{colors.success}"
    textColor: "#0c0c0f"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
  button-deny:
    backgroundColor: "transparent"
    textColor: "{colors.danger}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
  card-solid:
    backgroundColor: "{colors.elevated}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
  composer-dock:
    backgroundColor: "{colors.overlay}"
    rounded: "{rounded.lg}"
  session-item:
    backgroundColor: "transparent"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
---

# Design System: Agent Harness Inspector

## Overview

**Creative North Star: "The Observation Instrument（观察仪）"**

这套系统是一台**观察仪**，不是一块营销画布，也不是一个通用后台：它是开发者俯身观察一个 agent 干活时的仪表面板。暗色优先（`--surface-canvas #0c0c0f` 起，亮色经 `[data-theme='light']` 单点覆盖、双块同步维护），亮度分层取代阴影分层（canvas → chrome → workspace → elevated → overlay），信息密度是自觉选择而非偷懒。唯一的品牌签名是一道克制的淡粉（`--accent #f1b3ca`，亮色 `#c96990`）——它出现时必须意味着「这里可以交互」或「这里状态特殊」，绝不做无语义的装饰。浮层（composer / 命令面板 / popover）用玻璃材质，一切内联内容面用实心表面；终端块是「内容里的另一块屏幕」，跨主题恒定深底浅字。

**Key Characteristics:**
- 三栏结构：Session Rail | Agent Workspace | Run Inspector，<1200px Inspector 收起为开关
- 低对比 chrome、高清晰内容：面板靠色调差 + 1px 边分层，不靠阴影
- 签名组件：Run Pulse（运行生命体征胶囊）与 Trace Ladder（四档密度渐进披露）
- 动效只表达状态（呼吸=活着、pulse=联动、shimmer=流式），150-750ms，`prefers-reduced-motion` 全局兜底

## Colors

一句话：中性冷灰阶承载一切内容，一道淡粉承担全部品牌与交互信号，四个低饱和语义色只做小面积状态。

### Primary
- **Pale Blossom** (#f1b3ca，暗色；亮色用 Deep Blossom #c96990)：accent。用途白名单见 One Voice Rule——主操作按钮（发送）、选中态染底、focus 环、文本选择、Run Pulse 思考相、分叉按钮。

### Secondary
- **Success Green** (#6fce9e)：工具成功、run 完成、批准按钮。
- **Warning Amber** (#e3b565)：审批待决、运行降级提示。
- **Danger Red** (#e5726f)：失败、拒绝、错误横幅。
- **Info Blue** (#7c9eff)：重连/恢复等中性提示。语义色仅小面积（点、徽章、边、按钮），不做大面积染底（淡染 ≤10% alpha 除外）。

### Neutral
- **Canvas** (#0c0c0f)：应用画布/环境底。**Chrome** (#101014)：顶栏/Rail/Inspector。**Workspace** (#121217)：主内容区（最亮）。**Elevated** (#17171d)：内嵌卡与终端基座。**Overlay** (#262b34)：浮层。
- 文字三档：primary 0.92 / secondary 0.64 / tertiary 0.52 alpha（亮色同结构 0.92/0.62/**0.63**——UI-02 实测定值：0.55 在白底仅 4.12:1、0.60 在选中染底 4.46:1，均不达 AA）。**tertiary 不得低于 4.5:1 实测对比度。**
- 边：subtle 0.075 / strong 0.13 alpha（亮色 0.08/0.14）。
- **Terminal**（#0d0d0f 底 #d4d4d4 字）：跨主题恒定，不进主题变量组。

### Named Rules
**The One Voice Rule.** accent 只给「交互」与「状态」：hover、selected、focus、主操作、运行状态指示。**禁止**给非交互内容当语法高亮（如时间线事件类型名用中性 mono 色，不用粉）；禁止大面积铺陈。同屏粉色是信号，不是墙纸。

**The Contrast Floor Rule.** 一切可读文本（含 placeholder、元数据、注记）在**两个主题下**实测 ≥4.5:1。选 token 时看实测值，不看「看起来还行」。

## Typography

**UI Font:** Inter Variable（自托管 fontsource，wght 100-900）
**Data Font:** JetBrains Mono Variable（代码、命令、ID、seq、时长；数字一律 `tabular-nums`）

**Character:** 单一家族承担全部 UI 文字（产品 UI 不做 display/body 配对），层级靠「字号档 + 字重 + 透明度三档」三者协同，而不是透明度独扛。

### Hierarchy
- **Display** (600, 20px, 1.3)：空态标题。全 app 仅空态与弹窗标题允许 ≥17px。
- **Title** (600, 15px, 1.45)：composer 输入、区块标题。
- **Body** (400, 14px, 1.7, max 78ch)：助手正文、用户气泡。行宽受控是硬规则。
- **Label** (500, 12px, 1.5)：元数据、注记、按钮内文字、列表副行。**可读文本下限。**
- **Data** (mono, 12px, tabular-nums)：命令、路径、seq、时长、事件数。
- **Micro-label** (600, 10px, 0.08em, **仅全大写**)：面板眉标（RUN INSPECTOR 式）。10px 的唯一合法形态。

### Named Rules
**The 12px Floor Rule.** 一切需要阅读的文字 ≥12px；10px 只允许「全大写 + 字距」的 micro-label。层级靠字号档（12/13/14/15/20）参与表达，不让 11px 雾铺满全屏。

**The Contrast Floor Rule.**（见 Colors 节，两处同义同值）

## Layout

三栏骨架：Session Rail（固定宽，可折叠项目分组）| Agent Workspace（fluid，内容列 max 78ch 居中偏左）| Run Inspector（~380px，<1200px 收起为顶栏开关）。断点行为是结构性的（栏收起），不是流式排版。间距阶梯 4/8/12/16/20/24/32/40 严格执行；组内紧凑、组间疏朗，标题上方留白 > 下方。密度四档（紧凑/均衡/详细/Raw）是全局默认 + 单节点 override 的双通道。

## Elevation & Depth

**平面分层制**：深度由「表面亮度阶梯 + 1px 边」表达，主面板零阴影。阴影仅两级，且只属于浮层。玻璃（backdrop blur + saturate）是浮层专属材质。

### Shadow Vocabulary
- **Overlay** (`--shadow-overlay: 0 2px 8px rgba(0,0,0,.25)`，亮 0.08)：palette、composer 收起态等低浮层。
- **Popover** (`--shadow-popover: 0 8px 28px rgba(0,0,0,.42)`，亮 0.14)：picker 浮层、弹窗。

### Named Rules
**The Glass Only Floating Rule.** `.glass/.surface-floating` 只允许出现在浮层（composer dock、命令面板、popover、跟随浮标）。内联内容面（对话流里的卡片、审批卡、工具卡）**禁止**挂玻璃材质，也禁止出现在两级阴影体系之外的第三级辉光（如 `0 0 20px`）。

## Shapes

半径是语义阶梯不是装饰：4px chips/tags / 6px 输入与紧凑控件 / 8px 卡片与内嵌块 / 12px 浮层与 composer / 20px 仅命令面板 / full 只给小圆形控件与药丸。同尺寸同语义的圆角全 app 一致；边框语言：全周 hairline（subtle）为默认，**彩色单侧粗边条（>1px side-tab）只允许**：语义告警卡（warning/danger 实色 3px）与 accent 半透明 2px 签名条（delegation 摘要、reasoning 文本）这两类既有形态，不得新增第三类。

## Components

### Buttons
- **Shape:** 控件 6px；圆形操作（发送）full。
- **Primary（发送）:** blossom 底 + 32px 圆 + 深色图标；focus 双环挖空环（box-shadow 两环，outline none 是刻意的）。
- **Approve/Deny（审批）:** success 实底 / danger 描边，6px，高 37px，快捷键以 kbd chip 标注在按钮内。
- **Icon buttons:** 32×32 命中区，一律带 aria-label。
- 状态完备：default/hover/active/disabled/loading；disabled 不透明度降档 + cursor。

### Chips
- 控件行 picker（默认链/权限/Agent/推理）：elevated 底 + subtle 边 + 6px，icon+label+caret。
- 状态徽章（已完成/思考中/空闲）：药丸、语义色淡染底 + 实色字，Run Pulse 与普通徽章是**两种**组件不混用。

### Cards / Containers
- 实心 elevated 底 + subtle 边 + 8px + 内边距 12/16。**内联卡禁玻璃、禁第三级阴影。**
- 审批卡是唯一带语义染底的卡（warning 7% + hairline + 3px 实条，待决态；终态撤辉光收敛语义色）。

### Inputs / Fields
- composer dock 是一级浮层材质：overlay 玻璃 + 12px + focus-within 双环上浮；placeholder 三级文字色（≥4.5:1）。
- 平面输入（重命名等）：elevated 底 + subtle 边 + 6px；focus 换 accent 边。

### Navigation
- 顶栏 48px 档：左 logo+标题，中 Run Pulse，右密度四档 + icon 簇。
- Rail 分组：眉标（10px 大写）+ 计数徽章；会话项三行（标题/ID/元数据）选中粉染 8%。

### Run Pulse（签名组件）
icon + 色相 + 文字三通道表达运行相位（空闲/思考中/已完成/失败/中断），思考相呼吸辉光 750ms，真实秒数 + token 计量 + 「等待模型」诚实旁注。中断/取消中性色域，失败 danger 色域——不依赖单一颜色通道。

### Timeline（Inspector 主视图）
行 = seq(mono 三级色) + 事件类型(mono 中性色) + 注记(12px)；run 之间插分组分隔行；状态字（ok/失败）才用语义色。行 hover 显 Inspect chip，与 Inspector 双向 pulse 联动。

## Do's and Don'ts

### Do:
- **Do** 给每个交互面 hover/focus-visible/active/disabled/loading 完整状态。
- **Do** 让层级同时动用字号档、字重与透明度三档，三者至少占其二。
- **Do** 数字（seq/时长/计数）一律 mono + tabular-nums。
- **Do** 改暗色 token 时同步检查亮色块（`index.css` 双块纪律，Ticket #35）。
- **Do** 动效表达状态；一切动效过 `prefers-reduced-motion` 兜底。

### Don't:
- **Don't** 给非交互内容用 accent（One Voice Rule）。
- **Don't** 在内联内容面用玻璃、backdrop blur 或第三级阴影（Glass Only Floating Rule）。
- **Don't** 让任何可读文本低于 12px 或对比度低于 4.5:1（两主题实测）。
- **Don't** 用 `⌘` 字面符号硬编码快捷键文案；按平台显示（`src/lib/platform.ts`）。
- **Don't** 直出原始 JSON/转义字符串给用户；结构化呈现关键字段。
