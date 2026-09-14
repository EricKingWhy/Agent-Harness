# ADR-0008: Memory Capability 架构（双层 Protocol + LangMem 适配 + 自主存储）

**Status**: Accepted  
**Date**: 2026-09-04  
**Phase**: 6 (Memory Capability / Context Provider)

## Context

规格 06 §6 冻结了三条硬约束：

1. Memory MUST 暴露成 `MemoryCapability + MemoryContextProvider` 双层。
2. Core 不直接依赖 LangMem、Mem0 或自研实现。
3. 默认 Provider 是 LangMem，但必须可替换。

复用矩阵冻结了 LangMem = `REUSE + ADAPT`（默认 MemoryProvider，Core 禁止 import concrete class）。

不变量 #16/#17/#18 要求：Memory = Capability + Context Provider；LangMem 只是默认 Provider 可替换 Mem0；Knowledge/Web/MCP/Coding 都是 Capability/Tool 不写进 Agent Loop 特判。

Phase 5 已铺好 seam：`ContextProvider` Protocol（`select(session, token_budget) -> list[AnyMessage]`）+ `ContextBuilder.context_providers: list[ContextProvider]`（空列表）。

四个子决策需要冻结：
1. V1 交付边界。
2. 双层 Protocol 的分层语义。
3. LangMem 依赖方式。
4. 存储主权归属。

## Decision

### 子决策 1：最小闭环（store/recall/search + 单 scope + ContextProvider + degrade）

V1 不做全量 6 能力。只交付：

- `store` + `recall` + `search` 三原语（写入和检索两条主线）。
- `MemoryContextProvider`（按 budget 选 memory entries 注入 Context）。
- graceful degradation（Provider 故障不阻塞 Runtime）。
- scope 只实现 USER + SESSION 两层（抽象层留全 5 层 type）。

`update` / `delete` / `extract_candidates` 留接口不实现。GLOBAL / TENANT / AGENT scope 留接口不实现。

### 子决策 2：双层 Protocol——MemoryCapability（原语）+ MemoryContextProvider（注入）

```text
MemoryCapability (Protocol)
    async store(scope, content, metadata) -> memory_id
    async recall(scope, query, limit) -> list[MemoryEntry]
    async search(scope, query, limit) -> list[MemoryEntry]
        ↓ 依赖
MemoryContextProvider (实现 ContextProvider Protocol)
    async select(session, token_budget) -> list[AnyMessage]
        内部：调 Capability.search → 按 relevance/recency/importance 修剪到 budget → 拼 SystemMessage
```

- `MemoryCapability` 管 store/recall 原语（能否存取）。
- `MemoryContextProvider` 管 select（按预算选哪些注入 Context）。
- 后者依赖前者。换 Provider 时只换 `MemoryCapability` 实现，Context 选择逻辑不动。

### 子决策 3：LangMem 走 optional extra（`pip install intelligence-agent[memory]`）

- Core 不强依赖 LangMem。没装 `[memory]` → `FakeMemoryCapability`（内存 dict）；装了 → `LangMemMemoryCapability`。
- 和 Phase 5 的 aioboto3 走 `[artifact]` extra 一致。

### 子决策 4：存储主权归我们——LangMem 通过 BaseStore 适配我们的存储

研究发现：**LangMem 不拥有存储**——它完全委托给 LangGraph 的 `BaseStore` 接口。

落地路径：

```text
我们的存储层
├─ MemoryRecordStore (Protocol) → SQLite 实现（权威记录）
├─ VectorIndexStore  (Protocol) → Milvus 实现（向量索引）
├─ Outbox relay（进程内 asyncio 后台任务，保证 SQLite→Milvus 最终一致）
└─ SqliteMilvusBaseStore (实现 langgraph BaseStore Protocol)
    ↑ 适配层：把 LangMem 的读写翻译成我们的双存储

LangMemMemoryCapability
└─ 内部使用 LangMem（Formation + Consolidation + search）
   全部通过 BaseStore 接口操作，不知道底层是我们的 SQLite + Milvus

FakeMemoryCapability
└─ 测试实现，纯内存 dict + 简单文本匹配
```

LangMem 负责 Formation（提取）+ Consolidation（合并去重）+ search（检索算法）。Milvus 负责向量检索。SQLite 负责权威记录。三层职责清晰。

## Rationale

### 为什么最小闭环而非全量

- LangMem 自己的 update/extract_candidates 算法仍在演进，盲目包一层会很快被上游改穿。
- 4 scope 在没有真实多用户场景时没法验证语义正确性，做了是死代码。
- Context Provider + degrade 是规格 Gate 硬条件（"切换 Fake Provider 不改 Core" + "Memory 挂掉基础 Agent 仍运行"），必须做。
- 不变量 #17「LangMem 只是默认 Provider 可替换」要求抽象层足够薄，最小闭环比全量更容易做到「换 Mem0 不改 Core」。

### 为什么双层 Protocol

- 规格用「MUST 暴露成 X + Y」的措辞，明确是两个东西。
- 读写原语（store/recall）和上下文选择（select）关注点不同——前者「能不能存取」，后者「按 budget 选哪些进 Context」。
- 分层让 LangMemProvider 只实现 store/recall，Context 选择逻辑是项目自己的薄层——换 Mem0 时只换 Provider，选择逻辑不动。

### 为什么 LangMem 走 BaseStore 适配而非只用部分能力

- 研究证实 LangMem 已把存储抽象成 `BaseStore`——只需实现 Protocol，不需要适配 LangMem 的任何具体类。
- 让 LangMem 的全部价值（Formation + Consolidation + search）可用，同时保持存储主权（SQLite 事实源、Milvus 向量索引、outbox 一致性）。
- 自己重写向量检索是重复造轮子（违反 Reuse First）。

### 为什么存储主权在我们而非 LangMem

- 用户明确要求：「SQLite 保存权威 Memory Record，Milvus 保存向量索引；LangMem 只负责 Memory Formation / Consolidation，不拥有数据」。
- 和 Artifact 的设计一致（七牛云是事实源，我们保持控制）。
- 不变量：SQLite 是事实源，Milvus 是索引（可从 SQLite 重建）。

## Consequences

- 新增 `MemoryCapability` Protocol + `MemoryContextProvider`。
- 新增 `MemoryRecordStore` Protocol + `VectorIndexStore` Protocol（内部接口分离，对外通过 `MemoryStore` 单接口封装）。
- 新增 `SqliteMilvusBaseStore`（实现 LangGraph `BaseStore`）。
- 新增 `LangMemMemoryCapability`（默认实现）+ `FakeMemoryCapability`（测试实现）。
- LangMem + langgraph-core 加入 optional extra `[memory]`。
- `ContextBuilder.context_providers` 从空列表变为可注入 `MemoryContextProvider`。
- 新增 `memory/degraded` SessionEvent（Memory 故障降级时 append）。
- 新增 `IdentityContext` + `contextvar`（见 ADR-0009）。
