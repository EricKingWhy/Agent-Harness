# ADR-0010: Capability Registry 与 Plugin Config

**Status**: Accepted
**Date**: 2026-09-05
**Phase**: 7 (Capability / Plugin Foundation + Skills)
**依据**: spec 08（全文）、13 §3（Capability seam PORT DESIGN）、13 §5（Registry 属 BUILD）、14 Phase 7 交付与 Gate

## Context

Phase 6 已有一条竖切 Capability seam（`MemoryCapability` Protocol → `LangMemMemoryCapability` Provider → `MemoryContextProvider` Consumer），但它是点对点接线：Web 装配代码直接 import 具体 Provider 类。Phase 7 要把这条 seam 泛化成通用机制，使"新增领域能力（如 Finance）不修改 Agent Core"成为结构保证（spec 08 §1、§8）。同时必须守住：插件不能绕过 Tool Permission / Operation Ledger（08 §9）、Optional 故障降级（08 §7）、Consumer 使用前检查 descriptor（08 §5）。

## Self-grill 决策

### Q1：Registry 的接口形状？
**决策**：命名 Registry，五个方法：`register(descriptor, provider)` / `get(name)`（缺失抛 `CapabilityError("not_found")`）/ `optional(name)`（缺失返回 None → OPTIONAL 降级路径）/ `descriptor(name)` / `available()`。重复注册同名抛错（不做静默覆盖——静默覆盖正是 08 §5 禁止的"接受但忽略"的温床）。
**理由**：08 §3"Provider 可多实例共存时使用命名 Registry"；V1 显式注册（08 §6），不做 entry-point 扫描、不做 Marketplace。
**后果**：Provider 实例化发生在注册前（factory 函数），Registry 本身零生命周期魔法。

### Q2：Descriptor 字段与校验时机？
**决策**：Pydantic 模型，字段严格取 08 §5 清单：`name / version / provider_name / capabilities[] / risk / supports_streaming / supports_recovery / supports_concurrency / config_schema`，外加两个本项目必需位：`degradation`（REQUIRED_CORE / OPTIONAL_RUNTIME / OPTIONAL_OBSERVABILITY，08 §7 三分类）与 `enabled`。提供 `supports(capability: str) -> bool`；Consumer 使用前 MUST 检查，不支持时抛 `CapabilityError("unsupported")`——显式报错，绝不静默忽略（08 §5 原文）。
**理由**：字段清单是规格原文，不自创；`degradation` 是 08 §7 分类的载体，`enabled` 是"按配置启停"（08 §9 验收 3）的载体。
**后果**：health/availability 字段 08 标注"按需"——V1 不做健康检查轮询，DEFER。

### Q3：错误词汇表？
**决策**：`CapabilityError(RuntimeError)` + 四个码：`not_found`（注册表无此能力）、`unsupported`（有此能力但 descriptor 不支持所需子能力）、`disabled`（配置显式停用）、`init_failed`（装配期失败：factory 构造失败 / 注册冲突 / config 非法）。全部显式抛出。另：`unsupported` 在 V1 是保留码——唯一 Consumer 由显式装配选定，还没有按子能力在多 Provider 间挑选的场景，Consumer 侧检查随多 Provider 选择一起落地（DEFER）。
**理由**：08 §2 要求 error vocabulary；四个码恰好覆盖 §9 验收的 3/4/5 三条失败形态。

### Q4：Plugin Config 的来源与形状？
**决策**：Settings 新增 `CAPABILITIES` 环境变量（JSON 字符串），结构 `{"<capability_name>": {"provider": "<provider_name>", "enabled": bool, "options": {...}}}`，经 Pydantic TypeAdapter 校验为 `CapabilityConfigMap`。装配函数 `wire_capabilities(registry, config, tool_registry, context_providers)` 按配置驱动 builtin factory。配置缺省 = `{}` = 只有 REQUIRED_CORE 检查，零行为变化。
**理由**：本项目配置一贯走 .env + pydantic（config.py），不引入第二套 YAML 配置文件；08 §6 的 YAML 是"示例形态"，其本质要求是"显式配置加载"——JSON env 满足同一本质且零新依赖。
**后果**：`config_schema` 字段 V1 只做声明与文档（消费方 `options` 直接透传 factory），不做 JSON Schema 运行时校验——DEFER，等第二个真实 Consumer 出现再收紧。

### Q5：builtin factory 注册哪些？
**决策**：V1 只登记两个 factory：(1) `memory` → `LangMemMemoryCapability`（需 `[memory]` extra + 配置齐，同 Phase 6 Web 装配逻辑，迁入 factory 后 `_build_runtime` 不再直接 import 具体 Provider 类——这正是 08 §9 验收 1"切换 Memory Provider 不改 Core"的落点）；(2) `demo` → `TickerCapability`（Gate 用最小 demo：一个 `tick` 工具贡献进 ToolRegistry，走统一 Executor）。Artifact 不迁——ArtifactStore ABC 已是 seam 且 Phase 5 Gate 稳定，改动收益为零（Scope Lock）。
**理由**：08 §9 验收 1 需要 memory 走 Registry 证明"换 Provider 不改 Core"；Gate"新增 demo capability 不改 Agent Loop"需要 demo 实证。

### Q6：Capability 如何贡献 Tool / ContextProvider？
**决策**：不定义强制基类。贡献走**装配侧约定**：`wire_capabilities` 内置对已知 capability 的接线（memory → MemoryContextProvider + memory_writer；demo → 其 tools）。Capability 包提供 `ContributesTools` / `ContributesContextProviders` 两个可选 Protocol，实现了的 provider 由装配函数统一收集，工具一律进 ToolRegistry（统一 Executor 路径，08 §9 验收 6）。
**理由**：08 §4 列了五种 Consumer，强制单一贡献接口会造出"万能 Provider"假抽象；V1 只有 2-3 个接线点，显式装配比反射式发现更可读（08 §6：不要一开始实现复杂机制）。
**后果**：新增 capability 的成本 = 写 factory + 在 wire_capabilities 加一段显式接线（改的是装配层，不是 Agent Loop——满足 Gate 1 的字面与精神）。

## Consequences

- `AgentRuntime`（Agent Loop）零改动——Gate 1 的结构保证。
- Web `_build_runtime` 的 Memory 装配代码改为走 registry；REQUIRED_CORE 缺失在装配期显式失败，OPTIONAL 缺失返回 None 降级（与 Phase 6 行为一致）。
- Registry 是进程内单例（挂在 AppState），无跨进程语义——DEFER。

## 补充（T5/#62，2026-09-05）：装配期 factory 失败的降级语义

`_BUILTIN_WIRING` 每项带该能力声明的降级档位：`wire_capabilities` 里 OPTIONAL capability 的 factory 抛错（外部依赖故障等）→ 记 warning 并跳过装配；REQUIRED_CORE → 向上抛。失败的能力不会出现在 Registry，Consumer 走 `optional()` 的 None 降级路径。两层分工：capability 代码内部仍显式抛 `init_failed`（Q5 不变），**装配边界**按 08 §7 决定降级还是失败。实证见 `tests/capability/test_phase7_gate.py::TestDegradation`。
