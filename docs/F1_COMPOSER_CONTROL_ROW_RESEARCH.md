# F1 Composer Control Row — 实现前调研报告

> Ticket F1（Phase 2b）：在 Composer 区块加一行 control row，含五个选择器。
> 本报告基于 `D:\intelligence-agent-frontend\web` 目录的现有代码调研产出。

---

## 1. Composer 现有结构

**文件**：`web/src/components/Composer.tsx`

### Props 接口

```typescript
interface Props {
  streaming: boolean;
  onSubmit: (task: string) => void;
  onCancel: () => void;
  presetTask?: PresetTask | null;
  models?: ModelCatalogEntry[];        // GET /api/models
  selectedModel?: string | null;
  onModelChange?: (name: string | null) => void;
}
```

### JSX 结构（当前）

```
<div className="composer-wrap">
  <div className="composer-dock surface-floating">
    <textarea id="composer-input" ... />
    <ModelPicker ... />                ← 唯一控件，绝对定位在 dock 右下
    {streaming ? <Esc提示 + Stop按钮> : <Send按钮>}
  </div>
</div>
```

关键观察：

1. **没有 control row 容器**——`ModelPicker` 直接放在 `.composer-dock` 内，靠 CSS `position: absolute; right; bottom` 定位到 textarea 右下角。
2. **`.composer-dock` 是 `position: relative`**——子元素绝对定位的锚点。
3. **textarea 的 padding-right 是 52px**——只给 Send/Stop 按钮腾位置，没给 ModelPicker 腾位置。ModelPicker 靠 `align-self: flex-end` + 绝对定位浮在 textarea 底部右侧。
4. **`memo(Composer)`**——流式期间 props 稳定，输入框不随对话区每个 delta 重渲染。
5. **ModelPicker 在 Composer 里是直接内联渲染的**，没有通过中间组件包装。

### 与 model/permission 相关的字段

当前 Composer 只接收 `models` / `selectedModel` / `onModelChange` 三个与选择器相关的 props。F1 需要扩展为五个控件的数据流。

---

## 2. ModelPicker 模式分析

**文件**：`web/src/components/ModelPicker.tsx`

### 架构模式

```
Popover.Root (受控 open)
  ├── Popover.Trigger asChild
  │     └── <button className="composer-model model-picker">
  │           ├── <Cpu icon />
  │           ├── <span>{triggerLabel}</span>
  │           └── <ChevronDown />
  └── Popover.Portal
        └── Popover.Content className="model-picker-content"
              └── <Command> (cmdk)
                    ├── <CommandInput /> (搜索)
                    └── <CommandList>
                          ├── <CommandGroup> (默认链)
                          └── <CommandGroup heading={provider}> (按 provider 分组)
```

### 可复用的模式要素

| 要素 | ModelPicker 实现 | F1 复用策略 |
|------|------------------|-------------|
| **Trigger 按钮** | `button.composer-model.model-picker`，icon + label + chevron | 四个新控件复用同结构，换 icon 和 aria-label |
| **Popover portal** | Radix `Popover.Root` + `Popover.Portal` + `Popover.Content` | 直接复用 |
| **搜索过滤** | cmdk `Command` + `CommandInput` + `CommandList` + `CommandItem` | 单选控件复用；Context Providers 多选需扩展 |
| **分组** | `groupByProvider()` → `CommandGroup heading={provider}` | Permission Modes / Agent Profiles / Reasoning Efforts 无需分组（列表短），但可复用 CommandGroup 无 heading 用法 |
| **空目录降级** | `if (models.length === 0) return null;` | 四个新控件同原则：空数组 → 返回 null → 调用方隐藏入口 |
| **选中态** | `effectiveSelectedModel === m.name` → 加 `sel` class + Check icon | 复用同模式 |
| **disabled** | `aria-disabled={disabled \|\| undefined}` + `disabled={disabled}` | 复用 |
| **CSS 类名** | `.composer-model` (trigger) + `.model-picker-*` (内部) | 新控件可用同族类名，如 `.composer-control` + `.control-picker-*` |

### 关键设计决策（从 ModelPicker 提取）

1. **cmdk filter 自定义**：ModelPicker 用 `filter={(value, search, keywords) => ...}` 做子串匹配，而非 cmdk 默认的 command-score。新控件列表短，可直接用默认 filter 或同款子串匹配。
2. **DEFAULT_VALUE sentinel**：null 选中态用 `'__default__'` 字符串作为 cmdk Item value，避免与真实条目冲突。新控件如果有「默认」选项，可同模式。
3. **triggerLabel 计算**：`selectedEntry?.name ?? '默认链'`——从传入数组中查找选中项的 display name。新控件同模式：从 entries 中找 `id === selectedId` 的 `display_name`。

---

## 3. API 层现状

**文件**：`web/src/lib/api.ts`

### 现有类型定义

```typescript
export interface ModelCatalogEntry {
  name: string;
  provider: string | null;
  model: string | null;
  default: boolean;
}
```

### 现有函数

| 函数 | 端点 | 返回 |
|------|------|------|
| `getModels()` | `GET /api/models` | `ModelCatalogEntry[]` |
| `startSession(payload)` | `POST /api/sessions` | `Response`（SSE 流） |
| `listSessions()` | `GET /api/sessions` | `SessionSummary[]` |
| `getSessionEvents(id)` | `GET /api/sessions/{id}/events` | `AgentEvent[]` |
| `streamSession(id, afterSeq)` | `GET /api/sessions/{id}/stream` | `Response` |
| `postApproval(id, approved)` | `POST /api/sessions/{id}/approve` | `unknown` |
| `cancelSession(id)` | `POST /api/sessions/{id}/cancel` | `{ status: string }` |
| `recoverSession(id)` | `POST /api/sessions/{id}/recover` | `AgentEvent[]` |

### 缺失的函数（F1 需新增）

以下四个函数在 `api.ts` 中**完全不存在**，需要新增：

1. `fetchPermissionModes()` → `GET /api/permission-modes`
2. `fetchAgentProfiles()` → `GET /api/agent-profiles`
3. `fetchReasoningEfforts()` → `GET /api/reasoning-efforts`
4. `fetchContextProviders()` → `GET /api/context-providers`

### POST /api/sessions 请求体现状

```typescript
export interface StartSessionPayload {
  task: string;
  workspace?: string;
  max_steps?: number;
  auto_approve?: boolean;
  model?: string;  // T10 #103
}
```

**缺失字段**（F1 需新增到 `StartSessionPayload`）：

- `permission_mode?: string`
- `agent_profile?: string`
- `reasoning_effort?: string`
- `context_providers?: string[]`

### B1 后端契约回顾

三个单选端点的 entry 结构固定：
```json
{ "id": "str", "display_name": "str", "description": "str" }
```

顶层 key 用复数短名：`efforts` / `profiles` / `providers`。

Context Providers 是多选，`GET /api/context-providers` 当前诚实返空数组 `{"providers": []}`。

---

## 4. App.tsx 状态管理

**文件**：`web/src/App.tsx`

### models 目录的状态管理模式（F1 四个新控件照搬）

```typescript
// 状态
const [models, setModels] = useState<ModelCatalogEntry[]>([]);
const [selectedModel, setSelectedModel] = useState<string | null>(null);

// fetch 封装（失败降级空数组）
const fetchModels = useCallback(async () => {
  try {
    setModels(await getModels());
  } catch {
    setModels([]);
  }
}, []);

// 初始加载
useEffect(() => { void fetchModels(); }, [fetchModels]);

// token 变化时重拉
useEffect(() => onTokenChange(() => {
  setAuthRequired(false);
  void refreshSessions();
  void fetchModels();
}), [refreshSessions, fetchModels]);

// 422 未知模型时自动刷新目录
useEffect(() => {
  if (!error || !isUnknownModelError(error)) return;
  void (async () => {
    const list = await getModels().catch(() => []);
    setModels(list);
    setSelectedModel(prev => (prev && list.some(m => m.name === prev) ? prev : null));
  })();
}, [error]);
```

### createSession / handleSubmit 如何组装 POST body

```typescript
const handleSubmit = useCallback((task: string) => {
  focusRun();
  void submitTask({
    task,
    max_steps: 10,
    auto_approve: true,
    ...(selectedModel ? { model: selectedModel } : {}),
  });
}, [submitTask, focusRun, selectedModel]);
```

**关键观察**：`submitTask` 来自 `useSession()` hook。POST body 在 `handleSubmit` 中组装，当前只注入 `model` 字段。F1 需要在这里追加 `permission_mode` / `agent_profile` / `reasoning_effort` / `context_providers`。

### Composer 如何接收 props

```tsx
<Composer
  streaming={streaming}
  onSubmit={handleSubmit}
  onCancel={cancelStream}
  presetTask={presetTask}
  models={models}
  selectedModel={selectedModel}
  onModelChange={handleModelChange}
/>
```

F1 需要扩展 Composer props，传入四个新控件的数据和回调。

---

## 5. CSS 现状

**文件**：`web/src/styles/app.css`

### composer-wrap / composer-dock 布局

```css
.composer-wrap {
  padding: var(--space-sm) var(--space-lg) var(--space-lg);
}
.composer-dock {
  position: relative;               /* 子元素绝对定位锚点 */
  border-radius: var(--radius-lg);
  box-shadow: var(--edge-light), var(--shadow-popover);
  /* transition ... */
}
```

### composer textarea 布局

```css
.composer {
  display: block;
  width: 100%;
  padding: var(--space-md) 52px var(--space-md) var(--space-lg);
  /* font, min-height ... */
}
```

textarea 的 `padding-right: 52px` 只给 Send/Stop 按钮腾位置。

### ModelPicker trigger 样式

```css
.composer-model {
  appearance: none;
  align-self: flex-end;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 220px;
  padding: 3px var(--space-sm);
  font-size: var(--text-xs);
  font-family: inherit;
  color: var(--text-secondary);
  background: var(--surface-elevated);
  border: 0.5px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: ...;
}
```

### 关键发现：没有 control row 容器

当前布局是：
```
.composer-dock (position: relative)
  ├── .composer (textarea, block, width 100%)
  ├── ModelPicker (button.composer-model, align-self: flex-end)
  └── Send/Stop (button.composer-send/stop, position: absolute, right+bottom)
```

ModelPicker 的 `align-self: flex-end` 暗示 `.composer-dock` 曾经是或现在是 flex 容器，但从 CSS 看 `.composer-dock` 没有显式 `display: flex`——它靠 `position: relative` + 子元素绝对定位工作。ModelPicker 的 `align-self: flex-end` 在非 flex 容器中不生效，实际定位靠的是它在 DOM 中的位置（textarea 之后）和默认的 block/inline-block 流。

**F1 需要新增**：一个 `.composer-controls` 或 `.composer-row` 容器，放在 textarea 下方、Send/Stop 按钮之前，用 flex 布局横向排列五个控件。

---

## 6. 测试现状

### Composer.test.tsx

**文件**：`web/src/components/Composer.test.tsx`

SSR 契约测试模式：
- `renderToString(createElement(Composer, { ...base, models: [], ... }))`
- 断言 HTML 包含/不包含特定 class 名和文本
- 三条测试：① 端点缺席（models 空）→ 选择器不渲染 ② 目录在场 → trigger 渲染 + 显示「默认链」 ③ selectedModel 有值 → trigger 显示该模型名

### ModelPicker.test.tsx

**文件**：`web/src/components/ModelPicker.test.tsx`

同 SSR 契约模式，六条测试覆盖：空目录降级、trigger 渲染、选中态文本、已移除模型归一化、portal 内容不在 SSR、disabled 标记。

### e2e/fixtures.ts 中的 routeApi mock 模式

**文件**：`web/e2e/fixtures.ts`

```typescript
export interface ApiMock {
  sessions?: unknown[];
  events?: FrameSpec[];
  models?: unknown[];
  onSessionPost?: (route: Route) => Promise<void> | void;
  onStreamGet?: (route: Route) => Promise<void> | void;
}

export function routeApi(page: Page, mock: ApiMock): void {
  void page.route('**/api/**', async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === '/api/health') return route.fulfill(...);
    if (path === '/api/sessions' && req.method() === 'GET') return route.fulfill(...);
    if (path === '/api/sessions' && req.method() === 'POST') { ... }
    if (/^\/api\/sessions\/[^/]+\/events$/.test(path)) return route.fulfill(...);
    if (/^\/api\/sessions\/[^/]+\/stream$/.test(path)) { ... }
    if (path === '/api/models') return route.fulfill(...);
    return route.fulfill({ status: 404, ... });
  });
}
```

**关键观察**：`routeApi` 的 `ApiMock` 接口需要扩展四个新端点的 mock 数据字段。未 mock 的路径返回 404——F1 新增的四个端点如果不加入 mock，会触发 404 降级路径（前端 catch → 空数组 → 隐藏入口）。

### e2e/model-picker.spec.ts

**文件**：`web/e2e/e2e/model-picker.spec.ts`

Playwright 交互测试模式：
- `routeApi(page, { sessions: [], events: [], models: CATALOG })`
- `page.locator('.composer-model[aria-label="模型选择"]')`
- 键盘打开浮层 → 搜索过滤 → Esc 关闭 → 方向键 + Enter 选档 → trigger 文本更新

---

## 7. 权限模式端点现状

### 搜索结果

在 `D:\intelligence-agent-frontend\web` 目录下搜索 `permission-modes`、`permission_mode`、`agent-profiles`、`agent_profile`、`reasoning-efforts`、`reasoning_effort`、`context-providers`、`context_providers`：

**全部零命中。**

### 结论

前端**完全没有消费**这四个新端点。`api.ts` 中没有对应的 fetch 函数，`types.ts` 中没有对应的类型定义，`App.tsx` 中没有对应的状态管理，`Composer.tsx` 中没有对应的控件。

F1 是这些端点的首次前端集成。

---

## 8. 实现路径建议

### 8.1 新增文件

| 文件 | 用途 |
|------|------|
| `web/src/components/ControlPicker.tsx` | 通用单选控件（Permission Mode / Agent Profile / Reasoning Effort 共用），复用 ModelPicker 的 Popover + cmdk 模式 |
| `web/src/components/ContextProviderPicker.tsx` | Context Providers 多选控件，基于 ControlPicker 扩展 checkbox 语义 |
| `web/src/components/ControlPicker.test.tsx` | SSR 契约测试 |
| `web/src/components/ContextProviderPicker.test.tsx` | SSR 契约测试 |
| `web/e2e/control-row.spec.ts` | Playwright 交互测试（五控件联动 + payload 字段名验证） |

**替代方案**：如果不想新建 ControlPicker，可以直接在 ModelPicker 基础上泛化为 `SingleSelectPicker<T>`，让 ModelPicker 也成为它的实例。但这会改动已就位的 ModelPicker，违反 Scope Lock §8。建议新建 ControlPicker，与 ModelPicker 并存。

### 8.2 修改文件

| 文件 | 改动内容 |
|------|----------|
| `web/src/lib/api.ts` | 新增四个 fetch 函数 + 四个 entry 类型 + 扩展 `StartSessionPayload` |
| `web/src/types.ts` | 如需要，新增共享的 `CatalogEntry` 接口（id/display_name/description） |
| `web/src/components/Composer.tsx` | 扩展 Props 接口，在 textarea 下方新增 `.composer-controls` 行，渲染五个控件 |
| `web/src/App.tsx` | 新增四个 useState + 四个 fetch 函数 + 扩展 handleSubmit 组装 POST body |
| `web/src/styles/app.css` | 新增 `.composer-controls` flex 布局 + `.composer-control` trigger 样式（继承 `.composer-model` 同族） |
| `web/e2e/fixtures.ts` | 扩展 `ApiMock` 接口，新增四个端点的 mock 路由 |

### 8.3 四个控件的统一接口设计

#### 共享类型（`web/src/lib/api.ts` 新增）

```typescript
/** 通用目录条目——B1 契约：id / display_name / description。 */
export interface CatalogEntry {
  id: string;
  display_name: string;
  description: string;
}
```

#### ControlPicker props 签名

```typescript
interface ControlPickerProps {
  /** aria-label，也是 trigger title 的一部分。 */
  ariaLabel: string;
  /** 目录条目（来自端点）。空 → 返回 null（调用方隐藏入口）。 */
  entries: CatalogEntry[];
  /** 当前选中 id（null = 未选/默认）。 */
  selectedId: string | null;
  /** 选中回调；null 表示选了「默认」或取消选中。 */
  onChange: (id: string | null) => void;
  /** trigger 上显示的 icon。 */
  icon: LucideIcon;
  /** 未选中时 trigger 显示的 placeholder 文本。 */
  placeholder: string;
  disabled?: boolean;
}
```

#### ContextProviderPicker props 签名

```typescript
interface ContextProviderPickerProps {
  ariaLabel: string;
  providers: CatalogEntry[];          // GET /api/context-providers
  selectedIds: string[];              // 多选
  onChange: (ids: string[]) => void;
  icon: LucideIcon;
  placeholder: string;
  disabled?: boolean;
}
```

### 8.4 control row 的 CSS 布局方案

#### HTML 结构（F1 后）

```
<div className="composer-wrap">
  <div className="composer-dock surface-floating">
    <textarea ... />
    <div className="composer-controls">          ← 新增 control row
      <ModelPicker ... />
      <ControlPicker ... />                      ← Permission Mode
      <ControlPicker ... />                      ← Agent Profile
      <ControlPicker ... />                      ← Reasoning Effort
      <ContextProviderPicker ... />              ← Context Providers
    </div>
    {streaming ? <Esc提示 + Stop按钮> : <Send按钮>}
  </div>
</div>
```

#### CSS 方案

```css
.composer-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-xs);
  padding: 0 var(--space-sm) var(--space-sm);
}

/* 控件 trigger 继承 .composer-model 同族样式 */
.composer-control {
  /* 同 .composer-model 的 appearance / display / gap / padding / font / color / background / border / border-radius / cursor / transition */
}
```

**响应式考虑**：
- 桌面（≥1024px）：五个控件横排在一行，flex-wrap 允许换行。
- 平板（820px-1024px）：可能换行成两行，gap 保持。
- 手机（<820px）：控件可能需要折叠或滚动。但根据约束「Scope Lock §8：只加 Composer control row」，不应过度设计响应式——flex-wrap + gap 已经足够处理大多数情况。

**与 Send/Stop 按钮的关系**：
当前 Send/Stop 按钮靠 `position: absolute; right: var(--space-sm); bottom: var(--space-sm)` 定位在 dock 右下角。新增 control row 后，Send/Stop 按钮可以继续绝对定位（浮在 control row 右侧），或者改为在 control row 内作为最后一个 flex 子元素。建议后者更简洁。

### 8.5 测试策略

#### SSR 契约测试（vitest，`*.test.tsx`）

每个控件至少三条：

1. **正常选项**：entries 非空 → trigger 渲染 + 显示当前选中 label + aria-label 在场
2. **空目录隐藏**：entries = [] → 控件不渲染（return null）
3. **提交 payload 字段名对齐**：POST /api/sessions 请求体中 `permission_mode` / `agent_profile` / `reasoning_effort` / `context_providers` 字段名正确

第三条需要在 App 层面 mock fetch 并捕获 POST body，验证字段名和值。

#### e2e 交互测试（Playwright，`*.spec.ts`）

1. **routeApi mock 扩展**：`ApiMock` 接口新增 `permissionModes?` / `agentProfiles?` / `reasoningEfforts?` / `contextProviders?` 字段，routeApi 新增四条路由匹配。
2. **五控件联动**：打开页面 → 五个 trigger 可见 → 分别打开、选择、关闭 → trigger 文本更新。
3. **空目录降级**：mock 某端点返空数组 → 对应控件不渲染。
4. **POST payload 验证**：选完五个控件 → 填写 task → 发送 → 拦截 POST /api/sessions → 断言 body 含正确的字段名和值。

#### GUI QA 回归（6 档宽度）

手动或 Playwright 截图回归：
- 1440px：全展开，五控件横排。
- 1280px：同上。
- 1024px：可能换行。
- 820px：Inspector 折叠后空间变窄，控件可能换行成两行。
- 768px：更窄，控件可能需要 flex-wrap。
- 浅色主题：所有控件在浅色背景下可读、对比度达标。

---

## 9. 风险与注意事项

### 9.1 会话内真相仍是模型卡

控件只提交偏好到 `POST /api/sessions`，运行时是否消费由后端决定。当前 Phase 5 是 staged no-op——API 边界验证通过（未知值 → 422），运行时记一条 INFO 日志后忽略。UI 不应断言「已生效」。

### 9.2 空目录隐藏入口

`GET /api/context-providers` 当前诚实返空数组 `{"providers": []}`。空就是空，前端据空列表自行 fallback——隐藏 Context Providers 控件，不伪造。

### 9.3 Esc/Enter 冒泡满足 §19

Radix Popover 内部的 cmdk Command 在按 Esc 时会关闭浮层（§19「Esc 关闭最上层临时表面」）。Enter 在 cmdk 中选中当前 active item。这两个按键事件不应冒泡到 App 全局 Esc 中断监听——Radix Popover 的 `onOpenChange` 会处理关闭，App 的 Esc 监听有 `t.closest('[role="dialog"]')` 守卫，但 Popover 的 role 不是 dialog。需要确认 Radix Popover 打开时是否会阻止 App Esc 中断流式。

**建议**：在 ControlPicker 的 Popover.Content 上加 `onInteractOutside` / `onEscapeKeyDown` 处理，确保 Esc 先关闭浮层再冒泡。或者在 App 的 Esc 监听中增加守卫：检查 `document.activeElement` 是否在 Popover Content 内。

### 9.4 reduced-motion 守护满足 §18/§21

ModelPicker 已有 `@media (prefers-reduced-motion: reduce)` 守护，关闭入场动画。新控件复用同模式。

### 9.5 Scope Lock §8

只加 Composer control row，不动 Inspector / Workspace / Conversation 等既有区块。不提前做未来 Phase 的抽象。

### 9.6 从新 main 开新 feature branch

不从已合并的 `feat/frontend-c` 继续。新分支从最新 `main` 切出。

---

## 10. 总结

F1 的实现核心是**复制 ModelPicker 模式四次**（单选 × 3 + 多选 × 1），关键工作量分布：

| 工作项 | 估计复杂度 |
|--------|------------|
| `api.ts` 新增四个 fetch 函数 + 类型 | 低 |
| `types.ts` 新增 `CatalogEntry` 接口 | 低 |
| `ControlPicker.tsx` 新建（复用 ModelPicker 模式） | 中 |
| `ContextProviderPicker.tsx` 新建（多选扩展） | 中 |
| `Composer.tsx` 扩展 Props + 新增 control row JSX | 中 |
| `App.tsx` 新增四组状态 + fetch + handleSubmit 扩展 | 中 |
| `app.css` 新增 `.composer-controls` + `.composer-control` 样式 | 低 |
| `fixtures.ts` 扩展 ApiMock + 四条路由 | 低 |
| SSR 契约测试 × 2 文件 | 中 |
| e2e 交互测试 × 1 文件 | 中 |
| GUI QA 6 档宽度回归 | 低 |

**最大风险**：不是技术实现，而是**后端 B1 契约的对齐**——如果 B1 尚未交付端点，前端无法真正集成测试。建议先用 B1 契约文档中的 mock 数据跑通 SSR 契约测试和 e2e 交互测试，等 B1 交付后再做联调。
