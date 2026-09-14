# ADR-0014: Web UI Redesign 架构决策（本轮 UI 重构）

- 状态：Accepted（grill 2026-09-06，用户逐项拍板后全速推进）
- 关联：PRD `goal/.../docs/spec/Agent_Runtime_Web_UI_Redesign_PRD_UX_Spec.md`（冻结）/ ADR-0005（Web Inspector 栈）/ spec 11_STREAMING_API_WEB_UI / 不变量 #3/#4/#18/#22

## 背景

本轮是对 `intelligence-agent-frontend` Web UI 的 **UI/UX 重构**（PRD 明确："不是业务功能重写"）。目标体验：中间做成 ZCode 式 Continuous Agent Stream；右侧 Run Inspector 保持 DeepSeek Harness 式深度 Runtime Debugger，且右栏必须比中间更详细；现有功能不得删减（D11）。

当前前端现状（grill 前事实调查）：

- **栈**：React 19.2 + Vite 8 + TS 6 + Vitest 5；Radix UI primitives + lucide-react + Inter/JetBrains Mono；174 vitest 测试 passing。
- **事件 schema**：后端 `session/event.py` 单一真相源，16 类 EventType（session/run/user/model/tool/artifact/context/operation/memory），**无** PRD §5.2 要求的 thinking/search/skill/mcp/subagent/todo 一等公民事件；前端 `gen_event_types.py` 镜像生成。
- **中间主区**：`Conversation.tsx` 把 Turn 投影成 user 消息 + execution chain（model segments ↔ ToolCards 交替），靠 `deriveChain`。重复圆形 Brain 图标作 avatar（违背 D12）。
- **Inspector**：`StepDetail.tsx` 5 平级 tabs（Chat/Timeline/Changes/Terminal/Artifacts）+ 事件级 Input/Output/Raw 三段。Timeline 已有 200 行尾窗裁剪。
- **density**：`density.ts` 全局 `data-density` 属性（compact/balanced/detailed/raw）驱动 CSS；每组件 ad-hoc `expanded`/`collapsed` useState，非统一状态机。
- **主题**：`theme.ts` `data-theme`（dark/light）+ localStorage。
- **virtualization**：Timeline 尾窗 200 行；Conversation 无任何 windowing。

## 决策

### D1 — 事件语义来源：纯前端推断，不改后端协议

新增 **前端 RuntimeEventKind 推断层**（`lib/eventKind.ts`），把现有 SessionEvent 归类成 PRD §5.2 的语义 kind：

- `model/started→delta→completed` 流 → `thinking`（运行中）/ `final-answer`（终态回答）
- `tool/call` + `tool.name === 'bash'` → `terminal`
- `tool/call` + `tool.name ∈ {read, grep, glob}` → `search`
- `tool/call` + `tool.name` 含 edit/write/apply_patch → `write`
- `tool/call` + `mcp__` 前缀 → `mcp`
- `tool/call` + 其它 → `tool`（generic）
- `tool/result` 失败 → `error`（语义叠加在原 kind 上，不替换）

**不** 在 `session/event.py` 新增 EventType。理由：(1) PRD 开头冻结"本轮是 UI/UX 重构，不是业务功能重写"；(2) AGENTS.md §4.4 Secondary Agent 不承担协议级重规划（那是 Primary Developer 的活）；(3) 改 SessionEvent 影响 append-only / JSONL 持久化 / resume / replay / 不变量 #3/#4/#18，远超本轮边界。

**subagent / todo / skill 当前后端无事件承载**：Event Rendering Registry 注册 renderer 但数据不存在时不渲染（不伪造、不占位）。后端未来加事件时只需接线。

### D2 — Density 双层模型：全局默认 + 每事件 manual override

- **全局 density**（沿用 `density.ts` 的 `data-density` 四档）= 每事件的**默认 L 级**：Compact=L0、Balanced=L0+部分 L1、Detailed=L1、Raw=L2。
- **manual override**：用户手动展开某事件后进入 `Map<eventKey, Level>` override 集合，切全局 density **不重置** override（符合 PRD §6 规则）。override 存活在 `useDisclosure` hook，切 session 清空（与现有 `key={session_id}` remount 一致）。
- 收敛现有 ad-hoc `expanded`/`collapsed` 进统一 L0-L3 状态机。

### D3 — Inspector 结构演进：Timeline 常驻 + Event Detail + 聚合 tabs 次级

- **Timeline 升为 Inspector 常驻主体**（不再是 5 tabs 之一）：seq · type · summary，点 event 在右半出 Event Detail。
- **Event Detail 扩到四段**（PRD §8.4）：Overview / Input / Output / Raw。现有三段加 Overview 段。
- **Run-level Overview**（现 Chat tab 的 RUN/TOOLS/CONTEXT/MODEL/TRACE 区块）保留为次级 tab / 折叠区。
- **Changes / Terminal / Artifacts tabs 保留**（D11 不删），下沉为次级 tab。
- 是对现有 StepDetail 的**重排 + 扩展**，不是重写——可分 ticket 做。

### D4 — 视觉系统：叠加 tokens.css，零新工具链

- 新建 `web/src/styles/tokens.css`，定义 PRD §16-18 的 token 体系（spacing 4/8/12/16/20/24/32/40、radius scale、color layer ≥4 层 dark + light、typography scale、motion duration、surface layer）。
- 现有 60KB `app.css` 散落的魔法值**逐步**替换成 `var(--token-...)`，每个组件独立 ticket 可回滚。
- **不** 引入 Tailwind / CSS-in-JS——现有已是 CSS 变量风格，零运行时依赖（Reuse First + Scope Lock）。

### D5 — Main↔Inspector 联动：hover Inspect + click 跳转（双向）

- **中间 → 右**：中间任意事件 hover 显示 "Inspect" 按钮，点击：(1) 右栏关着则打开；(2) Timeline 定位对应 event；(3) 高亮该 event；(4) Event Detail 切到该事件。
- **右 → 中间**：Inspector Timeline 点 event → 中间滚动到对应事件 + pulse 600-900ms fade。
- **选中 ≠ 展开**：选中控制 Inspector 上下文，展开控制中间 inline detail。

### D6 — 图标：继续用 lucide-react（零新依赖）

PRD §10 所有语义图标在 lucide-react 都有对应（Brain/Search/Terminal/Wrench/Sparkles/Plug/Bot/ListChecks/Cpu/AlertTriangle/Check/Database/Book）。已装，Reuse First。**移除** Conversation 里重复的圆形 Brain avatar（D12），按 kind 用语义图标。

### D7 — Virtualization：Conversation 也上 @tanstack/react-virtual

引入 `@tanstack/react-virtual`（单一成熟依赖），Conversation（中间主区）与 Timeline 都做窗口化。PRD §20.2 + Case B（30+ tool events）+ Case F（huge raw）明确要求。改造现有 scroll 逻辑；现有 memo + copy-on-write 投影层不变。

### D8 — 回归保护：现有测试全保留 + 增量交互测试

- 现有 174 vitest 测试全绿基线，本轮不改不删。
- 新增组件交互测试（eventKind 推断器、L0-L3 状态机、联动、Command Palette）。
- 视觉验收：dev server + chrome-devtools MCP 对 PRD §32 Case A-G 截图，存 `.scratch/acceptance/`。

## 后果

- **正面**：本轮纯前端、零后端协议依赖、可独立验证可回滚；中间立刻有 ZCode 式语义叙事；Inspector 升级到 PRD §8 核心；后端未来加一等公民事件只需接线 renderer。
- **权衡**：subagent / todo / skill 在后端加事件前不渲染（诚实降级，非伪造）；@tanstack/react-virtual 是本轮唯一新依赖；60KB app.css 的 token 迁移是渐进式（不一次性重写）。
- **不变量守卫**：不改 SessionEvent（#3/#4/#18）；前端推断层不维护第二套真相（#22——推断是纯函数 view over events，events 仍是唯一事实源）；Tool 一条统一执行路径（#7）不受影响（UI 层不动 Runtime）。

## 参考来源

- 用户 grill Round 1 + Round 2 全部"按推荐"拍板记录，2026-09-06
- PRD `goal/Lightweight_Observable_Agent_Harness_Spec/docs/spec/Agent_Runtime_Web_UI_Redesign_PRD_UX_Spec.md`
- 现有地基：`web/src/lib/projection.ts`（投影源）/ `web/src/components/StepDetail.tsx`（Inspector 雏形）/ `web/src/lib/density.ts` / `web/src/lib/theme.ts`
