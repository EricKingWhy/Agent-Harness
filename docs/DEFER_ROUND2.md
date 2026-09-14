# Round 2 细节加固 — 设计级 DEFER 清单

> 来源：Round 2 细节审计（context builder / checkpoint / recovery / tooling）。
> 按 AGENTS.md §5 与 §8，这些是设计级或投机性变更，超出当前 ticket scope，
> 只报告不改；落地需 Primary Developer 确认后再开 ticket。

## 决策执行记录（2026-09-05，用户拍板）

用户对 Round 8 交付的 DEFER 清单逐项拍板，执行结果：

**已落地（本批 commit）**：
- R8-1 恢复子系统接线生产 runtime（Ledger/Checkpoint/SessionMetaStore 注入 + WorkspaceRegistry 映射持久化 + POST /api/sessions/{id}/recover 恢复端点）
- R6-4 + R8-3 认证 fail-closed（配置密钥即强制认证 + 强制 exp；未配置启动横幅告警）
- R6-2 零 chunk 流归 model/failed + run/failed
- R8-2 read/grep 输出预算（2000 行/50KB + offset 分页 + 可执行截断标记；grep 单行 500 字符 + max_results ≤1000）
- B 组九项：R6-3 重复 id 去重、R8-6 delete 验证、R4-5 busy_timeout、R6-5 .env 锚定、
  R6-8 provider 去重、R6-6 create_session 顺序、R4-6 formatter 告警、R3-7 run_id、R6-7 事件顺序
- D9→实施：JSONL append 增加 os.fsync（用户要求断电不丢）
- C1 协作取消（Sandbox.exec cancel_event 钩子 + ExecResult.cancelled + BashTool 接线）
- C2 环境变量白名单（默认 OS 必需项白名单 + passthrough_env 逃生门）
- C5 Ledger 复合主键 (session_id, tool_call_id)
- C3a/C3b writeback 逐候选隔离 + close 先 drain
- C3c/R3-4 抽取 prompt 输入有界化（单事件 1000 字符、最多 50 事件）
- C4 provenance 确定性约束（无 user/message 窗口的 USER 候选降级 SESSION）

**关闭（过时/重复）**：
- R4-3（derive/dangling 双真相源）：Round 5 已收敛，实质解决
- 旧#1（= R6-1）、旧#3（= R6-8）：重复条目，以 R6 编号为准
- 旧#2（estimate_message_tokens 微优化）：用户拍板保持 DEFER，保留在下节

**保持 DEFER（用户拍板）**：
- R4-1 Model Fallback（未来 Phase）、R6-1 压缩缓存、R7-2 append 同步 IO、
  R7-3 skill catalog 刷新、R4-2 同 id 并发、R3-8 图像 token、旧#2 微优化、
  旧#5 当前轮 tool 块不可压缩、R4-4 JSONL fsync（**fsync 已实施**，本条仅剩
  "多进程撕裂行"部分——仍无触发路径）、R3-6 本地 sandbox FS 限制（Docker 为真边界）

**残余设计项（需 Primary 后续决策）**：
- recover 端点租户内授权（R9）：POST /api/sessions/{id}/recover 已过认证中间件，
  但与全部既有端点一致只做 authN 不做 authZ——多租户场景下任意租户的合法 token
  可恢复他人 session（第一个带状态变更的恢复面，V1 单用户可接受，多租户前必须补）
- 记忆逐候选来源追踪（provenance 记忆 schema 扩展）——本批以确定性降级规则落地，
  更强方案需记忆模型字段设计
- 记忆逐候选来源追踪（provenance 记忆 schema 扩展）——本批以确定性降级规则落地，
  更强方案需记忆模型字段设计

---


## 1. ContextBuilder 的压缩摘要缓存（设计级）

**位置**：`src/agent_harness/context/builder.py::ContextBuilder.build`

**现状**：每次越过 `auto_compact_threshold` 都会 `ContextCompactor(...)` 重建并
调用模型 `ainvoke` 生成摘要。同一会话在恢复 + 多轮 run 中多次重建上下文时，
若历史投影未变会重复跑摘要。

**为何 DEFER**：
- 缓存失效边界非平凡：键若只取 prefix 消息计数，会漏掉任何前缀内容的修改；
  键若取内容哈希，则每次 build 都要做一次完整哈希（开销可能抵消节省）。
- 缓存状态引入"会话级可变状态"，与 ContextBuilder 当前无状态契约冲突，
  需要重新定义缓存存放点（builder 实例？session？session_meta？）与失效策略。
- 属于性能优化而非正确性修复——按 §9.2 Simplicity First 与 §8 Scope Lock，
  当前不投机构造抽象；先有性能证据（profile）再决策。

**重启条件**：profile 显示压缩摘要调用是 run 时长的主要贡献者，或观察到
同一前缀连续触发 ≥3 次摘要。

## 2. ContextBuilder 单 build 内多次 estimate_message_tokens（微优化）

**位置**：`src/agent_harness/context/builder.py::build`（行 42, 64, 75）

**现状**：一次 build 内对同一组消息多次估算 token。

**为何 DEFER**：估算是纯函数、近 O(n)；合并需要在压缩前后区分估算点，
可读性代价大于收益。`estimate_message_tokens` 不是热路径瓶颈。

## 3. ContextBuilder 的 ContextProvider 去重（设计级）

**位置**：`src/agent_harness/context/builder.py::_with_providers`

**现状**：注入重复的 ContextProvider 时，两者贡献会叠加进入上下文。

**为何 DEFER**：
- 去重需假定"什么算重复"——按类型？按贡献内容哈希？这是装配者的意图，
  不是 builder 应替用户决策的事。
- 用 ContextBuilder 的人在构造时控制 `context_providers` 列表，去重职责
  更适合放在装配点（DI / capability wiring），而非投影入口。

**重启条件**：观察到真实装配路径会无意注入重复 provider 且无法在装配点修复。

## 4. OperationLedger 主键 = tool_call_id 单列（跨会话碰撞隐患）

**位置**：`src/agent_harness/storage/operation_ledger.py`

**现状**：Operation 以 `tool_call_id` 为主键，未含 session_id。跨会话复用同一
`tool_call_id`（例如测试固定 ID、或模型生成碰撞）会让两条 Operation 互相覆盖。

**为何 DEFER**：
- 改主键为 `(tool_call_id, session_id)` 复合键是 schema 迁移，影响
  list_for_session / get / update_state 全部查询路径与 #29/#30 已冻结契约，
  必须由 Primary Developer 走 SDD 流程评估。
- 现网风险低：模型生成的 `tool_call_id` 是高熵随机串；测试固定 ID 是测试
  范畴问题，不应驱动生产 schema。

**重启条件**：观察到生产 Ledger 出现 tool_call_id 碰撞导致的 Operation 覆盖。

## 5. 当前运行期的 tool/call + tool/result 块不可压缩（设计级）

**位置**：`src/agent_harness/context/compactor.py::_validate_tool_blocks`

**现状**：压缩算法把"完整 AIMessage + ToolMessage 块"视为原子单元；若单个
块本身就超预算，会直接 raise ContextWindowExceededError，没有更细的降级。

**为何 DEFER**：
- 这是 compactor 的有意设计：拆解 tool 块会让 AIMessage.tool_calls 与
  配对的 ToolMessage 失去对应关系，破坏不变量 #7（统一工具路径 + 配对语义）。
- 子块压缩（如把 ToolMessage.content 替换为引用 + artifact）属于专项设计，
  需与 ArtifactOverflowHandler / spec 06 共同演进。

---

# Round 3 细节加固 — 设计级 DEFER 清单

> 来源：Round 3 并行审计（MCP/memory writeback/skills discovery/context tokens/sandbox）。
> 同样按 AGENTS.md §5/§8 报告不改。

## R3-1. MCP 子系统整体未实现（spec gap，未来 phase）

**位置**：`src/agent_harness/mcp/` 目录不存在。

**现状**：spec 09 §1/§10 要求的 Remote MCP Server → Client → Adapter → Registry →
Executor 链路完全缺失；`pyproject.toml` 无 MCP 依赖。

**为何 DEFER**：按 14_IMPLEMENTATION_ROADMAP，MCP 属于未来 phase，当前不应超前
落地。任何 MCP 工具的统一执行路径问题（不变量 #7）、错误映射、连接生命周期
都没有对象可守——这是阶段问题，不是 bug。

**重启条件**：进入 MCP phase 时整体设计。

## R3-2. Memory writeback close() 取消而非 drain（设计决策）

**位置**：`src/agent_harness/memory/writeback.py::close`

**现状**：`close()` 对所有在飞任务 `task.cancel()`，不 drain。

**为何 DEFER**：当前契约已被
`tests/memory/test_context_provider.py::test_stream_mirrors_retrieval_degradation_and_writer_can_close`
明确钉死为"close 取消在飞任务"。改成 drain 是关停语义的设计选择
（快关 vs 不丢记忆），需要 Primary Developer 明确应用关停契约：
- 长 drain 会不会拖死滚动重启的 graceful shutdown budget？
- drain 超时后退回 cancel 的预算应是多少？

**重启条件**：用户/Primary 明确关停语义后改契约并改对应测试。

## R3-3. 超大 memory content 永久死信（设计）

**位置**：`src/agent_harness/memory/embeddings.py:14`（`check_embedding_ctx_length=False`）

**现状**：超过 embedding 模型 token 上限的 content 永远索引失败、5 轮后死信，
留在 SQLite 但永远 search 不到。

**为何 DEFER**：合理的修复要么在 store 入口截断（丢语义保可检索），要么在
embedding 前做 chunked embed（新能力）。两者都是设计决策。

**重启条件**：观察到真实生产记忆因超长被死信，或决定加 chunked embed 能力。

## R3-4. extractor 把整段会话无截断塞进单条 LLM prompt（设计）

**位置**：`src/agent_harness/memory/extractor.py:33-35`

**现状**：长会话 prompt 超模型上下文 → 静默回退到关键词启发式，无 degraded 事件
或日志区分。

**为何 DEFER**：修复需要在 extractor 内引入 token 预算 + 分段抽取 + 显式 degraded
事件，是 extractor 的新设计，超出当前 scope。

**重启条件**：profile 显示长会话下 LLM 抽取路径频繁回退到启发式。

## R3-5. 本地 sandbox 泄漏 host 环境变量（安全加固，需设计）

**位置**：`src/agent_harness/sandbox/local.py:121-131`（`Popen` 未传 `env=`）

**现状**：模型经 `sandbox.exec("env")` 能拿到 host 的 `OPENAI_API_KEY`、
`DATABASE_URL` 等任意环境变量——绕过文件系统路径安全（不变量 #11 边界泄漏）。

**为何 DEFER**：local.py 文档已声明是"开发/测试后端，不做进程级隔离"，
生产应走 docker.py。但即便开发后端，过滤 env 是有价值的硬化。延后是因为：
- 需要明确白名单（`PATH`、`SYSTEMROOT`、`LANG`、`HOME`、`USERPROFILE` 等）
  且不能破坏既有依赖 env 的命令测试。
- 这是安全决策，应向用户明示而非默写。

**建议**：未来引入 `SandboxEnvPolicy` 注入白名单/黑名单，默认拒绝凭据式键
（`*_KEY`/`*_TOKEN`/`*_SECRET`/`*_CREDENTIAL*`），其余按白名单。

**重启条件**：用户批准 sandbox 安全硬化，或观察到开发环境真实泄漏。

## R3-6. 本地 sandbox 无 FS 限制（已知限制，文档化）

**位置**：`src/agent_harness/sandbox/local.py`

**现状**：`cwd=workspace_root` 仅设初始工作目录，`shell=True` 下 `cd /`、
绝对路径都能逃出 workspace。

**为何 DEFER**：local.py 文档已显式声明不做进程级隔离，生产走 docker.py。
真正修复需要在 POSIX 引入 bwrap 类 namespace 封装——属于重大设计变更。

**重启条件**：决定给本地后端加 namespace 隔离能力。

## R3-7. context_provider MEMORY_DEGRADED 事件不带 run_id（跨层）

**位置**：`src/agent_harness/memory/context_provider.py:54-57`

**现状**：降级事件不带 `run_id`，无法归因到具体 run；writeback 路径却带了。

**为何 DEFER**：ContextProvider 在 build() 内被调用，不知道当前 run_id；
要带 run_id 得改 ContextProvider 协议（注入 run_id）或在 session 里跟踪
current run——跨层改动，超出加固 scope。

**重启条件**：观察到多 run 交错场景下降级事件归因断裂的真实痛点。

## R3-8. estimate_message_tokens 对多模态图像爆炸（无触发路径）

**位置**：`src/agent_harness/context/tokens.py:12-14`

**现状**：`model_dump_json()` 把 base64 image 也算进 token 数；单张 1MB 图
会让估计多出 ~330K token，触发过早压缩。

**为何 DEFER**：当前 codebase 无任何多模态入口（grep `image_url`/`image_url`
零命中）；按 §8 不为不存在的输入加防御。待真实多模态路径出现时再做内容
分类剔除（替换 base64 为固定图像开销常量）。

**重启条件**：引入多模态消息路径时。

---

# Round 4 细节加固 — 设计级 DEFER 清单

> 来源：Round 4 并行审计（model/provider/logging/config + session/storage/web）。

## R4-1. Model Fallback 链未实现（spec 02 §7，未来 phase）

**位置**：`src/agent_harness/model/provider.py`、`src/agent_harness/cli.py`

**现状**：spec 02 §7 明确要求 transient 失败（timeout/429/provider unavailable）
可触发 fallback 到备用 provider/model，并记录 primary/fallback + reason + attempt；
当前 `create_chat_model` 只返回单个 ChatOpenAI，无 fallback 链、无重试、无归因事件。

**为何 DEFER**：fallback 链是 ModelConfig + provider + runtime 协同的新设计，
属 spec 02 要求的功能但非当前 phase 必需；落地需要错误分类（transient vs
config vs auth）与 fallback 链 schema，应作为独立 ticket 由 Primary Developer
主导，不在加固循环里塞进来。

**重启条件**：进入 model fallback 的专门 ticket。

## R4-2. Session 同 id 多实例并发 append 可能重号（无真实触发路径）

**位置**：`src/agent_harness/session/session.py::append`

**现状**：`_next_seq` 是实例内存字段；同一 session_id 被两个 Session 实例
持有并发 append 会生成两条同 seq 行，`Session.resume` 严格校验会 brick。

**为何 DEFER**：当前所有调用路径都不并发持有同 id 的两个 Session 实例
（web 每次新建 session；recovery 单进程串行；test 都独立 store）。按 §9.1
"不存在的攻击面"，为不存在的并发路径加 store 层 seq 分配或文件锁属于投机。
真实修复（seq 分配下沉到 store 单一事实源，或文件级排他锁）是跨层改动。

**重启条件**：观察到真实生产出现同一 session 被并发持有两个实例的场景。

## R4-3. derive_messages 与 detect_dangling 用两套工具配对真相源（设计）

**位置**：`src/agent_harness/session/derive.py`

**现状**：derive_messages 基于 `MODEL_COMPLETED.tool_calls`；detect_dangling
基于独立 `TOOL_CALL` 事件。两条路径在当前 runtime 发射顺序下暂时一致，但
任何旁路写入（replay、手工拼装、未来不经过 Ledger 的工具路径）会让两端分歧。

**为何 DEFER**：统一两端是 derive 设计层面的重构（选哪个作单一真相源、
对现存所有事件流的影响），超出加固 scope。

**重启条件**：出现 derive_messages 投出孤立 ToolMessage 的真实事件流。

## R4-4. JSONL 写入 flush 无 fsync + 文本模式可能撕裂行（无多进程触发）

**位置**：`src/agent_harness/session/store.py`

**现状**：`fh.flush()` 不调 `os.fsync`；文本模式单逻辑 write 可能拆多次
syscall，多进程 append 可能交错损坏行。

**为何 DEFER**：单进程内文本 TextIOWrapper 缓冲不会撕裂；多进程并发 append
同一 session JSONL 当前不存在触发路径（见 R4-2）。引入 O_APPEND + os.write
单次 syscall + fsync 是性能与耐久性的权衡，需要专门设计。

**重启条件**：决定支持多进程并发写入同一 session，或要求断电级耐久性保证。

## R4-5. SqliteOperationLedger 每操作新连接、无 busy_timeout PRAGMA

**位置**：`src/agent_harness/storage/sqlite.py`

**现状**：`initialize` 只设了 `journal_mode=WAL`，无 `busy_timeout`/`synchronous`；
aiosqlite 默认 timeout=5s，长写并发会抛 `database is locked`。

**为何 DEFER**：当前恢复路径由文件级 pessimistic lock 串行化，写并发不激烈；
改 PRAGMA + 单长连接 + 事务边界是 ledger 性能/并发设计的专门工作，应与
Primary 协同。

**重启条件**：观察到真实 ledger 写并发超时，或进入 ledger 性能优化 ticket。

## R4-6. EVENT_TYPES 白名单"半强制"：formatter 静默改写为 system_log

**位置**：`src/agent_harness/logging.py:205-207`

**现状**：业务经 log_event 强校验；绕过 log_event 直接 `logger.log(...,
extra={"event_type": "...拼错..."})` 会被 formatter 静默归到 system_log，
无告警。

**为何 DEFER**：本仓当前所有 event_type 写入都经 log_event，无旁路；改 formatter
为告警模式属诊断协议变更，影响面需评估。

**重启条件**：出现真实旁路写入拼错 event_type 的案例。

## R6-1. 压缩结果不缓存：每步重建投影 + 重复跑摘要 LLM（设计级）

**位置**：`src/agent_harness/context/builder.py:41-61` + `agent/runtime.py:225`

**现状**：CONTEXT_COMPACTED 只持久化元数据不含摘要内容，derive_messages 忽略
该事件；run 内每一步都重投影全量历史并重跑一次摘要 LLM（30s 超时预算），
同轮内模型可见上下文可能每次不同（摘要重新生成）。usage_total 也不含摘要调用。

**为何 DEFER**：缓存失效键（event mark）或"摘要消息持久化"是 derive/事件模型
层面的设计变更，牵动 replay/resume 语义。

**重启条件**：多步长会话的摘要 LLM 成本/延迟成为实测瓶颈，或 Primary 决定
把摘要内容作为一等事件持久化。

## R6-2. 零 chunk 流被当成"成功完成"（协议语义待定）

**位置**：`src/agent_harness/agent/runtime.py:266-275,337-356`

**现状**：provider 流吐 0 chunk（内容过滤/上游静默失败）时聚合为空 AIMessage，
按 completed + final_text="" 收尾；SSE 客户端无法区分"模型答了空话"与"上游失败"。

**为何 DEFER**：把空完成改为 model/failed 是主 SSE 契约的行为变更，影响前端
消费语义，需 Primary 确认（也牵涉聚合后 content 与 tool_calls 双空的判定规则）。

**重启条件**：Primary 确认空完成应视为失败；或出现真实 provider 零流案例。

## R6-3. 重复非空 tool_call id 让 compaction 永久失败（边界归属待定）

**位置**：`tooling/contract.py:ToolCall.normalize` vs `context/compactor.py:_validate_tool_blocks`

**现状**：模型吐两条相同非空 id 的 tool_call 时，normalize 只补空 id 不去重，
_validate_tool_blocks 按"expected id 集合不重复"拒绝投影——越过阈值后 session
永久 context_window_exceeded。

**为何 DEFER**：去重边界需设计决策（derive 层改写历史 vs normalize 层合成新 id
vs compaction 层跳过坏块），牵动 tool_call_id 一致性不变量，不宜顺手改。

**重启条件**：真实模型/网关吐重复 id 的案例，或 Primary 指定归一层。

## R6-4. JWT_SECRET 未配置时静默关闭身份校验（安全策略待定）

**位置**：`src/agent_harness/web/app.py:307` + `config.py`

**现状**：`if settings.jwt_secret and authorization:` ——未配置 jwt_secret（默认值）
时任何带 Authorization 的请求都被当 trusted "local" 身份放行且无告警日志；
配合 allow_origins=["*"] 等于把 agent API 开放给任意网页。

**为何 DEFER**：fail-closed 是部署策略变更（本地开发场景会直接不可用），需要
Primary 决定"未配置即拒绝启动"还是"启动横幅告警"还是"仅非本地模式 fail-closed"。

**重启条件**：进入真实部署/多租户阶段，或 Primary 拍板策略。

## R6-5. env_file 相对路径依赖 CWD（部署约定）

**位置**：`src/agent_harness/config.py:8`

**现状**：`.env` 按 CWD 解析；从其它目录启动 uvicorn/CLI 时静默加载不到配置，
错误推迟到首个请求内 ConfigError（HTTP 500）。

**为何 DEFER**：改为包根锚定或启动期 fail-loud 是部署约定变更，影响现有
启动脚本与 worktree 约定（AGENTS.md §13）。

**重启条件**：出现真实"从错误目录启动导致配置丢失"的部署事故。

## R6-6. create_session 组装顺序：runtime 构建失败留下孤儿 session（SSE 帧协议）

**位置**：`src/agent_harness/web/app.py:377-414`

**现状**：Session.start → workspace.mkdir → _build_runtime 任一抛错时客户端拿
JSON 500 而非 SSE error 帧，且 store 里留下只含 session/started 的孤儿 session
与空 workspace 目录。

**为何 DEFER**：正确修法（先组装后建 session，或错误转终端 SSE 帧）牵动
session 生命周期与 SSE 协议，属接口设计。

**重启条件**：SSE 错误帧协议统一设计时一并处理。

## R6-7. ARTIFACT_CREATED 先于 TOOL_CALL 落盘（事件顺序协议）

**位置**：`tooling/overflow.py:60-62` vs `agent/runtime.py:392-415`

**现状**：executor 跟踪 ledger 时 ARTIFACT_CREATED（含 tool_call_id）在
execute_batch 内追加，早于该轮 MODEL_COMPLETED/TOOL_CALL 持久化——日志消费者
看到前向引用。

**为何 DEFER**：修法（缓冲 overflow 事件 vs 先写 TOOL_CALL）改变事件发射协议，
影响 replay 语义与现有测试。

**重启条件**：事件顺序协议统一评审时处理。

## R6-8. runtime 双入口注入 context_providers 可能重复执行（API 契约）

**位置**：`src/agent_harness/agent/runtime.py:137-139`

**现状**：同时传 context_builder 与 context_providers 时，provider 列表直接
extend 到 builder 已有列表，无去重——同一 provider 每 build 跑两次。

**为何 DEFER**：正确语义（报错拒绝 vs 忽略 providers vs 按身份去重）是 API
契约决策，当前无真实调用方踩中。

**重启条件**：出现组合传参的真实调用方，或 Primary 定 API 契约。

## R7-1. 工具超时/取消掐不断沙箱子进程（协作取消设计）

**位置**：`tooling/executor.py:555` + `tools/bash.py:65` + `sandbox/local.py`

**现状**：asyncio.timeout 只取消 await，bash 真正跑在 asyncio.to_thread 线程上
无法中断——TIMEOUT 报给模型（或客户端断连取消）后命令继续改 workspace 最长
到沙箱自身 60s 上限。

**为何 DEFER**：需要给 sandbox exec 设计协作取消钩子（进程句柄/事件），是
sandbox 边界协议变更；现状有 60s 硬上限兜底，不是无界。

**重启条件**：Sandbox 执行协议下一次设计评审，或出现超时后副作用伤及真实
环境的案例。

## R7-2. Session.append 同步磁盘 IO 在事件循环上（后台写队列设计）

**位置**：`session/store.py:42-44`（调用点 runtime._drive 全程）

**现状**：每次 append 同步 open/write/flush；web 读路径已走 to_thread，写路径
没有——并发 session 下每个 append 让所有在途 SSE 流等本地磁盘延迟。

**为何 DEFER**：改后台写队列/to_thread 牵动 append 的同步返回语义（seq 分配、
checkpoint 边界、测试大量依赖同步可见性），属存储层并发设计工作。

**重启条件**：实测多 session 并发下 append 延迟成为吞吐瓶颈。

## R7-3. Skill catalog 一次性快照无刷新路径（生命周期设计）

**位置**：`capability/wiring.py:_wire_skills` + `skills/capability.py`

**现状**：catalog 在首请求 wiring 时扫描一次；之后新增技能不可见、删除技能的
load 报 io 错误（已映射为 typed CapabilityError，Round 7），errors/conflicts
随时间过期。

**为何 DEFER**：刷新语义（TTL / 显式 refresh 工具 / 每次 catalog 调用重扫）
是产品决策，影响 provider 生命周期契约。

**重启条件**：真实使用中出现"热更新技能"需求。

## R7-4. Memory writeback 部分失败丢后续候选（outbox 所有权重构）

**位置**：`memory/writeback.py:31-33`

**现状**：extract 出的候选顺序 store，第 N 个失败后其余静默丢弃（只有一条
MEMORY_DEGRADED）；outbox 只覆盖已入 SQLite 的记录，不含未 store 的候选。

**为何 DEFER**：正确修法（候选先入 record store、由 outbox relay 统一拥有
重试）是 writeback/outbox 职责边界重构，牵动 ADR-0008 语义。

**重启条件**：memory 可靠性专项 ticket（与 outbox 死信阈值时间化一起设计）。

## R8-1. 恢复子系统在生产 runtime 完全未接线（ wiring 缺口，最高优先）

**位置**：`web/app.py:_build_runtime`（无 operation_ledger / checkpoint_policy /
session_meta_store）；全仓无 RecoveryCoordinator / Session.resume 调用方

**现状**：Phase 4 组件（Ledger / Checkpoint / RecoveryCoordinator）只被测试
驱动——唯一生产入口 web runtime 没接线，也没有任何 recover()/resume 的
HTTP/CLI 入口。进程崩溃后 web session 的悬空 tool_call 永久无人修复，
不变量 #12/#13/#14 在生产路径不可执行。

**为何 DEFER**：接线 + 恢复入口暴露是 ticket 级工作（涉及启动配置、恢复 API
的鉴权语义、前端交互），不是顺手修复；需要 Primary 确认接线方案。

**重启条件**：Primary 排期恢复接线 ticket（建议作为 #27 后续最高优先）。

## R8-2. read/grep 工具输出无上限（OOM + ledger 膨胀）

**位置**：`tools/read.py:73-76`（整文件进 content）、`tools/grep.py:112-121`
（整行进 matches，max_results 只有下界）

**现状**：读 2GB 日志或 grep 压缩 bundle 会把多 MB 内容放进 ToolResult——
进入 Context（模型可见）、SessionEvent、SQLite ledger（result_json 全量）。
ArtifactOverflowHandler 是唯一缓解但默认未配置且不看 list 字段。

**为何 DEFER**：截断上限是工具契约变更（模型可见行为 + 前端展示），需与
overflow handler 的 artifact 化协同设计（截断应留 artifact ref 而非静默丢）。

**重启条件**：overflow handler 默认接线时一并设计统一的内容预算策略。

## R8-3. JWT 匿名请求 fail-open + 无 exp 强制（部署策略）

**位置**：`web/app.py:330-332,339-341`

**现状**：配置了 jwt_secret 时，无 Authorization 头的请求仍拿 trusted local
身份；require 列表不含 exp——无 exp 的合法签名 token 永不过期。与 R6-4
（未配置 secret 时静默关闭校验）同属认证策略决策。

**为何 DEFER**：fail-closed / exp 强制会破坏现有本地开发流与已发 token，
需要 Primary 拍板策略（同 R6-4 一并决策）。

**重启条件**：同 R6-4。

## R8-4. Memory 抽取的注入清洗与来源约束（信任链设计）

**位置**：`memory/extractor.py:30-39` + `writeback.py` + `context_provider.py:44-48`

**现状**：会话内容（工具输出/文件内容）进入抽取 prompt 仅靠 prompt 声明
"untrusted"；LLM 路径候选无来源检查——注入指令可被"抽取"成 USER scope
记忆（跨会话）并在未来 SystemMessage 回灌。Round 8 已加 2000 字符上限，
但 provenance 约束与清洗属信任链设计。

**为何 DEFER**：provenance 标记（候选只能来自 user/message 等）是记忆模型
的字段/语义扩展，影响 writeback/store/注入链。

**重启条件**：memory 安全专项（与 R7-4 writeback outbox 所有权一起）。

## R8-5. 并发 session 可声明同一 workspace 名（所有权缺失）

**位置**：`web/app.py:422-424` + `_validate_workspace_name`

**现状**：两个 session 可同时用同一 workspace 名——两个 agent 对同一目录
并发执行 MUTATING 工具，edit 的 read-modify-write 会丢更新。

**为何 DEFER**：所有权模型（workspace 绑定创建 session / 目录锁 / 拒绝复用）
是产品决策，V1 单用户本地场景风险低。

**重启条件**：多用户 / 并发任务成为支持场景。

## R8-6. WorkspaceRegistry.delete() 部分删除谎报成功

**位置**：`sandbox/registry.py:111-115` + `local.py:LocalSubprocessSandbox.delete`

**现状**：rmtree(ignore_errors=True) 遇锁定文件静默失败仍删映射——孤儿目录
留在磁盘且注册表无记录（与 R7-1 的 60s 进程窗口叠加时易触发）。

**为何 DEFER**：正确语义（删除后验证 + 保留映射重试 / 显式 partial 报告）
是清理协议设计；当前危害仅限磁盘残留。

**重启条件**：workspace 清理专项（可快修，非紧急）。
