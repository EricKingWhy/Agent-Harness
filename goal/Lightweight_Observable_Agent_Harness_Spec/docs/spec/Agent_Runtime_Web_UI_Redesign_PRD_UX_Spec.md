# Agent Runtime Web UI Redesign — PRD + UX Specification

> **文档用途**：本文件作为后续 SDD（Spec-Driven Development）的上游产品/交互规格。后续前端 AI 应先基于本文件继续 `grill-me` 澄清实现细节，再生成正式 Spec / Tickets，之后按 Ticket 小步实现并逐步 Code Review。
>
> **核心原则**：本轮是 **UI/UX 重构，不是业务功能重写**。现有 Session、Run、Tool Call、Trace、Raw Event、密度模式、Inspector、主题切换等能力原则上全部保留；重点重构 **信息呈现模型、视觉语言、折叠/展开交互、层级关系和运行态体验**。

---

## 0. 文档状态

- 状态：需求冻结版（可进入 SDD 二次澄清）
- 优先级：P0
- 目标平台：Desktop Web First
- 主要分辨率：1280 / 1440 / 1600 / 1920 px
- 主要用户：
  1. 普通 Agent 使用者：希望简单、清晰、快速完成任务
  2. Agent 开发者 / 调试者：希望看到完整 Runtime、Tool、Trace、Input/Output/Raw
- 产品定位：**默认简洁使用体验 + 一键进入深度 Debug 体验**

---

# 1. 产品愿景

本项目不是普通 Chat UI，也不是普通后台 Dashboard。

它应同时具备四种能力：

1. **ZCode 式 Continuous Agent Stream**：中间主区像一条连续、自然、可折叠的 Agent 工作流，而不是散乱日志。
2. **DeepSeek Harness 式 Runtime Inspector**：右侧 Inspector 是产品核心亮点，必须比中间主区更详细、更工程化、更适合 Debug。
3. **Linear / Raycast 式信息层级**：高信息密度，但不拥挤、不混乱、不靠大量 Card 堆叠。
4. **Apple-level polish**：排版、间距、控件、状态、动效、边缘、材质和反馈都要精细。

最终体验应让用户依次产生以下感受：

> 第一眼：**“这不是普通开源 Agent Demo。”**
>
> 第二眼：**“这个 Agent 的运行过程非常透明。”**
>
> 第三眼：**“信息很多，但是完全不乱。”**
>
> 第四眼：**“像一个真正成熟的 AI Developer Tool。”**

---

# 2. 已冻结的产品决策

以下决策视为本轮硬约束，除非后续 SDD grill-me 明确重新推翻，否则不得擅自改变。

| 编号 | 决策 | 冻结结果 |
|---|---|---|
| D1 | 右侧 Run Inspector | **保留常驻能力，且是项目特色；信息必须比中间更详细** |
| D2 | 紧凑 / 均衡 / 详细 / Raw | **全部保留** |
| D3 | 中间主区架构 | **ZCode 式 Continuous Agent Stream**；右侧承担 Harness 式 Runtime Debugger |
| D4 | Tool 默认展示 | **按 Tool 类型智能决定** |
| D5 | Progressive Disclosure | **必须做多层渐进式展开** |
| D6 | 失败 Tool | **默认不强制全部展开；与普通 Tool 一样保持可控折叠** |
| D7 | 思考状态 | **保留“思考 / 持续时间 / 状态摘要”，但不得暴露私有 Chain of Thought** |
| D8 | Skill / MCP / Subagent | **全部成为一等 Runtime Event** |
| D9 | Todo / Plan | **原生显示，类似 ZCode 的轻量任务进度块** |
| D10 | Inspector 打开方式 | **保留现有顶部按钮：点击打开 / 收起右栏** |
| D11 | Inspector 现有能力 | **全部保留，不能删减** |
| D12 | Runtime 图标 | **取消重复统一圆形 Agent 图标；按事件类型使用语义图标** |
| D13 | 视觉方向 | **Apple / ZCode：干净背景、少 Card、靠 typography + spacing + hairline 组织** |
| D14 | 信息密度 | **接近 ZCode 当前密度** |
| D15 | 顶部栏 | **功能全部保留，只做美化和层级优化** |
| D16 | 用户消息 | **保留右侧轻量 prompt surface / 气泡** |
| D17 | 最终回答 vs Runtime | **最终回答高对比；Runtime Stream 低对比** |
| D18 | Code/Shell/JSON 展开 | **高级 Code Surface：高亮、复制、换行、滚动、全屏/放大** |
| D19 | Command Palette | **本轮加入** |
| D20 | 产品服务对象 | **默认简洁体验 + 一键 Debug 深度** |

---

# 3. 当前 UI 的核心问题

当前 UI 的问题不是“配色不好看”这么简单，而是 **信息组织模型不够自然**。

## 3.1 中间主区过于像“结构化日志”

当前 Tool Call、bash、write、模型输出等大量内容并列展示，事件之间虽然清楚，但缺少“叙事关系”。

问题表现：

- 同一种圆形 Agent 图标重复出现，形成视觉噪音。
- Tool Call 更像表格/日志，而不是 Agent 正在做什么。
- Input / Output / Raw 一旦展开，立即变成大块工程数据，占据主工作区。
- 用户难以一眼区分：
  - Agent 正在思考
  - 正在查询
  - 正在调用 Tool
  - 正在运行子 Agent
  - 正在汇报最终答案

## 3.2 右侧 Inspector 有价值，但“主次关系”还不够高级

右栏是本项目的核心特色，因此不能弱化。但当前右栏视觉上更像 Debug 数据面板，尚未形成成熟 Inspector 的产品感。

主要问题：

- Trace / event 列表视觉优先级过高且过于同质。
- event_type、模型名、Tool 名、结果状态之间层级不足。
- 失败状态、选中状态、active event 的视觉反馈不够细腻。
- Raw JSON 很强，但缺少围绕 Raw 的导航、摘要、定位和关联信息。

## 3.3 顶部“紧凑 / 均衡 / 详细 / Raw”是有价值的，但目前像 Debug Toolbar

这四种模式本身应保留，但需要从“4 个外观按钮”升级成真正的 **Display Density / Debug Depth Control**。

模式之间不仅要改变“展开多少”，还应明确：

- 主区信息密度
- Tool 默认展开策略
- Runtime 摘要层级
- Inspector 默认展开深度
- Raw 数据是否进入主视图

## 3.4 缺少 ZCode 式的“过程语义”

用户提供的 ZCode 参考图中，有几个非常关键的设计细节：

- **思考**：脑图标 + 持续时间
- **查询**：放大镜 + 文件数
- **终端**：终端图标 + 命令摘要
- **技能**：Skill 图标 + skill 名称
- **MCP**：插件/连接器式图标 + 动作名称
- **子智能体**：Agent 图标 + 类型 + 子任务
- **待办**：Todo 图标 + 当前进度 + 可展开 checklist

这些不是单纯“可爱图标”，而是 **把 Runtime Event 变成了人能读懂的动作语言**。

本项目必须实现这一层。

---

# 4. 新的信息架构

页面保留现有三大区域，但重新定义职责。

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Top Bar / Global Controls                                           │
│ Run ID · Status · Compact · Balanced · Detailed · Raw · Inspector… │
├───────────────┬───────────────────────────────────┬─────────────────┤
│ Session       │ Continuous Agent Stream           │ Run Inspector   │
│ Navigator     │                                   │                 │
│               │ User Prompt                       │ Runtime Timeline│
│               │ Thinking / Search / Skill / MCP   │ Event Detail    │
│               │ Tool / Todo / Subagent / Answer   │ Input / Output  │
│               │                                   │ Raw / Metadata  │
├───────────────┴───────────────────────────────────┴─────────────────┤
│ Floating Composer                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

## 4.1 中间主区的职责

中间主区回答：

> **Agent 正在做什么？**

它必须：

- 人类可读
- 连续
- 有叙事感
- 默认简洁
- 可按事件展开
- 保留足够开发者信息，但不淹没用户

## 4.2 右侧 Inspector 的职责

右侧回答：

> **Agent Runtime 到底发生了什么？**

它必须：

- 比中间更详细
- 有完整 event timeline
- 有 Tool Input / Output
- 有 Raw event
- 有 seq / event_id / run_id / step_id / tool_call_id
- 有模型信息、token、duration、状态
- 有事件关联
- 有复制 / 定位 / 跳转能力

中间和右栏不是重复，而是 **两个不同抽象层级**。

---

# 5. Continuous Agent Stream — 中间主区规格

## 5.1 事件分类

中间主区至少支持以下一等事件类型：

1. User Message
2. Agent Thinking / Progress
3. Search / Read
4. Tool Call
5. Tool Result
6. Skill Invocation
7. MCP Invocation
8. Subagent Start / Running / Completed
9. Todo / Plan
10. Model Call（按密度模式显示）
11. System / Runtime Notice
12. Error / Warning
13. Final Answer

未来 Capability、Memory、RAG、Checkpoint、Replay 等也应能复用这一事件系统。

---

## 5.2 事件视觉语义

### Thinking / Progress

图标：**脑 / brain**

示例：

```text
🧠 思考 · 持续了 3 秒
```

可选第二行安全摘要：

```text
正在分析当前代码修改范围
```

**禁止**显示模型私有 Chain of Thought 原文。

允许显示：

- 用户可理解的阶段摘要
- Planner 输出的结构化步骤名称
- Runtime 已公开的 progress event
- “分析代码 / 检查测试 / 验证页面 / 整理结果”等动作级摘要

### Search / Read

图标：**放大镜**

示例：

```text
⌕ 查阅 · 3 文件
```

展开后可显示：

```text
AGENTS.md
src/runtime/tool_executor.py
web/components/RunInspector.tsx
```

### Terminal / Bash

图标：**Terminal**

默认：

```text
▣ 终端   npm run test
```

或者：

```text
▣ bash   sleep 25                                       10.0s
```

### Skill

图标：**魔棒 / sparkle / skill**

```text
✦ 技能   code-review
```

### MCP

图标：**plug / connector**

```text
⌁ MCP   Chrome DevTools · Take screenshot
```

### Subagent

图标：**robot / agent**

```text
▣ 子智能体   general-purpose · Standards review
```

### Todo / Plan

图标：**checklist**

```text
☷ 待办   UI 验收 1/5
```

展开：

```text
✓ 收集改动范围
→ 浏览器活体验收 UI 效果
○ Standards + Spec 评审
○ vitest + tsc + lint
○ 聚合评审报告
```

### Error

使用轻量错误图标 + 文本状态，不要满屏红。

```text
× bash   sleep 25
  TIMEOUT · 10.0s
```

失败 Tool **不自动强制完全展开**，但必须有清晰的错误摘要。

---

# 6. Progressive Disclosure — 渐进式展开模型

本项目必须从“整个页面切换显示密度”升级为“全局密度 + 局部事件展开”双层模型。

每个事件至少有以下四层：

## L0 — Summary Row

默认可见。

内容：

- 语义图标
- 事件类型
- 一句话动作摘要
- duration
- status

例如：

```text
✓  ▣ bash   npm run test                                 1.24s
```

## L1 — Inline Detail

点击事件展开。

可能显示：

- Input 摘要
- Output 摘要
- 文件列表
- Tool 参数
- 搜索结果摘要
- Model usage 摘要

## L2 — Advanced Inline Surface

再次展开 / 点击 “View details”。

显示：

- 完整 Input
- 完整 Output
- Terminal output
- Code diff
- JSON tree

## L3 — Inspector / Raw Debug

点击 “Inspect” 或右侧 Inspector 中定位事件。

显示：

- 完整 Raw event
- event_id
- seq
- timestamp
- session_id
- run_id
- step_id
- tool_call_id
- 相关 model event
- 相关 result event

### 规则

- 手动展开状态优先于全局模式。
- 用户手动展开后，切换 Compact/Balanced/Detailed 不应无故丢失当前选中事件。
- 失败事件保持折叠，但 L0 必须显示清晰错误摘要。
- 大输出必须 max-height + 内部滚动，不得无限撑高主页面。

---

# 7. 四种显示模式重新定义

四种模式全部保留，但要定义清晰语义。

## 7.1 紧凑 Compact

目标：快速扫一眼 Agent 在干什么。

默认：

- Thinking：单行
- Search：单行
- Skill：单行
- MCP：单行
- Tool：单行
- Todo：折叠
- Model Call：默认隐藏或合并成 Runtime meta
- Final Answer：正常完整显示

适合：普通用户 / 长任务快速浏览。

## 7.2 均衡 Balanced（推荐默认）

目标：兼顾“好看”和“可观察”。

默认：

- Thinking：单行 + 可选短摘要
- Search：单行，可展开文件
- Tool：单行 + 关键参数摘要
- Tool Result：成功结果默认收起；失败显示错误摘要
- Skill / MCP / Subagent：单行 + 状态
- Todo：显示当前进度，可展开
- Model Call：在需要时显示模型 + token + duration 摘要

## 7.3 详细 Detailed

目标：开发者直接在中间主区进行大部分 Debug。

默认：

- Tool Input / Output 展开到 L1
- Search 文件列表可直接显示
- Model Call 显示 token / latency
- Skill/MCP 参数摘要显示
- Subagent 状态显示
- Todo 默认展开

但仍不等于 Raw。

## 7.4 Raw

目标：原始调试视图。

中间主区允许直接展示 Raw event block，但仍需：

- syntax highlight
- JSON tree / fold
- copy
- max-height
- 事件边界清晰

右侧 Inspector 仍然保留，而且可以比中间 Raw 更完整。

---

# 8. 右侧 Run Inspector — 核心特色规格

## 8.1 产品地位

Run Inspector 是本项目的差异化亮点，不能被降级成辅助面板。

它必须比中间主区：

- 更详细
- 更稳定
- 更适合工程排错
- 更适合查看事件关联
- 更适合长期观察完整运行链

---

## 8.2 Inspector 顶部区域

保留：

- `RUN INSPECTOR`
- Run 状态（成功 / 失败 / Running）
- Run ID
- Inspector close/toggle
- 当前选中 event 类型

视觉要求：

- 使用 typography + hairline 分区
- 不做笨重 KPI 卡片
- 失败状态使用低饱和红 + 轻背景，不使用强烈实心红块

---

## 8.3 Runtime Timeline

Timeline 是 Inspector 的核心。

示例：

```text
0  session/started
1  user/message      运行 bash 命令 sleep 25
2  run/started
3  model/completed   qwen3.8-flash · 2162 tokens
4  tool/call         bash { command: "sleep 25" }
5  tool/result       TIMEOUT
6  model/completed   qwen3.8-flash · 2510 tokens
7  tool/call         bash { command: "date +%s ..." }
8  tool/result       ok
...
```

优化要求：

- seq 独立列，弱对比
- event type 使用 monospace + accent
- 摘要使用正常 UI 字体或浅 mono
- 当前选中 event 有明确但克制的 active state
- error event 可使用红色小点 / 红色 event type
- tool/call 与 tool/result 通过视觉关联表现为一组
- model/completed 可显示模型名、token、latency

### 事件配对

如果数据允许，必须支持：

- tool/call ↔ tool/result
- model/start ↔ model/completed
- subagent/start ↔ subagent/completed

通过：

- 相同 tool_call_id
- step_id
- span_id / trace_id

实现逻辑关联。

---

## 8.4 Inspector 详情层

Inspector 详情至少包含：

- Overview
- Input
- Output
- Raw

如果现有项目还有其他内容，全部保留。

### Overview

展示：

- event type
- status
- duration
- timestamp
- seq
- step id
- tool name / model
- token usage

### Input

Tool 参数 / Model Input / MCP 参数。

### Output

Tool Result / Model summary / error。

### Raw

完整事件。

Raw 支持：

- JSON tree fold
- syntax highlight
- copy object
- copy path
- copy event id
- wrap toggle
- expand all / collapse all（可放进更多菜单）

---

# 9. Inspector 与中间主区联动

这是本轮必须做好的高级体验。

## 9.1 从中间定位 Inspector

中间任意 Tool / Skill / MCP / Subagent 事件：

- hover 显示 `Inspect`
- 点击后：
  1. 如 Inspector 关闭，则打开
  2. Timeline 自动定位对应 event
  3. 右侧高亮该 event
  4. 详情区显示对应内容

## 9.2 从 Inspector 反向定位中间

右侧点击某 event：

- 中间主区滚动到对应 Agent Stream 事件
- 使用短暂 highlight / pulse，持续约 600–900ms
- 不做夸张动画

## 9.3 选中状态

“选中事件”与“展开事件”是两个状态，不能混为一谈。

- 展开：控制中间 inline detail
- 选中：控制 Inspector 当前上下文

---

# 10. 图标系统

## 10.1 原则

不再给所有 Runtime Event 重复一个大圆形 Agent 图标。

每一种事件使用固定语义图标。

## 10.2 建议映射

| Event | Icon 方向 |
|---|---|
| Thinking | Brain |
| Search / Read | Search / Magnifier |
| Terminal / Bash | Terminal |
| Tool generic | Wrench |
| Write/Edit | Pencil / File Edit |
| Skill | Sparkles / Wand |
| MCP | Plug / Connector |
| Subagent | Bot / Agent |
| Todo | List Checks |
| Model | Spark / CPU / Model |
| Error | Circle X / Triangle Alert |
| Success | Check |
| Memory | Database / Layers |
| RAG | Book / Search |

## 10.3 视觉要求

- 图标 16–18px 为主
- stroke 宽度统一
- 默认灰色
- 仅状态/类型必要时使用 accent
- 图标和事件类型之间留稳定间距
- 不要每行再套圆形底座

---

# 11. 用户消息与最终回答

## 11.1 User Prompt

保留右侧轻量气泡 / prompt surface。

要求：

- 边框极细
- 背景比页面略深/浅一级
- 不要 ChatGPT 大气泡感
- 最大宽度建议 60–72%
- 字号与正文一致或略大

## 11.2 Final Answer

Final Answer 必须从 Runtime Stream 中“跳出来”。

方式：

- Runtime Event：低对比度、偏工程 UI
- Final Answer：正常高对比正文
- Markdown 标题、列表、code block 做完整排版
- 不给整个回答套大 Card

---

# 12. Todo / Plan 组件

这是本轮 P0。

## 12.1 Header

```text
☷ 待办   浏览器活体验收 UI 效果   1/5   ▾
```

## 12.2 Item 状态

- `✓` completed
- `→` current
- `○` pending
- `×` failed

## 12.3 视觉

参考 ZCode：

- 整体是一块很轻的 surface
- 不要重边框
- 当前项文字权重更高
- completed 可轻微 strike-through
- pending 降低对比度

---

# 13. Tool / Terminal / Code Surface

## 13.1 Tool Row

统一结构：

```text
[status] [icon] [tool-name] [summary / path / command]                [duration]
```

示例：

```text
✓  🔧 write   秋天的三个意象.md                              1ms
✓  ▣ bash    python3 -c "..."                              1ms
×  ▣ bash    sleep 25                                      10.0s
```

## 13.2 展开后的 Input / Output

采用标签化 section：

```text
INPUT
{ ... }

OUTPUT
{ ... }
```

视觉要求：

- label 使用 11–12px mono uppercase
- 内容区 13–14px mono
- 背景轻微分层
- 允许 copy
- max-height
- 内部滚动

## 13.3 Terminal

终端输出可保留浅色页面中的白色 surface，也可深色模式采用深色 surface。

必须支持：

- monospace
- copy command
- copy output
- wrap / no-wrap
- horizontal scroll（仅 no-wrap）
- full-screen / enlarge（建议）

---

# 14. 顶部栏

现有功能全部保留，只优化视觉和交互层级。

## 14.1 必须保留

- Run ID
- Run status
- Compact
- Balanced
- Detailed
- Raw
- Inspector toggle
- Theme toggle
- 其他现有图标/功能

## 14.2 视觉

模式切换使用 segmented control：

```text
[ 紧凑 | 均衡 | 详细 | Raw ]
```

要求：

- active tab 使用内嵌 surface
- 非 active 透明
- 外层有 subtle border
- 不使用强主题色填充

Inspector toggle：

- 保留现有类似“侧栏”图标
- Active 时使用 accent outline / subtle tint
- 点击后右栏平滑展开/收起

---

# 15. Command Palette

本轮加入。

快捷键：

- Windows/Linux：`Ctrl + K`
- macOS：`⌘ + K`

第一期命令至少包括：

- Toggle Run Inspector
- Switch to Compact
- Switch to Balanced
- Switch to Detailed
- Switch to Raw
- Search Runtime Events
- Jump to Latest Event
- Copy Run ID
- Copy Trace ID（若存在）
- Toggle Theme
- Focus Composer

视觉参考：Raycast / Linear。

要求：

- 中心浮层
- 高级但克制
- 支持 fuzzy search
- keyboard-first
- backdrop blur 只用于该浮层区域

---

# 16. 视觉设计系统

## 16.1 基础方向

核心不是“液态玻璃铺满页面”，而是：

> **Clean Surface + Typography + Spacing + Hairline + Selective Glass**

即：

- 主工作区：干净实色背景
- Sidebar / Inspector：轻微色差形成层级
- Top Bar / Composer / Command Palette：可以有少量半透明或 glass 质感
- 不允许满屏重度 blur

## 16.2 Light Mode

建议层级：

- Canvas：#FAFAFA / #F8F8F8 附近
- Main surface：接近白
- Sidebar / Inspector：比主区深 1 个层级
- Hairline：低对比 neutral
- Primary text：高对比深灰
- Secondary：中性灰
- Tertiary：更浅灰

注意：实际色值应通过现有主题系统和视觉验收微调，不要求机械照抄上述值。

## 16.3 Dark Mode

禁止纯黑 + 纯白。

需要：

- Canvas dark
- Surface dark
- Elevated surface
- Hover surface
- Active surface

至少 4 层。

## 16.4 Accent

Accent 颜色主要用于：

- active inspector toggle
- selected timeline event
- links
- tool/event type 小范围强调
- focus ring

页面 85%+ 应保持 neutral。

---

# 17. Typography

UI 字体：

```css
-apple-system,
BlinkMacSystemFont,
"Segoe UI",
Inter,
sans-serif
```

代码字体：

```css
"JetBrains Mono",
"SFMono-Regular",
Consolas,
monospace
```

建议层级：

- 12px：meta / label
- 13px：runtime secondary
- 14px：runtime primary
- 15–16px：正文
- 18px：section heading

要求：

- runtime event 可大量使用 13–14px
- 最终回答保持更舒适的 15–16px
- duration / token / seq 使用 tabular-nums

---

# 18. Spacing / Radius / Hairline

## 18.1 Spacing Token

```text
4 / 8 / 12 / 16 / 20 / 24 / 32 / 40
```

## 18.2 Radius

- 微型控件：8
- Segmented control item：8–10
- User prompt：12–16
- Composer：16–20
- Command palette：18–22

不要所有东西统一一个巨大圆角。

## 18.3 Hairline

优先通过：

- 1px 低对比分隔
- spacing
- background tone

组织层级。

少用完整 Card border。

---

# 19. Motion

动效允许精致，但必须服务于状态变化。

## P0 Motion

- Inspector 展开/收起：220–280ms
- Event inline expand：160–220ms
- Todo expand：160–220ms
- Selected event highlight：600–900ms fade
- Command palette：120–180ms opacity + scale
- Composer focus：120–160ms elevation / border transition

## 性能原则

- 优先 transform / opacity
- 不在长列表的每一行做复杂进入动画
- 不对大面积区域持续 blur animation
- 支持 `prefers-reduced-motion`

---

# 20. 性能预算

这次 UI 可以变漂亮，但不得牺牲 Agent Runtime 的可用性。

## 20.1 目标

- 切换四种模式：主线程不出现明显卡顿
- Inspector 打开：视觉响应即时
- 100+ Runtime Event：滚动保持流畅
- 大 Raw JSON：不得一次全部渲染复杂树
- 长 Tool Output：按需渲染

## 20.2 必须执行

- 长事件列表 virtualization 或窗口化策略
- JSON tree lazy expand
- Tool advanced detail lazy mount
- 仅展开事件渲染 heavyweight component
- memoize event row
- 避免每次 token / runtime update 导致整个页面重渲染
- backdrop-filter 严格限制

## 20.3 推荐性能门槛

前端 AI 在实现阶段应自行设立测量基线，至少比较改造前后：

- First render
- Event append latency
- 100 / 500 event scroll
- Inspector toggle latency
- Detailed/Raw switch latency

如果无法量化，也至少用 React Profiler / browser performance 检查明显回归。

---

# 21. 响应式

Desktop First。

## >= 1440

- Sidebar + Main + Inspector 三栏
- Inspector 默认宽度建议 320–420px

## 1280–1439

- Sidebar 可缩窄
- Inspector 维持可用宽度
- Main 仍优先保证正文可读

## < 1280

本轮至少保证不崩坏：

- Sidebar 可 collapse
- Inspector 可 overlay / drawer 化
- Top toolbar 可收紧

不要求完整移动端产品化。

---

# 22. Accessibility

必须：

- keyboard navigation
- aria-label
- visible focus ring
- icon-only button tooltip
- 不仅靠颜色表达状态
- reduced motion
- 文字对比度合格
- Segmented control 可键盘切换
- Command palette keyboard-first

---

# 23. 组件架构建议

建议至少拆分：

```text
AppShell
  TopBar
  SessionSidebar
  AgentWorkspace
    UserPrompt
    RuntimeStream
      RuntimeEventRow
      ThinkingEvent
      SearchEvent
      ToolEvent
      SkillEvent
      MCPEvent
      SubagentEvent
      TodoEvent
      ModelEvent
      ErrorEvent
      FinalAnswer
    Composer
  RunInspector
    InspectorHeader
    RuntimeTimeline
    TimelineEventRow
    EventDetailPanel
      OverviewTab
      InputTab
      OutputTab
      RawTab

CommandPalette
CodeSurface
JsonTree
TerminalSurface
CopyButton
ExpandableSection
```

同时建立统一：

```text
design-tokens
runtime-event-icons
motion-tokens
surface-tokens
typography-tokens
```

---

# 24. 数据 / 状态模型要求

为了避免 UI 改造反向污染业务逻辑，建议新增纯展示层 ViewModel。

例如：

```ts
interface RuntimeEventViewModel {
  id: string
  seq?: number
  kind: RuntimeEventKind
  title: string
  summary?: string
  status: 'idle' | 'running' | 'success' | 'error' | 'warning'
  durationMs?: number
  timestamp?: string
  toolName?: string
  modelName?: string
  tokenUsage?: TokenUsage
  input?: unknown
  output?: unknown
  raw?: unknown
  relatedEventIds?: string[]
  stepId?: string | number
  toolCallId?: string
}
```

原则：

- 后端协议不因 UI 重构被随意改变
- 优先由 Adapter / selector 把原始 event 转成 UI ViewModel
- Raw 数据永远保留

---

# 25. Event Rendering Registry

建议不要在一个巨大 switch 中硬编码所有事件。

可以设计：

```ts
const runtimeEventRenderers = {
  thinking: ThinkingEvent,
  search: SearchEvent,
  tool_call: ToolEvent,
  tool_result: ToolEvent,
  skill: SkillEvent,
  mcp: MCPEvent,
  subagent: SubagentEvent,
  todo: TodoEvent,
  model: ModelEvent,
  error: ErrorEvent,
}
```

未来 Memory / RAG / Checkpoint 等只需注册新 renderer。

---

# 26. UX 状态机

至少明确以下状态：

## Inspector

```text
closed
open + no selection
open + selected event
```

## Runtime Event

```text
collapsed
expanded-L1
expanded-L2
selected
selected + expanded
```

## Tool

```text
idle
running
success
error
```

## Todo

```text
collapsed
expanded
```

## Command Palette

```text
closed
open
searching
executing
```

---

# 27. 空状态 / Loading / Running

## Empty Session

不要空白页。

显示：

- 简洁欢迎区域
- Composer
- 可选少量快捷动作

## Agent Running

Timeline / Stream 中需要：

- Running event 有 subtle pulse / spinner
- 不使用夸张 loading animation

## Waiting

显示：

```text
等待 Tool 返回…
```

或对应 Runtime 状态。

---

# 28. 错误体验

错误不是“整块红 Card”。

原则：

- 红色只用于关键状态
- 错误事件摘要清晰
- Raw 错误信息可展开
- Inspector 中可快速定位错误 event
- Timeline 提供 error marker

例：

```text
×  bash   sleep 25
   TIMEOUT · 10.0s
```

---

# 29. 禁止事项

以下行为视为需求违背：

1. 删除右侧 Inspector
2. 弱化 Inspector，使其比中间信息更少
3. 删除 Compact / Balanced / Detailed / Raw
4. 修改后端 API 只为迁就 UI
5. 用大量 Card 包裹所有 Runtime Event
6. 全页面重度 Liquid Glass
7. 大面积蓝紫渐变
8. 每一行都重复圆形 Agent 图标
9. Tool Output 默认无限展开
10. 失败 Tool 一律强制展开全部 Raw
11. 暴露模型私有 Chain of Thought
12. 把 ZCode UI 逐像素复制
13. 让 Raw JSON 成为普通用户默认视图
14. 为了动效引入明显性能回归
15. 用 UI 重构为名修改业务行为

---

# 30. SDD 阶段必须继续 grill-me 的问题

本 PRD 已冻结产品方向，但前端 AI 在正式写 Spec 前，仍必须针对实现细节 grill-me，至少覆盖：

1. 当前前端技术栈 / React 版本 / 状态管理
2. 当前 Runtime event schema
3. 当前 Inspector 组件结构
4. 四种模式当前行为差异
5. 哪些 event 已经有 thinking/search/skill/subagent 数据
6. Todo 数据是否已有后端事件
7. MCP / Skill / Subagent 是否已存在统一 event
8. 当前 Raw JSON renderer
9. 当前长列表是否已经 virtualized
10. Inspector 当前宽度与 resize 行为
11. 是否已有 Command Palette 依赖
12. Icon library
13. 主题系统
14. 当前 accessibility 基础
15. 哪些视觉改动必须避免破坏现有截图测试 / E2E

**只有这些实现信息澄清后，才能进入 Ticket 拆分。**

---

# 31. Ticket 拆分建议顺序（仅作为后续 tickets 的骨架）

后续不要一次大改。建议拆成以下 Epic / Phase：

## Phase 0 — Baseline & Safety

- 建立视觉/性能基线
- 现有功能回归清单
- Runtime event adapter

## Phase 1 — Design Tokens + App Shell

- typography
- spacing
- color
- surface
- icon
- top bar polish

## Phase 2 — Runtime Stream Foundation

- Event Row shell
- semantic icons
- collapsed state
- duration/status

## Phase 3 — Progressive Disclosure

- L0/L1/L2
- Input/Output
- CodeSurface
- TerminalSurface
- JsonTree

## Phase 4 — Event Types

- Thinking
- Search
- Skill
- MCP
- Subagent
- Todo

## Phase 5 — Inspector Polish

- Runtime Timeline
- event pairing
- selection
- Input/Output/Raw
- copy / jump

## Phase 6 — Main ↔ Inspector Linking

- inspect from stream
- jump from inspector
- selected state

## Phase 7 — Four Display Modes

- Compact
- Balanced
- Detailed
- Raw

## Phase 8 — Command Palette

- Ctrl/Cmd + K
- commands
- keyboard navigation

## Phase 9 — Performance

- virtualization
- lazy render
- profiler

## Phase 10 — Visual QA + Code Review

- Light
- Dark
- 1280/1440/1920
- long run
- error run
- huge raw event

---

# 32. 验收场景

至少必须用以下真实场景验收。

## Case A — 普通短任务

- 1 用户消息
- 1 thinking
- 1 tool
- 1 final answer

预期：非常干净，不像 Debugger。

## Case B — Tool-heavy 长任务

- 30+ tool events
- search / bash / write 混合

预期：信息密度高但能扫读，不卡顿。

## Case C — Tool Timeout

- bash `sleep 25`
- TIMEOUT
- Agent 再次处理

预期：

- 中间清晰显示失败摘要
- 不强制全展开
- 右侧 Timeline 精确定位 tool/call ↔ tool/result

## Case D — Skill + MCP + Subagent

预期：每种事件有独立语义图标与文案。

## Case E — Todo

- 5 项
- 1 completed
- 1 running
- 3 pending

预期：类似 ZCode 的可折叠进度块。

## Case F — Huge Raw JSON

预期：

- 不冻结页面
- JsonTree lazy expand
- max-height
- copy 可用

## Case G — Inspector Toggle

预期：

- 一键开关
- 中间区平滑重排
- 不丢选中 event

---

# 33. 视觉验收标准

如果最终效果出现以下任何特征，需要返工：

- 仍像普通开源 Demo
- UI 只是“换色”
- Tool Call 仍像单纯日志
- 右栏仍像 JSON dump
- 所有事件视觉权重一样
- 仍大量使用重复圆形图标
- Compact/Balanced/Detailed/Raw 差异不清楚
- 最终答案淹没在 Runtime 中
- Event 展开后把页面撑得极长
- 交互细节不如 ZCode
- Light Mode 像普通后台
- Dark Mode 只是纯黑
- Inspector 不能与主区互相定位

通过标准：

1. 默认视图接近 ZCode 的连续 Agent 工作流体验
2. 右侧 Inspector 明显比 ZCode 更“Developer / Harness”
3. 主区与右栏形成“可读叙事 vs 原始真相”的双层体验
4. 四种显示模式有清晰价值
5. Tool / Skill / MCP / Subagent / Todo 均有一等视觉语义
6. 视觉高级、响应快、长任务不卡

---

# 34. 最终产品定义

最终不是：

> ZCode Clone

也不是：

> DeepSeek Harness Clone

而是：

> **ZCode 的 Continuous Agent Stream**  
> + **DeepSeek Harness 的深度 Run Inspector / Runtime Timeline**  
> + **Linear / Raycast 的高信息密度层级**  
> + **Apple 级视觉与交互精度**

一句话定位：

> **一个默认像成熟 AI 产品、展开后像专业 Agent Debugger 的双层 Agent Runtime Web UI。**

---

# 35. 给前端 AI 的执行总指令

> 先不要直接大规模改代码。
>
> 1. 阅读本 PRD。
> 2. 阅读当前前端目录结构、组件树、主题系统、Runtime event schema 和 Inspector 实现。
> 3. 对照本 PRD 做一次 gap analysis。
> 4. 使用 grill-me，只询问会影响架构、状态模型、组件边界、兼容性或验收标准的问题。
> 5. 用户确认后生成正式 SDD Spec。
> 6. 再进入 tickets 拆分。
> 7. 每个 ticket 必须小步实现、可独立验证、可独立回滚。
> 8. 每个阶段完成后做视觉验收 + 功能回归 + code-review。
> 9. **严禁一次性重写整个前端。**
>
> 本轮成功的核心不是“做得花”，而是：
>
> **中间像 ZCode 一样自然、右边像 DeepSeek Harness 一样深入、整体像成熟商业产品一样精致。**

