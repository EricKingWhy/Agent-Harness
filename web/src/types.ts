/** Shared types — mirror backend SessionEvent / AgentEvent shapes.
 * Source of truth: src/agent_harness/agent/types.py + session/event.py
 * Frontend never owns truth; it projects events into view-models.
 */

/**
 * Event type constants are GENERATED from session/event.py (single source) —
 * see web/src/generated/event-types.ts. Do not hand-edit values here.
 */
export { EventType, STREAM_ONLY_TYPES, type EventTypeValue } from './generated/event-types';

/** A single SSE frame from POST /api/sessions or durable event from GET events. */
export interface AgentEvent {
  type: string;
  data: Record<string, unknown>;
  seq: number | null;
  /** ⚠ 可能整个键缺失，但**只在历史事件路径**：`GET /api/sessions/<id>/events` 走
   *  `SessionEvent.to_dict`，它省略值为 None 的字段（实测 59 事件里 2 条无此键：
   *  session/started、user/message）。**SSE 帧相反**——`web/serialization.py::_envelope`
   *  恒写这个键，无归属显式下发 `null`（实测 59/59 帧键都在）。两条路径喂同一个
   *  `AgentEvent`，故类型取超集「可能缺失」；契约与冻结规格一致
   *  （03_SESSION_EVENT_MODEL.md 的 `run_id?` / 03_RUNTIME_EVENT_CONTRACT.md 的
   *  `run_id?: string | null`）。判空一律宽松 `!= null`：严格 `!== null` 会把键缺失
   *  当有值，run_id 直接 `.slice()` 抛 TypeError。 */
  run_id?: string | null;
  /** 语义与超集理由同 `run_id`。⚠ 额外陷阱：模板字符串接受 `undefined`，所以
   *  `if (e.step_id !== null) \`step ${e.step_id}\`` 仍能通过 tsc——**正是 BUG-008
   *  的写法**（渲染出字面量 "step undefined" 与伪造 key `step:undefined`）。
   *  本字段必须 `!= null` 判空。 */
  step_id?: number | null;
  /** Durable-event timestamp (SessionEvent.time, present on GET /events history).
   *  SSE frames don't carry it yet — projection falls back to client clock. */
  time?: string;
  /** Present on historical events read from the store. */
  event_id?: string;
  /** Present on SSE-streamed events (injected by POST /api/sessions endpoint).
   *  Absent on historical events read from the store (session_id is known from the URL). */
  session_id?: string;
  /** Reasoning 块聚合键——envelope 顶层字段（T-contract #116，后端 SessionEvent.block_id
   *  序列化位置）。reasoning/started|delta|completed|interrupted 携带；data.block_id
   *  是 legacy 容错位（投影解析顺序：envelope → data → 合成）。 */
  block_id?: string;
}

/** 项目引用（WS-3 / #153；后端 `src/agent_harness/web/app.py::WorkspaceRef`）。
 *  `id` 用于请求与重命名，`title` 用于显示——两者都由后端给，前端零推导。 */
export interface WorkspaceRef {
  id: string;
  title: string;
}

/** 项目目录状态（WS-4 / #154，后端 `web/projects.py::Project.status`）。
 *  `missing-dir` = 注册时存在、现在被移走/改名——后端**只如实上报，不改记录**，
 *  所以前端也不能据此隐藏项目（那会把用户注册过的东西变没）。 */
export type ProjectStatus = 'ok' | 'missing-dir';

/** 项目实体（WS-4 / #154，后端 `web/projects.py::Project`）。
 *
 *  `session_ids` 是**账本手工序**（用户拖出来的顺序，后端已过滤成员资格）——
 *  前端按它渲染项目内顺序，**不按活动时间重排**（WS-3 的契约立场）。 */
export interface Project {
  id: string;
  path: string;
  title: string;
  status: ProjectStatus;
  session_ids: string[];
  created_at: string;
  updated_at: string;
}

/** DELETE /api/projects/{id} 的响应（软删除结果）。
 *
 *  `detail` 是后端写好的中文文案，**必须原样展示**：它明确说「会话与目录都没删」，
 *  是 AC5 要的那句「不让人误以为会话连坐消失」的唯一权威来源（前端不自己编）。 */
export interface ProjectDeleted {
  id: string;
  deleted: boolean;
  sessions_detached: number;
  detail: string;
}

/** 一个子目录条目（`GET /api/host/dirs`，ADR-0028 D2）。
 *
 *  `path` 是宿主侧的**真实绝对路径**——这正是该端点存在的理由：浏览器拿不到真实
 *  路径（`<input type=file>` 只给 `C:\fakepath\…`，Web 平台没有目录路径 API），
 *  所以候选路径只能由宿主端列举出来。`name` 与 `path` 都由后端给，前端零拼接。 */
export interface HostDirEntry {
  name: string;
  path: string;
}

/** 目录列举结果（`GET /api/host/dirs`，ADR-0028 D3/D4）。
 *
 *  `path === null` = **根模式**（请求没带 `path`）：`entries` 是盘符/根列表。
 *  此时"当前目录"并不存在——界面据此禁用「向上」与「选择此目录」，而不是假装
 *  当前在某个路径上。
 *  `truncated` = 子目录数超过后端上限（500），`entries` 只含**排序后**的前 500
 *  条：必须如实提示，否则用户会以为"这个目录里就这么多"。 */
export interface HostDirsListing {
  path: string | null;
  parent: string | null;
  truncated: boolean;
  entries: HostDirEntry[];
}

/** 记忆归属范围（后端 `memory/types.py::MemoryScope`）。
 *
 *  `session` 的记忆按**会话**归属；HTTP 用户入口只暴露 `user`（浏览会话记忆需要
 *  可信的会话绑定，MEM-4 明确不在范围）。类型上保留两者：模型工具侧与未来入口
 *  都可能出现 session 行，管理面必须能如实渲染而不是把未知值当 user。 */
export type MemoryScope = 'user' | 'session';

/** 一条记忆（后端 `web/memory.py::MemorySummary`，GET /api/memories 的元素）。
 *
 *  `content` 是**权威记录里的正文**（不是向量检索的投影——管理界面要的是"我记住
 *  了什么"，不是"哪几条最像某个 query"）。`metadata` 已由后端剥掉 provider 内部
 *  载荷（`public_metadata`），前端只渲染 `content` / `created_at` / `scope`。
 *  `created_at` 是后端给的 ISO 字符串，前端零解析、零改写（格式化只在展示层）。 */
export interface MemorySummary {
  id: string;
  content: string;
  scope: MemoryScope;
  metadata: Record<string, unknown>;
  created_at: string;
}

/** DELETE /api/memories/{id} 的响应（硬删成功）。
 *
 *  **硬删不可恢复**（不是软删/回收站）：后端 `forget` 真的移除记录行与索引。
 *  失败语义在后端是**显式**的：id 不存在 → 404、不属于当前入口 → 403、
 *  记忆能力未装配 → 503（前端据此区分"没了"/"不给删"/"未启用"）。 */
export interface MemoryDeleted {
  id: string;
  deleted: boolean;
}

/** Session summary from GET /api/sessions. */
export interface SessionSummary {
  session_id: string;
  event_count: number;
  first_event_time: string | null;
  last_event_time: string | null;
  /** 首条 user/message content（后端截断 128 字符；无则 null）——Session Rail
   *  标题零额外请求预填（后端 Gap 3）。events 扫描保留为 fallback。 */
  first_user_message: string | null;
  /** Langfuse trace id（后端 Gap 2）。Langfuse Phase 15 才接入，当前恒 null——
   *  UI 显示「未追踪」，属预期降级而非故障。 */
  trace_id: string | null;
  /** Langfuse trace 可点击 URL（契约 2d7f87a，ADR-0018 D7 延伸）：后端用官方
   *  get_trace_url(trace_id) 构造，含 host + project_id，前端零 URL 拼接。
   *  trace_id 与 trace_url 并列不互替：前者机器可读（Copy 命令），后者人类
   *  可点击（详情面板超链接）。未启用 Langfuse 两者都 null。 */
  trace_url: string | null;
  /** 会话所属项目（WS-3 / #153，后端 `SessionSummary.workspace`）。
   *  **未分组 = null**（历史遗留 / 未命名 workspace / 装配里没有项目索引）——
   *  后端绝不伪造（不变量 #21 同族）。分组 UI 按 `null` = 未分组渲染（#155）。 */
  workspace: WorkspaceRef | null;
  /** #171：是否已归档。**非可选**——与 `workspace` 同款理由：后端把它声明为必填
   *  （`web/app.py::SessionSummary.archived`），前端声明成可选就会让"漏读"变成
   *  `undefined`，于是已归档的行静默丢掉徽标、也躲过归档开关的过滤。
   *  这是「已归档」徽标与归档可见性过滤**唯一**的数据源。 */
  archived: boolean;
}

/** `POST/DELETE /api/sessions/{id}/archive` 的成功回执（#171）。
 *  `archived` 是**动作后**的真值（幂等：重复归档仍是 true）。 */
export interface SessionArchived {
  id: string;
  archived: boolean;
}

/** `DELETE /api/sessions/{id}` 的成功响应（硬删回执，#172 / ADR-0029）。
 *
 *  与 `ProjectDeleted`（软删）**刻意不同形**：那个带 `sessions_detached` 与 `detail`
 *  来解释"会话没被删"，这里走到 200 就是**东西没了**——没有墓碑、没有回收站，
 *  也没有"半删"状态可表达。后端 schema 用 `Literal[True]` 把这件事钉死
 *  （`web/app.py::SessionDeleted`），前端类型照抄同一个字面量：调用方因此写不出
 *  一个无意义的 `if (receipt.deleted)`（那问题在客户端根本不存在）。
 *
 *  `events` = 删除前事件日志的条数（**删除前**取——删完只剩文件系统，无从统计）；
 *  `detached_from_projects` = 本次从几个项目账本里摘掉了它（正常 0/1）。两者是
 *  确认回执的唯一数据来源：前端不自己数，也不猜。 */
export interface SessionDeleted {
  id: string;
  deleted: true;
  events: number;
  detached_from_projects: number;
}

/**
 * Token 用量形状——model/completed.data.usage 与 run/completed.data.usage_total
 * （后端 Gap 1）。AgentEvent.data 是宽松 Record<string, unknown>，此接口是
 * projection 边界窄化解析的契约文档：三字段必须全为有限数，否则整体按 null
 * 处理（UI 显示「—」，绝不部分伪造或补零）。
 */
export interface UsageStats {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

// ── View-models (projection output) ──

/** 空状态示例任务注入 Composer 的载荷（对象引用变化即触发注入）。 */
export interface PresetTask {
  text: string;
  id: number;
}

/** 会话呈现模式——conversation 永远属于 mode 指向的会话（编译期保证）。
 *
 * - idle：无选中会话（空状态）。
 * - live：正在流式创建/跟随的新会话；sessionId 为 null 表示 POST 已发出、
 *   首帧尚未确认（session_id 由 SSE 帧注入）。
 * - viewing：查看（历史重建）中的会话。
 *
 * 迁移规则：live → viewing 只发生在流结束/出错/取消时；viewing/live 之间切换
 * 由 selectSession 处理（切走即放弃当前流，幂等）。
 */
export type SessionMode =
  | { kind: 'idle' }
  | { kind: 'live'; sessionId: string | null }
  | { kind: 'viewing'; sessionId: string };

export interface ToolCall {
  tool_call_id: string;
  name: string;
  args: Record<string, unknown>;
  /** DSH 四态语义（冻结决策 "Unique Product Signatures" 第 69 行）：
   *  running（进行中）| success（成功）| failed（失败）| stopped（被中断，≠ error）。 */
  status: 'running' | 'success' | 'failed' | 'stopped';
  result?: unknown;
  /** before/after 内嵌 "use <读回工具>(<id>)" marker 时 archived=true + artifactId
   *  ——diff 内容已归档到 artifact，视图渲染占位态。
   *  `artifactTool` 是 marker 里**后端实际建议**的读回工具名（S3 → `inspect_artifact`，
   *  MinIO / Local → `read_artifact`）：回显与复制都用它，不在前端替换（#186 AC4）。 */
  diff?: {
    before: string;
    after: string;
    truncated: boolean;
    archived?: boolean;
    artifactId?: string;
    artifactTool?: string;
  };
  started_at?: string;
  completed_at?: string;
  /**
   * Raw event payloads (Trace Density Raw tier — Brief "Raw = 原始事件 JSON").
   * Verbatim shallow copies of the projection source events (type/time/step_id/data);
   * never fabricated, never synthesized from parsed fields.
   */
  raw_call?: Record<string, unknown>;
  raw_result?: Record<string, unknown>;
  /** Artifact produced by this tool call when output overflows the inline limit.
   *  Set by artifact/created event (Phase 5). Inspector fetches via inspect_artifact. */
  artifact?: ArtifactRef;
  /** T3（#96）：流式输出缓冲（tool/output_delta 逐段累积；按事件序保 channel）。 */
  output?: ToolOutputChunk[];
}

/** T3（#96）：工具输出流块（契约 C2 tool/output_delta）。
 *  channel 保真（stdout/stderr 分色，视觉可合并）；相邻同通道 delta 由投影
 *  合并进尾块，数组规模有界。result 到达后 chunks 保留（流式内容不丢弃）
 *  ——渲染优先 chunks，缺失回退既有 result 路径（视图不双写）。 */
export interface ToolOutputChunk {
  channel: 'stdout' | 'stderr';
  text: string;
}

/** Large tool output offloaded to the ArtifactStore (Phase 5, spec 06 §15).
 *  The model only sees a summary + this ref; the full content lives in storage.
 *
 *  三个元数据字段**可空**（#186 AC5 / #185 AC4）：`size` / `mime_type` /
 *  `source_tool` 由 `ArtifactStore` 决定是否持久化——MinIO 不持久化
 *  `source_tool`，S3 持久化。缺了就是 `null`，**不填默认值**：一个编出来的
 *  `'application/octet-stream'` 或 `0` 会让界面显示一个并不存在的字节数。 */
export interface ArtifactRef {
  artifact_id: string;
  size: number | null;
  mime_type: string | null;
  source_tool: string | null;
}

/** #186：`GET /api/sessions/{sid}/artifacts/{aid}` 的一行（后端 `ArtifactSlice.lines`）。
 *
 *  `truncated`/`full_length` 只在**该行超长被截断**时出现——原行保留在 artifact 里，
 *  视图据此如实标记"此行有省略"，不把半截行当完整行。 */
export interface ArtifactSliceLine {
  line_number: number;
  text: string;
  truncated?: boolean;
  full_length?: number;
}

/** #186：外置产物的**局部**读取结果（后端 `ArtifactSlice`，`storage/artifact.py`）。
 *
 *  `truncated` 是"返回内容不完整"的并集（行数截断 ∪ 字符截断）——界面必须如实显示，
 *  否则用户会以为这就是全文。`total_lines` 是全文行数（不是返回行数）。 */
export interface ArtifactSlice {
  artifact_id: string;
  lines: ArtifactSliceLine[];
  total_lines: number;
  returned_lines: number;
  truncated: boolean;
}

export interface ModelSegment {
  /** Accumulated streamed text so far (from model/delta legacy / text/delta durable). */
  text: string;
  status: 'streaming' | 'done';
}

/** 推理块状态（T2 #95）——块生命周期与原语层的共享别名（reasoningCursor /
 *  disclosure 引用此处，单一来源）。 */
export type ReasoningStatus = 'streaming' | 'completed' | 'interrupted';

/** T2（#95）：推理/进度块（契约 C1 reasoning 事件族，S1 双来源共用一种块）。
 *  source=model = provider 思考（reasoning_content）；source=agent = agent 进度
 *  叙述。completed/interrupted 后不可变（spec 02 §8.1），迟到 delta 丢弃。
 *  visibility=internal 的事件永不投影为本块（spec 02 §15 硬边界）。 */
export interface ReasoningBlock {
  /** 稳定聚合键（data.block_id；缺失时投影合成 `r:{step}:{seq}`，重放确定）。 */
  blockId: string;
  source: 'model' | 'agent';
  /** 累积流文本（折叠前读视口与展开面消费同一份缓冲——两视图永不失同步）。 */
  text: string;
  status: ReasoningStatus;
  started_at?: string;
  completed_at?: string;
}

export interface Turn {
  step_id: number;
  /** User input that kicked off this turn. */
  user_message: string;
  /**
   * Latest model segment (kept for streaming caret + existing consumers).
   *
   * INVARIANT: `model === segments[latest model activity's index]` — the same
   * object, not a copy. applyEvent's clone breaks this alias (it clones model
   * and segments separately), so it re-aligns the reference after cloning;
   * mutations to one must stay visible through the other. If this field is
   * ever removed, the re-alignment step in applyEvent goes with it.
   */
  model: ModelSegment;
  /** All model segments in event order — one LLM burst each (execution chain). */
  segments: ModelSegment[];
  tools: ToolCall[];
  /** Execution chain in true event order: model bursts ↔ tool calls interleaved. */
  activities: TurnActivity[];
  status: 'streaming' | 'done' | 'failed';
  started_at?: string;
  completed_at?: string;
  /** Phase 12 白盒透明（ADR-0014 #69）：tool/failure-guard 落所在轮——
   *  soft 渲染为系统提示条，hard 渲染为终止标记。 */
  notices?: RunFailureGuard[];
  /** Phase 13 Multi-Agent（ADR-0015）：agent/delegation-started 创建节点、
   *  finished 按 child_session_id 回填——turn 级编排事实（与 notices 机制对齐，
   *  ConversationState 不加全局字段）。 */
  delegations?: Delegation[];
  /** Harness 注入纠正消息的来源标记（user/message data.injected_by）——
   *  非真人输入，渲染为系统提示条而非用户气泡。 */
  injected_by?: string;
  /** T9 #139：本轮 run 的轮次索引（1-based，来自 run/started data.turn_index）。
   *  per-turn 事实——同轮所有事件共享，供 TurnView 渲染「第 N 轮」标签。
   *  null = 该轮未携带该字段（旧版后端 / 非 run 起始路径）。 */
  turn_index: number | null;
  /** BUG-001 fix：user/message 事件的 seq（持久事实），用作 fork 锚点。
   *  后端 POST /forks 要求 from_seq 是 user/message 的 seq；
   *  此前传 turn.step_id（resolveStep 合成值）→ 422。
   *  null = 该轮没有 user/message 事件（不应该出现，但防御性处理）。 */
  user_message_seq: number | null;
  /** T2（#95）：reasoning 块字典（按 blockId 索引；顺序事实在 activities——
   *  reasoning 与 model/tool 是 S2 兄弟节点）。delta 高频更新走 COW 单块替换。 */
  reasoningById?: Record<string, ReasoningBlock>;
}

/** RepeatedToolFailureGuard 触发记录（tool/failure-guard 事件，ADR-0014 #69）。
 *  soft = 注入 user-role 纠正消息；hard = 终止本轮（end_run）。 */
export interface RunFailureGuard {
  level: 'soft' | 'hard';
  tool_name: string;
  consecutive_failures: number;
}

/** Multi-Agent 委派（agent/delegation-started / finished，Phase 13 ADR-0015）。
 *  父流白盒编排事实：child 的完整多轮历史在 child 自己的 session（后端 Gate 4
 *  不变量），父流只有 start/finish 两个锚点。阻塞语义：finished 返回即 child
 *  已终态。
 *
 *  status 说明：契约冻结 finished.status ∈ {completed, failed}（无中间态）。
 *  前端视图态在此基础上扩展两个——running（started 已到、finished 未回填）与
 *  stopped（父 run 中断时未回填的委派，finalizeRun settle；中断 ≠ 错误，与
 *  tool 同一 DSH 语义域）。stopped 不是契约值，只由前端投影产生。
 *
 *  copy-on-write 契约：delegations 数组与 tools 同规则——cloneTurn 会浅拷贝
 *  数组，但变更必须整体 reassign（或经 pushDelegation），禁止对克隆前共享的
 *  数组原地 push（会污染旧 turn 引用）。 */
export interface Delegation {
  /** 子代理 profile 名：'research_review' | 'coding'（V1 内置）。 */
  target: string;
  /** 给 child 的完整任务描述（自洽，父对话不含在内）。 */
  task: string;
  /** child 独立会话 id——钻取主键，UI 可见可复制。 */
  child_session_id: string;
  status: 'running' | 'completed' | 'failed' | 'stopped';
  /** 结构化结果的文字摘要（可能带后端 #86 溢出截断指针后缀）。 */
  summary?: string;
  started_at?: string;
  completed_at?: string;
}

/** One entry of a turn's execution chain, in true event order (Trace Ladder). */
export type TurnActivity =
  | { kind: 'model'; /** Index into turn.segments. */ index: number }
  | { kind: 'tool'; tool_call_id: string }
  | { kind: 'delegation'; child_session_id: string }
  | { kind: 'reasoning'; blockId: string };

/** Context compaction record (context/compacted event, Phase 5 spec 06).
 *  Run-level metadata — the Inspector Context panel surfaces these. */
export interface ContextCompaction {
  compacted_turn_count: number;
  summary_message_count: number;
  token_estimate: number;
  fallback_used: boolean;
  time?: string;
}

/** A tool operation that crashed mid-flight and needs human reconciliation
 *  (operation/reconcile-required event, Phase 4/5 spec 07 §13).
 *  Surfaces in the Inspector as an approval queue item. */
export interface ReconcileRequired {
  tool_call_id: string;
  tool_name: string;
  args_identity: string;
  state: string;
  time?: string;
}

/** Pending interactive approval — tool/approval-requested event (#37, PRD §2.2).
 *  Runtime pauses at ToolExecutor._check_approval until user resolves via
 *  POST /api/sessions/{id}/approve. ApprovalCard renders this inline. */
export interface PendingApproval {
  approval_id: string;
  tool_name: string;
  tool_call_id: string;
  action_type: string;
  title: string;
  description: string;
  arguments_preview: Record<string, unknown>;
  permission: string;
  policy: string;
  reason: string;
  allowed_decisions: string[];
  time?: string;
  /** 该审批所在 run 已终结（completed/failed/interrupted）仍未被 permission/resolved
   *  配对 → 后端审批队列已随 run GC（session/service.py:1233-1241），决策永不可能
   *  再提交（POST /approve → 404）。判据全部来自事件流，无需新 API。
   *  ApprovalCard 据此渲染只读失效态，不再提供必然失败的批准/拒绝按钮。 */
  stale?: boolean;
}

/** 已裁决的审批 —— `permission/resolved` 事件（#184，Inspector PERMISSION 段）。
 *
 *  为什么需要单独一条：`pending_approvals` 是**队列**（决议即移出），所以"裁决结果"
 *  在投影里无处可查。Inspector 要如实回答"这个会话批过什么"，就必须把决议留痕。
 *
 *  `tool_name` / `policy` 从**同一 approval_id 的请求**带过来（请求必先于决议到达）；
 *  配不上对（例如事件窗口从中间开始）时留空 → 渲染 `—`，不猜。 */
export interface ApprovalDecision {
  approval_id: string;
  /** deny / approve_once / approve_session / approve_policy（后端 PermissionDecision）。 */
  decision: string;
  reason: string;
  /** 同 approval_id 请求里的工具名；配不上对时 undefined（不猜）。 */
  tool_name?: string;
  time?: string;
}

export interface ConversationState {
  session_id: string;
  turns: Turn[];
  /** The turn currently receiving events, if streaming. */
  active_step_id: number | null;
  run_status: 'idle' | 'running' | 'completed' | 'failed';
  /** run/failed.data.reason === 'cancelled'（客户端断连，df4f7d8→da394a9 批语义）
   *  时为 true——Run Pulse 显示「已取消」（中断 ≠ 错误，同 bash stopped 语义域）。 */
  run_cancelled: boolean;
  /** Run-level metadata for the Inspector (Phase 5 events). */
  compactions: ContextCompaction[];
  reconcile_queue: ReconcileRequired[];
  /** Pending interactive approvals (#37, PRD §2.2).
   *  tool/approval-requested adds to this list; permission/resolved removes.
   *  Empty array = no pending approval (auto-approve or already resolved). */
  pending_approvals: PendingApproval[];
  /** 已裁决的审批（`permission/resolved`，到达顺序）。与 `pending_approvals` 互补：
   *  两者合计 = 本会话出现过的全部审批。Inspector PERMISSION 段据此显示"裁决结果"
   *  （#184）。决议事件**不改写**任何 `pending_approvals` 之外的状态。 */
  approval_decisions: ApprovalDecision[];
  /** 本会话生效的审批阈值（`tool/approval-requested.data.policy`，逐事件折叠）。
   *
   *  为什么折叠而不是渲染时扫事件：扫描要 O(events)（"整个会话没有审批"是**最坏**情况，
   *  必须扫完），而这段在 Inspector 打开时每次渲染都会跑。折叠成字段后每事件 O(1)——
   *  与 `model` / `usage_total` 同一路数（投影的职责就是增量折叠）。
   *
   *  为什么这是唯一来源：`permission_mode` 不在任何 SessionEvent 里、也没有 GET 接口，
   *  审批请求携带的 `policy` 才是 ToolExecutor 当时实际用的阈值。无审批事件 → null。 */
  permission_policy: string | null;
  /** Every event that flowed through the projection, in arrival order (verbatim).
   *  Timeline tab truth source — never filtered or reshaped (invariant #22).
   *
   *  ⚠ NOT a snapshot: `applyEvent` pushes into this very array in place, so an
   *  older `ConversationState` value shares it and its `events` keeps growing
   *  (deliberate hot-path trade-off — see the contract at `projection.ts`).
   *  Never key a `useMemo`/`useEffect` on `events` identity, and never stash it as
   *  a frozen "before": copy it, or derive what you need, before the next append. */
  events: AgentEvent[];
  /** Events whose type didn't match any known case (UnknownSurfaceNode 协议,
   *  冻结决策第 69 行 "unknown 事件渲染为 raw 行兜底，永不静默丢弃")。
   *  Kept separately so Timeline / Inspector can surface them explicitly
   *  rather than dropping silently. Subset of `events`. */
  unknown_events: AgentEvent[];
  /** Run-level observability（后端 Gap 1/2）。全部来自事件真值，缺失即 null——
   *  UI 显示「—」/「未追踪」，绝不伪造 0：
   *  - model：最新携带 data.model 的 model/completed；
   *  - usage_total：run/completed.data.usage_total（权威聚合）覆盖前端对
   *    model/completed.usage 的累计值（运行中视图）；
   *  - cost_usd / trace_id / trace_url：run/completed 与 run/failed 对称携带
   *    （契约 2d7f87a——失败 run 也有可见 trace）；未启用 Langfuse 恒 null。 */
  model: string | null;
  usage_total: UsageStats | null;
  cost_usd: number | null;
  trace_id: string | null;
  trace_url: string | null;
  /** 最近一个携带 run_id 的事件的 run 归属（PRD §8.2 Inspector 头部 Run ID）。
   *  事件真值，缺失即 null——UI 隐藏该位，不回退 session_id 冒充（零伪造）。 */
  run_id: string | null;
  /** Phase 12 白盒透明（ADR-0014）：最近一次 model/fallback——模型卡「已切换」态。
   *  字段缺失（形状不完整）时不记录（零伪造）；后续 model 已切 to_model。 */
  model_fallback: { from_model: string; to_model: string; reason: string } | null;
  /** T8 #138：最近一次 run/interrupted 事件的信息。null = 无中断。
   *  来自事件真值。`step_id` 可为 null 且那是真值：进程在该 run 的首个带步号
   *  事件之前就死了（run/started 不带 step，检测器只能沿用后续事件的 step_id）
   *  ——UI 应说「首个步骤开始前中断」，不要渲染成「第 ? 步」。 */
  run_interrupted: { step_id: number | null; interrupted_seq: number | null; reason: string } | null;
  /** T9 #139：当前 run 的轮次索引（1-based）。来自 RUN_STARTED.data.turn_index。
   *  null = 尚未收到 RUN_STARTED 或字段缺失。UI 可据此显示「第 N 轮」。 */
  turn_index: number | null;
  /** T1（#94）幂等簿记：本会话已应用的持久事件 seq 集合（spec 02 §6.1 at-least-once
   *  去重键）。append-only 共享日志纪律（同 events）：只增不改、跨快照共享引用、
   *  绝不整体替换。null-seq 帧不入册——ephemeral 流式信号（model/delta 等）
   *  按契约永不持久化也永不去重。 */
  seenSeqs: Set<number>;
}
