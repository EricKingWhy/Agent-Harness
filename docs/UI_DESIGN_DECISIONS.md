# UI Design Decision Record（冻结）

> 依据 `Intelligence_Agent_Web_UI_Design_Brief.md` §23。grill-me 已完成（A–H 全部主题 + 空态 tab / 背景氛围 2 个衍生项），用户裁定如下。**冻结后进入实现。**
> 日期：2026-09-04

## Product Positioning

- **IDE/workbench 感 + 中等技术密度**。像 IDE + runtime inspector，不像聊天 app。
- 默认视图：结构化执行链 + 派生计数可见，重型细节（Input/Output/Raw）进渐进披露。
- 受众：用户本人为主，兼顾面试/演示观看者。

## Visual Direction

- **Dark-first**：暗色为一等公民优先打磨；亮色主题保持可用但非本 Phase 重点。
- **强调色**：青/蓝灰冷调家族，具体色值实现期迭代，**避开 AI 紫**。
- **环境光氛围减淡保留**：body radial-gradient 保留但减淡（约 50%），保留一点现有品牌记忆。
- **玻璃收缩**：只用于 Composer dock、（未来）命令面板、popover/浮层。三栏主面板改实心表面 + 亮度分层 + 1px 边框。
- 反模式清单（Brief §28）全量生效：无全局 glassmorphism、无 20px+ 大圆角、无输入框蓝光、无装饰渐变、无假图表。

## Layout / IA

- 单一 Application Shell（非三张卡）：App Bar + Session Rail + Agent Workspace + Run Inspector。
- 桌面参考比例：rail 220–260px / inspector 280–340px / workspace 弹性。
- 响应式：宽屏三栏；中屏 Inspector 可收起（关闭不卸载，采纳 DSH 语义）；窄屏 rail 折叠为抽屉。
- 圆角语义阶梯：xs 4 / sm 6 / md 8 / lg 12（浮层），xl 仅命令面板。阴影砍到 2 档（overlay/popover），主面板零阴影。

## V1 Tabs（五个全上）

`Chat | Timeline | Changes | Terminal | Artifacts`

- **常驻 tab + 空态文案**：会话无对应数据时显示解释性空态（如"本次会话未产生文件变更"），不隐藏 tab、不做假数据。
- Terminal 场景 = bash 工具调用的命令执行面；Changes = diff 双栏（复用现有 ToolCard diff 形态的数据）；Artifacts = artifact 聚合页（列表 + 内容查看，数据来自 artifact/created + artifact 切片）。
- 未来 tab（Context/Memory/Evaluation/SubAgents）不实现，但 tab 架构为其留位。

## Inspector Scope

- **只显真数据 + 空槽标注**。
- V1 真数据区块：RUN（status/id/started/duration 由事件 time 推）、TOOLS（计数/活跃/失败）、CONTEXT（compaction 真值）、ARTIFACTS、TRACE（事件计数 + seq 跳转）。
- MODEL / CHECKPOINT：**可扩展空槽**，标注"后端未暴露"，绝不伪造。
- 事件级 Inspector：采纳——点 Timeline 行/工具块，Inspector 切到该事件详情（Input/Output/Raw），可返回 Run 级。
- 后端 Gap 已记录（tokens/model/cost/trace_id/checkpoint 无事件无 API）；需要真值时另写提示词交后端扩 payload，前端不抢做。

## Trace Density

- **四档：Compact / Balanced（默认）/ Detailed / Raw**。
- 全局切换控件 + localStorage 持久化。
- Compact = ✓ 摘要行；Balanced = 标题 + 耗时 + 关键参数；Detailed = 全字段 + Input/Output；Raw = 原始事件 JSON。
- 已完成 Turn 默认折叠为派生计数摘要（N 工具 · M 轮 · 真实耗时），**替换现有伪造的 "~N tok"**。

## Glass Usage

- 仅 Composer dock（现有 surface-floating 级别保留）、命令面板（V2）、popover。
- 玻璃 token 体系保留并沿用现有降级路径（@supports / prefers-reduced-transparency）。
- Timeline 事件体、JSON、diff、终端、inspector 表格 = 实心恒定表面。

## Theme Strategy

- Token-only（现有约束不变）。语义 token 组按 Brief §8（bg-app/sidebar/workspace/inspector、surface-1/2/overlay、border-subtle/strong、text-primary/secondary/tertiary、accent + 四状态色）。
- 亮色变量与暗色同步维护（修复现有两份重复定义的漂移风险）。
- 主题切换持久化（现状不持久化，顺手修复）。

## Unique Product Signatures（G 轮：四个全采纳）

1. **Run Pulse**：统一运行状态指示器。状态集：Idle / Thinking / Calling model / Running tool / Waiting approval / Retrying / Checkpointing / Completed / Failed。icon + 色 + 文字三通道，永不 color-only。出现于 App Bar、Session Rail 行、Inspector 头。
2. **Trace Ladder**：Chat 内工具活动呈现为执行链（User→LLM→Tool→Result→…），与 Timeline 共享同一 projection.ts 纯函数层——两视图是同一事件流的不同投影，绝无第二真相。
3. **上下文 Inspector**：事件点击切换 Inspector 上下文（Run 级 ↔ 事件级），一键返回，不用弹窗。
4. **Observable by Default**：密度四档 + 摘要→详情→Raw 渐进披露全部内嵌主工作区，不做独立 debug 页。

补充采纳的 DSH 语义：工具四态 `running|ok|error|stopped`（interrupted ≠ error）；unknown 事件渲染为 raw 行兜底，永不静默丢弃；Runtime 权威配对、UI 只渲染冻结切片（写入前端 contract 条款）。

## Session Model（E 轮）

- 会话行 = **首条用户消息截断为标题** + 短 ID（mono）+ 事件数 + 相对时间 + Run Pulse 状态点。
- Run 不做独立 UI 概念（现实现单会话单 run）。
- 分组：Running / Today / Yesterday / Older（真实时间语义，不造假组织）。

## Out of Scope

- 后端事件 payload 扩展（usage/model/duration_ms/checkpoint API）——另行提示词交后端。
- 审批流真实接线（#37 blocked WebSocket，后端空壳）。
- 让步链拖拽调宽、虚拟化长列表（无证据不预优化，Brief §26）。
- 按 wire tool name 的专属卡片体系（保持 variant 分类表）。
- useSession 判别态架构、projection.ts 纯函数层、SSE 层、现有 Vitest 测试——**架构冻结区，只许扩展不许重写**。
- #37、#39 issue 内容。

## Acceptance Criteria

Brief §27 全量：不再像三张浮动卡；Linear 式冷静层级可见；内容强于 chrome；阴影/圆角克制；玻璃限于浮层；中栏是 Agent Workspace 而非纯 Chat；运行状态一目了然；摘要→详情→Raw 可钻取；Inspector 有意义；非四者拼贴克隆；现有功能全部保持工作；零假指标；暗亮主题可用；键盘/焦点合格；常见笔记本宽度可用。
