# 调研：记忆可插拔 / 项目→多会话 / 跨进程与 workspace 独占锁

> 触发：用户就「可插拔记忆」「怎么做到一个项目下多个会话（像 ZCode）」「多进程共享同一 workspace 是什么场景、要不要做独占锁、参考谁」提问。
> 本文是**评估与建议**，不含产品代码改动。每条结论都带仓库内 file:line 证据或上游出处。
> 分支 `feat/backend`。上游出处来自本批次对 DSH / Pi / oh-my-pi 源码的检索与对 ZCode 落盘结构的只读观察。

---

## 0 结论速览

| 问题 | 结论 |
| --- | --- |
| 记忆可插拔现在能用吗 | **不能**。`provider` 配置被校验、被写进 `CapabilityDescriptor`，但**不参与构造**——`builtin` 与 `langmem` 都造 LangMem。属**规格已要求、代码未实现**的 Gap |
| 可插拔怎么做 | 照抄仓库已有的 `_BUILTIN_WIRING` 形状，加一张 **per-capability provider 分派表**；真正要先拍板的是**seam 划在哪**（换整个 `MemoryComponents` 还是只换 `MemoryCapability`） |
| 需要 grill-me → 手册 → tickets 吗 | **不需要完整 SDD 周期**。规格已冻结需求、无产品歧义、只是一处代码 Gap；**需要**一页 ADR 级决策（定 seam）+ 1 张 ticket |
| 一个项目下多个会话 | **后端已经支持**（同一 `workspace` 名 → 同一目录，`service.py:319-325`），缺的是**可见性**：列表契约无 `workspace` 字段 → 前端无法分组 |
| 上传项目 | **完全不存在**。全仓无 upload / import / git clone 端点 |
| 多进程共享 workspace 的场景 | 多 worker、CLI+Web 并存、独立后台进程。**当前仓库是单进程**，故**非必选** |
| 独占锁要做吗 | **现在不要做全套**。建议先加**启动期单实例锁**（对 session root），把危险形状变成响亮失败；真正的多写者模型等真有多进程需求再做 |
| 参考谁 | 项目→多会话：**DSH**（唯一显式建模 Workspace 实体 + 有序 sessionIds 账本）；锁：**DSH 的单写者 handle + 租约**，或 **ZCode 的 SQLite WAL**（它根本没有独占锁）；可插拔装配：**DSH + Pi** |

---

## 1 记忆可插拔：现在的真实状态

### 1.1 规格早已要求

- 不变量 #16：**Memory = Capability + Context Provider**。
- 不变量 #17：**LangMem 只是默认 Provider，可替换 Mem0 / 自研**。

所以"可插拔"是**已冻结的需求**，不是新增愿望。

### 1.2 代码没实现（Gap，三处证据）

1. `src/agent_harness/capability/wiring.py:420` —— `_KNOWN_PROVIDERS["memory"] = {"builtin", "langmem"}`：**名字被接受**。
2. `src/agent_harness/capability/wiring.py:101` —— `CapabilityDescriptor(..., provider_name=cfg.provider)`：**配置值被如实写进描述符**。
3. `src/agent_harness/capability/factories.py:42-90` —— `build_memory_components(settings)` **签名里根本没有 provider，也不分派**：`from agent_harness.memory.langmem_capability import LangMemMemoryCapability` 是无条件 import，两个 provider 名走同一条路。

**后果（比"不能换"更糟）**：描述符会**声称一个并未生效的 provider**。若用户按"可插拔"的预期配 `provider: "mem0"`，今天会在装配期被 `_KNOWN_PROVIDERS` 拒掉（响亮失败，可接受）；但一旦有人把 `"mem0"` 加进白名单而忘了接分派，系统就会**静默地用 LangMem 而对外自称 mem0**——这正是 08 §5「不允许接受但静默忽略」要防的形状。

### 1.3 怎么做：照抄仓库自己的形状

仓库已有正确的分派模式，只是 memory 没接上：

```python
# wiring.py:405
_BUILTIN_WIRING: dict[str, tuple[Any, Degradation]] = {
    "memory": (_wire_memory, Degradation.OPTIONAL_RUNTIME),
    ...
}
```

最小改动 = 给 memory 加一张 provider 子表，并在 factory 上把 provider 变成参数：

```python
# 建议形状（示意，未实现）
_MEMORY_PROVIDERS = {
    "builtin": _build_langmem_components,   # 今天的行为
    "langmem": _build_langmem_components,   # 显式别名，同一实现
    # "mem0": _build_mem0_components,       # 未来：新增一行 + 一个 builder
}
```

`_wire_memory` 里把 `cfg.provider` 传下去，`build_memory_components(settings, provider)` 查表分派；未知 provider 仍走装配期硬失败。改动面：`wiring.py`（十余行）+ `factories.py`（签名与分派）+ 一个"两个 provider 都产出可用 capability"的测试。

### 1.4 真正要先拍板的是 seam（不可逆的那一步）

"换一个记忆后端"到底换掉什么？两种划法：

| 划法 | 换掉的东西 | 保留 | 代价 |
| --- | --- | --- | --- |
| **A. 整个 `MemoryComponents` 包** | capability + records + vectors + relay + writeback | Agent Loop 侧契约（`MemoryWriteback` / `MemoryContextProvider`） | 新 provider 要自带存储与索引；自由度最大，重复实现最多 |
| **B. 只换 `MemoryCapability`（`store`/`search`/`recall`）** | LangMem 那一层 | SqliteMemoryRecordStore + Milvus + OutboxRelay 管线 | 改动最小；但 Mem0 这类自带存储的后端会被迫套进我们的 SQLite/Milvus 管线 |

**建议 A 作为 provider 的边界，但把"向量库可换"单独当成已存在的 seam 看待**——`VectorIndexStore` 已经是 Protocol（`memory/vector_store.py:10-13`），`MilvusVectorStore` 只是它的一个实现。也就是说插拔有两个层次，不要混为一谈：**换记忆产品（A/B）** 与 **换向量库（已有）**。

这一点必须先定，因为它决定了 `MemoryComponents.initialize()` / `close()` 的生命周期契约归谁——定了再写代码，一行都不用返工。

---

## 2 项目 → 多会话：能力已在，可见性缺失

### 2.1 后端已经支持共享 workspace

`src/agent_harness/session/service.py:319-325`：

```python
workspace_name = self._validate_workspace_name(workspace_name)
workspace = (
    self._state.workspaces_root / workspace_name
    if workspace_name is not None
    else self._state.workspaces_root / session_id     # 缺省=每会话独立
)
```

`POST /api/sessions` 的请求体里有 `workspace: str | None`（`web/app.py:195`），且校验规则明确：**只接受单个目录名、不接受路径、必须落在 `workspaces_root` 内**（`web/app.py:468-499`，防路径穿越与符号链接逃逸）。

**所以：今天就用同一个 `workspace` 名连续创建多个会话 = 一个项目下多个会话，共享同一工作目录。** 这是 storage 层的既有能力，不是待开发功能。

### 2.2 缺的三块（按依赖顺序）

| # | 缺口 | 位置 | 影响 |
| --- | --- | --- | --- |
| 1 | 列表契约无 `workspace` | `session/store.py:36-55`（`SessionSummaryStats`）与 `web/app.py:283-304`（`SessionSummary`）；前端 `types.ts:46` 同样没有 | **前端无法知道某会话属于哪个项目** → 无法分组 |
| 2 | 无"按 workspace 列会话"的能力 | `sandbox/registry.py` 只有 `create`/`get`/`exists`/`stop`/`delete` + 私有 `_read_mapping`，**没有枚举** | 拿不到"这个项目的会话集合" |
| 3 | 无项目导入 | 全仓 grep `UploadFile` / `upload` / `import` / `git clone` **零命中** | "上传项目"确实不存在 |
| 4 | 前端无 UI | `components/`、`hooks/` 内无按 workspace 分组；仅 `useSession.ts` 在建会话时透传 `workspace` | 用户看不到项目维度 |

**注**：前端 `api.ts:77` 已经能**传** `workspace`（`workspace?: string`），所以缺口 4 是"能创建但看不到"，不是"完全没接线"。

### 2.3 上游怎么建模（供选型）

| 方案 | 模型 | 落盘 | 对我们的适配度 |
| --- | --- | --- | --- |
| **DSH** | **Workspace 是持久实体**（uuid + 规范化 path）+ **有序 `sessionIds` 账本**；`SessionHeader.cwd` 做双重成员校验 | `<root>/--<normalized-cwd>--/<encoded-id>/session.v3.jsonl.zstd` | **最贴合**。它是唯一把"项目—会话"关系**显式建模**的；有序账本天然回答"这个项目下有哪些会话" |
| Pi | **没有项目实体**，cwd 就是项目 | `~/.pi/agent/sessions/--<path>--/<ts>_<id>.jsonl` | 最省事：目录名即项目。但"列出项目"要靠扫目录，改名即断链 |
| oh-my-pi | 规范化 cwd 分桶 + `additionalDirectories` | 同 Pi 家族 | 同上，多了多目录归属 |
| **ZCode**（只读观察） | **DB 为中心** | `db.sqlite`（**WAL** 模式）含 `session` / `session_entry` / `message` / `part` / `turn_usage` / `permission` / `workflow_*`；另有每会话 `rollout/model-io-sess_<id>.jsonl`、`agents/<sess>/`、`exec/<sess>/call_*.log`、`log/zcode-YYYY-MM-DD.jsonl` | 一劳永逸（查询自由），但引入第二个真相源——与本项目不变量 #22「不维护第二套不可对账 Session 真相」有张力 |

**建议参考 DSH**：加一个 Workspace 实体（uuid + path + 有序 sessionIds），JSONL 仍是唯一会话真相，账本只是**索引**（可从会话侧重建，不是第二真相源）。这与不变量 #22 相容。若只想最小步：先把 `workspace` 加进列表契约（缺口 1），前端即可分组——**这一步不需要新实体**，只需在映射表里读回 `workspace_root` 的目录名。

---

## 3 多进程共享 workspace：场景、必要性、参考

### 3.1 什么场景会出现

1. **多 worker**：`uvicorn --workers N` 或水平扩容，多个进程服务同一 `sessions_root`。
2. **CLI + Web 同时跑**：两边都指 `settings.workspace_dir`。
3. **独立后台进程**：恢复协调器 / outbox relay 拆到独立进程。
4. **外部工具**：编辑器插件、MCP server 碰同一 workspace。

### 3.2 对当前需求有帮助吗——没有，且非必选

- 仓库内**未见多 worker 配置**；生产入口是单进程 `--factory create_prod_app`（`web/app.py:1355-1361`）。
- `RunManager._runs` / `_live_session` / `ActiveRunConflict` 都是**进程内**结构 → **跨进程没有 run 归属共识**。就算给 JSONL 加了文件锁，两个进程仍可能同时跑同一会话的 run（锁只防日志写乱，不防重复执行副作用）。
- 结论：**今天做跨进程支持是投机**（§9.2）。真做，要连 run 归属一起设计，不是加个锁就完事。

### 3.3 建议：先做"廉价加固"，不做全套

| 层次 | 做什么 | 成本 | 收益 |
| --- | --- | --- | --- |
| 现在（建议做） | **启动期单实例锁**：对 `sessions_root` 取一个 advisory lock / lockfile，第二个进程启动即**响亮失败**并提示 | 极小 | 把最危险的"两进程同时写"变成启动期可理解的错误；本轮 BUG-011 的进程内锁 + seq 守卫（已合）继续兜住单进程内的并发 |
| 将来（有需求再做） | **会话级单写者 handle + 租约**（DSH 形状）：`open(id, 'write')` 第二次 → 明确 already-owned 错误 | 大（要连 run 归属） | 真正多写者安全 |

**不做**"每次 append 加文件锁"：慢，且解决不了重复执行副作用——那是 run 归属问题，不是 IO 问题。

### 3.4 上游怎么做的（对照用户的两问）

- **ZCode：它根本没有独占锁。** 用的是 **SQLite WAL** ——多读一写由数据库事务/锁保证，协调点是 session 表，不是文件锁。
- **DSH：有会话级租约。** `SessionHandle` 单写者 + 跨进程文件租约；第二次 `open(id, 'write')` → `SessionAlreadyOwnedError`。
- **Pi：只在 server/worker 模式加锁。** `proper-lockfile.lock(path, {stale: 2000, update: 1000})` + 创建用 `flag:"wx"`（排他创建）；默认模式只有进程内 `openSessions` map。
- **oh-my-pi**：未发现跨进程租约。

**所以"独占锁是必选"这个前提不成立**——三个主流实现里两个只在特定模式下加锁，一个（ZCode）完全不靠文件锁。**参考 DSH**（要跨进程就读它的单写者 + 租约），**或参考 ZCode**（愿意引入 DB 就让 DB 管事务；代价是第二真相源，与不变量 #22 冲突，不推荐）。

---

## 4 需要走 grill-me → 手册 → tickets 吗

| 议题 | 建议流程 | 理由 |
| --- | --- | --- |
| 记忆 provider 分派 | **1 页 ADR 决策 + 1 张 ticket** | 规格已冻结需求（不变量 #16/#17），无产品歧义；不确定的只有 **seam 划法**（§1.4），定完即可施工 |
| 列表契约加 `workspace` | **直接把 ticket 拆出来做** | 纯增量字段，与 ARCH-4b（`trace_url` 契约）完全同构，已有成熟套路（后端权威锁 + 前端类型注解 fixture） |
| 按 workspace 分组 / 项目实体 | **值得过一轮 grill-with-docs** | 这里才有真正的产品决策：Workspace 是实体还是目录约定？要不要有序账本？删除项目时会话怎么办？ |
| 跨进程 / 独占锁 | **暂不开单**，先登记为已知边界 | 前提（多进程）当前不成立；单实例锁可作为"廉价加固"小票单独提出 |

按 §5：主 Spec Kit 归 Primary Developer；以上是**建议与最小修订范围的界定**，不擅自扩大。

---

## 5 一句话回答用户

- **可插拔**：规格早就要求了，代码只差一张分派表；真正要先定的是"换记忆产品"还是"换向量库"两个不同的 seam。不需要整套 SDD，一页决策 + 一张票。
- **项目 → 多会话**：后端**已经能**（同名 `workspace` = 同目录），你看到的"只有会话"是因为**列表契约不返回 workspace**、前端没有分组 UI、也没有导入项目的端点。参考 **DSH** 的 Workspace 实体 + 有序 sessionIds。
- **多进程 / 独占锁**：多进程场景对你的本地单用户需求**没有帮助、也非必选**；ZCode 甚至不靠文件锁（用 SQLite WAL），DSH 才是单写者 + 租约。建议现在只加**启动期单实例锁**，全套等真有需求。
