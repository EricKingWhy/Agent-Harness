# ADR-0029 — 用户显式硬删会话（不可恢复、无墓碑）

**Status**: Accepted
**Date**: 2026-09-13
**Related**: #172（本决策的 ticket；用户 2026-09-13 明确裁决「我同意硬删除」）、
#171（**归档**——可逆的整理动作，与本 ADR 并存且语义不重叠）、
ADR-0026（记忆硬删 + outbox —— **本 ADR 的模板**：硬删如何不说谎、审计放哪里、谁来承担确认）、
ADR-0025（Workspace 实体；其 Non-Goals 曾把「会话硬删除」列为非目标——**本 ADR 推翻那一条**）、
ADR-0027（会话 cwd 可为任意已存在目录——**本 ADR 的安全约束正由它逼出**）、
ADR-0004（Round 5 Q18：`archived` 标记 + 手动 `cleanup`，不做自动 TTL）、
spec `03_SESSION_EVENT_MODEL.md`（§append-only / §"Full SessionEvent History MUST 保留"）
**Refines**: ADR-0004 的"不自动清理"（本 ADR 提供一个**用户显式**的、非自动的删除入口）

---

## Context

### 1. 功能断裂：会话只增不减

真实 workspace 已累积 **86 个会话**、侧栏越来越长，而产品**没有任何移除会话的能力**：
`SessionStore` 只有 `append_event` / `read_events` / `list_session_ids`；HTTP 面只有「软删除项目」
与「移出项目」（都不动会话）；CLI 也没有删命令。用户诉求是**真正删掉**（不只是藏起来）。

### 2. 与 spec 的正面冲突（已由用户裁决）

`03_SESSION_EVENT_MODEL.md`：

> Session MUST 采用 **append-only typed SessionEvent log**
> - Full SessionEvent History MUST 保留。
> - **不允许删除原 tool interaction 事实。**

**用户裁决（2026-09-13）**：该条按「**系统**不得静默丢弃历史」解读——压缩/摘要不得替换原始事件；
**用户对自己会话的显式删除不受此条禁止**。按 AGENTS.md §9.1（规格实质冲突必须由用户决策），
本条记录即为裁决凭据，不由 Agent 自行放宽。**同时** `03` 的约束在本 ADR 里被"翻译成可执行规则"：
系统内部任何路径都不得再出现第二种"悄悄删历史"（见 D7 的非目标清单）。

### 3. 致命前置：现成的 delete 路径会删掉用户仓库

`WorkspaceRegistry.delete(session_id)` 一路走到 `LocalSubprocessSandbox.delete()`：

```python
def delete(self) -> None:
    """彻底删除 workspace 目录。..."""
    shutil.rmtree(self._workspace_root, ignore_errors=True)
```

而 ADR-0027 之后 `workspace_root` **可以是用户的任意真实目录**（cwd 会话：映射里就写着
`D:\some\repo`）。也就是说：**任何复用 `WorkspaceRegistry.delete` 的硬删实现都会 `rmtree` 用户的
代码仓库。** `docs/PHASE_STATUS.md:322` 早已登记「这条路径**今天不能有任何生产调用方**」，
实测确认目前只有测试在调。`docs/adr/0025` 也预告过：「若要暴露任何 delete 语义必须先处理它」。

### 4. 会话的真相源在文件系统，不在 DB

`GET /api/sessions` 是**文件系统驱动**的（`SessionStore.list_session_ids()` 扫 `<root>/<sid>/events.jsonl`），
而 `session_meta` / `checkpoints` / `operations` / `workspace_sessions` 是**辅助**（恢复、台账、成员资格）。
这决定了删除的**顺序**与**崩溃语义**（D3）。

---

## Decision

### D1：语义 = 硬删，不可恢复，无墓碑

删掉就是删掉：事件日志、恢复辅助数据、沙箱工件一并消失；**没有回收站、没有 undo、没有 tombstone**。
这与 ADR-0026 对记忆的选择一致（该 ADR 逐字写着「**硬删不可恢复**：误删不可逆（**无墓碑、无回收站**）。
这是用户明确选择」），并与之一致地把**不可恢复性的责任推给入口层**：谁都不许在**无显式确认**的
路径上调用它（前端必须二次确认；若将来有模型工具入口，必须是 DANGER + 审批）。

**"这个会话曾经存在过"只在结构化日志里可查**（D7），不在领域数据里留痕——刻意不与"真相源是文件系统"
的口径打架。

### D2：删除面是**白名单**，且**永不读映射**（本 ADR 的安全核心）

只允许删除**用 `workspace_dir + session_id` 自己拼出来**的三条路径：

| 路径 | 是什么 |
| --- | --- |
| `<workspace_dir>/sessions/<sid>/` | 事件日志目录（唯一真相源） |
| `<workspace_dir>/workspaces/<sid>.json` | 沙箱映射记录 |
| `<workspace_dir>/workspaces/<sid>/` | 默认形态的会话工作区目录（harness 自建） |

**禁止**把映射里的 `workspace_root` 当作删除目标（它可能指向用户仓库）。因此**不调用**
`WorkspaceRegistry.delete()`；改为新增一个**不读映射**的窄方法（`discard_session_artifacts`），
并保留 `delete()` 的"无生产调用方"状态。会话 id 必须先过 `validate_session_id`
（`[A-Za-z0-9_-]+`，路径穿越防护），否则 `../../` 这类输入会让"只删自己拼的路径"这条保证失效。

回归锁（**必须有**）：造一个 cwd 会话指向一个临时真实目录（内含文件）→ 硬删 → 断言该目录
**仍然存在且内容逐字节不变**（`tests/web/test_session_delete_api.py`）。

**"仅当该目录确实是默认形态"如何判定**（#172 的原话）：**由构造决定，不读任何映射**。
`<workspace_dir>/workspaces/<sid>/` 这个路径本身就是默认形态的定义——它由注册表用
`root + session_id` 拼成，只有 harness 会往里写（`create` 的默认分支、以及
`resume_and_launch` 的无条件 `mkdir`），用户目录永远不在这个前缀下。所以判定规则是写死的
构造规则，而不是"解析映射再决定删什么"——后者才是会删到用户仓库的那条路。

**#172 点名的 `resume_and_launch` 坑与规避方式**：`resume_and_launch` 会**无条件**
`mkdir <workspaces_root>/<sid>/`（`session/service.py:568-569`）并让运行时用它，于是
**cwd 会话 resume 之后，映射里的 `workspace_root` 会被改写成默认目录**。也就是说删除
**不能假设"映射一定还指向 cwd 目录"**。本 ADR 的规避方式就是 D2 本身：删除目标由
`session_id` 算出，与映射"此刻写着什么"无关——两种形态下要删的都是 harness 自己的字节，
用户的真实目录两种形态下都不会被引用。（该坑本身**不在本票修**：它不影响删除的正确性，
改它属于会话工作区语义，另开票。）

### D3：顺序 = 先 DB、后文件；每一步幂等，重跑即自愈

- **DB 行先删**（`session_meta` / `checkpoints` / `operations` / `workspace_sessions`），**文件后删**。
- 理由：崩溃窗口的后果不对称。
  - "DB 已删、文件还在" → 会话**仍可见**（列表是 FS 驱动）但丢了恢复辅助数据；**重跑 `DELETE` 可自愈**（每步幂等）。
  - "文件已删、DB 行还在" → 会话从列表消失，但 `session_meta` 残留会让 lineage **冒出幽灵父节点**
    （`build_lineage_tree` 从 `session_meta` 建节点），而重跑只会得到 404、**无法自愈**。
- **刻意不引入新的 outbox / 状态机**：ADR-0026 的 outbox 是为了让"跨系统（SQLite ↔ 向量库）的
  最终一致"可重放；本场景的两个存储是**同一台机器上的 DB 与文件**，靠"DB 先行 + 全步幂等 + 可重跑"
  就已收敛。§9.2 Simplicity First：不为了对称而复制一套用不上的机制。
- 已知残留窗口（记录在案）：清理与"会话列表"之间没有全局锁，删除瞬间另一个列表请求可能仍看见该会话
  （下一个请求即消失）。不加锁——列表是只读快路径，为它引入全局写锁不划算。

**#172 建议的"启动期一致性检查"：不做，理由如下**（该条是 ticket 的**建议**，不是契约段；此处
显式记录偏离）。它要防的是"文件先删、DB 后删"留下的孤儿 `session_meta` 行——而 D3 把这个方向
整个排除了，那条孤儿在本设计里不可能产生。反方向（DB 行已删、文件还在）**无法被检查出来**：
`session_meta` 缺失是**正常**状态（86 个历史会话都没有行，行只在 fork / checkpoint 流程里写），
所以"文件有、行没有"不是异常信号，任何基于它的启动告警都会对着全部历史会话误报。真正需要它的
是"文件先删"的设计；我们没选那个设计，因此不引入一个只会误报的检查（§9.2）。崩溃后的可见症状
（会话还在列表里但恢复辅助数据已丢）本身是诚实的，用户再删一次即收敛。

### D4：guard 五条

| 条件 | 结果 | 理由 |
| --- | --- | --- |
| 无 `events.jsonl` | **404** `SessionNotFound` | 与既有会话端点同款 |
| id 形态非法 | **422** `InvalidSessionId` | 路径穿越防护（D2） |
| 有 **fork** 子会话 | **409**，detail 带子会话数量 | 不级联（静默毁掉用户没选中的会话不可接受）、不静默 orphan（会在 UI 上留下悬空来源链接）；由用户先处理子会话。委派子会话不算（D5） |
| 在途 run | **409** `ActiveRunConflict` | 不允许在别人正在写日志时抽走地面 |
| 有挂起审批 | **409** `ActiveRunConflict` | 队列由 run 的 done-callback 回收，可能滞后于 task 收尾（#172 要求两道都要） |

**"在途"必须用严格判据**，不能用 `RunManager.get_active()`：后者的文档明确写着
「task 已 done 但 terminal 旗标未及置位（finally 在途）的收尾窗口**视为非在途**」——
那个窗口正是 finalizer 还在跑的时刻，用于取消/重连是对的，用于删除是错的。故新增
`RunManager.is_busy()`（"存在 run 且 task 未 done"）。

### D5：委派子会话（内部子 Agent）不阻止删除——已知代价

fork 子会话是**用户可见**的独立会话，故阻止删除（D4）。而**委派子会话**是内部构造
（无映射、无独立工作区、与父共享 sandbox）：它的父子边**由父日志承载**（真相是父日志里的
`delegation-started` 事件），lineage 的补行把它**索引**进 `session_meta`
（`parent_session_id` + `origin="delegation"`，`session/lineage.py:81-102`）。若把它们也算进
guard，任何用过子 Agent 的会话（很常见）都将永远无法删除。**取舍：允许删除，接受该边消失**
（真相随父日志一起没了，子会话此后显示为根）。记录为已知代价，不做级联清理（§9.2）。

**但"显示为根"不会自动发生**：索引行还在，`parent_session_id` 若不清理就会指着一个已不存在的
会话——`build_lineage_tree` 把它渲染成 `(parent missing)` 的**悬空链接**，而这条边**永远无法
自愈**（`_scan_edges` 只从父日志推导边）。所以删除序列里**紧随 DB 步**多一步
`SessionMetaStore.clear_delegation_parent(parent_sid)`：把 `origin='delegation'` 且父为被删会话的
行的 `parent_session_id` / `origin` 清空（只动这一类行；fork 子行不可能存在，因为已被 409 挡住），
于是子会话回到真正的根。它与相邻的 `cleanup` 各自是一次独立的 SQLite 事务——**不共享事务**，
靠"每步幂等 + 序列可重跑"收敛（D3）。这一步**动了别的会话的行**，所以要如实计数并写进审计日志
（`repaired_delegation_links`）——副作用可以存在，但必须被看见。

**判定方式**：`session_meta.parent_session_id == sid` **且 `origin != "delegation"`**。
两种子行的来源在实现里是分开写死的——fork 写 `origin="fork"`（`session/fork.py:220`），
委派由 lineage 回填 `origin="delegation"`（`session/lineage.py:83,102`）——所以这个判据是
可执行的、不是"看情况"。**guard 读的是索引而不是事件流**（要区分 fork / 委派就必须有索引，
扫日志代价不成比例）：索引行只在"有人看过家谱图 / 跑过 lineage"之后才存在，所以**没回填过的
委派边对 guard 不可见**——两种情形都放行，行为一致，不会出现"点开家谱图之后突然删不掉"。
`origin` 为 NULL 而父不为 NULL 的行在当前产品里不该出现，按**保守**方向处理（当成 fork 拒绝），
宁可让用户先去处理子会话，也不留一个悬空父链接。

### D6：不级联 Memory / Artifact（今天没有能力，不硬造）

- **Memory**：`memory_records` **没有** `session_id` 列，SESSION scope 的会话 id 藏在 `namespace` JSON 里，
  **没有索引、没有按会话批量删的 API**。级联需要新查询 + 新索引 → 另开票。
  本 ADR 记录后果：会话删掉后，它的 SESSION 记忆变成**不可达残留**（正常绑定路径再也取不到）。
- **Artifact**：对象存储按 `{session_id}/{artifact_id}` 命名，但 `ArtifactStore` ABC **没有 delete**；
  且 fork **不复制** artifacts（ADR-0017 D5）→ 删父会让**子会话继承的 artifact 引用悬空**。
  记录为已知限制，不在本票修。

  > **2026-09-14 修订（#192 落地本地那一半）**：新增默认 Provider
  > `LocalArtifactStore`（spec 06 §3）时，会话硬删第 ⑦ 步**已连带丢弃
  > `<artifact_dir>/<session_id>/`**（`storage/local_artifact.py::discard_local_artifacts`）。
  > 它严格遵守 D2 的形状：**不读映射**、只删 harness 用 `artifact_dir + session_id`
  > 自己拼出来的路径，所以**不是**本 D6 意义上的"级联删除"（不涉及查询索引、也没有
  > 跨对象图遍历）。仍然**没做**的两件事：① `ArtifactStore` ABC 仍**没有** delete，
  > 配了 S3/MinIO 时**远端对象不会随会话消失**（留下孤儿对象）；② fork 子会话**继承**
  > 的引用在父会话硬删后**依然不可解析**（D1/D5 已接受的代价）。
  > 于是删除行为**随部署而异**（本地删、远端留）——这是记录在案的语义，不是疏漏。

### D7：审计走结构化日志，不进 `SessionEvent`

新增 `session_delete` 事件（注册进 `logging.py` 的 `EVENT_TYPES`），字段**只含 id 与计数**
（`session_id` / `events` / `detached_from_projects` / `repaired_delegation_links`），
**不带任何会话内容**。
照抄 ADR-0026 的同款理由与既有实现：「只带 id 与身份，不带记忆内容」——审计要回答"谁在什么时候
删了哪个会话"，正文进日志只是多余的泄露面。（不预先加 `entry_point`：今天只有 HTTP 这一个
入口，等真有第二个入口时再加，§9.2。）

**同时明确"不许再有第二个悄悄删历史的路径"**（把 spec 03 的禁令翻译成可执行规则）：
本 ADR 只开**用户显式**这一个口子；系统内部的压缩/摘要/裁剪**依然禁止**删除原始事件。

### D8：与 #171（归档）并存，语义不重叠

| | 归档（#171） | 硬删（本 ADR） |
| --- | --- | --- |
| 可逆 | 是（可取消归档） | 否 |
| 入口确认 | 不需要（可逆） | **必须**二次确认写明"不可恢复" |
| 历史 | 保留（只改列表可见性） | **销毁** |
| 用途 | 日常整理（侧栏太长） | 销毁数据（含隐私诉求） |

两者不是替代关系：归档解决"看着乱"，硬删解决"不想要了"。

---

## Consequences

- **误删不可逆**，且没有任何技术兜底（无墓碑/无回收站）。风险全部由**入口层的显式确认**承担——
  这是本 ADR 记下的**依赖**，不是"以后再补"的待办：前端半必须实现不可恢复的二次确认（#172 前端 AC）。
- 与 ADR-0025 的 Non-Goals 冲突条目（「会话硬删除」）随之作废。
- `WorkspaceRegistry.delete()` 继续**没有**生产调用方；本 ADR 新增的安全替代是 `discard_session_artifacts()`。
- 删除后 lineage 中若存在委派子会话，它们会显示为根（D5）；SESSION 记忆成为不可达残留（D6）。
- 可观测性：删除是**结构化日志**里的一条事实，不是会话事件；`GET /api/sessions` 不再返回它。

## Non-Goals

- 回收站 / undo / 墓碑 / 恢复入口。
- 自动清理、TTL、按时间或体积的批量删除（ADR-0004 明确不做自动 TTL）。
- Memory 的级联删除（D6，需另开票：要新查询+索引）。
- Artifact 的**远端**级联删除（D6，需另开票：要先给 `ArtifactStore` 加 delete，并处理
  对象存储的删除错误语义）。**本地那一半已于 #192 落地**（见 D6 修订注）。
- 级联删除 fork 子会话（D4：拒绝而非级联）。
- 修改 `WorkspaceRegistry.delete()` 的既有语义（只需**不调用**它）。
- 模型工具入口（若将来要有，按 ADR-0026 同款：DANGER + 审批）。

## Alternatives considered

| 方案 | 为什么没选 |
| --- | --- |
| **只做归档，不做硬删** | 用户明确要"真正删掉"（含销毁数据/隐私诉求）。归档解决不了"我不想让这些字节躺在磁盘上"。两者并存（D8）。 |
| **软删（`session_meta.archived` + 隐藏）当硬删** | 就是 #171；它可逆，因而不满足"删掉"的语义。 |
| **保留墓碑行** | 与 ADR-0026 的先例不一致（该 ADR 明确"无墓碑"）。墓碑会引入一个"已删但还在"的半状态，每个读者都要处理它——正是本仓不变量 #22 警惕的第二真相。审计需求已由结构化日志满足。 |
| **复用 `WorkspaceRegistry.delete()`** | 会 `rmtree` 用户的真实仓库（Context §3）。**这是硬性否决，不是偏好。** |
| **文件先删、DB 后删** | 崩溃窗口留下**无法自愈**的孤儿 `session_meta` 行 + lineage 幽灵节点（D3）。 |
| **引入 outbox / 删除状态机** | 两个存储同机，DB-first + 幂等重跑已收敛（D3）。§9.2：不复制用不上的机制。 |
