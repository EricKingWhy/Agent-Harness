# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

有工程背景的 agent 构建者/使用者：**本机自用、小团队内部使用**。在本地跑 harness，用真机会话来调试 agent 行为——看 trace、对账工具调用、查一次 run 为什么跑歪。
（不是面向外部开发者的分发产品，也不是以评测/对比为主的工具；这两类只作为未来可能性，不作为当前设计的前提。）

## Product Purpose

把「对话」升级为「可观测的运行时工作区」：Agent 的执行过程——事件、工具调用、改动、产物、权限、checkpoint——在同一个 shell 里**可看、可查、可对账**。
成功的样子：一次 run 跑歪时，用户不需要读日志文件，就能在界面上指到具体事件、看到那次工具调用真实发生了什么。

## Positioning

**append-only typed SessionEvent 是唯一真相，UI 只是它的投影。** 会话可 resume / replay / fork，每个界面元素都能指回具体事件。
相邻产品无法照抄这一点：它不是一个聊天界面上加了调试面板，而是"事件流是本体、界面是视图"的架构结论。

## Operating Context

- 本机运行、单人使用；API 默认本地信任模式（`JWT_SECRET` 未配置时不做身份校验）。没有多租户/协作场景要照顾。
- 日常真实使用的面（用户 2026-09-13 亲述）：**Timeline（事件时间线）、Terminal（命令输出）、Overview**。右栏 Inspector 的 **Changes 与 Artifacts 目前实际不使用**——这不代表该删除，但代表它们不该成为设计的重心。
- 主要形态是长时间挂在屏幕上的开发工具（桌面 / 笔记本），PRD §5.2 明确移动端非目标。
- 真实会话里能拿到的供给面：`GET /api/sessions/{id}/events` 事件流（含 `artifact/created`、`artifact/externalized`、`tool/approval-requested`、`permission/resolved`、`tool/output_delta`）；改动以 `tool/result.data.{before,after,truncated}` 携带，**没有独立 diff 事件**；`/api/sessions/{id}/approve` 与 `/api/permission-modes` 是仅有的两个相关端点。

## Capabilities and Constraints

必须守住的约束（都是已裁决的）：

- **UI 不维护第二套会话真相**（不变量 #22；代码里多处注释以它为准，例如 `App.tsx` 的"Panel geometry is transient — NOT persisted"）。
- **真实运行数据，不得伪造指标**（PRD 非目标；Inspector 的不可得数据必须显示 `—`/`Unavailable` 或整段省略）。
- **能力可组合**：tab / 动作应由能力声明驱动，不硬编码 Coding-only 的固定 tab 集（PRD 目标 5 + 非目标 6）。
- **键盘优先、桌面/笔记本优先**（PRD 目标 6 / §5.2）。

已知技术约束（实测，不是猜测）：

- 终端**没有 PTY / 交互式 shell**：`sandbox/local.py` 是一次性 `subprocess.Popen`，输出经 `tool/output_delta` 合帧增量推送。因此任何"终端面板"只能是**命令输出聚合**，不可能是双向交互终端。
- **没有 artifact 内容 HTTP 接口**：产物内容只有模型工具（`inspect_artifact` / `read_artifact`）能读；网页端拿不到，`DiffBlock` 的"点击查看"深链因此至今未接线。
- `GET /api/capabilities` 已声明 `surfaces.{artifacts,terminal,changes}`，但**前端从未消费**（全局无 `getCapabilities`）——契约现成而悬空。
- 两处 diff 渲染并存：中心列的 `DiffBlock`（ToolCard / ApprovalCard 用）与 Inspector `ChangesTab` 内联的 `.diff-cols`。

## Brand Commitments

- 产品名 `intelligence-agent`，界面语言以中文为主（既有 UI 文案全中文）。
- 既有视觉系统是**代码即权威**：`src/index.css` 用 `[data-theme]` 属性切换暗/亮，暗色 token 在 `:root`、亮色在 `:root[data-theme='light']` 覆盖（AGENTS.md §15 要求新增 token 两处同步）。
- 明确非目标：**不复制 Linear / ZCode / Raycast 的品牌**（PRD 非目标 2）——学交互范式可以，抄外观不行。

## Evidence on Hand

- `goal/Lightweight_Observable_Agent_Harness_Spec/docs/spec/Intelligence_Agent_Web_UI_Design_Brief.md`（Brief：中心列模式、Inspector 开放问题）。
- `docs/spec/Observable_Agent_Workspace_SDD/01_PRODUCT_PRD.md`（PRD：§5.1 三区策略、§6.x 各面、§12 Inspector 八段）。
- `docs/BENCHMARK_SYNTHESIS.md`（采纳/不采纳清单：已明确**不采纳**让步链三栏 shell 完整实现，只采纳"Inspector 关闭不卸载"语义与跨视图 focus 协议）。
- `docs/EVENT_VOCABULARY.md`（生成物，38 个事件名的唯一事实源）。
- `web/e2e/` 240 条 e2e 与 `t-contrast.spec.ts`（对比度 ≥4.5、12px 字号地板）+ `workspace-modes.spec.ts`（Split/Preview 当前是 disabled 预留位的守卫测试）。
- **不存在**：`PRODUCT.md`（本文件是首份）、`DESIGN.md`、任何用户研究/可用性数据、任何真实用户证言。未来工作不得凭空编造用户证据或指标。

## Product Principles

1. **可观测默认（Observable by default）**：重要的 agent 动作必须可见、可点进、可对账；不允许"发生了但界面没说"。
2. **界面是投影，不是第二真相**：新增任何视图都必须能指回事件；不得新建一套与事件流并行、可能不一致的状态。
3. **真实优先于好看**：拿不到的数据宁可显示 `—` 或省略，也不填占位数字或装饰性图表。
4. **能力驱动组合**：面（surface）随能力声明出现/隐藏，而不是为一个能力写死一套壳。
5. **高密度键盘优先**：为长时间使用的单人开发工具优化——少弹窗、少跳页、键可达。

## Accessibility & Inclusion

- 既有门槛是**具体数字**而非口号：正文/元信息对比度 ≥4.5、字号地板 12px、暗亮双主题都必须在 e2e 里通过（`web/e2e/t-contrast.spec.ts`）。
- 窄屏（≤820px）与 <1200px 有明确行为约定：Inspector 先折叠（保持挂载、不卸载），Rail 之后折叠。
- 任何新增面板必须补齐：键盘可达（可 Tab 到、可 Esc 关）、`aria-*` 状态如实（`workspace-modes.spec.ts` 已在守 `aria-disabled`/`aria-pressed` 的诚实性）。
