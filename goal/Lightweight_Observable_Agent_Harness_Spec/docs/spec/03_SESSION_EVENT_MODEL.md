# 03 — Session Event Model

## 1. 核心决定

Session MUST 采用 **append-only typed SessionEvent log** 作为 Agent 交互历史的主要事实源。

设计参考 DeepSeek Harness 的 event-sourced Session；Session Tree / Fork / Compaction 思路参考 Pi。

不要维护一套无法和 Event Log 对账的“隐藏 messages 真相”。

## 2. Event Envelope

建议最小字段：

```text
event_id
seq
time
type
session_id
run_id?
agent_id?
step_id?
data
source_event_ids?
```

要求：
- `seq` 在单 Session 内单调递增；
- event append 后不可原地修改；
- 修订使用新 Event 表达；
- payload 采用类型化 DTO。

## 3. 核心 Event Vocabulary

**实装全量以生成物为准**：`docs/EVENT_VOCABULARY.md`（由 `scripts/gen_event_vocabulary.py`
从 `event.py` 生成，人工可读 + 机器可解析，勿手改；类型总数与「持久化 / 仅广播」的分节计数
都写在它的头部合计行里）。本文件 MUST NOT 写死事件名清单或类型数量——§3 的旧表正是这样烂掉的
（母票 #173 实测：那张 24 个名字的表里，**21 个实装名从未入表**，另有 **8 个表内名在实现里不存在**
——改名 4 / 列错 1 / 未实现 3）。本文档只负责**语义与分层**（§3–§3.3 保留判据，不保留名字清单）。

本文件里出现的名字都是**例子或指代**，不是清单；清单只有生成物一份。

契约源指向链（**单向，左侧为准**）：

```text
src/agent_harness/session/event.py                  ← 唯一事实源
                                                       （常量 + EVENT_TYPES / STREAM_ONLY_TYPES）
  ├─ scripts/gen_event_vocabulary.py ─→ docs/EVENT_VOCABULARY.md         ← 本文 §3 指向的权威枚举
  └─ scripts/gen_event_types.py ─────→ web/src/generated/event-types.ts   ← 前端词汇表

守卫生成物不漂移：tests/test_event_vocabulary_generated.py
                  tests/test_event_types_generated.py
                  （缺名 / 多名 / 改了 event.py 没重新生成 → 测试红）
```

语义口径：
- 「持久化」= 进 append-only JSONL，`replay` / `fork` / `derive_messages` 可见；
  「仅广播」= 流式瞬时信号，MUST NOT 落盘（不变量 #4：Event ≠ Diagnostic Log）。
- **仅广播**类型（如 `model/started`、`model/delta`，完整名单见生成物的「仅广播」一节）只承载
  **合帧后**的流式信号：`model/started` 让 UI 立刻出现"正在生成"，`model/delta` 是增量
  （ADR-0016 §3.1：禁止的是 per-token 行，不是合帧 chunk 本身）；完整 AIMessage 由
  `model/completed` 持久化，它属于「持久化」一节。
- 逐 token 的原始增量 MUST NOT 永久写入 JSONL（日志爆炸），聚合粒度由运行时按 ADR-0016 决定。
- 事件信封字段（`event_id` / `seq` / `run_id` / `step_id` / `time` …）见 §2；`step` 边界由信封上的
  `step_id` 表达，没有独立的 step 事件（见 §3.3）。

## 3.1 与 SessionEvent **分层**的存储层概念（不是事件）

下面这些概念属于**存储层**，MUST NOT 作为 SessionEvent 写入事件流 / JSONL，
也 MUST NOT 出现在事件词汇表（`docs/EVENT_VOCABULARY.md`，§3）里。分层的理由是同一条：事件流记的是「**对话里发生过什么**」
（`derive_messages` 要读的事实），而这些是「**存储层怎么恢复**」的实现辅助——混进事件流
会让 replay 语义被存储细节污染（ADR-0004 Round 5 Q16）。

| 概念 | 存放位置 | 为什么不是 SessionEvent |
| --- | --- | --- |
| **Checkpoint**（`checkpoint/saved`） | 存储层（见 `07_STORAGE_PERSISTENCE_RECOVERY.md`） | checkpoint 是恢复辅助状态，不是对话事实；`derive_messages` 不需要它。**`checkpoint/saved` 永远不进 SessionEvent**（ADR-0004 Round 5 Q16；实现侧硬约束见 `agent/runtime.py` 与 `storage/checkpoint.py` 顶部注释） |
| **Operation Ledger** | SQLite `operations` 表（`operation_id = tool_call_id`，ADR-0004 Round 5 Q17） | Ledger 记的是**副作用账本**（配合 reconcile 与恢复），不是对话内容。它不参与 `derive_messages`，只被 `RecoveryCoordinator` 读。（`operation/reconcile-required` 是**事件**——那一条是「模型该知道上次有个 operation 进了 NEED_RECONCILE」的对话事实，由 RecoveryCoordinator append。） |
| **Artifact 大内容** | Local / MinIO / S3 兼容存储（spec 06） | 事件里只留 **ref**（`artifact/created` / `artifact/externalized` 携带 `artifact_id` + `size` + `mime_type`），模型只拿 summary + ref，正文不进事件流也不进上下文 |

判据一句话：**会不会改变"模型该看到什么"**。会 → 事件；只是"重启后怎么接着跑"的辅助 →
存储层，不进事件流。

## 3.2 历史名 → 实装名映射（**旧名不是契约**）

本表是为了让按早期 spec 名字检索的人能找到落点。**契约只有一个方向：实装名。**
旧名是历史/概念名，MUST NOT 被当成有效事件名去实现或匹配（改的是文档，不改事件名——
见母票 #173 §4 非目标）。

| spec 历史名 | 实装名（唯一契约） | 证据 |
| --- | --- | --- |
| `agent/delegated` | `agent/delegation-started` | `src/agent_harness/session/event.py`（`AGENT_DELEGATION_STARTED`） |
| `agent/completed` | `agent/delegation-finished` | `src/agent_harness/session/event.py`（`AGENT_DELEGATION_FINISHED`） |
| `approval/requested` | `tool/approval-requested` | `src/agent_harness/session/event.py`（`TOOL_APPROVAL_REQUESTED`）；`web/app.py` 的广播注释亦写作 `tool/approval-requested`（durable） |
| `approval/resolved` | `permission/resolved` | `src/agent_harness/session/event.py`（`PERMISSION_RESOLVED` + `PermissionResolvedData`，见本文 §9） |

判据：事件名的唯一事实源是 `src/agent_harness/session/event.py`；前端词汇表由
`scripts/gen_event_types.py` 从它生成（`web/src/generated/event-types.ts`），有守卫测试
`tests/test_event_types_generated.py`。

## 3.3 未实现的设计草案（**勿按此实现**）

下面三个名字来自早期模型草案，`src/` 与 `tests/` 全目录 **0 命中**（既无常量也无可疑发射点），
且当前设计已用别的机制表达了同一件事——所以它们**不是**"待补的漏实现"。
若要真的引入，必须另开实现票（写清 payload / 不变量 / 谁发射 / 是否持久化）并链回 #173；
在开会之前，MUST NOT 按这些名字实现或匹配。

| 草案名 | 结论 | 当前用什么表达同一件事 |
| --- | --- | --- |
| `step/started` | **草案，不实现** | step 边界由**信封上的 `step_id`** 表达（`session/event.py` 的 EventEnvelope 字段；运行时每条事件都带 `step_id`）。再发一对 step 生命周期事件等于给同一事实造第二个来源，违反单一事实源 |
| `step/completed` | **草案，不实现** | 同上。判读"某步是否结束"用该步事件的存在性与终态（`run/completed` / `run/failed` / `run/interrupted` + 信封 `step_id`），不引入新的成对事件 |
| `context/built` | **草案，不实现** | 上下文装配的结果由 `context/compacted`（压缩后摘要）+ `compaction/start` / `compaction/end`（replay 确定性 bracket）+ `model/completed` 的 usage 共同表达。逐次装配的完整 prompt 不进事件流（体积与冗余，且模型只看得到结果） |

## 4. Derive Messages

模型历史 SHOULD 由 SessionEvent 投影得到：

```text
events
→ derive_messages()
→ message history
→ ContextBuilder
```

要求：
- Tool Call 与 Tool Result 必须正确配对；
- Recovery ToolResult 使用原 `tool_call_id`；
- Compaction Summary 是一种新的 Context 投影，不删除原 Event；
- UI 也尽量消费同一 Event 流。

## 5. Resume

Resume：

```text
load session events
→ validate lineage / seq
→ restore persistence state
→ restore sandbox mapping
→ reconcile operations
→ repair message consistency
→ continue
```

Resume MUST NOT 默认重放所有 Tool。

## 6. Replay

Replay 目标：
- 从已持久化 Event 重新派生 UI / messages / trace；
- 允许“逻辑回放”；
- 默认冻结已发生 Tool Result，不重新产生外部副作用。

如果需要“重新执行式 replay”，必须显式进入不同模式，并要求权限/隔离。

## 7. Fork

Fork MUST 创建新的 Session lineage：

```text
parent session
→ select fork boundary
→ seed child with prefix / snapshot
→ child first live event
→ continue independently
```

要求：
- 父 Session 不改变；
- child 保存 parent identity + fork point；
- UI 能显示 lineage/tree；
- Artifact Ref 可以按权限复用；
- Sandbox fork 的物理策略可独立于 SessionEvent fork。

## 8. Compaction 与 Session

Compaction 只是 Runtime Context 的投影优化。

- Full SessionEvent History MUST 保留。
- Summary MUST 记录其 source range / source events。
- 不允许删除原 tool interaction 事实。
- Fork 到 compaction 之前的历史节点仍应可解释。

## 9. Durable Backend

第一版支持：
- JSONL：最透明、可 grep/tail；
- SQLite：本地索引/查询；
- PostgreSQL：生产型可选 Adapter。

JSONL 与数据库可以同时启用，但需要定义一个清晰的 commit 顺序与恢复策略，避免“双主事实源”。

推荐：SessionStore 抽象负责 append，具体 backend 决定 JSONL-only 或 DB+JSONL projection。

## 10. Acceptance Criteria

- 进程重启后可读取 Session；
- 可从 Event 重建消息链；
- dangling tool call 被检测；
- Resume 不重复已确认成功 Tool；
- Fork 后父子 Session 独立；
- Replay 不触发真实副作用；
- Compaction 后旧历史仍存在；
- UI 可根据事件重新构建主要视图。
