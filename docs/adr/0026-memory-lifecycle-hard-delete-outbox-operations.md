# ADR-0026 — 记忆生命周期：硬删 + outbox 操作类型 + last-write-wins

**Status**: Accepted
**Date**: 2026-09-12
**Related**: ticket #156（MEM-1；后续 #157 解禁 LangMem / #158 冲突消解 / #159 遗忘入口 / #160 前端记忆 UI）、
ADR-0008（Memory Capability 架构）、ADR-0009（Memory namespace 与 scope 授权）、
规格 `06_CONTEXT_ARTIFACT_MEMORY.md` §6（Provider 建议能力含 `update()` / `delete()`）与 §8（失败语义）、
不变量 #16（Memory = Capability + Context Provider）、#21（可选能力故障不拖垮 Core）
**Supersedes**: 无。**Refines**: ADR-0008 子决策 1 的**V1 交付边界**——那里写着
"`update` / `delete` / `extract_candidates` 留接口不实现"。本 ADR 把 `update` / `delete`
（对外名 `update` / `forget`）纳入交付，并冻结它们的语义与并发模型；ADR-0008 的其余部分
（双层 Protocol、LangMem = REUSE+ADAPT、存储主权在项目内、scope 只实现 USER+SESSION）全部不变。

---

## Context

### 用户诉求与"我们主动关掉的四件事"

用户要**真正的 update / delete / forget / 冲突消解**。调研结论是这四件事不是架构不支持，
而是被主动关掉的：①`langmem_capability` 的 `actions_permitted=("create",)`；
②`enable_deletes=False`；③`base_store_adapter` 对 `PutOp(value=None)`（LangGraph 里那就是删除）
直接 `NotImplementedError`；④没给 LangMem 传 `query_model`，于是 manager 永不检索既有记忆，
其 prompt 里的 "Compare & Update / Remove incorrect or redundant" 全程空转。
前三条属于 #157 的"解禁"，本条 ADR 处理的是**我们自己的权威层缺的机制**。

> **勘误（2026-09-12，由 #158 实测更正）**：④ 的机制归因**不成立**。`langmem/knowledge/extraction.py`
> 只在 `query_model is not None` 时启用查询生成；`query_model is None` 时走 `else` 分支，用
> `get_dialated_windows(...)` 生成的 query 照样执行 `store.asearch`（即检索一直在跑）。
> 真正的缺口是**生产装配没给 capability 传 `model`**（`LangMemMemoryCapability(records, vectors)`），
> 而 manager 分支由 `if self._model is not None` 守卫 → 该分支从未执行。修复见 #158
> （`factories.build_builtin_memory_components` 传入同一个模型给消解与抽取）。
> 本 ADR 的 D1–D6 决策不受影响；仅此机制陈述更正，避免后续票为一个不存在的病因去传 `query_model`。

### 缺的机制（本票要补）

- `MemoryCapability` 只有 `store/recall/search`，没有 update/forget 动词。
- `MemoryRecordStore` 没有 delete。
- **outbox 无法表达删除**：`memory_outbox(memory_id PK, revision)` 没有操作类型，
  `PendingMemory` 只有 `entry`（删除时没有 entry 可携带）。
- 没有定义并发语义（`revision` 是每次写新生成的 uuid）。

### 已有一半（不重写）

`SqliteMemoryRecordStore.store()` 本就是 `ON CONFLICT(memory_id) DO UPDATE`（同 id 覆盖 = 更新）；
`MilvusVectorStore.delete(memory_id, identity, scope)` 已实现且按 namespace 过滤 —— 索引侧只需接线。

### 已定位的坑（本 ADR 的直接动因）

`pending()` 以 `memory_records JOIN memory_outbox` 驱动。一旦删除真的去摘记录行，
**JOIN 会把这个 id 直接过滤掉**：outbox 行还在，relay 永远读不到，向量索引留下永久残留
（语义上"忘不掉"）。已在实现前于当前代码上复现：硬删记录行后 `pending() == []`，
而 `memory_outbox` 里那行仍在。所以 outbox 必须能**脱离记录行独立驱动**。

### 用户决策（2026-09-11）

- **删除语义 = 硬删**（真删记录行与向量，不留墓碑）。
- 冲突消解策略 = **LLM 决定合并/取代**（#158；本票只铺机制）。
- 审计**不进会话事件流**（记忆是 Capability，不是会话真相；不变量 #16/#22）。

---

## Decision

### D1. 动词与语义：`MemoryCapability.update` / `forget`

- `update(memory_id, scope, content, metadata) -> memory_id`：**按 id 覆盖写（upsert by id）**。
  这一层只提供**机制**；"该不该更新、更新哪一条"是冲突消解（#158）的策略，不写进本层。
  因此 id 不存在时按新记忆写入（与 `store` 的区别只是 id 由调用方给定）——这与上游
  LangGraph `PutOp` / LangMem manage-update 的语义一致，避免同一片功能出现两种"更新"。
- `forget(memory_id) -> bool`：**硬删**。语义按"先看行是否存在、再校验归属"的顺序定义：
  - id 不存在 → `False`（**幂等**：忘了又忘不是错误；且没有记录行就没有可路由的
    namespace，无法安全清理索引，所以也不产生索引意图）；
  - 存在但属于别的 tenant/user/scope → `PermissionError`（与 `store` 同源；静默 False 会让
    调用方以为删掉了）；
  - SESSION 绑定的记忆要求当前上下文绑定同一 session，否则 `PermissionError`；无绑定时
    `ValueError`（**仅当这条记忆确实存在时**才做绑定校验，理由同上：不存在必须幂等）。
- 索引**异步**跟进：三个写动词只保证"权威记录 + outbox 意图"落盘，向量索引由 relay 收敛。
  调用方不得假设"方法返回 ⟹ 检索已更新"。

### D2. `MemoryRecordStore.delete`：摘行 + 记意图，同事务

- 硬删记录行**与**写一条 `DELETE` 索引意图在同一个 `BEGIN IMMEDIATE` 事务里：
  outbox 写失败时记录行不许单独消失（否则既查不到、也无法修复索引残留）。
- 归属校验按 namespace（`tenant/user/scope` 全比），与 `store` 同源同码（`PermissionError`）。

### D3. outbox = "每个 id 一行的索引期望状态"+ 操作类型 + 自足路由列

- 新增 `operation ∈ {upsert, delete}`；同 id 的后写覆盖前写（含 upsert↔delete 互相覆盖）——
  索引只需收敛到最新期望，不必重放历史。
- 新增路由列 `tenant_id / user_id / scope / namespace`：**删除变更没有记录行可依赖**，
  identity/scope/session 必须由 outbox 自己携带。
- `pending()` 改为**以 outbox 为驱动表**（`LEFT JOIN memory_records`）。
- **孤儿自愈**：outbox 说 upsert、记录行却已不在（升级前遗留 / 绕过契约的删除）→ 按"期望
  状态 = 不存在"处理并记 warning。索引里可能正留着残留，这是唯一能清掉它的机会。
- **脏 `operation` 自愈（方向 = 非破坏性的 upsert）**：`operation` 值不认识时不能抛错——会让
  `pending()` 每轮失败、被 relay 当"outbox 不可用"咽掉 → 索引静默停止收敛；也不能按删除
  处理：对一条还活着的记录，删除先清掉索引里的正确内容，`acknowledge` 随后又给残留的记录行
  写上 `indexed=TRUE` 并移除 outbox 行 → 记忆搜不到、还声称已索引、且无待办意图去修（静默
  丢失，比"停在看得见的坏状态"更糟）。按 upsert 两个方向都收敛且不丢数据：记录行还在 → 用
  权威内容重新索引；记录行已不在 → 由上一条孤儿自愈收敛为删除。CHECK 只在补列时装（SQLite
  不能给既有列追加约束），所以这条兜底是无 CHECK 老库上的唯一防线。

### D4. 并发：内容 last-write-wins，`revision` 是索引同步的乐观令牌

- 写入是单条 `BEGIN IMMEDIATE`（SQLite 单写者）→ 同 id 并发写被串行化，后提交者获胜。
- relay 同步的是哪个 `revision`，就只允许 ack 那个 revision（`memory_id + revision` 匹配失败
  即放弃）。因此"同步期间内容又被改掉"不会让索引停在被覆盖前的版本上：这一轮不 ack，
  下一轮把新内容同步进去；陈旧 ack 也吞不掉新版本。
- **刻意不加 `updated_at` / `version`**：没有调用方做 read-modify-write 的版本比较（#158 先
  检索再写），加了只是装饰；而给 `MemoryEntry` 加字段会牵动每个 fake/adapter 与 LangMem 的
  item 映射。将来若要按"更新时间"排序，那时再加列 + 迁移，并同步更新此结论。

### D5. 迁移：老库就地补列 + 回填，不可路由的孤儿行丢弃并告警

- `initialize()` 检测 `memory_outbox` 缺少 `operation` 列时就地 `ALTER TABLE` 补列，并从
  记录行回填路由事实。
- 无记录行可回填的旧 outbox 行**不可路由**（拼不出 identity/scope）：留着会让 `pending()`
  每轮失败 → 迁移期丢弃并**带 id** 告警（只报数量无法对账）。
- 迁移来的列可空、新建库不可空：`ALTER TABLE ADD COLUMN` 无法"先空后填"再收紧，此差异
  只影响磁盘形状，不影响行为（新库只由本模块写入）。

### D6. 索引失败语义沿用既有约定

删除与写入共用同一套"保留 outbox、下轮重试、连续 5 次死信（进程内）、`indexed=FALSE`
可观察"的约定（不变量 #21）。删除失败不得静默丢失。

---

## Consequences

**正面**：记忆真的有生命周期——删除会到达向量索引且可验证（按 id 读回断言，而不是只看
"搜不到"）；删除在网络故障下可重试、不静默丢失；索引与权威记录的一致性有可测试的收敛规则；
#157/#158/#159 有了共同前置（动词、outbox 操作类型、并发结论都已冻结）。

**负面 / 权衡**：

1. **硬删不可恢复**：误删不可逆（无墓碑、无回收站）。这是用户明确选择，但它把"确认/审批"
   的责任推给了入口层（#159 的模型工具必须是 DANGER + 审批；用户 API 需要显式确认）。
   本 ADR 记录这条依赖：**谁都不许在无确认路径上直接调 `forget`**。

   > **2026-09-12 重新裁决（#157 交付后）**：上面这条"无确认路径不得删除"被放宽在**一个受控
   > 例外**上——LangMem 的固化/整合路径（`writeback` → manager）现在会自主硬删。放宽的理由与
   > 边界：**(a)** manager 只能删**它自己检索回来的 id**，trustcall 的校验器会直接拒掉不在本次
   > 检索集合里的文档 id（真机证据：指名去删别人的 doc id 时校验报错并列出可用 id）；**(b)** 这些
   > id 必然落在调用者自己的 namespace 内，adapter 的 `authorize` 再拒一次跨归属删除（真机证据：
   > 同租户跨 user 与跨 tenant 两种形状都被 `PermissionError` 拒掉，对方记录与索引都原样在）；
   > **(c)** 触发场景是"整合刚学到的内容时发现旧记忆过时"，属于非交互的后台路径，没有可询问的对象。
   > 因此**面向用户的显式遗忘入口仍然必须有确认**（#159 的 DANGER + 审批、#160 的 UI 二次确认）——
   > 被放宽的只是"后台整合路径"，不是"用户说忘就忘"。
2. 删除变更没有记录行 → `indexed` 标志对删除无意义（ack 时的 `UPDATE` 命中 0 行，幂等）。
3. 迁移列可空使新旧库的磁盘 schema 不完全一致（见 D5）。
4. 删除的传播是异步的：`forget` 返回后短时间内检索仍可能命中（直到 relay 跑完一轮）。
   用户可见语义是"最终一致"，解释成本落在 UI/文档（#160）。

---

## 非目标

不解禁 LangMem 的 `update` / `delete`（该非目标已由 #157 于 2026-09-12 交付：adapter 把
`PutOp(value=None)` 映射为硬删、manager 打开 `enable_deletes`，见 Consequences ① 的重新裁决）；
不做 retrieve-before-write / 冲突消解策略（#158）；不做模型工具与用户 API（#159 / #160）；
不改 scope 集合；不新增任何记忆相关的 `SessionEvent`。
