# Phase 14 上游调研 — Resume / Replay / Fork 完整化

> 用途：喂 `/grill-with-docs`（ADR-0016）的参照物底稿。纯调研，零代码。
> 写于 2026-09-06。集成期间静置 `.scratch/`（gitignore），grill 启动时提升进 docs/ 并入 ADR 引用。
> 来源：冻结规格（本仓库 goal/…/spec/03、14）+ pi.dev 官方文档 + Claude Code 官方文档 + LangGraph 官方文档（context7 镜像）。

---

## 1. 冻结规格已划定的边界（不可再讨论，只可落实现）

spec 03 §6-§8 + §10 验收（Session/Event/Resume 模块）：

- **Replay（§6）**：默认 = **逻辑回放**——从已持久化 Event 重新派生 UI/messages/trace，
  **冻结已发生 Tool Result，不产生外部副作用**。「重新执行式 replay」必须显式进入
  不同模式并要求权限/隔离（对应不变量 #12「Checkpoint 不等于副作用恢复」）。
- **Fork（§7）**：MUST 创建新 Session lineage：parent 不变 → 选 fork boundary →
  **seed child with prefix/snapshot** → child 独立续跑。child 保存 **parent identity +
  fork point**；UI 能显示 lineage/tree；Artifact Ref 按权限复用；**Sandbox fork 物理
  策略独立于 SessionEvent fork**。
- **Compaction 交互（§8）**：Full history MUST 保留；Summary 记录 source range；
  **Fork 到 compaction 之前的节点仍应可解释**（implies：fork seed 不能依赖"当前
  投影"——必须能从 full history 重建 boundary 处的上下文）。
- **事件词汇**：spec 03 事件表列有 `session/forked`——**尚未进 EVENT_TYPES**（现仅
  session/started、session/resumed），是 Phase 14 交付物。
- roadmap Phase 14 交付清单：replay projector / fork boundary / lineage tree /
  child session seed / UI+CLI commands / artifact-workspace fork policy。
- 复用矩阵（spec 13）：Session Tree/Fork/Compaction 思路参考 **Pi**（钦定参照物）。

## 2. 上游参照

### 2.1 Pi（钦定参照，pi.dev/docs 官方）

**存储形态**：每会话一个 JSONL；首行 `SessionHeader`（version/uuid/timestamp/cwd，
**可携带 `parentSession` 指向 fork 来源**）；此后每条 entry 共享基座
`{type, id(8-hex), parentId, timestamp}`——**树在文件内**（id/parentId 链），当前
位置 = active leaf。branch = 新 entry 指向较早的 parent（同文件内分叉，不建新文件）。

**三层命令语义**（关键决策参照）：

| 命令 | 文件 | 选择器 | 语义 |
| --- | --- | --- | --- |
| `/tree` | 同一文件 | 全树 | 原地跳到任一 entry 续跑/改发（树探索不落新文件） |
| `/fork` | 新文件 | user-message 选择器 | 从早前 prompt 起新会话（header 记 parentSession） |
| `/clone` | 新文件 | 当前 active 分支 | 复制当前分支再继续（防污染原线） |

**branch_summary**：`/tree` 切分支时可把被放弃分支 LLM 摘要成 `branch_summary`
entry（带 `fromId`）挂在新位置——**换线不丢上下文、不重放**。entry 类型里
`custom`（不进 LLM 上下文）与 `custom_message`（进上下文，display 可控）严格二分。

**Compaction**：`compaction` entry 含 `tokensBefore` + `retainedTail`（新式）——
**自包含检查点**，context 构建从 leaf 向根走，遇 compaction 先发它再发其后内容，
无需走更老的 entry。**labels**：`label` entry 带 `targetId` 指向任意 entry（命名
checkpoint，如 checkpoint-1）。

**SessionManager API 面**（可抄形状）：`create/open/continueRecent/inMemory/forkFrom` +
`getLeafId/getBranch/getTree/getChildren/branch/branchWithSummary/resetLeaf` +
`buildContextEntries/buildSessionContext`。

### 2.2 Claude Code（checkpointing/rewind 官方文档）

- **Checkpoint = 每条用户 prompt**：快照「工具编辑过的文件」+ 会话历史绑定；
  bash 改的文件不追踪（明确声明"不是 Git 替代品"）；保留最近 100 个 checkpoint，
  默认 ~30 天过期。
- **`/rewind` 三选一恢复**：code+conversation / 仅 conversation / 仅 code；
  另有「从这里开始摘要/到此为止摘要」（= 定向 /compact，留在同会话内）。
- **分叉**：`/branch` 或 `claude --continue --fork-session`——保原会话完整，开新线。
- 可借鉴的克制点：它把「会话回退」与「文件回退」拆成两个独立轴（我们对齐规格
  §7「sandbox 物理策略独立于 SessionEvent fork」）；bash/外部副作用不进快照域，
  边界诚实。

### 2.3 LangGraph（time-travel 官方文档）

- `get_state_history(config)`：反序 checkpoint 快照流（snapshot 带 `next`、
  `checkpoint_id`、`metadata.step/source`）。
- **Replay** = `invoke(None, 过去config)`：checkpoint 之前不重跑，之后**真重跑**
  （LLM/API 副作用真实发生）——这正是我们规格 §6 要求显式授权的「重新执行式」。
- **Fork** = `update_state(过去config, values=...)` 在过去点造**新分支 checkpoint**
  （原历史不动）→ `invoke(None, fork_config)` 在分支上续跑。同 thread_id，分支 =
  checkpoint 树。
- 对我们的映射：LangGraph 的"replay"≈我们需显式模式的重新执行式（Phase 14 建议
  DEFER）；LangGraph 的"fork"≈规格 §7，但它分叉的是**状态快照**而非事件流——
  我们是 event-sourced，fork seed 应从事件前缀重建（derive 已有），checkpoint
  机制不参与 fork 语义（Phase 4 checkpoint 是持久化边界，不是时间旅行机）。

### 2.4 ZCode（第一手经验，非文档）

会话线性 + 续接摘要（context 耗尽时 summary 进新窗口，`#sess_*` 可引用历史会话
读取）——没有用户可见的 fork。它的「续接摘要」本质 = pi 的 branch_summary 用在
compaction 场景。启示：**摘要挂接点**在长会话 UX 里比完整 replay 更常用。

### 2.5 DeepSeek Harness

spec 03 的 event-sourced Session 设计本就参考它，Phase 1 已吸收；无独立 fork/replay
特性可再挖，不重复调研。

## 3. 现状盘点（规格要求 → 已有 → Gap）

| 交付物 | 已有 | Gap |
| --- | --- | --- |
| replay projector | `derive_messages`（Phase 1，messages 级逻辑回放 + dangling 合成）；Web inspector 全事件流消费（Phase 9/10，只读投影已可用） | 「产品级 replay」缺：CLI replay 命令、replay 的**冻结 tool result** 语义显式化、（可选）step-through |
| fork boundary | 无。Session 线性 append-only；EVENT_TYPES 无 `session/forked` | fork 边界选择规则、seed 构造（事件前缀重放 vs 快照）、`session/forked` 事件 |
| lineage tree | delegation `child_session_id`（Phase 13，扁平 parent→child） | fork 的 parent identity + fork point 落点（SessionMetaStore? 事件?）；跨 fork+delegation 的统一 tree 视图 |
| child session seed | delegation 的 child = **全新上下文**（task 自洽），非 prefix-seed——与 fork 是两种语义，勿混 | fork seed 与 delegation seed 的共性抽象（都是"以某上下文起 run"）是否值得一个 seam |
| UI/CLI commands | CLI：StreamRenderer（Phase 9）；Web：会话列表/详情 | /tree /fork /rewind 类命令面；Web lineage 视图 |
| artifact/workspace fork policy | WorkspaceRegistry per-session sandbox；artifact store 全局（Phase 5） | fork 时 sandbox 物理策略（复制/共享只读/全新空目录）+ artifact_ref 权限复用规则 |

## 4. 预排序的 grill 问题（ADR-0016 待拍板）

1. **Q1 分叉的物理形态**：pi 的 tree-in-file（单文件 id/parentId 树） vs 规格 §7
   字面的 file-per-lineage（新 session 文件 + parent identity + fork point）。
   规格字面已倾向后者且不破「Session = append-only JSONL」不变量与既有全部恢复
   链；pi 的 `/tree` 原地探索可以用「fork 新文件 + lineage 视图」达到近似 UX。
   **初步倾向：file-per-lineage（守宪法），UI 补 tree 视图**——待 grill 拷打。
2. **Q2 fork boundary 选择规则**：任意 event？仅 user-message 边界（Claude/_pi 的
   /fork 都以 user prompt 为选择器）？stable boundary（复用 Phase 4 checkpoint 边界
   定义）？compaction 之前节点可解释性（§8）如何满足——seed 时从 full history 重建
   boundary 处上下文（derive 已能），摘要 source range 如何随 seed 携带。
3. **Q3 replay 产品形态**：逻辑回放已有两处雏形（derive_messages、Web inspector）；
   本期做 CLI `replay` 命令 + 语义显式化（冻结 tool result 写进文档/测试）？
   重新执行式 replay（LangGraph 式）建议 **DEFER**（副作用风险，规格允许显式模式
   但需求未出现）。
4. **Q4 sandbox/workspace fork 物理策略**：三选一（copy-on-fork / 共享只读 / 全新
   空目录 + 爯 workspace 只读引用）；artifact_ref 权限复用（spec：按权限）。与
   Phase 5 artifact 溢出管线、WorkspaceRegistry 的交互。
5. **Q5 UI/CLI 命令面**：pi 三命令（/tree /fork /clone）+ Claude /rewind 哪个子集
   进 V1？Web 与 CLI 各自承担什么（Web 天然适合 lineage tree 可视化；CLI 适合
   fork/continue 快捷键）。
6. **Q6 lineage 统一模型**：delegation（child_session_id 事件）+ fork（parent
   identity + fork point）两类边如何统一成 tree（SessionMetaStore 加 parent 字段？
   纯事件推导？）——前端 Phase 13 适配后点击钻取已可复用同一 API。
7. **Q7 branch_summary 要不要**：pi 的换线摘要（被放弃分支 LLM 摘要挂新线）在
   我们的 compaction（Phase 5 三层）之上是否加做，还是 DEFER。

## 5. 引用

- pi sessions: https://pi.dev/docs/latest/sessions ；session format: https://pi.dev/docs/latest/session-format
- Claude Code checkpointing: https://code.claude.com/docs/en/checkpointing
- LangGraph time travel: https://docs.langchain.com/oss/python/langgraph/use-time-travel
- 冻结规格: goal/Lightweight_Observable_Agent_Harness_Spec/docs/spec/03_SESSION_EVENT_MODEL.md §6-§8, §10；14_IMPLEMENTATION_ROADMAP.md Phase 14
