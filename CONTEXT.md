# intelligence-agent

一个 **Python / Async-first、轻量、透明、可恢复、插件化** 的通用 Agent Harness。
Coding / Knowledge / Research 等能力通过 Capability / Provider / Tool 可插拔接入，不是 Core 的特判分支。
本文件是项目的领域词汇表，只定义概念，不写实现细节。

## Language

**Sandbox**:
模型发起的命令与文件操作实际运行的隔离执行环境，是 Runtime 的安全边界而非 Prompt 约束。
_Avoid_: container, executor, environment

**Workspace**:
会话的**操作系统工作目录**——Coding Tool 的起始 cwd 与相对路径的解析基准。默认由 Harness 创建；也可指向**用户指定的已存在目录**（ADR-0027）。注意：权限档（READ_ONLY / WORKSPACE_WRITE / DANGER）是**工具级**授权闸，不做路径校验——目录不是硬围墙。
_Avoid_: working dir, project folder, bind mount, volume

**Project**:
用户**注册**的一个已存在目录在产品层的名字（DSH 模型：项目 = 目录）。是会话的分组单位；归属判定 = 会话工作目录与项目目录一致（账本 + cwd 双重校验，ADR-0025）。
_Avoid_: workspace（本代码库早期把项目实体叫 workspace，现已正名）, folder, repo

**Directory-rooted Session（目录会话）**:
工作目录指向**用户真实目录**（通常是某个项目）的会话——与默认的「Harness 工作区会话」（`workspaces_root` 下自动创建的 scratch 目录）相对。创建时界面必须明示"Agent 将直接读写该目录"（ADR-0027）。
_Avoid_: project session（与 Project 撞词）, attached session

**Coding Tool**:
在 Sandbox 内执行、按 `Tool` 契约暴露给模型的工具（read / write / edit / bash）。
_Avoid_: code tool, file tool, action

**Host**:
用户真实机器，Sandbox 的隔离边界之外的环境。
_Avoid_: 本机, server, node

**Container**:
由 Docker 提供的隔离执行环境，是 Sandbox 的一种后端实现。
_Avoid_: VM, jail, pod

**ExecResult**:
Sandbox 执行一条 shell 命令后返回的原生结果（exit_code / stdout / stderr / duration），由 bash 工具映射成 `ToolResult`。
_Avoid_: CommandResult, ShellResult, RunOutput

**命令业务失败**:
shell 命令返回非零 exit_code 但 Sandbox 调用本身成功（如 pytest 测试不通过）。这不是 Tool Runtime 异常，Agent 应读 stdout/stderr 决定下一步。
_Avoid_: tool failure, execution error, transient error

## Session / Event 层

**Session**:
一次会话的聚合根，持有 `session_id` 与已加载的事件列表；对外提供 `start` / `resume` / `append` / `derive_messages` / `begin_run` / `end_run` 等业务方法，是 Runtime 与外部世界（CLI / Web UI）交互的单一入口。
_Avoid_: conversation, dialogue, chat, context window

**SessionEvent**:
持久化、append-only、类型化的会话事实事件（`session/started`、`run/completed`、`tool/call` 等）。是 Resume / Replay / Fork / derive_messages 的唯一事实源；不可原地修改，修订用新事件表达。
_Avoid_: log entry, message, record, history item

**SessionStore**:
SessionEvent 的薄 IO 层，只负责"读 JSONL / append JSONL"两件事，不持有业务状态。V1 只实现 `JsonlSessionStore`，未来 SQLite / PostgreSQL 作为可替换后端接入。
_Avoid_: database, repository, event bus, message queue

**derive_messages**:
从 SessionEvent 序列投影出模型可见 messages 列表的纯函数。负责 tool_call / tool_result 配对与 dangling 检测；不修改事件、不产生副作用。遵循 `events → derive_messages() → message history → ContextBuilder` 流向。
_Avoid_: serialize messages, flatten history, get messages

**dangling tool_call**:
事件序列中存在 `tool/call` 但无匹配 `tool/result` 的孤立状态（通常因进程崩溃）。处理方式：检测后注入合成 `ToolMessage`（content 写明"执行被中断，结果未知"），让消息链自洽，模型能看到失败并自主决定下一步。
_Avoid_: orphan call, broken chain, missing result

**Run**:
一次 `AgentRuntime.run()` 调用的生命周期单元，绑定 `run_id`。同一 Session 可有多次 Run；Run 边界由 `run/started` 与 `run/completed` / `run/failed` / `run/interrupted` 事件标记，是 Phase 14 Fork 的切分依据。
_Avoid_: turn, iteration, loop, attempt

**run/interrupted**:
进程重启扫描时，对「开了没关」的 run 补记的中断事实（信封带 `run_id` / `step_id`，data 带 `interrupted_seq` / `reason`）。它只声明 run 被打断，**不判定工具副作用是否发生**——那仍由 Ledger reconcile 决定（不变量 #12/#14）。标记后强制 reconcile；UNKNOWN 工具调用需人工裁决，不盲重跑。
_Avoid_: crash log, aborted run, failed run（失败 run 是 `run/failed`，语义不同）

**Resume**:
从已持久化 SessionEvent 加载 Session 并继续对话的能力。流程：`load events → validate seq → restore state → reconcile → continue`。Resume MUST NOT 默认重放已完成 Tool。
_Avoid_: restart, reload, reconnect, replay（Replay 是独立概念，见 Phase 14）

**Diagnostic Log**:
用于 debug / 性能追踪 / 全链路观察的结构化日志（span / trace / agent_decision / retry 等），写入 `logs/agent.jsonl`。与 SessionEvent 分层（不变量 #5：Event ≠ Log），不是业务事实源，不可用于恢复。
_Avoid_: event log, session log, audit trail

**会话当前模型**:
一个 Session 在某一时刻生效的模型选择，由事件流派生而非可变字段：每次切换追加一条 `model/changed`（记 from/to provider + model），当前值取「最后一次切换 > 会话创建时的初值 > 默认链」。切换只写事实、不改历史，下一轮 Run 从事件流读取生效（不变量 #3 / #22）；「切回默认链」同样是一次切换（to 为空）。
_Avoid_: current model field, model override, session model config

**无副作用追加**:
向已有 Session 追加单条事件、但不触发 Resume 副作用的写入路径。Resume 会修复 dangling tool_call 并写 `session/resumed`；Run 在途时走 Resume 会把正在执行的 tool_call 误判为悬空并注入合成结果，破坏 tool_call / tool_result 配对（不变量 #7）。因此切换模型等旁路写入必须走只追加路径。
_Avoid_: raw append, append-only helper

## Storage / Recovery 层

**Operation**:
一次 Tool 调用在持久化层中的身份单元，绑定 `operation_id`（与 `tool_call_id` 1:1）。记录调用从 PENDING → RUNNING → SUCCEEDED / FAILED / CANCELLED 的状态流转；崩溃时 RUNNING 转 UNKNOWN / NEED_RECONCILE。是 reconcile 的最小粒度。
_Avoid_: tool call, invocation, action, transaction

**Operation Ledger**:
所有 Operation 的持久化状态账本。不是 SessionEvent 的副本——SessionEvent 记录"对话历史发生了什么"，Ledger 记录"每次 Tool 调用现在处于什么状态"。Reconcile 时读它而非重放 events，因为外部世界可能在崩溃期间已变（迁移已跑、付款已扣）。
_Avoid_: event log, operation history, execution log

**Checkpoint**:
Session 在某个稳定边界（`USER_ACCEPTED` / `MODEL_COMPLETED` / `TOOL_BATCH_COMPLETED` / `FINAL_COMPLETED`）上的"可恢复事实"快照。不是"代码执行到某一行"，也不是副作用恢复机制（不变量 #12）。Checkpoint + 对应的 SessionEvent SHOULD 尽可能事务化提交。
_Avoid_: save point, snapshot, game save

**Reconcile**:
崩溃恢复时，对照 Operation Ledger 判断每个未终止 Operation 的真实结局并补齐 ToolResult 的过程。按 Operation 终态分四种语义：SUCCEEDED + 缺结果 → 从 Ledger 合成恢复 ToolResult；FAILED → 合成失败结果；CANCELLED → 合成显式取消；PENDING → 可重执行；UNKNOWN → 进入 Tool-specific reconcile 或交用户处理（不变量 #14）。
_Avoid_: rollback, undo, replay, redo

**NEED_RECONCILE**:
UNKNOWN Operation 进入的待裁决状态——Ledger 无法自动判定副作用是否已发生。默认交用户处理，不允许盲重跑（不变量 #14）。
_Avoid_: error, blocked, paused, pending review

**Recovery ToolResult**:
Reconcile 阶段从 Ledger 合成的 ToolResult，复用原始 `tool_call_id`，让 derive_messages 能配对 dangling tool_call。与崩溃时注入的合成 ToolMessage 同目的，但数据来自 Ledger 而非"结果未知"占位。
_Avoid_: fake result, placeholder, dummy result

**ReconcileCallback**:
Resume 时遇到 UNKNOWN Operation 调用的用户裁决回调。与 `ApprovalCallback`（Phase 3，事前授权）平行——ReconcileCallback 是事后裁决（"这个 Operation 的副作用到底发生了吗"）。用户拿到 Operation 全上下文返回裁决（确认成功 / 确认失败 / 手动重跑 / 放弃）。
_Avoid_: approval callback, permission callback, review gate

**CheckpointPolicy**:
注入 AgentRuntime 的薄 seam，决定何时写 Checkpoint。AgentRuntime 在每个稳定边界（`USER_ACCEPTED` / `MODEL_COMPLETED` / `TOOL_BATCH_COMPLETED` / `FINAL_COMPLETED`）调 `policy.maybe_save(session, boundary_type)`。默认实现 `OnStableBoundary`；测试可用 `NoCheckpoint` / `EveryStep`。
_Avoid_: checkpoint manager, save strategy, persistence policy

**ReconcileHint**:
Tool 对"我怎么验证自己是否成功执行"的封装，供 ReconcileCallback 参考。含可验证性标记（verifiable / unverifiable）+ 建议验证动作。Tool ABC 默认返回 `ReconcileHint(verifiable=False)`——安全默认即 NEED_RECONCILE；可验证的工具（read/write/edit/glob/grep/git_status/git_diff）覆写。
_Avoid_: recovery hint, verification plan, side effect description

**RecoveryCoordinator**:
Resume 的编排器，注入 SessionStore + WorkspaceRegistry + OperationLedger + ReconcileCallback，按 07 §9 冻结顺序编排 8 步恢复，暴露 `recover(session_id) -> Session`。Session 只管 events，Runtime 只调 coordinator 一行——恢复是独立关注点。
_Avoid_: session manager, recovery manager, resume controller

**PendingPolicy**:
Reconcile 时对 PENDING Operation（Tool 未启动）的处理策略。默认 skip（合成 skipped ToolResult，最安全）；可注入 retry 策略。Ledger-first 顺序下 PENDING 极罕见。
_Avoid_: retry policy, execution policy, pending handler

**StartupInterruptionScan**（架构约束 / 候选 3）:
进程启动时对全部 session 做一次「无终态 run」扫描：先补记 `run/interrupted`（只写 run 级事实，不猜工具终态——不变量 #12），再强制走一遍 RecoveryCoordinator（Ledger reconcile 才判定工具结局；UNKNOWN 无 ReconcileCallback 时安全拒绝 → 记为「需人工确认」，不伪造、不盲重跑——不变量 #14）。顺序固定为「先标记中断，再 reconcile」；单 session 失败不阻断整轮扫描，以 `FAILED` + detail 如实上报。

**约束——单进程假设（V1）**：扫描**只能在「持有该会话的进程」启动时执行一次**（当前唯一调用点是 web lifespan）。原因：不变量 #22 要求事件流只有一个真相，而 `RunManager` 的在途 run 只存在于本进程内存里——另一个进程无法区分「run 正在跑」与「run 被崩溃打断」。

因此**禁止**在会与长驻服务并发的短命命令（CLI run / 子命令）里触发扫描：那会把别的进程在途 run 误标为中断，进而让两边各自从同一磁盘快照推算 seq 而撞号（会话不可 resume）。多进程 / 多 worker 部署需要跨进程 run lease，属后续 Phase；在此之前，横向扩容会破坏本约束。

本约束是该扫描**不能被吸收进 `RecoveryCoordinator`** 的根本原因之一（另一个是职责层次不同：扫描是「批量 + 三分类结论 + 单会话隔离」，recover 是「单 session 8 步编排」）。二者共享 reconcile 语义，但生命周期契约不同。
_Avoid_: startup recovery, boot scanner, crash sweep, multiprocess scan

## Streaming / Web UI 层

**AgentEvent**:
Runtime 向外发出的业务事件流（`agent/started`、`model/delta`、`tool/started`、`tool/completed`、`run/completed` 等），供 CLI / SSE / Web UI / Test / Trace 多面消费。与 Diagnostic Log 分层（不变量 #4 重申）：AgentEvent 是业务事实可重放，Diagnostic Log 是运维调试不可恢复。`print()` 不能当事件通道。
_Avoid_: log entry, debug message, notification

**ModelDelta**:
模型逐 token 流式产出的事件，对应 `model.astream()` 的单个 chunk。持久化可配置（spec 03 §3：live 必有，落盘可选）；完整 `AIMessage` 始终由 `model/completed` 持久化，delta 不替代完整消息。是「流式输出效果」的数据来源。
_Avoid_: token stream, partial message, streaming chunk

**AgentRuntime.run_stream**:
新增的流式驱动方法，签名为 `async def run_stream(session, user_input) -> AsyncIterator[AgentEvent]`。内部用 `model.astream()` 逐 chunk 产 `model/delta`，保留现有 `tool/call`/`tool/result`/`run/*`/`model/completed` 事件语义。旧 `run()` 保留签名不变（现有 252 测试和 demo 不破），重构为 `run_stream` 的消费端薄封装。
_Avoid_: streaming run, async run, chunked run

**SSE Surface**:
FastAPI 提供的 Server-Sent Events 下行通道（`GET /sessions/{id}/stream`），把 `run_stream` 的 AgentEvent 逐条推给前端。SSE 只是一层传输 surface，**不持有 Runtime 状态**（spec 11 §4）。客户端断连时要清理 generator/queue，不泄漏 producer task，不破坏 Session 一致性。
_Avoid_: push connection, event endpoint, streaming pipe

**Event Projection**:
前端的纯函数 reducer，把 raw SessionEvent / AgentEvent 流投影成渲染模型（对话流 / 工具列表 / step detail）。镜像 Python 侧 `derive_messages` 的逻辑，**不存独立业务真相**（不变量 #22）。保证刷新后从 `GET /sessions/{id}/events` 读历史 + 接 live SSE 完整重建视图。
_Avoid_: view model, state store, client-side truth

**Turn**:
Chat 视图里一个用户输入到下一次用户输入之间的完整循环，含模型若干轮 + 中间的所有工具调用。DSH 式「Thought for a while」折叠默认把过程收起，展开看完整推理 + 工具卡片。
_Avoid_: step, loop, iteration, response

**Tool Card**:
对话流里工具调用的可视化单元，按工具类型分专属卡片：bash → 终端黑卡（stdout/stderr/exit_code）；edit/apply_patch/write → diff 双栏（绿增红删，数据来自工具返回的 before/after）；其余 7 个 → 统一折叠卡片（参数 + 结果 JSON）。每张卡片显式生命周期态（running / success / failed / interrupted）。
_Avoid_: tool widget, call bubble, action block

**Approval Card**:
对话流内联的审批 UI 单元。agent 卡在需审批的 tool_call 时原地出现（工具名 + 参数 + 风险说明 + 同意/拒绝按钮），用户决策走 `POST /sessions/{id}/approve` 回传，批准后工具继续执行、结果回填同一卡片。不用 modal（割裂上下文）。
_Avoid_: permission dialog, confirm popup, auth modal

**Inspector 三栏**:
Web UI 的冻结布局（spec 11 §5）：左栏 Sessions/Runs/Fork Tree；中栏 Conversation + Agent activity + Tool calls；右栏 Step Detail（model 元数据 / tool args/result / retry / artifact / context / checkpoint / recovery）。Phase 4-5 字段在 initial 版本留空槽 + graceful empty state，后续 Phase 填。
_Avoid_: dashboard, console, panel layout

## Artifact / Context 层

**Artifact**:
完整保存但默认不直接注入模型的大对象/大输出。由 ToolResult 溢出自动产生（非 Tool 显式声明），通过 content-hash 寻址（`artifact_id` = 内容哈希）。存于 Runtime 域存储（七牛云 Kodo S3 兼容），不经过 Sandbox。模型只拿到 summary + `artifact_ref`，需要细节时用 `inspect_artifact` 按行局部读取。守不变量 #15「Artifact 大内容优先 Local / MinIO，模型只拿 summary + ref」——此处 MinIO 泛化为对象存储。
_Avoid_: cache file, blob, attachment, large output

**ArtifactStore**:
Artifact 的持久化边界（ABC）。`save()` 存内容返回 `Artifact` 元数据；`load()` 全量读回；`inspect()` 按行范围/关键词局部读。默认实现 `S3ArtifactStore`（七牛云 Kodo S3 兼容端点，用 `aioboto3`），测试用 `FakeArtifactStore`（内存）。接口保持 S3 抽象，未来可换 AWS S3 / R2 / COS。
_Avoid_: file system, blob store, object storage wrapper

**Artifact Overflow**:
ToolResult 后处理的自动溢出检测。当 ToolResult 的主输出字段超过阈值（字符数），Executor 的 `OverflowHandler` 自动调 `ArtifactStore.save()` 存原始内容，然后把 ToolResult 替换成截断摘要 + `artifact_ref`。摘要零 LLM——纯截断（前 N 行 + 后 N 行 + 元数据），在 Ledger 写入之前完成，保证 Ledger 记录的 `result_json` 与 `artifact_ref` 一致。
_Avoid_: truncation, output filter, result compression

**inspect_artifact**:
Phase 5 新增的第 10 个 Coding Tool，READ_ONLY 但操作 Runtime 存储而非 Sandbox。构造时注入 `ArtifactStore`（不是 `Sandbox`）。模型通过 `artifact_ref`（从 ToolResult 获得）按行局部读取 Artifact 细节：`start_line` / `end_line` / `keyword` / `max_lines`。大 Artifact 永远不完整灌回 Context。
_Avoid_: view artifact, artifact reader, file viewer

**ContextBuilder**:
Runtime loop 第 1 步的替换层（`build(session) -> list[AnyMessage]`），内部复用 `derive_messages` 投影 + 做后处理：替换 artifact overflow 后的 ToolMessage、检测 token 占用、按需触发 Compaction。单一入口，Runtime 不再直接调 `derive_messages`。预留 `context_providers: list[ContextProvider]` 扩展点（Phase 6 填 MemoryContextProvider，Phase 5 空列表）。
_Avoid_: context manager, message builder, prompt assembler

**estimate_tokens**:
Token 估算函数（`estimate_tokens(text) -> int`），用 `tiktoken` cl100k_base 精确计数。对所有 provider 一致（对非 OpenAI 模型是 ~10% 近似）。Compaction 的阈值（auto 0.70 / hard 0.85）相对于 `max_context_tokens`（默认 200000），基于这个估算。未来换 Claude 原生 tokenizer 是一行改动。
_Avoid_: token counter, length calculator, context meter

**Compaction**:
当 Runtime Context 的 token 估算超过 `auto_compact_threshold`（默认 0.70 × max_context_tokens）时，ContextBuilder 将早期完整的 AIMessage+ToolMessage 块（以 AIMessage 为原子边界，不可拆断 tool_call/ToolResult 配对）压缩成结构化 summary，注入 messages 头部。持久化 SessionEvent 不变（不变量：完整保存 ≠ 完整注入）；压缩产生 `context/compacted` 事件记录投影变更。
_Avoid_: context truncation, history pruning, window sliding

**Compaction 三层降级**:
摘要生成的降级链：(1) LLM 结构化摘要（用同一个 ModelProvider，保留 facts/decisions/constraints/failed_attempts/unresolved/artifact_refs/citations/tool outcomes）→ (2) LLM 失败时走 deterministic 机械提取（保留 HumanMessage 原文截断 + AIMessage 只留 tool_calls + ToolMessage 只留 tool_call_id + 截断 content）→ (3) 机械提取后仍超 `hard_guard_threshold`（0.85）则抛 `ContextWindowExceededError` 阻止 loop（spec §8：必须停止或要求用户处理）。
_Avoid_: fallback summary, emergency compression, context eviction

**ContextProvider**:
Phase 5 只定义 Protocol（`select(session, token_budget) -> list[AnyMessage]`），不实现。是 ContextBuilder 的扩展点——Phase 6 的 MemoryContextProvider 通过它往 Runtime Context 注入 memory entries。Core 不直接依赖任何具体 Provider。
_Avoid_: context plugin, injection hook, context source

**artifact/created**:
新增 typed SessionEvent，在 Artifact 溢出自动产生时 append。data 带 `{artifact_id, session_id, source_tool, tool_call_id, size, mime_type}`。是业务事实（Tool 副作用产生了外部存储对象），replay 和 fork 都需要。
_Avoid_: artifact log, storage record

**context/compacted**:
新增 typed SessionEvent，在 Compaction 完成后 append。data 带 `{compacted_turn_count, summary_message_count, token_estimate, fallback_used}`。记录 Runtime Context 投影的语义变更（从这个点开始早期 turns 被压缩），replay 时重建 Context 投影需要。
_Avoid_: compaction log, context snapshot

---

## Memory 层（Phase 6）

**IdentityContext**:
请求级的身份上下文（`tenant_id` + `user_id` + `scopes`），由 HTTP 中间件从 JWT 解析后设入 Python `contextvar`。所有 Memory 读写操作从 `contextvar` 读取，不接受外部参数传入。关键安全属性：中间件设置后模型层无法修改——模型不能伪造 `user_id` 查别人的数据。CLI / 测试设默认值 `(tenant_id="local", user_id="local")`。不进 SessionEvent（身份是请求级的，事件是持久的）。
_Avoid_: auth context, user session, identity token

**MemoryCapability**:
Memory 能力的读写原语层（`store` / `recall` / `search`），是 Protocol 不是具体实现。管「能不能存取记忆」。Core 永远只依赖这个 Protocol，不感知 LangMem 或任何具体 Provider。默认实现 `LangMemMemoryCapability`（通过 BaseStore 适配我们的存储），测试实现 `FakeMemoryCapability`（内存 dict）。换 Mem0 只换这个实现，上层不动。
_Avoid_: memory provider (provider 是具体实现，capability 是接口), memory manager

**MemoryContextProvider**:
Memory 能力的上下文注入层，实现 Phase 5 已定义的 `ContextProvider` Protocol（`select(session, token_budget) -> list[AnyMessage]`）。管「按 budget 选哪些记忆注入 Context」。内部调 `MemoryCapability.search` → 按 relevance / recency / importance 修剪到 budget → 拼成单条 SystemMessage 注入 Context（插在 system prompt 之后、对话历史之前）。是 `ContextBuilder.context_providers` 列表的填充者（Phase 5 空列表，Phase 6 填入）。
_Avoid_: memory injector, context memory hook

**MemoryScope**:
记忆的归属层级，对外是 5 值枚举（`GLOBAL` / `TENANT` / `USER` / `SESSION` / `AGENT`），对内映射成 namespace tuple（对齐 LangMem namespace + Milvus partition key）。V1 只实现 `USER`（跨 session 记住用户偏好）+ `SESSION`（session 内临时记忆），其余留枚举不实现。SESSION 的内部 namespace 追加由可信运行入口绑定的 session_id；未绑定时拒绝访问。检索默认只查当前用户的数据（由 IdentityContext 约束）。
_Avoid_: memory level, memory tier, memory namespace（namespace 是内部编码，不是用户面词汇）

**MemoryEntry**:
一条记忆的结构化表示（`id` / `content` / `metadata` / `score` / `created_at`）。由 MemoryExtractor 从 Session 事件流提取，存进 SQLite（权威记录）+ Milvus（向量索引），检索后拼进 SystemMessage 注入 Context。
_Avoid_: memory record（record 是存储层词汇，entry 是领域词汇）, memory item

**MemoryStore**:
Memory 的持久化边界（对外单接口，内部组合 `MemoryRecordStore` + `VectorIndexStore` 两个 Protocol）。权威记录存 SQLite（事实源），向量索引存 Milvus（partition key 按 tenant_id 隔离）。双写通过 outbox pattern 保证最终一致：SQLite 事务同时写记忆行 + outbox 行，进程内 asyncio relay 读 outbox 推到 Milvus。Milvus 写失败不丢数据（SQLite 里有，标记 `indexed=False`，后台重试）。Milvus 索引可从 SQLite 重建。
_Avoid_: memory database, memory backend

**MemoryExtractor**:
从 Session 事件流提取记忆条目的组件，两层降级：(1) LLM 抽取（用 ModelProvider，prompt 要求输出结构化 JSON 记忆条目，失败判据是超时 / 非 JSON / schema 不匹配）→ (2) 启发式规则（`user/message` 抽偏好关键词、`run/completed` 的 `final_text` 抽关键决策、`tool/result` `ok=False` 抽失败模式，纯规则不需 LLM）→ (3) 返回空列表（不写 Memory）。每次 run 结束后台自动触发，模型不参与写入决策。
_Avoid_: memory scraper, memory harvester

**memory/degraded**:
新增 typed SessionEvent，在 Memory Provider 故障降级时 append。记录「本次 Memory 不可用，未注入历史记忆」事实，前端可据此显示降级提示。不阻塞 Runtime loop。
_Avoid_: memory error, memory failed

**LangMem**:
默认 Memory Capability 实现（通过 `[memory]` optional extra 安装）。负责 Memory Formation（从对话提取结构化记忆）+ Consolidation（相似记忆合并去重）+ search（embedding + 相似度检索）。不拥有存储——通过 LangGraph 的 `BaseStore` Protocol 操作我们的 SQLite + Milvus。Core 禁止直接 import LangMem concrete class（不变量 #17）。
_Avoid_: memory engine, memory service

**Outbox（Memory）**:
Memory 双写一致性机制（transactional outbox pattern）。SQLite 单事务同时写记忆行 + outbox 行（要么都成功要么都回滚），进程内 asyncio 后台 relay 定期 poll outbox 表把未同步的行推到 Milvus 向量索引，成功后标记。relay 崩溃重启自动恢复（outbox 行持久化在 SQLite 里）。幂等性由 consumer 保证（按 memory_id 去重）。
_Avoid_: memory sync queue, vector indexer

## Phase 7：Capability / Plugin + Skills

**CapabilityRegistry**:
命名 Provider 注册表（spec 08 的核心机制）。`register(descriptor, provider)` / `get(name)`（缺失抛 `CapabilityError("not_found")`）/ `optional(name)`（缺失返回 None，OPTIONAL 降级入口）/ `descriptor(name)` / `available()`。重复注册同名抛错不静默覆盖。Provider 实例化发生在注册前（factory 函数），Registry 不做生命周期管理。进程内单例，挂在 AppState。
_Avoid_: plugin marketplace, service locator, DI container

**CapabilityDescriptor**:
能力的自描述元数据（spec 08 §5 字段清单原文）：`name / version / provider_name / capabilities[] / risk / supports_streaming / supports_recovery / supports_concurrency / config_schema`，外加 `degradation`（REQUIRED_CORE / OPTIONAL_RUNTIME / OPTIONAL_OBSERVABILITY 三分类）与 `enabled`。`supports(sub)` 是 Consumer 使用前的强制检查位——不支持必须显式报错，不允许"接受但静默忽略"。
_Avoid_: capability metadata bag, plugin manifest（V1 无 manifest 文件）

**CapabilityError**:
Capability 域的显式错误词汇表，四码：`not_found`（注册表无此能力）/ `unsupported`（有但 descriptor 不支持所需子能力）/ `disabled`（配置显式停用）/ `init_failed`（factory 构造失败）。全部显式抛出，无静默降级——降级只能走 `optional()` 的 None 路径。
_Avoid_: generic RuntimeError, silent fallback

**REQUIRED_CORE / OPTIONAL_RUNTIME / OPTIONAL_OBSERVABILITY**:
Capability 三档降级分类（spec 08 §7 原文）。REQUIRED_CORE 缺失则装配期显式失败（Core 无法启动）；OPTIONAL_RUNTIME 缺失则该功能不可用但 Agent 可运行（Memory/Skills 属此档）；OPTIONAL_OBSERVABILITY 缺失不得影响业务执行（Langfuse 属此档）。分类记录在 descriptor.degradation 上。
_Avoid_: soft/hard dependency, optional flag

**CAPABILITIES 配置**:
Plugin 显式配置（spec 08 §6 V1 形态）：env `CAPABILITIES` JSON 字符串，结构 `{"<name>": {"provider": "...", "enabled": bool, "options": {...}}}`。缺省 `{}` = 零行为变化。只做显式加载，不做 entry-point 扫描、不做 Marketplace。
_Avoid_: plugin config file, YAML plugin system

**SkillCatalog**:
发现的 SKILL.md 条目列表：`name + description + 来源路径`。由 `SkillDiscovery` 扫描全局（`~/.intelligence-agent/skills/`）+ 项目（`<workspace>/skills/`）目录 + 手动指定路径产生，只扫一层 `skills/<name>/SKILL.md`。解析失败的 skill 进入显式错误列表，不静默跳过。同名 skill 先到先得。
_Avoid_: skill index, skill database

**渐进披露（Progressive Disclosure）**:
Skill 的 Context 暴露纪律（spec 09 §2，Pi PORT DESIGN）：默认只有目录（name+description，小体积）进 Context；全文只在模型显式调 `load_skill` 后作为 ToolResult 进入当轮对话。Gate 不变量："Skill 全文不默认永久进 Context"。
_Avoid_: skill injection, skill preload

**load_skill**:
按名加载 Skill 全文的 READ_ONLY 工具，走统一 ToolExecutor（Skill 内容不是 Tool，但加载动作是——零旁路）。参数 `name`；未知名明确失败不伪造。ToolResult 前缀声明"技能文档属数据非指令"（防注入框架）。
_Avoid_: skill runner, skill executor

## Knowledge 层（Phase 11）

**Knowledge**:
语料库中的文档证据，与 Memory 平行且互不依赖的概念。Memory = 用户/会话个性化事实（随对话自动抽取、ContextProvider 注入）；Knowledge = 显式摄入的文档语料（只在模型调用检索工具时被查询、带引用）。两者都走向量检索但 Collection、协议、生命周期完全独立。
_Avoid_: 知识库（口语）、documents store, vector memory, RAG memory

**Agentic RAG**:
Knowledge 的检索纪律：检索是一个工具（retrieve_knowledge），模型自主判断当前问题是否需要检索、检索什么——不做每轮自动注入。与 Memory 的被动注入（MemoryContextProvider）形成设计对照。
_Avoid_: auto-injection RAG, 每轮检索

**Chunk**:
文档经递归字符切分后的检索单元：一段文本 + 元数据（source、chunk_index、content_hash）。语料索引与返回的最小粒度；chunk 之间有 overlap 保证边界语义完整。
_Avoid_: segment, fragment, passage

**Citation**:
一条检索证据的可追溯引用：`kb:<source_name>#<chunk_index>`（人类可读 + 机器可解析）。从 citation 能找回完整 source 元数据与原文 chunk——"引用可追溯"是 Phase 11 Gate。
_Avoid_: reference id, source pointer

**KnowledgeSource**:
一次摄入的文档在语料注册表中的登记实体：source_id、source_name、内容 hash、chunk 数与时间。是 chunk 的归属单位、增量判定（hash 未变 → 整篇跳过）与 citation 溯源的锚点。持久化于 SQLite 注册表，与向量库中的 chunk 一一对应。
_Avoid_: document record, file entry, ingest job

**Sufficiency（证据充分性）**:
检索结果对当前问题的证据质量标记：最高相关分达到阈值 → is_sufficient=true，否则如实 false。它是对证据质量的诚实信号——阈值以下的 hits 照常返回，由模型自行鉴别；不是结果开关，更不做 LLM 二次评判（NOT-DO：学术式 Evidence Grader）。
_Avoid_: relevance filter, answer confidence, evidence grade

## Web UI 层（Phase 9-10 / 本轮 UI 重构）

**Continuous Agent Stream**:
中间主区的呈现模型——把 Agent 的 Runtime Events 投影成连续、可折叠、人类可读的工作流叙事，而非散乱日志。回答"Agent 正在做什么"，与右栏 Run Inspector 形成"可读叙事 vs 原始真相"的双层体验。
_Avoid_: chat log, event list, message thread

**Run Inspector**:
右侧常驻的 Runtime Debugger，回答"Agent Runtime 到底发生了什么"。必须比中间主区更详细、更稳定、更适合工程排错：完整 event timeline、Tool Input/Output、Raw event、事件关联、复制/定位/跳转。是项目差异化亮点，不可降级为辅助面板。
_Avoid_: debug panel, side bar, secondary view

**RuntimeEventKind**:
中间主区对事件的**语义分类**（thinking / search / tool / skill / mcp / subagent / todo / model / error / final-answer 等），驱动语义图标与渲染器选择。由**前端推断层**从已有 SessionEvent（tool.name、model 流、mcp__ 前缀等）推导而来——不是新增后端 EventType（不改 SessionEvent 协议，不变量 #3/#4/#18 不动）。
_Avoid_: event type, backend event, raw event kind

**Progressive Disclosure Layer（L0/L1/L2/L3）**:
每条 RuntimeEvent 的四级展开模型——L0 摘要行（图标+动作+duration+status）/ L1 inline detail（input/output 摘要）/ L2 advanced inline（完整 input/output、diff、json tree）/ L3 Inspector Raw（完整原始事件 + event_id/seq/run_id/step_id/tool_call_id）。手动展开优先于全局 density；切换全局模式不丢失手动选中。
_Avoid_: expand state, collapse mode, detail toggle

**Density（四档全局密度）**:
全局默认展开层级与视觉密度调节器：Compact（扫读）/ Balanced（默认，兼顾好看与可观察）/ Detailed（中间主区 L1 debug）/ Raw（原始事件 JSON）。与每事件 manual override 正交——density 给默认 L 级，manual override 覆盖个别事件。沿用现有 `data-density` CSS 属性 + localStorage。
_Avoid_: view mode, display mode, zoom level

**Event Rendering Registry**:
RuntimeEventKind → React 组件 的映射表。新增事件类型只需注册 renderer，不动中间主区主循环。subagent / todo / skill 当前后端无对应 SessionEvent，registry 注册 renderer 但数据不存在时不渲染（不伪造、不占位），后端未来加事件只需接线。
_Avoid_: event switch, hardcoded renderer, case statement

**Inspector Focus**:
右栏当前的上下文焦点——Run 级（默认，展示 RUN/TOOLS/CONTEXT/MODEL/TRACE 摘要）或事件级（点 Timeline 行或中间事件后切到 Input/Output/Raw）。选中 ≠ 展开：选中控制 Inspector 上下文，展开控制中间 inline detail。
_Avoid_: selected event, active row, inspector state

**Main ↔ Inspector Linking**:
中间主区与右栏的双向定位：从中间事件 hover 显示 "Inspect" + 点击即跳（如右栏关着则打开 + Timeline 定位 + 高亮 + 切详情）；从 Inspector 点 event 反向滚动中间并 pulse 600-900ms。是本轮高级体验的核心。
_Avoid_: sync selection, cross-panel highlight, click-through

## Web Search / Reliability 层（Phase 12）

**Web Search**:
模型可自主调用的互联网检索能力，与 Knowledge 平行的检索域。背后是 `WebSearchProvider`（默认 Tavily），实现统一 `RetrievalProvider` 协议。`web_search` 是独立工具（spec §8 硬约束：Web MUST 独立于 retrieve_knowledge），citation 格式 `web:<url>`。不暴露 `read_web_source` 二次读取工具（网页二次抓取成本/法律风险 vs KB 本地切片）。
_Avoid_: internet search tool, browser tool, scraper

**RetrievalProvider**:
Knowledge 和 Web 共享的窄检索协议：`search(query, *, k, gl, hl, freshness) -> list[RetrievalHit]`。两个域各自实现（KB 额外保留 chunk 生命周期方法）；替换 provider = 替换策略类，调用方不感知底层。这是「加搜索方式只要加策略类」的接缝点。
_Avoid_: search engine interface, retrieval facade

**Retrieval Fallback Policy**:
当 `retrieve_knowledge` 返回 `is_sufficient=false` 时，tool result 附带 contextual 提示（"知识库证据不足，可调用 web_search 工具"）。决策仍由模型做出（agentic）；该提示是 tool 侧 affordance，不是 Agent Loop 特判（不违反「Knowledge/Web 是 Capability/Tool，不写进 Loop」不变量）。这是 spec §8 的「轻量 Retrieval Fallback Policy」实现，显式区别于学术 CRAG 的 Runtime 自动编排。
_Avoid_: CRAG（学术名，我们显式不做自动编排）, auto web escalation, retrieval fallback chain

**Repeated Tool Failure Guard（同错熔断）**:
AgentRuntime 的运行时护栏：当模型连续 N=3 次以完全相同的指纹（tool_name + canonical args）调用同一工具且结果失败 → 软熔断（注入 user 角色纠正消息）；再 N=3 仍同指纹失败 → 硬熔断（end_run failed）。计数器在指纹变化时清零。堵住「模型在工具受限环境下反复重试同一失败烧穿步数/token」的回路（#69）。无上游蓝图（pi-mono/oh-my-pi/claude-code 都没这个）。
_Avoid_: tool circuit breaker（我们做的是指纹级不是 provider 级）, tool retry limiter

**Model Fallback**:
主 model provider 瞬时故障（timeout / 5xx / 429 / 连接失败）时切到备用 provider 的运行时韧性机制。非瞬时故障（认证/参数/不支持 tool）不切、直接报错。决策在 provider/model 层（Agent Loop 不感知），通过 `FallbackPolicy` 接口的默认两级实现落地，未来升级全链只换 policy 实现。与 Tool Retry 完全分离（各自独立责任域）。
_Avoid_: model switching, provider rotation, quality-based fallback（我们显式只做瞬时，不做质量判断）

## Multi-Agent 层（Phase 13）

**AgentProfile / AgentSpec**:
Profile 是预定义的 agent 角色（main/coding/research_review，核心域对象，tool_scope 显式声明）；Spec 是运行时实例化描述（AgentFactory 校验后构造现有 AgentRuntime）。动态创建 = 实例化 AgentSpec，绝不生成代码。create_agent 不是 LLM 可见工具（防权限提升）。
_Avoid_: agent class, agent plugin (profile 不是插件；编排能力才是)

**Supervisor**:
持有 delegate 工具的 main profile——编排即 Agent Loop 本身，DelegationDecision = delegate 工具调用参数。无独立编排器组件；路由决策由模型做出（agentic）。
_Avoid_: orchestrator component, router, master agent

**Delegation（delegate 工具）**:
supervisor 把 scoped task 派给子代理的工具，经统一 ToolExecutor（不变量 #7），阻塞并行。参数 {target, task, constraints?}，target 只能是预定义 profile。超预算 = 明确失败回填（不静默截断）。属 multiagent capability（可装卸插件）。
_Avoid_: spawn command, subagent API call

**SubAgentResult**:
子代理只回结构化产物：status/summary/artifacts/citations/changed_files(推导)/unresolved。绝不倾倒完整历史（不变量 #19）。summary 超限溢出为「压缩摘要 + artifact 引用」，主 agent 按需读取（不变量 #15）。tests 字段 V1 缺席（无真实来源不伪造）。
_Avoid_: full transcript dump, child message log

**SubagentProvider**:
spawn 执行器的可替换接缝：V1 唯一实现 in-process（复用同一 AgentRuntime）；未来 subprocess/remote(ACP) = 换实现。属 multiagent capability 的内部 seam。
_Avoid_: agent factory (Factory 是校验+构造；Provider 是执行), runtime copy

**Delegation Budget**:
三级预算：max_delegations=8（每 run）、max_active_children=4（并行）、child max_steps=10。repeated-delegation 熔断复用同错熔断指纹机制（target+task 哈希）。作用域不得混淆（spec §12）。
_Avoid_: global token budget, unlimited delegation

**Spawn vs Fork**:
spawn = 全新 child context/session（V1）；fork = 从父 Session 事件前缀 seed（Phase 14 fork boundary）。V1 只有 spawn，SubagentProvider seam 为 fork/remote 留位。
_Avoid_: clone, copy session

## Streaming UI 层（S-UI，ADR-0016）

**Detached Run**:
run 生命周期与 HTTP 请求生命周期的解耦态：`POST /api/sessions` 只是把 `run_stream` 驱动为独立 asyncio.Task 并返回一个订阅者，断连（SSE generator 被取消）只做 unsubscribe，**绝不取消 run**。这是对 Phase 9「断连即取消」语义的有意修订（ADR-0016 §2.1）。run 的终止只有两个外部路径：显式 `POST /cancel` 与孤儿回收。
_Avoid_: background run, fire-and-forget, async detach

**RunManager**:
web 层的 run 生命周期托管（`web/runmanager.py`）：per-session detached task + 订阅者扇出 + **seq 幂等合并**（session listener 通道与 `_drive` 镜像通道按 durable seq 去重汇流，durable 事实唯一来源是 `Session.append`）+ 有界订阅队列（2000 帧，满时丢最旧保最新——seq gap 让客户端重连自愈）。拥有 `memory_session_var` 的绑定权。
_Avoid_: run registry, task manager, event bus

**合帧（Coalescing）**:
思考/文本/工具输出的 chunk 按窗口（30ms）或尺寸上限（4KB）或生命周期边界合并成**一条 durable 事件**再落盘 + 发帧（S19：禁逐 token 行；S20：绝不扣数据做打字机）。一条合帧 = 一次 `Session.append` = 一个 seq = 一帧 SSE，live 与重放完全同源。实现：`agent/streaming.py BlockStreamer`（思考/文本）与 `tooling/output_stream.py ToolOutputStream`（工具输出，线程安全 sink）。
_Avoid_: batching, debounce, token buffering, typewriter

**block_id**:
流式块的聚合键（SessionEvent/AgentEvent/SSE 帧信封字段，ADR-0016 §3.2）：同一段思考的 delta 共享同一 `block_id`（`rsn-<step>-<序号>`），文本转场/工具转场后新思考段取新 id（02 §8.1 块不变量）。文本与工具输出不用它：文本按既有 turn/step 聚合，工具输出按 `tool_call_id` 聚合。
_Avoid_: chunk id, segment id, group key

**Reasoning 事件族**:
provider 真实思考的 durable 事件（`reasoning/started|delta|completed|interrupted`，data 带 `source`）。**零伪造**：模型不吐思考整族不出现；是否支持思考不按模型名判断（事件驱动）。接出经 `ReasoningChatOpenAI`（langchain-openai 基类丢弃第三方 `reasoning_content`，子类抬进 additional_kwargs）。`interrupted` 保留已落盘部分内容（16.4）；`source:"agent"` 词汇预留给 agent 进度叙述。
_Avoid_: thinking stream, CoT events, hidden thought

**text/delta**:
合帧文本增量（durable），**唯一的文本流通道**——`model/delta` 词汇保留 stream-only 但运行时不再发射（Phase 14 并行约定 event.py 只做加法，且对齐规格 02 §7.4 命名）。拼接 == `model/completed.data.content`。
_Avoid_: model delta, token delta, partial message

**after_seq 重连**:
`GET /api/sessions/{id}/stream?after_seq=N` 的 cursor 续传协议：重放 durable 事实（seq>N）→ 接上在途广播（先订阅后取游标，无缝无重复）→ 终态 run 重放即收尾。backlog 超 1000 发 `stream/truncated` 控制帧（无 seq、非运行事实），客户端走 `GET /events` 全量重建后再连。前端幂等投影键 = seq。
_Avoid_: Last-Event-ID, resume token, sync endpoint

**孤儿回收（Orphan Reclaim）**:
detached run 的零订阅者连续超过 `RUN_DISCONNECT_GRACE_SECONDS`（默认 300s）→ RunManager 取消 run task，取消臂收尾 `run/failed(reason=orphaned)`——与显式取消（reason=cancelled）、异常臂（无 reason）构成 02 §17 的错误语义分型。
_Avoid_: gc, janitor, timeout kill

**Model Catalog**:
`AGENT_MODELS`（JSON 数组）定义的会话级可选模型集（ADR-0016 §5）：`GET /api/models` 列出（默认链 + 条目，零密钥字段），`POST /api/sessions` 的 `model` 参数按 name 选择；条目 api_key/base_url/temperature 缺省回落全局配置。**fallback 链不受选择影响**（ADR-0014：catalog 只替换 primary）。思考能力不进元数据（事件驱动）。
_Avoid_: model routing table, model registry, provider pool
## Session Lineage 层（Phase 14）

**Fork**:
从既有 Session 的事件前缀派生新独立会话（file-per-lineage：每个 session 保持线性 append-only JSONL，树是文件之上的元数据关系）。fork = 用户 CLI 动作，绝不是模型可见工具。父文件 fork 后一字不改。
_Avoid_: branch in place (pi 的树内分叉，被否), session copy (clone 无 provenance), model-invoked fork

**Fork Boundary**:
合法的 fork 切点：前缀必须止于 run 终态（completed/failed）之后——child 文件绝不能以悬空 run 开头。UX 选择器是「从第 N 条用户消息分叉」，两条用户消息之间天然 run 完整。
_Avoid_: arbitrary event boundary, mid-run fork point

**Seed**:
fork 时复制进 child 的事件前缀：重编 seq（child 局部单调）、保留原 event_id 与全部数据。child 自包含可读，不依赖父文件存活（§10 父子独立）。复制原始事件使 fork 到 compaction 之前的节点仍可解释（§8）。
_Avoid_: lazy reference seed (child 依赖父存活 = 不独立), snapshot-only (丢事件事实)

**session/forked**:
child 侧的 provenance 事件（seed 后、第一条活事件前）：parent_session_id / fork_point_seq / boundary_user_message_seq? / tail_summary?。零计算字段；物理细节（workspace 路径）不进事件词表。
_Avoid_: parent-side fork event (父不可改)

**Lineage / Lineage Edge**:
会话树的边，统一两类来源（origin: fork | delegation），双层存储：事件 = 真相（可审计可重建），SessionMetaStore = 索引（parent_session_id / origin / fork_point_seq，O(1) 建树）。delegation child 与 fork child 同树。
_Avoid_: event-only tree scan (全库扫描), index-only (丢审计), second source of truth

**Tail Summary**:
fork 时对父会话 fork point 之后 tail 的一次 LLM 摘要，经 session/forked 可选字段挂 child——file-per-lineage 下「被放弃的尝试」的信息桥。默认开、--no-summary 关、失败降级不挂接（不变量 #21）。injected 语义，绝不清算成用户发言。
_Avoid_: branch summary entry (pi 树内机制，我们无换线场景), mandatory summary

**Copy-on-Fork**:
fork 的 workspace 物理策略：父 workspace 整目录复制为 child 的（fork 点世界快照），物理策略独立于事件 fork。Artifact 不复制——全局 store 内容寻址 ref 直接复用。
_Avoid_: shared workspace (并发写), artifact copy (ref 即可), workspace path in events

**Replay（逻辑回放）**:
从已持久化事件重新派生视图（CLI replay 命令 / Web inspector），tool result 一律冻结终态，绝不产生外部副作用（§6）。重新执行式 replay（真重跑，LangGraph 式）是另一档位，须显式授权模式——本阶段 DEFER。
_Avoid_: re-execute on replay, replay as recovery (恢复是 RecoveryCoordinator 的域)

## Observability / Eval 层（Phase 15）

**Langfuse 旁路（Bypass Observability）**:
`OPTIONAL_OBSERVABILITY` 档的首个实现：未配置 = 模块完全缺席零开销；任何 SDK 异常/端点故障被单一异常边界吞掉，主流程零感知；热路径只做内存操作，全部发送走 SDK 后台队列。三层观测（SessionEvent / 诊断 JSONL / Langfuse）互补不可替代。
_Avoid_: sync network in hot path, capability descriptor 包装（那是 Tool 能力体系）, silent exception (旁路故障必须留 JSONL 诊断痕迹)

**Trace 映射（Trace Mapping）**:
复用既有 ID 的固定对应：session_id→Langfuse session、一次 agent run→trace（恢复链用 `resumes` metadata 标注）、model call→generation、tool operation→tool span、SubAgent→`agent` 型 observation（官方多 Agent 规则：无双 dispatch 节点、递归嵌套、具体命名）。不发明第二套 trace identity。
_Avoid_: new identity system (spec 12 §4), dispatch+execution 双节点, generic trace names

**Trace Content 边界（full / redacted）**:
`LANGFUSE_TRACE_CONTENT` 控制上云内容：full=完整输入输出（自有 dev 项目默认），redacted=只传 metadata+截断/摘要。redaction 是单一函数边界的 hook，未来接策略不改埋点。
_Avoid_: per-call ad-hoc masking, hook as afterthought

**熔断与丢弃计数（Drop Counter）**:
Langfuse 端点持续不可达时旁路暂停发送（指数退避），期间被跳过的写入计数只进 JSONL 诊断行——Event ≠ 诊断日志，SessionEvent 流保持纯净业务事实。
_Avoid_: drop counter into SessionEvent, unbounded retry backlog

**Golden Case**:
Langfuse Dataset 条目；真相源在 repo（`evaluation/datasets/*.jsonl` 版本化导出 + seed 脚本推送），云端不是唯一真相。Eval Runner 项目所有、调真实 AgentRuntime（不为评测重写 Runtime），结果作为 Experiment 上报。
_Avoid_: cloud-only truth (repo 无导出则不可复现), eval-specific runtime

**Deterministic Assertion**:
代码判断的评测断言（tool 选择、dangling=0、recovery 成功、kill/resume 恢复），跑在 ScriptedModel + 真实 Runtime 上、可进 CI；与 LLM judge（语义质量、须校准、只搭不启用）严格分档。
_Avoid_: single opaque score (spec 12 §6), judge for what code can assert, real-model assertions in CI

## Final E2E 层（Phase 16）

**Final Full E2E**:
Roadmap 收尾 milestone——一条完整场景链串联所有核心能力（research → KB → web → citation → coding → kill → recovery → replay → fork → Langfuse trace → Eval report），证明端到端可串 + Gate 指标达标。这是集成验收，不是"把所有 Phase 的 Gate 重跑一遍"。
_Avoid_: 20-step ScriptedModel 大剧本（脆化）, 重复测各 Phase 已覆盖的能力（delegation/compaction/memory/MCP/web-ui）

**分段独立断言 + 薄编排层（Segmented Assertions + Thin Orchestrator）**:
20 节点链路不连续真跑（单步偏离全链崩），拆成分段独立断言（每段独立红/绿/重跑）+ 一个薄编排层 test function（5-6 轮简化链路）证明关键路径可串。薄编排层承担 "Full E2E reproducible" Gate。
_Avoid_: monolithic end-to-end script（维护成本远超收益）

**Probe-gated Integration（探测门控集成）**:
外部依赖不可用时自动 skip 并登记原因（不算失败）的 integration 测试模式。Docker sandbox restore 用此模式（`_docker_available() + skipif`）——daemon 在则真跑容器重建，不在则 skip。与手动验收清单不同：probe-gated 是自动探测、有就跑、没有自动跳。
_Avoid_: 手动验收清单承载可自动化的验证, CI 硬依赖 Docker daemon

**Gate 指标精确化（Gate Metric Precise Definitions）**:
Roadmap 6 项 Gate 的精确口径（ADR-0019 D8）：duplicate confirmed = 0 条重复确认（非计数）；dangling = 0（合成补齐）；core recovery = 全或无（状态恢复 + Ledger 对账闭环 + 继续到 terminal，非百分比）；citation validity = 格式合法 + KB chunk 可查；permission violation = 显式越权被拦 + 合法调用放行；Full E2E reproducible = 薄编排层 deterministic 可复跑。
_Avoid_: 模糊百分比指标无算法支撑, 只测"没遇到边界"不测"边界有效"

**只量不裁（Measure Don't Gate）**:
性能基线（E2E wall clock + 各段耗时）记录到 PHASE16_GATE.md 供后续回归对比，但不设硬阈值——ScriptedModel 延迟不代表真实延迟，真性能优化是独立 Phase。
_Avoid_: CI 硬阈值用 ScriptedModel 延迟（无参考价值）, 性能优化混入 Final E2E

## Prompt 管理层（ADR-0023）

**Prompt Section**:
prompt 的最小可组装单元：冒号命名空间（`profile:coding:identity` / `tool:bash` / `runtime:context_snapshot`）、集中分配的 order、参与的 scope 集合、注入目标、模板正文，以及从正文自动推导出的变量依赖（`requires`）。
_Avoid_: 把整段 prompt 当不可拆的黑盒（失去组装能力）, 手写 requires（可从模板扫描推导）

**Prompt Registry**:
section 的唯一注册与组装入口。扁平结构、重名即抛错（与 CapabilityRegistry 同构）；按 scope **筛选**而非分层覆盖；提供 `available()` 全量视图作为"一处看全貌"的唯一真相。
_Avoid_: scoped-overrides-global 覆盖层（与 CapabilityRegistry 的"重名即抛错"契约冲突）, 把注册表当成安全边界

**严格模板插值（Strict Interpolation）**:
只识别 `{{name}}`（`name` = `^[a-z][a-z0-9_]*$`）；未声明、未提供值、语法非法一律**抛错**；替换值不再二次扫描（无递归插值）。引用实现里 pi 与 ZCode 均静默渲染为空，本项目刻意取严格。
_Avoid_: 未知变量静默渲染为空（故障不可见）, 引入模板执行能力（Jinja2 的属性访问/方法调用是注入面）

**注入目标（Injection Target）**:
section 的两个去向：`system`（稳定内容，进消息列表首部 SystemMessage 前缀）与 `meta_user`（易变的运行时事实，作为 user-role 段插在当前用户消息之前）。分两段的目的是保住 system 前缀稳定，使 prefix cache 不被易变内容击穿。
_Avoid_: 把易变内容放进 system 前缀（其后全部内容失去缓存）

**运行时上下文快照（Runtime Context Snapshot）**:
`meta_user` 段的实现：cwd、日期、模型名、可用工具清单、OS。**运行时组装、永不落盘**——不 `session.append`，故不进 JSONL、不进 `derive_messages()` 投影、不进记忆抽取。与 ADR-0020a 为 system_prompt 立下的纪律一致。
_Avoid_: 持久化为 `user/message`（会落盘、会回放、且单独一条即令记忆抽取的 USER 候选不被降级为 SESSION）, 从投影里过滤掉它（模型也就看不见了，与注入目的矛盾）

**Persona（前缀/后缀覆盖）**:
部署期可定制的人格前缀与后缀，经环境变量 JSON（`AGENT_PERSONA`）覆盖内置值，沿用项目既有的"复杂配置 = env 里 JSON 字符串"约定（与 CAPABILITIES / AGENT_MODELS 同构）。
_Avoid_: 为 persona 单独引入配置文件加载器（项目无此先例）

**Prompt 不变量校验（Prompt Invariants）**:
R1 名唯一 / R2 scope 合法 / R3 变量名合法（注册期）；R4 变量有值 / R5 每 scope 恰有一条 identity / R7 产物非空（组装期）；R6 排序确定性由 `(order, name)` 稳定排序保证（非校验）；另加**进程启动自检**对全部 scope 跑一次空组装 fail-fast。此项超出全部参考实现（dsh 的 invariant 插件仅覆盖 R1/R3 类）。
_Avoid_: 把必需 section 清单拍脑袋堆大（只有 identity 是全部 profile 都有的事实）, 只在组装期才发现悬空引用
