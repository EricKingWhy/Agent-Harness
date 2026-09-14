# 两个 Ticket 提示词：context_providers 运行时消费（B2）+ 多选控件（F3）

> **给后端 AI 和前端 AI 的任务提示词。**
> **依赖关系**：B2 是 F3 的前置——B2 落地后 `GET /api/context-providers` 才会返真实清单，F3 的多选控件才有数据可消费。
> **顺序**：先做 B2，B2 集成入 main 后再开 F3。

---

## Ticket B2：context_providers 运行时消费（给后端 AI）

### 背景

Phase 5 把 `context_providers` 作为 staged 契约接收（POST `/api/sessions` 的 `CreateSessionRequest` validator 接受 `context_providers: list[str]`）。当前 runtime 完全忽略这个参数——用户提交了想启用哪些 provider，但 `build_runtime` 只打 no-op 日志就丢弃了。

同时，`agent_profile` 和 `reasoning_effort` 已分别在 ADR-0020a 和 `79e2860` 落地运行时消费。`context_providers` 是 RUNTIME sub-tickets 的最后一个待落地字段。

### 现状（已为你摸清，不用重新扫描）

```
src/agent_harness/
├── context/
│   ├── provider.py      # ContextProvider Protocol: async def select(session, token_budget) -> list[AnyMessage]
│   └── builder.py       # ContextBuilder 已支持 context_providers: list[ContextProvider]，经 _with_providers 按预算注入
├── capability/
│   └── wiring.py        # conditional append：MemoryContextProvider + SkillCatalogContextProvider → wiring.context_providers
├── memory/
│   └── context_provider.py     # MemoryContextProvider 实现
├── skills/
│   └── context_provider.py     # SkillCatalogContextProvider 实现
├── assembly.py          # build_runtime：context_providers: list[str] 参数当前 no-op（line 130-131）
└── web/
    └── app.py           # GET /api/context-providers 当前诚实返空 {"providers": []}
```

**关键 gap**：
1. `wiring.context_providers` 装配的是 **provider 实例列表**（基于配置开关 conditional append），没有稳定的 **provider id**——无法被用户的 `context_providers: list[str]` 引用。
2. `build_runtime` 收到用户的 `context_providers: list[str]` 后，没有 registry 去查找对应的 provider 实例——即使想消费也找不到东西。
3. `GET /api/context-providers` 不知道 wiring 装配了哪些 provider（wiring 是 runtime conditional，没有静态清单），所以诚实返空。

### 要做什么

让用户通过 web 层提交的 `context_providers: list[str]` 真正影响 runtime 装配的 provider 集合。具体：

1. **给 wiring 装配的 provider 赋予稳定 id**：在 `capability/wiring.py` 的 conditional append 处，把每个 provider 关联一个稳定 id（如 `"memory"` / `"skills"`）。需要一个数据结构把 id → provider 实例的映射暴露出来（不是裸 list）。注意 wiring 当前是 conditional append（基于配置开关），id 注册要尊重这个条件——配置关了就不注册。

2. **build_runtime 消费用户的 context_providers**：用户传了 `context_providers: list[str]` → 用这些 id 从 wiring 的 registry 里 filter 出用户选中的 provider 实例，传给 ContextBuilder。用户不传（None）→ 用 wiring 装配的全集（当前默认行为，向后兼容）。

3. **GET /api/context-providers 返真实清单**：从 wiring 的 registry 派生 `CatalogEntry` 列表（id / display_name / description），不再诚实返空。注意：wiring 是 runtime conditional（取决于 settings），端点应该反映**当前配置下实际装配的 provider 集合**，而不是静态全集。

4. **validator 更新**：`CreateSessionRequest` 的 `context_providers` validator 当前可能接受任意 `list[str]`——应该校验 id 集合是否在当前装配的 registry 内（与 `agent_profile` / `reasoning_effort` 的单一事实源模式一致，Reuse First §6）。

### 必须守住的约束

- **不变量 #16**：Memory = Capability + Context Provider。provider 是 capability，不是写死进 Agent Loop 的特判。
- **不变量 #17**：LangMem 只是默认 Provider，可替换。registry 机制不能把 MemoryContextProvider 硬编码。
- **不变量 #6**：完整保存 ≠ 完整注入。ContextBuilder 已有 token budget 机制，不要绕过。
- **向后兼容**：`context_providers=None` → wiring 装配的全集（当前行为）。
- **诚实原则**：配置关了的 provider 不出现在 registry / GET 清单里，validator 也不接受它。
- **Scope Lock §8**：只做 context_providers 运行时消费，不顺手重构 wiring 或 ContextBuilder 的其他部分。
- **§9.2 Simplicity First**：最小改动。如果只需要在 wiring 里加一个 id 映射层，不要造一个完整的 provider registry subsystem。

### 验收标准

- [ ] 用户传 `context_providers: ["memory"]` → runtime 只启用 MemoryContextProvider（不启用 skills）
- [ ] 用户传 `context_providers: []` → runtime 不启用任何 provider（用户显式选了空）
- [ ] 用户不传 `context_providers` → runtime 用 wiring 全集（向后兼容）
- [ ] 用户传不存在的 id → validator 422
- [ ] `GET /api/context-providers` 返当前配置下实际装配的 provider 清单（非空，如果配置开了的话）
- [ ] 配置关了某个 provider → 该 provider 不出现在 GET 清单，validator 也不接受
- [ ] 全量 pytest 0 failed（Python 3.13 环境）
- [ ] ruff clean
- [ ] ADR 记录关键决策（如 "wiring registry 的边界"、"'空列表 vs None' 语义"）

### 测试要求

- 至少 3 条 assembly 测试：用户选中子集 / 空列表 / None 默认
- 至少 1 条 validator 测试：不存在的 id → 422
- GET 端点测试：返当前装配清单（参照 `test_web_phase5_staged_endpoints.py` 模式）
- 不要破坏现有的 MemoryContextProvider / SkillCatalogContextProvider 测试

### 参考

- `src/agent_harness/assembly.py` line 116 / 130-131（当前 no-op）
- `src/agent_harness/capability/wiring.py` line 77-105 / 141-165（conditional append 模式）
- `src/agent_harness/context/builder.py`（ContextBuilder 已支持 context_providers，无需改）
- ADR-0020a（agent_profile 运行时消费的先例）
- `79e2860`（reasoning_effort 运行时消费的先例）

---

## Ticket F3：context_providers 多选控件（给前端 AI）

> **前置**：B2 必须先集成入 main。B2 落地后 `GET /api/context-providers` 会返真实清单（非空），本 ticket 才有数据可消费。

### 背景

Phase 2b 的 Composer control row 已落地（F1，`20116b1`），含三个 **单选** ControlPicker（Permission Mode / Agent Profile / Reasoning Effort）。但 `context_providers` 从设计上是 **多选**——用户可以同时启用 memory + skills 等多个 provider。

当前前端：
- `ControlPicker.tsx` 是单选控件（Popover + cmdk Command，与 ModelPicker 同模式）
- `context_providers` 目录空时 ControlPicker `return null` 不渲染
- `api.ts` 的 `StartSessionPayload.context_providers` 字段类型当前是什么？需要确认（可能是 `string | null` 单选形态，需要改成 `string[]`）

B2 落地后，`GET /api/context-providers` 会返 `{"providers": [{id, display_name, description}, ...]}`——目录非空，ControlPicker 会渲染，但它是单选，无法满足多选需求。

### 要做什么

为 `context_providers` 提供一个**多选控件**。两个选项：

**选项 A（推荐）**：新建 `MultiSelectPicker.tsx`（复用 ControlPicker 的 Popover + cmdk Command 模式，但支持 `selectedIds: string[]` + toggle 语义）。Composer control row 里用它替代 context_providers 那个位置的 ControlPicker。

**选项 B**：扩展 ControlPicker 加 `multiple?: boolean` prop。单选走原路径，多选走 toggle 路径。

选哪个看哪个改动更小、更符合 §9.2 Simplicity First。推荐 A——单选和多选的交互语义差异足够大（确认型 vs 累加型），强行塞进一个组件会增加内部分支。

### 必须守住的约束

- **不变量 #6**：完整保存 ≠ 完整注入。前端只负责让用户选哪些 provider，不管 provider 怎么消费 budget——那是 ContextBuilder 的事。
- **a11y**：多选控件的角色语义是 `role="listbox"` + `aria-multiselectable="true"`（不是单选的 `aria-pressed`）。cmdk 的 listbox 可能已经支持，需要验证。
- **空目录降级**：B2 落地后 GET 端点会返真实清单，但如果用户配置关了所有 provider（返空），多选控件仍要 `return null` 不渲染（与 ControlPicker 同原则：空就是空，不伪造）。
- **键盘导航**：与 ControlPicker 同——Tab 进 trigger / Enter 打开 / 方向键移动 / Space 或 Enter toggle 选中 / Esc 关闭（§19）。
- **Scope Lock §8**：只加 context_providers 多选控件，不改 Permission / Agent / Reasoning 的单选 ControlPicker。
- **POST 契约**：`context_providers` 在 POST body 里是 `string[]`（不是单选 string）。空数组 = 用户显式选了不启用任何 provider；不传字段 = 用后端默认（与 B2 的语义对齐）。

### 验收标准

- [ ] 多选控件渲染（当 `GET /api/context-providers` 返非空目录时）
- [ ] 多选控件不渲染（目录空时 `return null`）
- [ ] 用户可以 toggle 选中 / 取消选中多个 provider
- [ ] trigger 显示已选数量或已选 id 列表（看哪个 UX 更好）
- [ ] 键盘导航：Tab / Enter / 方向键 / Space toggle / Esc 关闭
- [ ] POST body 的 `context_providers` 是 `string[]`
- [ ] tsc / oxlint / Vitest / build 全绿
- [ ] Playwright e2e：多选交互（参照 `control-row.spec.ts` 模式）
- [ ] 不破坏现有的三个单选 ControlPicker

### 参考

- `web/src/components/ControlPicker.tsx`（单选先例）
- `web/src/components/ModelPicker.tsx`（Popover + cmdk 模式源）
- `web/src/lib/api.ts`（`StartSessionPayload` + `getPermissionModes` 等 fetch 函数）
- `web/e2e/control-row.spec.ts`（e2e 模式）
- B2 的 `GET /api/context-providers` 契约（落地后）

### 工作流

1. 等 B2 集成入 main
2. 从新 main 开 `feat/frontend-context-providers`（或你选的分支名）
3. `pnpm install` 确认依赖
4. 实现多选控件 + Composer 集成 + api.ts 扩展
5. 四门禁 + Playwright e2e
6. 写交接单，交给 Git Integrator 集成

---

## 集成顺序总览

```
B2（后端，context_providers 运行时消费）
  ↓ 集成入 main
F3（前端，context_providers 多选控件）
  ↓ 集成入 main
RUNTIME sub-tickets 全部完成 ✅
```
