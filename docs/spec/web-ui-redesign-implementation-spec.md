# Web UI Redesign — Implementation Spec

> **上游**：PRD `goal/.../docs/spec/Agent_Runtime_Web_UI_Redesign_PRD_UX_Spec.md`（冻结）+ ADR-0014（本轮架构决策，用户拍板）。
> **性质**：UI/UX 重构，不是业务功能重写。现有能力全部保留（D11），现有测试全绿基线（174 vitest passing）。
> **边界**：纯前端，零后端协议改动。subagent / todo / skill 无后端事件时注册 renderer 但不渲染。

## 1. 现状基线

- 栈：React 19.2 + Vite 8 + TS 6 + Vitest 5；Radix primitives + lucide-react；Inter / JetBrains Mono。
- 事件 schema：后端 `session/event.py` 单一真相源，16 类 EventType；前端 `gen_event_types.py` 镜像生成到 `web/src/generated/event-types.ts`。
- 中间主区：`Conversation.tsx` → `TurnView` → `deriveChain` → `ChainNodeView`（model 段 / `ToolCard`）。
- Inspector：`StepDetail.tsx` 5 平级 tabs（Chat/Timeline/Changes/Terminal/Artifacts）+ 事件级 Input/Output/Raw 三段；Timeline 有 200 行尾窗。
- density：`density.ts` 全局 `data-density` 四档；组件内 ad-hoc expanded/collapsed state。
- 样式：`app.css` 60KB 单文件，`:root`（dark 默认）+ `[data-theme='light']`。
- 关键既有约定：projection.ts 是事件→视图唯一投影源（不变量 #22）；zero-fake-metrics（缺失显示 — 不伪造）；DSH 四态（running/success/failed/stopped，中断≠错误）。

## 2. 目标架构

```
AppShell
  TopBar            ← segmented control 四档 density + Inspector toggle + Theme + Auth chip
  SessionSidebar    ← SessionList（保留，样式对齐 tokens）
  AgentWorkspace
    UserPrompt      ← 右对齐轻量 surface（现有 msg-bubble-user 保留）
    RuntimeStream   ← Conversation 改造：RuntimeEventRow（registry 分发）
      thinking / search / terminal / write / tool / mcp / model / error / final-answer
      (subagent / todo / skill renderer 注册但当前无数据不渲染)
    Composer        ← 保留
  RunInspector      ← StepDetail 改造
    InspectorHeader ← RUN INSPECTOR + Run 状态 + Run ID + close
    RuntimeTimeline ← 常驻主体（seq · type · summary · duration）
    EventDetail     ← Overview / Input / Output / Raw 四段
    次级 tabs       ← Run Overview / Changes / Terminal / Artifacts（保留不删）
CommandPalette      ← Ctrl/Cmd+K，Radix Dialog
```

共享基础件：`tokens.css` / `eventKind.ts`（推断）/ `disclosure.ts`（L0-L3）/ `EventRegistry.tsx` / `CodeSurface` / `JsonTree`（已有）/ `CopyButton`（已有）。

## 3. 核心机制

### 3.1 RuntimeEventKind 推断（lib/eventKind.ts，ADR-0014 D1）

纯函数，view over events，不产生第二真相：

```ts
type RuntimeEventKind =
  | 'thinking' | 'search' | 'terminal' | 'write' | 'tool'
  | 'mcp' | 'model' | 'error' | 'final-answer'
  | 'skill' | 'mcp-server' | 'subagent' | 'todo'   // 注册但当前无数据不渲染
```

推断规则（输入：ToolCall 或 model 段）：
- bash → terminal；read/grep/glob → search；edit/write/apply_patch → write；`mcp__` 前缀 → mcp；其它 → tool
- model 段 streaming → thinking；done 且是 turn 最后段 → final-answer；否则 model
- tool.status === 'failed' → 叠加 error 语义（图标/颜色变化，kind 不变）
- ToolCall.diff 存在 → write 专用 diff 形态（复用现有 DiffBlock）

### 3.2 Progressive Disclosure（lib/disclosure.ts，D2）

- `Level = 0 | 1 | 2 | 3`；全局 density → 默认 Level 映射：compact=0, balanced=0(带 L1 摘要), detailed=1, raw=2。
- `useDisclosure` hook：`Map<eventKey, Level>` override；`levelFor(key, densityDefault)` = override ?? densityDefault；`setLevel(key, lv)`；切 session 清空（key 含 session_id 前缀或 hook 随 session remount）。
- L3 不在本 map 内——L3 = 点 Inspect 进 Inspector（联动，不是中间区展开）。
- 手动展开优先于全局；切换 density 不丢 override。

### 3.3 Event Rendering Registry（D8 预留）

```ts
const runtimeEventRenderers: Record<RuntimeEventKind, ComponentType<RendererProps>> = {...}
```
未知 kind 兜底 UnknownEventRow（渲染 raw 摘要，对应现有 unknown_events 协议）。subagent/todo/skill 有 renderer 但数据源（后端事件）当前不存在 → 永不命中，不伪造。

### 3.4 Inspector 重排（D3）

StepDetail 布局改为：
- InspectorHeader：`RUN INSPECTOR` + run badge + Run ID（短）+ close 按钮
- 主体两栏（Inspector 内部）：左 = RuntimeTimeline（常驻，seq·type·summary·duration，点击选中）；右 = EventDetail（Overview/Input/Output/Raw 四段 tabs；无选中时显示 Run Overview = 现 ChatTab 内容）
- 次级 tabs（Run Overview / Changes / Terminal / Artifacts）收纳在底部或下拉，保留全部现有能力（D11）

### 3.5 Main↔Inspector 联动（D5）

状态归属 App 层（与现有 focus 类似）：
- `selectedEventKey: string | null`（选中的事件，双向共用）
- 中间行 hover → 显 Inspect 按钮；点击 → `openInspector(key)`：inspectorOpen=true + selectedEventKey=key + Timeline scrollIntoView + 高亮
- Inspector Timeline 点击行 → selectedEventKey + 中间对应 RuntimeEventRow scrollIntoView + pulse 600-900ms（CSS animation, prefers-reduced-motion 关闭）
- 选中 ≠ 展开：selected 只驱动 Inspector + 中间高亮框，不改 L 级

### 3.6 density 双层（D2 落地）

- `density.ts` 保持 API 不变（全局 attr + localStorage）。
- 新增 `useDisclosure(sessionId)`：override Map；Conversation/ToolCard 从 props 接 `level` + `onToggleLevel`，替换现有内部 expanded state。
- TopBar segmented control 样式升级（tokens），行为不变。

### 3.7 Command Palette（PRD §15）

- Radix Dialog + 自绘列表；Ctrl/Cmd+K 开关；fuzzy 过滤（子序列匹配即可，不引库）；↑↓ 选择、Enter 执行、Esc 关。
- 命令集：Toggle Run Inspector / 四档 Switch / Search Runtime Events（过滤 Timeline 并跳第一条命中）/ Jump to Latest Event / Copy Run ID / Copy Trace ID / Toggle Theme / Focus Composer。

### 3.8 Virtualization（D7）

- 依赖：`@tanstack/react-virtual`（唯一新依赖）。
- Conversation 的 RuntimeStream 与 Inspector Timeline 均窗口化；保持现有"近底部自动滚动"与"加载更早"行为。
- 大 JSON（L2/Raw）lazy mount：只有展开到该级才挂 JsonTree。

## 4. 视觉 tokens（PRD §16-19 直译）

- spacing: 4/8/12/16/20/24/32/40；radius: 8/10/12/16/18/20/22；hairline: 1px 低对比。
- dark ≥4 层 surface（canvas/surface/elevated/hover/active）；light: canvas #FAFAFA 系、sidebar/inspector 深一级。
- typography: UI Inter；code JetBrains Mono；12/13/14/15/16/18 阶；duration/token/seq 用 tabular-nums。
- motion: inspector 220-280ms / inline expand 160-220ms / pulse 600-900ms / palette 120-180ms；全部 `prefers-reduced-motion` 降级。
- accent 低饱和、85%+ neutral；错误 = 低饱和红 + 轻背景，不满屏红。

## 5. 禁止（PRD §29 全文适用）

不删 Inspector / 不删四档 / 不改后端 API / 不满屏 Card / 不全屏 glass / 不重复圆形图标 / 不默认展开 Raw / 不强制展开失败 Tool / 不暴露 CoT / 不逐像素抄 ZCode / 不为动效牺牲性能 / 不以 UI 重构为名改业务行为。

## 6. 验收

- PRD §32 Case A-G 全部走查（chrome-devtools 截图存 `.scratch/acceptance/`）。
- PRD §33 视觉验收标准逐条自查。
- 现有 174 测试 + 新增测试全绿；`npm run lint` 通过；`tsc -b` 通过。
- 性能抽查：100+ event 滚动、Inspector toggle、density 切换无明显卡顿（React Profiler 观察）。
