# GOAL: `context_providers` 运行时真实消费（RUNTIME 子批次，ADR-0020b）

> **批次定位**：Phase 5 RUNTIME 第三批（继 `agent_profile`[ADR-0020a] / `reasoning_effort` 之后）。
> **分支**：`feat/runtime-context-providers`，从 `origin/main`（`d7cb1c7`）起。
> **范围**：把会话级 `context_providers: list[str] | None` 从 staged no-op 提升为运行时真实消费——按名字筛选本次装配好的 ContextProvider 子集注入 ContextBuilder。
> **不在范围**：新建 ContextProvider、改 ContextBuilder 注入顺序、改 provider select 预算逻辑、feat/multiturn SessionService。
> **不变量守护**：#5（Persistent History ≠ Runtime Context）、#16（Memory = Capability + Context Provider）、#21（Optional Capability 故障不拖垮 Core）。

---

## 1. 现状勘察（已验证）

### 1.1 会话请求字段已接收但无 validator
- `CreateSessionRequest.context_providers: list[str] | None`（`web/app.py:132`）。
- **没有 `_validate_context_providers`**——不像 `reasoning_effort` / `agent_profile` 都有 validator 422 拒绝未知值。当前任意字符串透传到 `build_runtime`。
- 经 `build_runtime(..., context_providers=req.context_providers)`（`web/app.py:914`）传入 assembly。

### 1.2 assembly 层 staged no-op
- `build_runtime(context_providers: list[str] | None = None, ...)`（`assembly.py:116`）。
- 仅记 INFO 日志后忽略（`assembly.py:130-131`）：
  ```python
  if context_providers is not None:
      logger.info("context_providers=%s received but not yet consumed by runtime", context_providers)
  ```
- ContextBuilder 已接收 `context_providers=list(wiring.context_providers)`（`assembly.py:246`）——**这是 wiring 自动装配的全量集合，不受会话请求字段影响**。

### 1.3 已装配的 ContextProvider（wiring 注入路径）
- `MemoryContextProvider`：`capability/wiring.py:105`，仅当 memory capability 配置且 components 初始化成功才 append。
- `SkillCatalogContextProvider`：`capability/wiring.py:165`，仅当 skills capability 配置且 catalog 非空才 append。
- 二者均实现 `ContextProvider` Protocol（`context/provider.py:10`，单 `select(session, token_budget)` 方法）。
- **目前没有任何稳定 `name` 属性**——只有类名。会话请求要用字符串筛选，需要稳定标识符。

### 1.4 清单端点诚实返空（撒谎但 harmless）
- `GET /api/context-providers`（`web/app.py:796`）：硬编码 `{"providers": []}`，注释说「当前未装配任何 provider」。
- **事实**：当 CAPABILITIES 配了 memory/skills 时，`wiring.context_providers` 是有内容的；端点没暴露是因为本批之前没有稳定 id 抽象。
- `tests/web/test_web_phase5_staged_endpoints.py::TestContextProviders::test_empty_by_default_is_honest`：在 bare_client（无 CAPABILITIES）下断言返空——本批需保留这条仍通过（bare 下确实空）。

### 1.5 ContextBuilder 已消费 provider 列表
- `ContextBuilder._with_providers`（`context/builder.py:149`）：已遍历 `self.context_providers` 调 `select()` 注入消息。
- 即 **runtime 注入机制本身已完成**；本批只解决「会话请求字段 → 选哪些 provider」这一段。

---

## 2. 设计决策

### 2.1 Provider 稳定标识：`name` 类属性
两个具体 provider 各加一个类级 `name` 字符串常量：
- `MemoryContextProvider.name = "memory"`
- `SkillCatalogContextProvider.name = "skills"`

**为什么不用 Protocol 强制**：现有 Protocol 只声明 `select`；强加 `name` 会冲击所有未来 provider 在同一批落地。改 Protocol 是独立动作；本批只在两个具体实现上加属性，再用 `getattr(p, "name", None)` 容错读取（未来未命名 provider 不会被筛选命中，但不报错——fail-open）。同步把 `name: str` 加进 Protocol 是合适的，但为了 Scope Lock §8 最小化，本批只在具体类上加属性 + Protocol 加注释（不强约束）。

### 2.2 会话级筛选语义
`context_providers: list[str] | None` 传入 `build_runtime` 后：
- **`None`（默认）**：不筛选——所有已装配 provider 全部生效（向后兼容，现行为不变）。
- **非空 list**：仅保留 `wiring.context_providers` 里 `name ∈ context_providers` 的子集注入 ContextBuilder。
- **空 list `[]`**：显式选零个——不注入任何 provider（用户明确想跑一个「纯净」上下文）。与 `None` 语义不同（None=默认全量，[]=显式空）。
- **未知名字**：不报错——fail-open 跳过（与 capability OPTIONAL_RUNTIME 降级原则一致）。前端 `/api/context-providers` 清单是合法来源；用户手搓未清单名字时跳过比 422 更宽容（不影响 Core）。

**为什么不像 agent_profile/reasoning_effort 那样 422**：那两个字段是封闭枚举（三档 profile / 三档 effort），未知值是配置错误；context_providers 是动态依赖装配状态的开放集合，未装配时清单为空，validator 没法静态判定「这个名字以后会不会被装配」。运行时跳过更合适。

### 2.3 清单端点投影真实装配状态
`GET /api/context-providers` 改为读 `wiring.context_providers`，按 `name` 投影：
```json
{"providers": [
  {"id": "memory", "display_name": "Memory", "description": "..."},
  {"id": "skills", "display_name": "Skills", "description": "..."}
]}
```
- 未装配（bare 配置）→ 仍返 `{"providers": []}`——`test_empty_by_default_is_honest` 继续通过。
- display_name / description 用本批新建的 `CONTEXT_PROVIDER_DESCRIPTIONS` 常量（同 `REASONING_EFFORT_DESCRIPTIONS` 模式）。
- 仅当 capability 实际装配时对应 provider 才出现（动态投影，不伪造）。

### 2.4 ContextBuilder 接收筛选后的子集
`build_runtime` 在构造 `ContextBuilder` 前，对 `wiring.context_providers` 应用筛选：
```python
selected = _select_context_providers(wiring.context_providers, context_providers)
# ...
ContextBuilder(..., context_providers=list(selected), ...)
```
其中：
```python
def _select_context_providers(
    wired: list[Any], requested: list[str] | None,
) -> list[Any]:
    if requested is None:
        return list(wired)  # 默认全量
    wanted = set(requested)
    return [p for p in wired if getattr(p, "name", None) in wanted]
```

### 2.5 不改 AgentRuntime / ContextBuilder 内部
- `AgentRuntime.__init__` 已支持 `context_providers`（`runtime.py:265`）。
- `ContextBuilder` 已支持遍历注入（`builder.py:149`）。
- 本批不动这两个文件——只改 assembly 的筛选层 + 两个具体 provider 加 `name` + web 端点投影 + validator 补齐。

---

## 3. 改动清单

### 3.1 `src/agent_harness/memory/context_provider.py`
- `MemoryContextProvider` 加类属性 `name = "memory"`。

### 3.2 `src/agent_harness/skills/context_provider.py`
- `SkillCatalogContextProvider` 加类属性 `name = "skills"`。

### 3.3 `src/agent_harness/assembly.py`
- 移除 `context_providers` 的 no-op INFO 日志（`assembly.py:130-131`）。
- 加 `_select_context_providers(wired, requested)` helper（模块级函数）。
- 在 `ContextBuilder(...)` 构造处用筛选后的列表替代 `list(wiring.context_providers)`。

### 3.4 `src/agent_harness/web/app.py`
- 加 `CONTEXT_PROVIDER_DESCRIPTIONS: dict[str, dict[str, str]]` 常量（`memory` / `skills` 两键，与两个 provider 的 `name` 对齐）。
- 加 `CreateSessionRequest._validate_context_providers` validator：检查请求里的字符串非空、类型合法（不 422 未知名字——见 §2.2）；若需要可在 docs 注释解释为什么不 422 未知值。
- `GET /api/context-providers` 端点改为读 `wiring.context_providers` 按 `name` 投影，display_name/description 取 `CONTEXT_PROVIDER_DESCRIPTIONS`。
- 更新相关注释从「staged no-op」改「runtime consumed」。

### 3.5 SDD 文档
- `docs/spec/Observable_Agent_Workspace_SDD/03_RUNTIME_EVENT_CONTRACT.md`：`context_providers` 从 `phase: staged` 改「runtime consumed（按名字筛选已装配 provider 子集）」；至此 reasoning_effort / agent_profile / context_providers 三个 RUNTIME 字段全部消费完毕。
- `docs/spec/Observable_Agent_Workspace_SDD/08_DECISION_LOG.md`：ADR-0020 末尾追加 RUNTIME 三批落地小结。
- 新增 `docs/adr/0020b-context-providers-runtime-consumption.md`：记录本批决定（为什么用类属性而非 Protocol 强约束；为什么未知名字 fail-open 而非 422；为什么 None vs [] 语义有别；为什么清单端点动态投影而非静态枚举）。

---

## 4. 测试

### 4.1 改动既有测试
- `tests/web/test_web_phase5_staged_endpoints.py::TestContextProviders`：
  - `test_empty_by_default_is_honest`：bare_client（无 CAPABILITIES）仍返 `[]`——保留。
  - `test_schema_locked`：增加 `display_name` / `description` 字段断言（schema 形态对齐 efforts/profiles）。
  - `test_top_level_key_stable`：保留。
  - 需新增一条：CAPABILITIES 配了 memory/skills 时端点返回两条（用带配置的 fixture）。本批可放在独立测试文件避免冲击 staged_endpoints 测试的 bare 假设。

### 4.2 新增测试
**`tests/test_assembly_context_providers.py`**：
- `test_build_runtime_none_request_keeps_all_providers` — `context_providers=None` → wiring 全量注入（向后兼容）。
- `test_build_runtime_empty_list_injects_no_providers` — `context_providers=[]` → ContextBuilder.context_providers 为空（显式零）。
- `test_build_runtime_subset_filters_to_named` — `context_providers=["memory"]` 且 wiring 有 [memory, skills] → 只注入 memory。
- `test_build_runtime_unknown_name_silently_skipped` — `context_providers=["nonexistent"]` → 空列表（fail-open，不抛错）。
- `test_build_runtime_unknown_plus_known_keeps_known` — `context_providers=["memory", "ghost"]` → 只留 memory。

**`tests/web/test_context_providers_endpoint.py`**（新文件）：
- `test_endpoint_returns_wired_providers_when_capabilities_configured` — 用带 CAPABILITIES 的 settings 启 app，断言返 memory + skills 两条。
- `test_endpoint_provider_schema` — 每条含 id / display_name / description。
- `test_endpoint_id_matches_provider_name_attribute` — 端点返回的 id 集合 == 实际 wiring 里 provider 的 `name` 集合。

**`tests/memory/test_context_provider.py` / `tests/skills/test_context_provider.py`**（如果存在）或就近测试：
- `test_memory_provider_has_name_attribute` — `MemoryContextProvider.name == "memory"`。
- `test_skills_provider_has_name_attribute` — `SkillCatalogContextProvider.name == "skills"`。

### 4.3 不需要改的既有测试
- `tests/test_assembly.py`：4 个 build_runtime 调用默认 None → 全量注入，行为不变。
- `tests/agent/test_context_runtime.py`：测试 builder/runtime 的 provider 注入路径，不动。
- `tests/capability/*`：测试 wiring 自动 append，不动。

---

## 5. 实施顺序（TDD 切片）

1. **切片 A — Provider `name` 属性**（纯加法）：给两个 provider 加 `name` 类属性 + 2 条断言测试。先红后绿。
2. **切片 B — assembly 筛选层**：加 `_select_context_providers` + 改 build_runtime 用筛选结果 + 移除 no-op 日志 + 5 条筛选测试。
3. **切片 C — web 清单端点投影**：加 `CONTEXT_PROVIDER_DESCRIPTIONS` + 改端点动态投影 + 3 条端点测试 + 更新 staged_endpoints 测试 schema 断言。
4. **切片 D — validator + SDD 文档 + ADR**。
5. **全量回归**：`pytest`（基线 1264 tests）+ `ruff check`。

---

## 6. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 改清单端点返非空破坏 `test_empty_by_default_is_honest` | bare_client（无 CAPABILITIES）下 wiring 确实无 provider → 仍返 `[]`；测试用 bare 场景不变 |
| 加 validator 422 未知名字破坏现有行为 | 本批 validator **不** 422 未知名字（fail-open）；只校验类型与非空字符串 |
| None vs [] 语义混淆导致误删全量 | 单独测试两条 case：None 全量、[] 空集合；assembly helper 显式分支 |
| 未来无 `name` 的 provider 被 getattr 跳过 | 用 `getattr(p, "name", None)` 容错；未命名 provider 不被任何请求名字命中（fail-open 一致） |
| ContextBuilder 已注入逻辑被本批误改 | 本批不改 builder.py；只改传入它的列表内容 |

---

## 7. 完成判据（Gate）

- `pytest` 全绿（含新增测试；基线 1264 不破）。
- `ruff check` 清洁。
- `context_providers=None`（默认）→ wiring 全量注入（向后兼容）。
- `context_providers=["memory"]` → 仅注入 MemoryContextProvider。
- `context_providers=[]` → 不注入任何 provider（显式零，区别于 None）。
- `context_providers=["unknown"]` → 空注入（fail-open，不抛错）。
- `GET /api/context-providers`：bare 配置返 `[]`；CAPABILITIES 配了 memory+skills 返两条带 display_name/description。
- `MemoryContextProvider.name == "memory"`、`SkillCatalogContextProvider.name == "skills"`。
- SDD `03` + ADR-0020 末尾 + 新 ADR-0020b 记录本批决定。
- commit 一条：`feat(runtime): context_providers 运行时真实消费——按名字筛选已装配 provider 子集注入 ContextBuilder（RUNTIME 子批次，ADR-0020b）`。

---

## 8. 分支起点说明

本批从 `origin/main`（`d7cb1c7`）起新分支 `feat/runtime-context-providers`，工作在 `D:\intelligence-agent-runtime` worktree。
理由：
- `feat/backend` 当前有另一 AI 会话的未提交工作（T5 #135 MinIO externalization 在写 assembly.py），并行写入会违反 §13.3。
- runtime worktree 在 reasoning_effort 已合 main 后空置，复用为隔离施工区合规。
- 本批改动集中在 `assembly.py` / `memory/context_provider.py` / `skills/context_provider.py` / `web/app.py`，与 T5（也在改 assembly.py 不同区域）无文本冲突，但隔离开发避免并行写入风险。
