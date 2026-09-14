# ADR-0009: 多租户身份隔离（IdentityContext + contextvar + Milvus partition key）

**Status**: Accepted  
**Date**: 2026-09-04  
**Phase**: 6 (Memory Capability / Context Provider)

## Context

用户在 Phase 6 grill 中引入了多租户安全维度，这是规格 06 §7（Memory Scope）的延伸但远超规格原定范围：

> 存储方面可以按照租户 id、用户 id 划分命名空间或者分区，让检索默认只能查当前用户的数据，用户身份可以从 JWT 或者 session 里解析，由中间件统一注入到比如记忆写入、向量检索或者 redis 缓存里面，不能让前端随便传，更不能让模型决定访问谁的数据。

现状（事实查证）：
- Session 没有 `user_id` / `tenant_id` 字段（只有 `agent_id`）。
- SessionEvent 没有 `user_id` / `tenant_id`。
- `web/app.py` 的 `auth_seam` 是空壳（`# request.state.user_id = "local-user"  # 占位`）。
- config 没有 auth 相关配置。

三个子决策需要冻结：
1. 身份上下文的载体和传递机制。
2. MemoryScope 分层编码。
3. Milvus 多租户隔离机制。

## Decision

### 子决策 1：IdentityContext + Python contextvar

```python
@dataclass(frozen=True)
class IdentityContext:
    tenant_id: str
    user_id: str
    scopes: list[str]  # 用户有权访问的 scope 列表
```

- 中间件解析 JWT → 创建 `IdentityContext` → 设进 `contextvar`。
- MemoryStore 从 `contextvar` 读，不走参数传递。
- Runtime 不感知身份上下文（签名零侵入）。
- 关键安全属性：`contextvar` 在中间件设置后，模型层无法修改——模型不能伪造 `user_id` 查别人的数据。
- CLI / 测试场景设默认值 `IdentityContext(tenant_id="local", user_id="local")`。

### 子决策 2：5 层 MemoryScope 枚举（对外）+ namespace tuple（对内）

对外枚举（用户和模型看到的是清晰词汇）：

```python
class MemoryScope(str, Enum):
    GLOBAL = "global"        # 系统级，所有租户共享
    TENANT = "tenant"        # 租户级
    USER = "user"            # 用户级（V1 实现）
    SESSION = "session"      # 会话/任务级（V1 实现）
    AGENT = "agent"          # Agent 实例级
```

内部映射成 namespace tuple（对齐 LangMem namespace + Milvus partition key + metadata filter）：

```text
("memories", tenant_id, user_id, scope_value)
→ Milvus: partition_key=tenant_id, metadata_filter={user_id, scope}
→ LangMem: namespace=("memories", tenant_id, user_id, scope_value)
```

存储命名空间：`memory:{tenant_id}:{user_id}:{scope}:{memory_id}`。

V1 只实现 USER + SESSION，其余留枚举不实现。

### SESSION 隔离补充（用户批准，2026-09-04）

USER 沿用四段 namespace；SESSION 在末尾追加可信 `session_id`：
`("memories", tenant_id, user_id, "session", session_id)`。
独立 contextvar 由运行入口绑定，模型和请求 body 的 memory metadata 不能选择会话。
未绑定会话时拒绝 SESSION 操作，不能退回用户级共享。SQLite 与 Milvus 同样校验会话。

### 子决策 3：Milvus partition key（官方推荐多租户方案）

研究发现 Milvus 有四种隔离级别（Database / Collection / Partition / Partition key）。

选择 **Partition key**：

- Collection 里加 `tenant_id` 列作为 partition key，Milvus 自动路由和隔离。
- `user_id` + `scope` 作为 metadata filter 叠加逻辑隔离。
- 不需要 per-tenant collection 管理（Zilliz Cloud 免费实例 collection 数量有限）。
- 可扩展到百万租户。

检索默认只查当前用户的数据：

```text
search(tenant_id=identity.tenant_id, user_id=identity.user_id, scope, query)
→ Milvus: partition_key=tenant_id AND metadata.user_id=X AND metadata.scope=Y
```

模型不能指定查别的 user_id——identity 来自 `contextvar`（中间件设置），不接受外部传入。

## Rationale

### 为什么 contextvar 而非显式参数传递

- FastAPI / anyio 的标准做法，对 Runtime 签名零侵入——`run()` / `run_stream()` 不改签名。
- 显式参数要改一路签名（Session → Runtime → ContextBuilder → Provider → Store），每层加参数，破坏 Surgical 和 Simplicity。
- 挂在 Session 上把身份混进事件聚合根（职责分离）。
- 关键安全属性：中间件设置后模型层无法修改——模型不能伪造 user_id。

### 为什么 5 层枚举 + 内部 namespace tuple 的混合编码

- 研究发现：没有刚性层级，都是可组合的原语（Mem0 用 metadata filter、LangMem 用 namespace tuple、Letta 用 memory-block）。
- 对外枚举保持人类可读词汇（用户看到 `user` / `session` 而非 tuple 路径）。
- 内部 namespace tuple 对齐 LangMem 的原生模型和 Milvus 的 partition key。
- 不是双层抽象——是「面向人的词汇」到「面向存储的路径」的映射。

### 为什么 partition key 而非 per-tenant collection

- Milvus 官方文档推荐 partition key 用于多租户弹性场景（百万租户级）。
- Zilliz Cloud 免费实例 collection 数量有限，per-tenant collection 不现实。
- partition key + metadata filter 组合正好对应需求：tenant_id 做物理隔离，user_id + scope 做逻辑隔离。

## Consequences

- 新增 `IdentityContext` dataclass + `contextvar`。
- 新增 `auth_seam` 实现（解析 JWT → 设置 contextvar）。
- Session / SessionEvent 不加 user_id 字段（身份在 contextvar，不进事件流——身份是请求级的，事件是持久的）。
- 所有 MemoryStore 读写操作从 `contextvar` 读 IdentityContext。
- Milvus collection schema 包含 `tenant_id` partition key 列。
- 缓存 key（未来引入缓存时）必须格式化为 `{tenant_id}:{user_id}:{scope}:{query_hash}`——写在 ADR 中防止未来遗忘。
- config 新增 JWT secret / auth 相关配置（可选，默认 `local`）。
