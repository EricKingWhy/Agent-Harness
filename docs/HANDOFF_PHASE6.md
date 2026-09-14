# Phase 6 交接手册 — Memory Capability / Context Provider

> **给 Codex**：这份手册是你独立实施 Phase 6 的完整指引。27 个设计决策已通过 grill-with-docs 冻结，两个 ADR + CONTEXT.md 已落地。按顺序实施 6 个 ticket，每个 ticket 的精确插入点、测试命令、约束都在这里。

## 决策速查（27 个冻结决策）

实施备注（#51）：IdentityContext 接受 scopes 列表，构造时复制为不可变 tuple，避免 contextvar 子任务修改共享权限。JWT 复用 PyJWT（MIT），固定 HS256；未配置 jwt_secret 时不信任 Bearer 声明，使用 local 身份。

用户补充批准：SESSION namespace 追加可信 session_id（ADR-0009 补充），USER 保持四段。#56 使用专用 memory_gate_test Collection；需验证真实认证、CRUD、检索语义/隔离、删除与清理，并通过正式 Provider 路径执行。数据库沿用 default，不额外加 database 配置。

| # | 决策 | 选定 |
|---|---|---|
| Q1 | V1 交付边界 | **B** 最小闭环：store/recall/search + USER/SESSION scope + ContextProvider + degrade |
| Q2 | 双层 Protocol 分层 | **A** MemoryCapability（原语）+ MemoryContextProvider（注入），后者依赖前者 |
| Q3 | LangMem 依赖方式 | **A** optional extra `pip install intelligence-agent[memory]` |
| Q4 | 记忆写入触发 | **C** V1 只做自动后台抽取（Memory Tool 接口留好，Phase 6.1 补） |
| Q5 | 端到端测试后端 | **A** 真实 Milvus / Zilliz Cloud（用户提供凭证） |
| Q6 | MemoryCapability 签名 | **A** store(scope, content, metadata)→id / recall(scope, query, limit) / search(scope, query, limit) |
| Q7 | budget 协商 | **C** 两阶段：Provider 返回候选（带 score），ContextBuilder 做最终裁剪 |
| Q8 | 记忆抽取逻辑 | **D→修订** 两层降级：LLM 抽取 → 启发式规则（必须在 Phase 6 内完成） |
| Q9 | 存储主权 | **D 用户自定义** 存储主权在我们，LangMem 不拥有数据 |
| Q10 | degrade 行为 | **B** 抛到 Runtime 层面处理（通过 memory/degraded 事件暴露） |
| Q11 | 记忆生命周期 | **A** 跨 Session 持久化（user scope 下跨 session recall） |
| Q12 | 身份上下文载体 | **A** IdentityContext + Python contextvar |
| Q13 | MemoryScope 分层 | **C** 5 层：global/tenant/user/session/agent（V1 只实现 user+session） |
| Q14 | MemoryStore ABC 形状 | **B→修订为 C** 对外单接口，内部分离 MemoryRecordStore + VectorIndexStore |
| Q15 | 记忆注入格式 | **A** 单条 SystemMessage 插在 system prompt 之后 |
| Q16 | 双写一致性 | **A** SQLite-first + outbox pattern |
| Q17 | Runtime 怎么捕获 degrade | **D** memory/degraded SessionEvent（不阻塞 loop） |
| Q18 | 确认 Q14 | **C** 对外单接口，内部分离两个 Protocol |
| Q19 | LangMem 角色 | **C** LangMem 做 Formation+Consolidation+search，存储我们接管（通过 BaseStore 适配） |
| Q20 | 两层降级形状 | **B** 三层：LLM → 启发式 → 空 |
| Q21 | Redis 缓存 | **A** V1 不做（缓存 key 隔离规则写入 ADR 防遗忘） |
| Q22 | 端到端测试场景 | **A** 完整闭环：session1 写入 → session2 recall → 断言注入 |
| Q23 | ticket 拆分 | **A** 6 ticket 顺序依赖 |
| Q24 | Milvus 多租户隔离 | **A** partition key（tenant_id 列）+ metadata filter（user_id + scope） |
| Q25 | Q19 落地路径 | **A** 实现 BaseStore 接口适配我们的存储 |
| Q26 | MemoryScope 编码 | **C** 对外枚举 + 对内 namespace tuple |
| Q27 | outbox relay 运行模型 | **A** 进程内 asyncio 后台任务 |

## 架构总览

```text
HTTP 请求
  → auth_seam 中间件（解析 JWT）
  → IdentityContext 设入 contextvar
  → AgentRuntime.run_stream()
      → ContextBuilder.build(session)
          → MemoryContextProvider.select(session, token_budget)
              → MemoryCapability.search(scope, query, limit)
                  → SqliteMilvusBaseStore (实现 langgraph BaseStore)
                      → MemoryRecordStore (SQLite: 权威记录)
                      → VectorIndexStore (Milvus: 向量索引, partition_key=tenant_id)
              → 按 relevance/recency/importance 修剪到 budget
              → 返回 list[AnyMessage]（单条 SystemMessage）
          → 合并到 messages
      → 模型调用 ...
  
  run 结束 → MemoryExtractor 后台触发
      → LLM 抽取（失败↓）
      → 启发式规则（失败↓）
      → 空（不写 Memory）
      → MemoryCapability.store(scope, content, metadata)
          → SQLite 事务：写记忆行 + 写 outbox 行
          → asyncio relay poll outbox → 推到 Milvus → 标记成功

  Provider 故障 → append memory/degraded 事件 → 继续跑（不阻塞）
```

## 6 个 Ticket 详细指引

### Ticket #51 (#1): IdentityContext + middleware + contextvar 基础设施

**GitHub**: #51

**交付物**:
- 文件 `src/agent_harness/identity.py`:
  - `IdentityContext` dataclass（frozen=True，slots=True）: `tenant_id: str`, `user_id: str`, `scopes: list[str]`
  - `identity_context_var: contextvars.ContextVar[IdentityContext | None]`（默认 None）
  - `get_identity_context() -> IdentityContext`: 读 contextvar，None 时返回 `IdentityContext(tenant_id="local", user_id="local", scopes=["user", "session"])`
  - `set_identity_context(ctx: IdentityContext) -> contextvars.Token`: 设 contextvar，返回 token 供 reset
- `src/agent_harness/config.py`: 新增 `jwt_secret: str | None = None`
- `src/agent_harness/web/app.py` 的 `auth_seam`: 从 `Authorization: Bearer <jwt>` 解析 → 创建 IdentityContext → `set_identity_context()`。
  - **⚠️ R6-4/R8-3 契约已变更（2026-09-05，用户拍板 fail-closed）**：配置了 `JWT_SECRET` 时，匿名请求返回 401（不再降级 local 身份），且 token 必须携带 `exp`（永不过期的 token 被拒）。未配置 `JWT_SECRET` 时保持本地信任模式（fail-open），但启动时输出响亮告警。前端在配置了密钥的部署环境必须附带有效 Bearer token。详见 `docs/DEFER_ROUND2.md` 决策执行日志。

**测试** (`tests/test_identity.py`):
- `test_default_identity_when_contextvar_unset`
- `test_contextvar_set_then_read`
- `test_contextvar_isolated_across_async_tasks`（asyncio.create_task 各自隔离）
- `test_identity_is_immutable`（frozen=True）
- `test_auth_seam_sets_contextvar`（集成 web 层）

**测试命令**: `uv run pytest tests/test_identity.py -v`

**约束**:
- Runtime 的 `run()` / `run_stream()` 不改签名
- IdentityContext 不进 SessionEvent

---

### Ticket #52 (#2): MemoryScope + MemoryEntry + MemoryRecordStore (SQLite 实现)

**GitHub**: #52  
**前置**: #51 完成

**交付物**:
- 文件 `src/agent_harness/memory/types.py`:
  - `MemoryScope(str, Enum)`: GLOBAL / TENANT / USER / SESSION / AGENT
  - `MemoryEntry` (Pydantic BaseModel): `id: str`, `content: str`, `metadata: dict`, `score: float | None`, `created_at: str`, `scope: MemoryScope`, `indexed: bool = False`
  - `scope_to_namespace(scope: MemoryScope, identity: IdentityContext) -> tuple[str, ...]`: 枚举转 namespace tuple
- 文件 `src/agent_harness/memory/record_store.py`:
  - `MemoryRecordStore(Protocol)`: `async store(entry: MemoryEntry, identity: IdentityContext) -> str` / `async get(memory_id: str, identity: IdentityContext) -> MemoryEntry` / `async list_by_scope(scope: MemoryScope, identity: IdentityContext, limit: int) -> list[MemoryEntry]`
- 文件 `src/agent_harness/memory/sqlite_record_store.py`:
  - `SqliteMemoryRecordStore(MemoryRecordStore)`: aiosqlite 实现，表名 `memory_records`
  - 列: `memory_id TEXT PK`, `tenant_id TEXT`, `user_id TEXT`, `scope TEXT`, `content TEXT`, `metadata JSON`, `created_at TEXT`, `indexed BOOLEAN DEFAULT FALSE`
  - `store()` 和 outbox 写入在同一个 SQLite 事务里（BEGIN...COMMIT）
  - 查询带 tenant_id + user_id WHERE 条件（隔离）
- 文件 `src/agent_harness/memory/fake_record_store.py`:
  - `FakeMemoryRecordStore`: 内存 dict，测试用

**测试** (`tests/memory/test_record_store.py`):
- `test_store_and_get_roundtrip`
- `test_tenant_isolation`（tenant A 存的，tenant B 查不到）
- `test_user_isolation`（同 tenant 不同 user 隔离）
- `test_list_by_scope_user`
- `test_list_by_scope_session`
- `test_fake_store_matches_protocol`

**测试命令**: `uv run pytest tests/memory/test_record_store.py -v`

**约束**:
- 权威记录在 SQLite（事实源）
- 所有查询带 identity WHERE 条件（多租户隔离不变量）

---

### Ticket #53 (#3): VectorIndexStore (Milvus 实现) + Outbox relay

**GitHub**: #53  
**前置**: #52 完成

**交付物**:
- 文件 `src/agent_harness/memory/vector_store.py`:
  - `VectorIndexStore(Protocol)`: `async upsert(memory_id: str, content: str, metadata: dict, identity: IdentityContext) -> None` / `async search(query: str, identity: IdentityContext, scope: MemoryScope, limit: int) -> list[tuple[str, float]]`（返回 `(memory_id, score)`）
- 文件 `src/agent_harness/memory/milvus_vector_store.py`:
  - `MilvusVectorStore(VectorIndexStore)`: 用 pymilvus（或 langchain-milvus）连接 Zilliz Cloud
  - Collection schema 包含 `tenant_id` 作为 partition key
  - `user_id` + `scope` 作为 metadata 字段，检索时 filter
  - SDK 懒加载（和 S3ArtifactStore 的 aioboto3 一致）
  - `pip install intelligence-agent[memory]` 安装 pymilvus
- 文件 `src/agent_harness/memory/fake_vector_store.py`:
  - `FakeVectorStore`: 内存 dict + 简单文本匹配（`query in content`）代替向量相似度
- 文件 `src/agent_harness/memory/outbox_relay.py`:
  - `OutboxRelay`: 进程内 asyncio 后台任务
  - 定期 poll `memory_outbox` 表（未同步行），调 `VectorIndexStore.upsert()`，成功后标记 SQLite 记录 `indexed=True` + 删 outbox 行
  - 幂等：按 memory_id 去重（upsert 语义）
  - 构造参数: `record_store`, `vector_store`, `poll_interval_seconds: float = 5.0`

**测试** (`tests/memory/test_vector_store.py`, `tests/memory/test_outbox_relay.py`):
- `test_fake_vector_store_search_returns_matches`
- `test_fake_vector_store_empty_query`
- `test_outbox_relay_processes_pending`（写 outbox 行 → 启动 relay → 验证 vector_store 被调）
- `test_outbox_relay_idempotent`（同一 memory_id 重复处理不报错）
- `test_outbox_relay_marks_indexed_on_success`
- `test_outbox_relay_retries_on_vector_failure`（vector_store 第一次失败 → 不删 outbox → 下次重试）

**测试命令**: `uv run pytest tests/memory/test_vector_store.py tests/memory/test_outbox_relay.py -v`

**约束**:
- Milvus SDK 走 optional extra（不强依赖）
- relay 幂等（memory_id 去重）
- 单元测试用 FakeVectorStore，不碰 Milvus

**需要用户提供**: Zilliz Cloud 的 endpoint / token / collection 名（端到端测试用）

---

### Ticket #54 (#4): MemoryCapability Protocol + MemoryExtractor + LangMem BaseStore 适配

**GitHub**: #54  
**前置**: #53 完成

**交付物**:
- 文件 `src/agent_harness/memory/capability.py`:
  - `MemoryCapability(Protocol)`: `async store(scope: MemoryScope, content: str, metadata: dict) -> str` / `async recall(scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]` / `async search(scope: MemoryScope, query: str, limit: int) -> list[MemoryEntry]`
  - 从 `get_identity_context()` 获取 identity（不暴露在签名里——安全属性）
- 文件 `src/agent_harness/memory/extractor.py`:
  - `MemoryExtractor`: 两层降级 `async extract(events: list[SessionEvent]) -> list[tuple[MemoryScope, str, dict]]`
    - 第 1 层 `_llm_extract`: 用 ModelProvider ainvoke，prompt 要求输出 JSON `[{scope, content, importance}]`，失败判据：超时 / 非 JSON / schema 不匹配
    - 第 2 层 `_heuristic_extract`: 纯规则（user/message 抽偏好、run/completed 抽 final_text、tool/result ok=False 抽失败）
    - 第 3 层：返回空列表
- 文件 `src/agent_harness/memory/langmem_capability.py`:
  - `LangMemMemoryCapability(MemoryCapability)`: 默认实现
  - 内部通过 `SqliteMilvusBaseStore`（实现 LangGraph `BaseStore` Protocol）适配我们的存储
  - LangMem 的 Formation（`create_manage_memory_tool`）+ Consolidation + search 全部走 BaseStore
- 文件 `src/agent_harness/memory/base_store_adapter.py`:
  - `SqliteMilvusBaseStore`: 实现 LangGraph `BaseStore` Protocol
  - `put()` → 写 MemoryRecordStore + outbox
  - `get()` / `search()` → 读 MemoryRecordStore / VectorIndexStore
- 文件 `src/agent_harness/memory/fake_capability.py`:
  - `FakeMemoryCapability`: 内存 dict + 简单文本匹配，测试用

**测试** (`tests/memory/test_extractor.py`, `tests/memory/test_capability.py`):
- `test_extractor_llm_success`
- `test_extractor_fallback_to_heuristic_on_llm_timeout`
- `test_extractor_fallback_to_heuristic_on_bad_json`
- `test_extractor_returns_empty_when_nothing_to_extract`
- `test_heuristic_extracts_user_preferences`
- `test_heuristic_extracts_failed_attempts`
- `test_fake_capability_store_and_search`

**测试命令**: `uv run pytest tests/memory/test_extractor.py tests/memory/test_capability.py -v`

**约束**:
- Core 禁止 import LangMem concrete class（只依赖 MemoryCapability Protocol）
- identity 从 contextvar 读，不暴露在签名
- LangMem SDK 走 `[memory]` optional extra

---

### Ticket #55 (#5): MemoryContextProvider + memory/degraded 事件

**GitHub**: #55  
**前置**: #54 完成

**交付物**:
- 文件 `src/agent_harness/memory/context_provider.py`:
  - `MemoryContextProvider`: 实现 Phase 5 的 `ContextProvider` Protocol（`select(session, token_budget) -> list[AnyMessage]`）
  - `select()` 内部:
    1. 从 session 上下文提取 query（当前 user message + 最近对话主题）
    2. 调 `MemoryCapability.search(scope=USER, query, limit=20)` 获取候选
    3. 按 relevance / recency / importance 排序
    4. 按 token_budget 裁剪（用 `estimate_tokens()` 算每条占用）
    5. 拼成单条 `SystemMessage`（Markdown 结构化文本），插在 system prompt 之后、对话历史之前
  - try/except: `MemoryCapability` 故障 → append `memory/degraded` SessionEvent → 返回空列表
- `src/agent_harness/session/event.py`: 新增 `MEMORY_DEGRADED = "memory/degraded"` + 加入 `EVENT_TYPES`
- `src/agent_harness/agent/runtime.py`: ContextBuilder 构造时可注入 `MemoryContextProvider`；Runtime 结束后触发 `MemoryExtractor.extract()` 后台写入（`asyncio.create_task`，不阻塞返回）
- `src/agent_harness/context/builder.py`: `context_providers` 从空列表变为可注入

**测试** (`tests/memory/test_context_provider.py`):
- `test_select_returns_system_message_with_memories`
- `test_select_respects_token_budget`（budget 紧时裁剪低 score 条目）
- `test_select_empty_when_no_memories`
- `test_memory_degraded_event_on_provider_failure`
- `test_degraded_does_not_block_runtime`

**测试命令**: `uv run pytest tests/memory/test_context_provider.py -v`

**约束**:
- 不改 `ContextProvider` Protocol（Phase 5 已定义）
- memory/degraded 是 typed SessionEvent，进事件流
- 降级不阻塞 Runtime loop

---

### Ticket #56 (#6): 端到端集成测试 (真实 Zilliz Cloud Milvus)

**GitHub**: #56  
**前置**: #55 完成 + 用户提供 Zilliz Cloud 凭证

**交付物**:
- 文件 `tests/integration/test_phase6_memory_e2e.py`:
  - 完整闭环测试（Q22=A）:
    1. 起一个模拟 Session（user=Alice, tenant=Acme）→ 跑一段对话（含用户偏好「我喜欢 TypeScript」）→ run 结束 → MemoryExtractor 自动写入
    2. 等待 outbox relay 同步（或手动 flush）→ 验证 Milvus 里有对应向量
    3. 起第二个 Session（同一个 Alice/Acme）→ MemoryContextProvider.select() → 断言返回的 SystemMessage 包含「TypeScript」
    4. 起第三个 Session（不同用户 Bob/Acme）→ 断言 **查不到** Alice 的记忆（多租户隔离验证）
- 需要 Zilliz Cloud 凭证: `endpoint`, `token`, `collection_name`
- 凭证从 `.env` 读（不硬编码），缺凭证时 `pytest.skip`

**测试命令**: `uv run pytest tests/integration/test_phase6_memory_e2e.py -v`

**约束**:
- 不用 Fake，用真实 Milvus（和 Phase 5 真实七牛云对齐）
- 测试完清理写入的数据（teardown 删 Alice/Bob 的记忆条目）
- 多租户隔离是核心验证点

**需要用户提供**: Zilliz Cloud 的 endpoint / token / collection 名

---

## 全局约束（所有 ticket 适用）

1. **Scope Lock**: 不改 Phase 1-5 已落地的代码（除非 ticket 明确要求插入点）。不顺手重构。
2. **Simplicity First**: 每行 diff 可追溯到当前 ticket / ADR。
3. **TDD**: 每个 ticket 先写测试（red），再实现（green），再重构。
4. **ruff clean**: 每个 ticket 完成后 `uv run ruff check src/ tests/` 零报错。
5. **全量回归**: 每个 ticket 完成后 `uv run pytest` 全过（不破坏已有测试）。
6. **不变量**: 检查 AGENTS.md §7 的 22 条不变量，特别是 #16/#17/#18/#21。
7. **不 push main**: commit 到 `feat/backend`，push `feat/backend`。合并 main 由集成 AI 负责。
8. **LangMem 不碰存储**: LangMem 通过 BaseStore 操作，不直接连 SQLite / Milvus。

## 参考

- ADR-0008: Memory Capability 架构
- ADR-0009: 多租户身份隔离
- CONTEXT.md: Memory 层术语（IdentityContext / MemoryCapability / MemoryContextProvider / MemoryScope / MemoryEntry / MemoryStore / MemoryExtractor / memory/degraded / LangMem / Outbox）
- 规格 `06_CONTEXT_ARTIFACT_MEMORY.md` §6-§9
- 复用矩阵 `13_OPEN_SOURCE_REUSE_MATRIX.md`（LangMem = REUSE+ADAPT）
- Roadmap `14_IMPLEMENTATION_ROADMAP.md` Phase 6 Gate

## #53 实施证据

正式配置仅 MILVUS_URI / MILVUS_TOKEN / MILVUS_COLLECTION，token 为 SecretStr，database 使用默认值。pymilvus 2.6.x（Apache-2.0）经 memory extra 懒加载；LangChain Embeddings 注入，document/query 分别编码，维度从输出读取，COSINE + AUTOINDEX。模型配置待用户提供，不使用猜测维度创建远程 Collection。

2026-09-04：通过正式 MilvusVectorStore.connect 成功验证真实 Zilliz client/auth/list_collections，返回空列表，未创建 Collection、未写数据。不是 #56 完整 Gate。SDK 原始异常不出 adapter；当前 diff + 待提交文件 Secret scan 通过。

2026-09-05：**#56 完整 Gate 跑通并关单**（feat/backend @ ec2d8ed，`uv run pytest tests/integration/test_phase6_memory_e2e.py -m integration`，3 passed / 77.7s）。真实 Zilliz Cloud + SiliconFlow embedding（Qwen3-Embedding-8B，1024 维）：真实认证与 connect、缺失 Collection 映射 collection_not_found（零变更）、故意无效 token 映射 authentication 不泄密；完整记忆链路（AgentRuntime run → MemoryExtractor → SqliteMemoryRecordStore 同事务 outbox → 真实 embedding → 真实 Zilliz upsert）语义检索排序、limit 截断、多租户/多用户隔离（bob 与异租户检索为空、get None、Context 注入为空）、持久 outbox 失败重试排空、64 维对既有 1024 维 Collection schema_mismatch 拒绝；清理逐条 delete 断言消失 + drop 测试 Collection 断言不在列表。无 memory/degraded。全程未打印任何凭证。

Outbox 使用 revision 条件确认 + memory_id 游标分页，避免并发更新误确认和失败首页饿死后续任务。部署模型为单进程单 relay；start/stop 在 #55 组合入口接线。

官方 SDK 参考：https://milvus.io/docs/use-async-milvus-client-with-asyncio.md ，https://milvus.io/docs/use-partition-key.md 。

## #55 组合与生命周期

调用方将 MemoryContextProvider(capability) 经 context_providers 注入 AgentRuntime，将 MemoryWriteback(capability, extractor) 经 memory_writer 注入。只依赖本项目契约与编排组件，Core 不导入 LangMem/Milvus。组合入口负责 relay.start()/stop() 和 writer.drain()/close()；测试可在 drain 后 flush，服务退出时先收敛写入、再停止 relay 并关闭 vector client。Web 默认模型配置尚无 embedding 模型，未猜测 embedding 或自动连接远程库。

检索降级通过 Runtime 事件流镜像；后台写入在返回后发生，其降级事件持久化供刷新/回放读取，不保证已结束的 SSE 连接收到。

## #56 Embedding 选型（用户确认，2026-09-04）

SiliconFlow `Qwen/Qwen3-Embedding-8B`，endpoint `https://api.siliconflow.cn/v1`。用户要求速度/存储/精度折中，显式采用 1024 维（EMBEDDING_DIMENSIONS），而非模型默认 4096。工厂复用现有 langchain-openai OpenAIEmbeddings；check_embedding_ctx_length=False 保持字符串请求，维度经真实响应与 Collection schema 双重验证。仅新增原来缺失的 EMBEDDING_MODEL / EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_DIMENSIONS；API Key 为 SecretStr，只存本地忽略的 .env。

参考：https://docs.siliconflow.cn/cn/api-reference/embeddings/create-embeddings ，https://github.com/QwenLM/Qwen3-Embedding 。1024 维 float32 原始向量约 4 KiB，比 4096 维减少 75%；不代表总索引空间或端到端延迟同比降低。
