# ADR-0024 — Memory Provider Seam：`MemoryComponents` 作为 provider 边界 + 装配期真分派

**Status**: Accepted
**Date**: 2026-09-12
**Related**: ADR-0008（Memory Capability 架构）、ADR-0010（CapabilityRegistry 与插件配置）、
`docs/RESEARCH_PROJECT_MULTISESSION_AND_MEMORY_PLUGGABILITY.md` §1.4（seam 的 A/B 取舍）
与 ticket #149 body 的上游一手调研表（Mem0 / Zep-Graphiti / Letta 的存储归属证据；
排除 C 方案的理由见下文 D1，是本次决策自己的推理而非 §1.4 的结论）
**Supersedes**: 无。**Refines**: ADR-0008 的**两个**子决策——
① 子决策 2 里"换 Provider 时只换 `MemoryCapability` 实现"的隐含边界**不够**，实际边界是整个
`MemoryComponents` 包（下文 D1）；② 子决策 4「存储主权归我们」（SQLite 权威 / Milvus 索引）
**收敛为 `builtin` provider 的内部性质**，不再是跨所有 provider 的普遍不变量（D1 的直接后果）。

---

## Context

### 规格早已要求可插拔

- 不变量 #16：**Memory = Capability + Context Provider**。
- 不变量 #17：**LangMem 只是默认 Provider，可替换 Mem0 / 自研**。

### 代码没实现，且比"不能换"更糟

三处证据（ticket #149 背景节）：

| 位置 | 现状 |
| --- | --- |
| `capability/wiring.py` `_KNOWN_PROVIDERS["memory"]` | `{"builtin","langmem"}` —— **名字被接受** |
| `capability/wiring.py` `CapabilityDescriptor(..., provider_name=cfg.provider)` | 配置值被**如实**写进描述符 |
| `capability/factories.py` `build_memory_components(settings)` | 签名里没有 provider，`LangMemMemoryCapability` 是无条件 import —— **两个名字走同一条路** |

后果：**描述符会声称一个并未生效的 provider**。今天配 `provider: "mem0"` 会在装配期被白名单拒掉（响亮失败，可接受）；但一旦有人把 `"mem0"` 加进白名单而忘了接分派，系统就**静默用 LangMem 而对外自称 mem0**——正是 spec 08 §5「不允许接受但静默忽略」要防的形状。

### 上游一手调研：想做"记忆产品"的几乎都自带存储

| Provider | 存储归属 | 证据 |
| --- | --- | --- |
| LangMem | 跑在调用方给的 `BaseStore` 上 | README「functional primitives you can use with any storage system」 |
| Mem0 | **自带存储层** | `mem0/configs/base.py` 有 `vector_store` 默认 + `history_db_path`；25 个向量后端含 `milvus.py` |
| Zep / Graphiti | **硬依赖图数据库** | `pyproject.toml` 依赖 `neo4j>=5.26.0`（可选 FalkorDB / Neptune） |
| Letta | server 形态，自带状态 | README 自述 App Server + SDK + Cloud |

---

## Decision

### D1 — provider 的边界 = **整个 `MemoryComponents` 包**（选 A，不选 B/C）

一个 memory provider 换掉的是 **capability + records + vectors + relay + writeback 五件套**；
Agent Loop 侧契约（`MemoryWriteback` / `MemoryContextProvider` / `MemoryCapability` Protocol）**不变**。

**为什么不是 B（只换 `MemoryCapability`）**：Mem0 / Zep 这类自带存储的后端会被迫套进我们的
`SqliteMemoryRecordStore` + `MilvusVectorStore` + `OutboxRelay` 管线，等于把供应商塞进别人的存储模型——
"可插拔"名存实亡。自由度最大、重复实现最多的 A 才是真的插拔。

**为什么不是 C（provider 可选自带存储的分层双契约）**：两套生命周期都要维护，属为可能性造抽象（§9.2）。

**A 不是推倒重来**：现有 sqlite + milvus + outbox + langmem 组合**正好成为 `builtin` 这个默认 provider**，
一行不改地保留为默认行为。

### D2 — 插拔有两个**不同层次**，不要混为一谈

1. **换记忆产品**（本 ADR 的 seam，A/B 之争）：粒度 = `MemoryComponents`。
2. **换向量库**（**已存在的 seam**）：`VectorIndexStore` 早已是 Protocol（`memory/vector_store.py`），
   `MilvusVectorStore` 只是它的一个实现。这是 `builtin` provider **内部**的实现细节，
   不是 provider 边界——`builtin` 换向量库仍叫 `builtin`，`provider_name` 不该跟着变。

### D3 — 分派表是**唯一事实源**，白名单从它派生

`factories.py` 持有 `_MEMORY_PROVIDER_FACTORIES: dict[str, Callable[[Settings], MemoryComponents | None]]`，
形状照抄 `wiring.py` 的 `_BUILTIN_WIRING`（仓库自己的正确模式）。

`wiring.py` 的装配期白名单**不再硬编码 memory 的名字**，而是查 `memory_provider_names()`
→ 「接受的 provider 名」与「真有实现的 provider 名」**结构上是同一集合**，
D1 之前那种"白名单收下名字、无人接分派"的漂移不可能再发生。

新增一个记忆产品 = **分派表加一行 + 写一个 builder**，装配侧零改动。

### D4 — 命名收口：`langmem` = 已弃用别名，`builtin` = 规范名

`builtin` 与 `langmem` 今天指向同一实现（都是 sqlite + milvus + outbox + LangMem）。
本 ADR 明确语义：**`builtin` 是规范名**；`langmem` 保留为**已弃用别名**，接受但启用时
每次装配都 `warning` 提示改为 `builtin`（`enabled: false` 时装配根本不构造 provider，
自然不发 warning）。

**不直接删掉 `langmem`**：既有 `.env` 与测试配置写着它，删掉会让升级变成装配期硬失败
（unknown provider），代价大于收益。与旧状态的区别在于：**这里写明了**，且**装配会 warning**——
不再是"名字不同、实现相同、无人知道"。

### D5 — 未知 provider 是**装配期硬失败**，不降级

`build_memory_components(settings, *, provider=...)` 查表失败抛
`CapabilityError(code="init_failed")`——**复用 ADR-0010 Q3 冻结的四个码**（`init_failed` 的定义
就是"装配期失败：factory 构造失败 / 注册冲突 / config 非法"），不为这个场景新增第五个码。
配置写错是用户必须修的错误，**不走 OPTIONAL_RUNTIME 降级**（降级只留给外部依赖故障，
见 ADR-0010 的三分类）。同样的检查在 `wire_capabilities` 里对白名单先做一次——两层都是响亮失败。

### D6 — `initialize()` / `close()` 的生命周期**归 provider 所有**

`MemoryComponents` 的 `initialize()` / `close()` 由 **provider 自己**拥有与实现；
装配方只负责在启动期调用 `initialize()`、关停期调用 `close()`，**不假设内部有哪些组件**
（`builtin` 的顺序——先 records 建表、再 vectors 建 collection、最后启动 relay；
关闭时先停 relay、再关写回池、最后断向量库——是 `builtin` 自己的实现细节）。

**这条契约是本次实现中修出来的，不是天然成立的**：改造前装配方在 `initialize()` 之后
自己调了 `components.relay.start()`——`relay` 是 `builtin` 的内部组件，于是任何**不带
`.relay` 属性**的 provider（例如自带运行时的 Mem0/Zep 形态）会在装配期 `AttributeError`，
被 OPTIONAL 降级成"没有记忆"，与 D1「装配侧零改动」直接矛盾。修法是把 `relay.start()`
移进 `builtin` 自己的 `initialize()`（与 `close()` 里已有的 `relay.stop()` 对称）；
装配方现在真的只碰 `initialize()` / `close()` / `capability` / `writeback` 四个名字。

provider 换实现时生命周期语义随之改变，装配方**零改动**。这是 D1 的直接推论：
既然包内的东西都归 provider，怎么初始化/关闭自然也归 provider。

### D7 — 非目标（明确排除）

- **不做运行时热插拔**（不重启换 provider）。记忆侧有在途状态（outbox / 写回任务池 /
  Milvus 连接 / namespace），真热插拔需要 drain + 迁移或双写，成本远超收益。
  `initialize()` / `close()` 是**启动期生命周期**。
- 不做 C 方案（见 D1）。
- **不新增记忆能力**（update / delete / forget / 冲突消解）——本 ADR 只收敛 seam；
  capability 面偏窄是独立议题（#156–#159）。

---

## Consequences

### Positive

- **描述符不再撒谎**：`provider_name` 声称什么就一定用的什么（D3 + D5）。
- **漂移结构性不可发生**：白名单从分派表派生，不是两份要手工同步的清单。
- **新增 provider 成本可预期**：一行表项 + 一个 builder；装配侧、Agent Loop、测试脚手架都不动。
- **`builtin` 零行为变化**：默认值仍是原来的组合，默认路径逐字节相同。
- **生命周期归属清晰**：provider 包内有几个组件、什么顺序，都不泄漏到装配方。

### Negative / Trade-offs

- **provider 边界的责任变重**：新 provider 要自带存储与索引（A 的固有代价，见 D1 的取舍论证）。
- **`langmem` 名字长期留存**：一个已弃用别名会一直可配（换来的是升级不硬失败），
  代价是文档里要一直解释两个名字的关系——本 ADR 即该解释的锚点。
- **没有运行时热插拔**：换 provider 需重启（D7 明确接受）。

---

## Implementation evidence

- `src/agent_harness/capability/factories.py`：`_MEMORY_PROVIDER_FACTORIES` 分派表、
  `memory_provider_names()`、`build_memory_components(settings, *, provider="builtin")`（D3/D4/D5）、
  `build_builtin_memory_components()`（D1 的 `builtin` 实现，函数体与改造前逐字节相同）、
  `MemoryComponents.initialize()` 现负责启动 relay（D6 的修复）、`MemoryComponents` 生命周期 docstring（D6）。
- `src/agent_harness/capability/wiring.py`：`_STATIC_KNOWN_PROVIDERS` + `_known_providers()`
  （memory 查分派表，D3）、`_wire_memory` 传 `provider=cfg.provider` 且**不再**碰
  `components.relay`（D6）。
- 测试：`tests/capability/test_memory_provider_seam.py`（Fake provider 全分派、未知 provider
  装配期失败、白名单与分派表同源、`langmem` 别名解析到同一实现 + warning、
  provider 无内部组件也能装配）。
