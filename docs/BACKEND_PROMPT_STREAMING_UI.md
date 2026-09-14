# Backend Prompt — Agent Runtime Streaming UI 生产级改造（feat/backend 侧）

> 发件：前端 AI（feat/frontend worktree），经联合代码审计 + grill-me，**用户已逐项拍板**后授权发出。
> 定位：本轮是生产级系统改造，不是 Demo。三份上游规格是唯一权威，冻结产品决策不得删减。
> 你的 worktree：`D:\intelligence-agent-backend`（feat/backend）。**勿动 `web/`**（前端域，feat/frontend 会话在管）。merge main / push 策略照 §13/§14 旧例。
> 本文件与规格冲突时：以规格为准并报告 Gap，不得反向改规格。

---

## 0. 必读（按序，动工前读完）

1. `docs/spec/01_AGENT_RUNTIME_STREAMING_UI_PRD_v2.md` — 产品 PRD v2（继承 v1 冻结决策 D1-D20 + 流式决策 S1-S26）。**当前位于前端 worktree**：`D:\intelligence-agent-frontend\docs\spec\`（前端 commit `25e39bf` 已推 origin/feat/frontend；合入 main 后从 main 读亦可）。允许只读跨 worktree 引用，等集成同步后以仓内为准。
2. `docs/spec/02_RUNTIME_STREAMING_PROTOCOL_SPEC.md` — 共享契约（envelope / seq 幂等 / reconnect / block 状态机 / 持久化三层 / 隐私边界 / §21 后端所有权清单）。
3. `docs/spec/03_FRONTEND_STREAMING_UI_IMPLEMENTATION_SPEC.md` — 前端实现规格（读它主要为对齐契约语义，特别是 §21）。

## 1. 前端侧审计结论（与后端相关部分，供你对齐现状）

- Transport = **SSE**：`POST /api/sessions` 建会话并流式回 AgentEvent（FastAPI `EventSourceResponse`，`src/agent_harness/web/app.py:388-435`）。前端 fetch+ReadableStream 手工解析。**preserve-first 成立，不迁移**。
- 事件词表：18 durable 型 + `model/started`/`model/delta` stream-only（`session/event.py`）。`SessionEvent` 已有 `event_id`(uuid4) / `seq`(每 session 单调) / `time` / `run_id` / `agent_id` / `step_id`；SSE 帧已带 `seq`（`web/app.py:241`）。
- Provider = langchain-openai `ChatOpenAI`（`model/provider.py`，OpenAI 兼容，senseaudio 网关）。runtime `astream` 逐 chunk **只取文本**转 `model/delta`——chunk 里的 `reasoning_content`（Qwen/DeepSeek 思考）当前被丢弃。
- ToolExecutor 只发 `tool/call` + `tool/result`（emit_call_events/emit_result_event 单一 owner）；sandbox 全量捕获后一次性返回，无输出流。
- 断连 = EventSourceResponse 取消 generator → 取消臂 `run/failed(reason=cancelled)`（`runtime.py:176` 收尾，Phase 9/R5-8 刻意硬化）。**无 `POST /cancel`**——前端 Esc 中断目前靠 abort 连接借道取消臂。
- 无 cursor/resume：SSE 一次性流；`GET /api/sessions/{id}/events` 全量重放；无 `after_seq`。

## 2. 用户已拍板的决策（方向冻结，细节可在你侧 ADR/grill 中落）

| # | 决策 | 内容 |
|---|---|---|
| **D-A** | **detached-run 一步到位**（Q1=A） | run 与 HTTP 请求生命周期解耦：断连不杀 run，run 继续跑。配套：① `POST /api/sessions/{session_id}/cancel` 显式取消端点（前端 Esc/停止按钮改走它，不再靠断连）；② coalesced delta 落盘（S19，重连重放不丢已显示文本）；③ SSE 重连支持 `after_seq` cursor 续传；④ 孤儿 run 风险用「断连宽限期 + 超时回收」策略化解（数值你定，写入 ADR）。**注意**：这是对 Phase 9 取消臂语义的有意修订，必须 ADR。 |
| **D-B** | **thinking 真内容 + 多模型**（Q2=A） | 用户确认 **`qwen3.8-max-0902` 支持思考**（senseaudio 网关，阿里系）。要求：① provider 层接出 `reasoning_content` chunk → reasoning 事件族；② **多模型支持，不能写死一个模型**（会话创建可选模型，模型列表可查询）；③ per-model thinking 能力不同——**模型真吐思考就发 reasoning 事件、不吐就不发**（事件驱动，前端有则显示、无则不显示，零伪造）；④ source/visibility 语义按规格 02 §7.3/§15（provider 思考 vs agent 进度叙述都可走同一事件族，`source` 字段区分）。 |
| **D-C** | **分工**（Q3=A） | 你按同一份规格自行拆票实施（audit → grill → tickets → 逐票 implement + 测试 + review）。前端按 §3 契约清单消费；本清单是两端对齐物，形状可微调（微调请回传前端），**语义是硬的**。 |
| **D-D** | **不迁移 AI SDK**（Q4=A） | 保持现有 SSE transport + canonical envelope（seq/run_id/step_id/stream-only 语义）。AI SDK data-stream 是 JS-first 协议，对齐它会重排 canonical envelope、与 Inspector 深度和不变量 #22 冲突。按规格 02 §4.5 出 ADR 对照表收口 spike（可并入 D-A 的 ADR 或相邻）。 |

（grill Q5 的 shiki/Playwright 是前端 devDependencies，与你无关。）

## 3. 前端消费契约需求清单（对齐物）

**C1 — Reasoning 事件族**（规格 02 §7.3/§8.1）：
`reasoning/started` / `reasoning/delta` / `reasoning/completed` / `reasoning/interrupted`。
- data 最小字段：`delta`(string)；`source`(`'model' | 'agent'`)；中断事件带已完成文本语义（部分内容保留，S18/PRD 16.4）。
- **需要 block 标识**：同一段思考的 delta 聚合键。建议 envelope 加 `block_id: string | null`（reasoning/text/tool 输出通用，规格 02 §5 的语义等价物）；不想动 envelope 就放 data 里。前端按它聚合，绝不用时间戳猜。
- **持久化**：S18 要求历史重放恢复 reasoning——coalesced chunk 或 assembled block 落盘（粒度你定，S19 禁止 per-token 行）。落盘后它就是 durable 型，`event.py` 的 EVENT_TYPES / STREAM_ONLY 分类要相应修订（这是 ADR 内容）。
- **零伪造边界**：模型没吐思考 → 这组事件整个不出现 → 前端不渲染思考块。不要为 UI 效果合成空思考。

**C2 — Tool 输出流事件**（规格 02 §7.5）：
- `tool/output_delta`：data 至少 `{ tool_call_id, channel: 'stdout'|'stderr', delta }`。前端按 tool_call_id 关联。
- `tool/call_delta`（部分参数）：可选；不做则前端维持「args 完整才渲染摘要」现状，规格 03 §9.2 的 partial-args 态降级缺席。
- `tool/result` 仍是终态全量兜底；sandbox 需要从「全量捕获后一次返回」改为逐段发射（2M cap / 溢出 artifact 语义保持）。
- 持久化同 C1：历史重放要保留输出流。

**C3 — 取消端点**：`POST /api/sessions/{session_id}/cancel`。幂等；无在途 run 的语义（200 幂等成功 or 404/409）你定，前端按幂等消费。错误分类不并入「failed」语义混淆（规格 02 §17）。

**C4 — detached-run + 重连续传**：
- `POST /api/sessions` 仍是唯一入口；断连后 run 继续（宽限期 + 最大孤儿时长回收，数值入 ADR）。
- 重连端点：建议 `GET /api/sessions/{id}/stream?after_seq=N`（SSE）：从 seq>N 重放 durable 事实 + 接上在途流。落后过多时（阈值你定）可指令客户端走 `GET /events` 全量重建（规格 02 §10.4 的简化版：**cursor 重放即可，snapshot 层本轮 DEFER**，规模不需要）。
- session 不存在 → 404。心跳保持 sse-starlette 默认 ping（勿关，前端依赖连接活性判断）。
- 终态语义：run 已终态时重连 = 重放 durable 至终态后正常收尾。

**C5 — seq 幂等**：每 session 单调（已满足）；durable 与流式帧都带 seq；重放按 seq 序。前端将按 seq 去重（幂等投影），后端只需保证不重置、不回跳。

**C6 — 多模型**（D-B）：
- `POST /api/sessions` 增加可选 `model` 参数（不传 = 默认链，现行为不变）；fallback 链语义不动（ADR-0014）。
- 建议加 `GET /api/models`：返回可选模型列表（前端做选择器用）。形状你定，前端只要求「能列出 + 能按 run 指定」。
- `model/started` / `model/completed` 的 `data.model` 照旧（前端模型卡已消费）；思考与否不靠模型名硬编码判断，事件驱动。

**C7 — ADR**：D-A（detached-run + 取消语义修订 + delta 落盘粒度）必须 ADR；D-D 的 transport 对照表可并入。冲突时先报告再动（规格 01 §21 out-of-scope 清单：Agent 决策语义 / 工具选择语义 / 授权行为不得顺手改——**生命周期托管 ≠ 决策语义**，这条边界写清楚）。

## 4. 验收对齐（规格 01 §22 场景中后端责任部分）

- **C 工具输出**：stdout/stderr 增量发射、channel 保真、大输出不撑爆（预算/分页语义保持）。
- **D 中断**：interrupted 后部分内容保留在事件流（reasoning/text 都是）。
- **E 重连**：断连 → run 继续 → 重连 after_seq 续传 → 无重复块（幂等）。取消只发生在显式 `POST /cancel`。
- **F 历史**：重放恢复 reasoning/tool 输出/block 边界（持久化粒度的直接验收）。

## 5. 流程提醒

- 你的 SDD 流程照旧：审计（可复用 §1 结论，无需重扫）→ grill 只问代码解决不了的歧义 → tickets → 逐票红测先行 + pytest/ruff 全绿 → push origin feat/backend 等集成。
- 契约形状若要微调（字段名/端点路径/状态码），**改完回传前端**（用户中转或写回本文件均可），前端按最终契约联调——前端 tickets 会以 fixture 先行，不被你的进度硬阻塞。
- 疑似规格冲突：报告，不擅自删减冻结能力。
