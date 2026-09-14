# Benchmark Synthesis — Intelligence Agent Web UI 重设计

> 依据 `Intelligence_Agent_Web_UI_Design_Brief.md` §20 要求产出。研究阶段（Brief 步骤 1–4），代码零改动。
> 日期：2026-09-04

---

## 1. Linear — 视觉系统

**调研方式**：官网实测（DevTools 部分值）+ 公开设计惯例。官网动画过重导致实时截图超时，量化值部分依赖行业公认特征，已标注置信度。

### 采纳

| 模式 | 具体做法 | 对本项目的落地 |
| --- | --- | --- |
| 低对比 chrome | 侧栏/顶栏用比内容区低一档的表面亮度，靠亮度分层而非边框强分隔 | 三栏 surface 用 `--bg-sidebar` / `--bg-workspace` / `--bg-inspector` 三档语义 token，去掉现在的"三张浮动玻璃卡" |
| 克制圆角 | 行/控件 4–6px，卡片 8px，弹层 12px（置信度：高，行业公认） | 替换现有 6/10/14/20 阶梯 → 收敛为 xs 4 / sm 6 / md 8 / lg 12，xl 仅命令面板等浮层 |
| 弱阴影 | 主面板零阴影，仅浮层一层软阴影 | 阴影 token 从 5 档砍到 2 档（overlay / popover） |
| 状态颜色小面积点缀 | 状态色只出现在 dot/badge/文字，绝不铺满区域 | Run Pulse 用 8px dot + 图标 + 文字，永远三通道编码 |
| 暗色非纯黑 | Linear 暗底 ≈ `#08090A`（实测 body bg），内容区略抬亮 | 我们暗底从 OLED 纯黑系往 `#0B0C0E` 一类偏移，保 OLED 屏幕舒适但层级更稳 |
| 密而不挤的列表 | 行高 28–32px，secondary 文字小一号但同一行 | Session Rail 行改为单行紧凑式 |

### 不采纳

- Linear 品牌紫、任何紫色系强调色（Brief 明令避开 AI purple）。
- 其专有页面结构（Inbox/Initiatives 等业务概念）。
- 杂志式营销排版（与本工具无关）。

---

## 2. Cursor — Agent 工作区架构

**调研方式**：官网首页 agent 面板 demo 结构分析（agents 页需登录，307 → WorkOS，放弃登录）。

### 采纳

| 模式 | 观察到的证据 | 对本项目的落地 |
| --- | --- | --- |
| 任务状态分组 + 计数徽章 | "In Progress 2 / Ready for Review 3" 分组标题带数字 | Session Rail 按 Running / Today / Older 分组（Brief §10 授权，前提是真实语义） |
| 行内细粒度活动文案 | 任务行右侧 "Reading docs"、"Generating plan" | Run Pulse 的状态文案直接映射当前事件类型（Calling model / Running tool / …） |
| 产出度量在行内 | "Worked for 14m 22s"、"+135-21"、"Explored 12 files" | Turn 折叠摘要显示真实派生计数（N 工具 · M 轮 · 耗时），不用伪造 token 数 |
| 多模式工作区 tab | Chat / Plan / Browser 等一区多 tab | 中栏升级为 Chat / Timeline / Artifacts 工作区 tab（V1 范围见 grill-me C 轮） |
| 追问入口 | 完成卡片底部 "Add a follow up..." | Composer 在完成态保持常驻，弱化"聊天"感 |

### 不采纳

- 其营销页的风景壁纸/大 hero（产品页不需要）。
- Cloud agent 看板的完整复杂度（无此业务）。
- 屏幕录制回放等重型功能。

---

## 3. DeepSeek Harness — 可观测语义（本地源码级研究）

**调研方式**：clone 至 `%TEMP%\dsh-benchmark`，逐包读 `packages/core/session`、`ui-conversation`、`ui-trajectory`、`ui-tool`、`ui-chat`、`ui-layout`。

### 采纳（三条架构级决策 + 三条 UI 语义）

1. **配对责任在 Runtime，UI 只渲染冻结切片**。`ToolResultNode` 内嵌 `call`/`callTime`（可 null 降级），UI 不扫事件流自建 join。→ 写入前端 contract 明文条款，与 AGENTS.md 不变量 22 完全同构。我们现有 projection.ts 已是此模式，固化成规则。
2. **工具行四态状态机**：`running | ok | error | stopped`，interrupted ≠ error；重试链与终态失败分离渲染。→ 映射不变量 9（Model Fallback 与 Tool Retry 分离）的 UI 呈现；我们 ToolCard 现在只有 running/success/failed 三态，补 stopped 语义。
3. **UnknownSurfaceNode 兜底协议**：unknown 事件渲染为 raw 行（seq/time/type/data），永不静默丢弃。成本极低，保证 trace 完整性。我们 15 个事件类型之外未来新增时 UI 天然滞后，此协议直接解决。
4. **Turn-process 渐进披露（默认 compact）**：已完成 Turn 折叠中间过程为一个 disclosure，摘要是**派生的结构化计数**（N 消息 · M 工具 · K subagent）而非装饰。配"运行满 15s 才显示计时器"防抖。我们现有 Turn 折叠摘要的 "~N tok" 是伪造的，必须替换为真实计数。
5. **Timeline 的双轴投影语义**：`sequence/duration × compressed/actual` 四模式 + 三 lane（turn/request、message、tool）是纯函数投影，时间轴是可查询工具而非甘特装饰。V1 取其"lane 分组 + duration 列"的简化版。
6. **跨视图 focus 协议**：`openView('trajectory', callId)` 式 `ConversationViewRequest{view, focus}`。→ Chat 里点工具块 → Timeline 聚焦该 call；点 Timeline 行 → Inspector 切到事件级。一条薄协议打通三区。

### 不采纳

- `surfaceOp: replace` 的 surface 重写语义（与 append-only 不变量冲突，Scope Lock）。
- 让步链三栏 shell 完整实现（concession chain / drag handle）——先只采纳"Inspector 关闭不卸载"语义。
- 按 wire tool name 的 keyed slot 专属卡片体系——保持 GenericToolCard + 一张 variant 分类表（我们已有 bash/diff/artifact 切片三种，够用）。
- delta 级 timing 内嵌进 assistant/message 事件（与"大内容外置 artifact"冲突）。
- `tool/result.meta` 工具私有展示直通 UI（展示派生放前端 pure model）。

---

## 4. Raycast — 克制的 Liquid Glass

**调研方式**：官网结构考察（CSS 级细节不可得，结合 Brief §3.4/§9 的规范要求综合判断）。

### 采纳

- **玻璃只给浮层**：Composer dock、命令面板、popover、顶栏。信息密集区（timeline 事件体、JSON、diff、终端、inspector 表格）一律实心表面。Brief 规则原文：*"Glass for transient / floating / control surfaces. Solid surfaces for information-dense work surfaces."*
- 三栏主面板从 `.surface-raised`（blur-1 玻璃）**降级为实心 surface**——这是对现状最大的材质修正。
- 玻璃 token 体系保留（我们已有 `--glass-blur-1/2/3` 三级 + 降级路径），但应用面收缩到 2–3 个表面。

### 不采纳

- 全局 glassmorphism（Brief §28 首条反模式）。
- 发光渐变背景作为层级手段（我们现有 body 双 radial-gradient 环境光可保留但减淡，或去除——grill-me B 轮定）。

---

## 5. Intelligence Agent 独特综合（ !== 四者拼贴）

**产品身份**：Observable Agent Runtime Workspace——"不是聊天壳，是可观测的运行时工作台"。

三个独有签名（待 grill-me G 轮确认）：

1. **Run Pulse**：全产品统一运行状态指示器（Idle/Thinking/Calling model/Running tool/Waiting approval/Retrying/Checkpointing/Completed/Failed），icon + 色 + 文字三通道，出现在顶栏、Session Rail 行、Inspector 头。
2. **Trace Ladder**：Chat 中工具活动即执行链（User → LLM → Tool → Result → …），Timeline 是同一事件流的另一种投影——两视图共享同一 projection.ts 纯函数层，绝不出现两套真相。
3. **Observable by Default**：摘要 → 详情 → 原始事件的渐进披露内嵌在工作区内（Trace Density: Compact/Balanced/Detailed/Raw），不开独立 debug 页。

**关键现实约束（现状盘点结论，直接决定 grill-me D 轮）**：

| Brief 想要的指标 | 数据真值 |
| --- | --- |
| run/tool status | ✅ 真数据 |
| duration | ⚠️ 仅事件 time 差值可推；model/* 流事件无 time |
| artifact / compaction / reconcile | ✅ 真数据（Phase 5 事件） |
| tokens 消耗量 | ❌ 事件 payload 无；唯一数字是 compaction token_estimate |
| model / provider | ❌ 不存在于事件或 API |
| cost | ❌ 无 |
| trace_id / span | ❌ 只在后端诊断日志，不进事件流 |
| checkpoint | ❌ 后端机制完整但零暴露（无事件、无 API） |

→ Inspector 的 MODEL（tokens/cost/latency）与 CHECKPOINT 区块在纯前端范围内**只能留空或显示"后端未暴露"**；要显示真值必须扩后端事件 payload（如 model/completed 加 usage+model、run/completed 加 duration_ms、暴露 checkpoint/diagnostics API）。这属于跨端 Gap，按 AGENTS.md §1.1 应报告而不是前端伪造（Brief §25 也明令禁止 fake metrics）。

---

## 6. 给 grill-me 的问题清单（A–H 轮）

见 Brief §22。已在研究阶段准备好的倾向性答案（供用户否决）：

- **A**：偏 IDE/workbench；默认视图中等技术密度；受众 = 用户本人 + 面试/演示观看者。
- **B**：dark-first；强调色候选：中性蓝灰 / 青 / 靛（避开 AI 紫）；玻璃只留 Composer + 未来命令面板。
- **C**：V1 tabs = Chat + Timeline；Changes/Terminal 并入 ToolCard 已覆盖的场景，Artifacts 视 Brief。是否需要空态 tab 待定。
- **D**：Inspector V1 只显示真数据（RUN/TOOLS/CONTEXT/ARTIFACTS），MODEL/CHECKPOINT 显式标注"后端未暴露"或做成可扩展空槽；事件点击切换 inspector 上下文 = 是。
- **E**：会话命名 = 首条用户消息截断；run 不作为独立 UI 概念（单会话单 run 现实）。
- **F**：密度四档采纳，默认 Balanced，全局持久化。
- **G**：Run Pulse + Trace Ladder + 渐进披露采纳；Checkpoint 槽保留但标注。
- **H**：视觉 + IA 一起改（Brief 授权），但不动 useSession 判别态架构与 projection 纯函数层；现有 Vitest 全保。
