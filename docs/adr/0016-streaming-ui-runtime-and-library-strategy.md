# ADR-0016: Streaming UI 运行时与库策略（transport / 幂等 / 依赖 / DEFER 清单）

> **状态**：已接受（2026-09-06）
> **背景**：Agent Runtime Streaming UI 生产级改造轮（上游规格 `docs/spec/01_AGENT_RUNTIME_STREAMING_UI_PRD_v2.md` / `02_RUNTIME_STREAMING_PROTOCOL_SPEC.md` / `03_FRONTEND_STREAMING_UI_IMPLEMENTATION_SPEC.md`）。前端代码审计（feat/frontend，commit `25e39bf` 前后）+ grill 五问用户拍板（Q1-Q5）+ T1-T7 逐票实施。本 ADR 收口规格 02 §4.5 要求的 transport 决策对照表，并归档实施过程中产生的全部架构决议与 DEFER 项。
> **关联**：#94(T1) #95(T2) #96(T3) #99(T6) #100(T7) #102(T9)；后端契约 `docs/BACKEND_PROMPT_STREAMING_UI.md` C1-C7。

---

## 1. Transport 决策：保持 SSE（preserve-first），不迁移 AI SDK

现状：`POST /api/sessions`（FastAPI `EventSourceResponse`）建会话并流式回 AgentEvent；前端 `web/src/lib/sse.ts` fetch+ReadableStream 手工解析。生产可用（Phase 9 起历经断连取消、recover、auth 等硬化）。

按规格 02 §4.5 对照表逐轴评估（现状 = 现有 SSE + canonical envelope）：

| 轴 | 现有 Transport（选定） | AI SDK data-stream 迁移 |
|---|---|---|
| 首 delta 延迟 | 已达标（model/delta 直推 + 24ms 合帧） | 相当（协议层不带来收益） |
| 重连/续传 | 需后端 C4（after_seq cursor，D-A detached-run 已拍板） | 协议自带，但要求后端按 JS-first wire 重排 |
| 工具/推理流 | 契约 C1/C2 新事件族直入 canonical 词表 | 需映射到 UIMessage part 模型，语义有损 |
| Inspector 兼容 | 完整保留（events verbatim + Raw 钻取） | part 模型无 run_id/step_id/seq 等价物，Inspector 深度受损 |
| Replay/历史 | JSONL durable log 直出 | 需二次投影 |
| Provider 支持 | langchain-openai 现状 + C1 reasoning_content 接出 | Python 侧需适配层 |
| 复杂度/运维风险 | 增量（cursor + detached-run ADR） | 全线重排协议 + 双端联调 |
| 可测性 | 纯函数投影 + fixture 驱动（已验证 319 测试） | 重建测试体系 |

**决策（用户 Q4=A 拍板）**：不迁移。AI SDK data-stream 是 JS-first 协议，对齐它会重排 canonical envelope（seq/run_id/step_id/stream-only 语义），与不变量 #22（单一投影源）和 Inspector 深度（D1/D11 冻结）冲突。assistant-ui 同理（绑定自家 UIMessage 模型）。**采纳其架构模式而非依赖**：block 状态机（T2 ReasoningBlock）、renderer registry（eventKind 分发既有）、follow 原语（followLatest）。

## 2. 幂等与事件契约

- **去重键**：本轮取裸 `seq`（SSE 帧不携带 event_id——`_event_to_sse_dict` 形状；seq 每 session 单调，契约 C5）。**升级路径**：若未来 SSE 帧补带 event_id，按规格 02 §6.1 升级为 event_id 优先键。乱序小窗缓冲 **DEFER**（精确重复才幂等；未见过的回跳 seq 照常应用——T1 测试锁定）。
- **帧校验**：`lib/eventValidate.ts` 手写薄 guard（type/data/seq 三守门 + data/seq 缺失归一化）。规格 02 §14 的 Zod/Valibot 评估结论：**完整 schema 校验的引入时机 = T2/T3 事件契约（reasoning/tool 输出）经真事件联调冻结后再评估**——此前引入会把未冻结的载荷形状过早固化。
- **seen = applied**：幂等标记发生在投影成功之后（投影抛错时重投重新投影而非被误丢）；帧先落 events 日志（崩溃路径下日志可能双行，是可见痕迹而非事实丢失）。
- **append-only 共享簿记第二例外**：`ConversationState.seenSeqs`（Set，只增不改、跨快照共享引用）与 `events` 数组同构——COW 纪律的两处文档化例外（第一处见 HANDOFF_PERF_FRONTEND §4.3/§6 events append-only 日志）。
- **长会话热路径**：`withTurnAt` / `locateToolHostTurn` 最后一轮 O(1) 快路径（T9 基准发现 findIndex O(turns) 在数千轮成为每事件主导成本，8.79→~5µs/事件）。前提 = turn.step_id 唯一（resolveStep 单调递增设计不变量）。

## 3. Detached-run 与取消语义（用户 Q1=A 拍板，后端域）

run 与 HTTP 请求生命周期解耦：断连不杀 run（宽限期 + 超时回收策略数值由后端 ADR 定）；`POST /api/sessions/{id}/cancel` 显式取消；coalesced delta 落盘（S19）；SSE 重连 `GET /api/sessions/{id}/stream?after_seq=N` 续传。**对 Phase 9 取消臂语义的有意修订**——「断连=取消」退役，Esc/停止改走 cancel 端点。snapshot/reconcile 层 **DEFER**（cursor 重放在本轮规模足够，规格 02 §10.4 简化版）。前端配套：T4（#97 重连 resume）、T5（#98 cancel 接入），均 fixture/mock 先行。

## 4. 依赖决议

| 库 | 决议 | 依据 |
|---|---|---|
| TanStack Virtual | 沿用（既有） | Conversation turn 级虚拟化 + 动态测高已落地 |
| shiki 4.4.3 | 引入（Q5 批准） | fine-grained 装配：`shiki/core` + JS RegExp 引擎——全量入口会把 oniguruma wasm（~600KB）拖进模块图；core 109KB 独立懒加载 chunk，总构建 JS 10.2MB→2.87MB。语言白名单 40 项逐语言 chunk。单主题 github-dark（恒深底容器语义，见 highlight.ts docstring） |
| Playwright | 引入 devDeps（Q5 批准） | T8（#101）E2E 矩阵；交互级行为测试（展开/收起不打断流、跟随/脱离/回归、后台 profile）统归此票 |
| Motion | 不引入 | CSS 过渡已覆盖（Apple 缓动 token），规格 03 §3.4 允许 |
| Zod/Valibot | 暂缓（见 §2 时机） | 薄 guard 先行 |

## 5. DEFER / 遗留清单（含理由）

1. **snapshot/reconcile 层**——cursor 重放足够（规模不需要），后端 C4 阈值兜底。
2. **乱序小窗缓冲**——精确重复幂等已覆盖 at-least-once；真乱序属协议异常。
3. **useFollowLatest 共享原语推广**——followLatest 纯函数核已共享（ReasoningBlock/ToolOutputStream），hook 壳统一等第三个消费方出现再收。
4. **ExpandedBody 收起卸载丢跟随态**——DisclosureState 语义子集（数据不重建，PRD §6.4 后半句满足）。
5. **client telemetry 通道**（PRD §18：stream_first_delta_ms 等）——需要独立 metric 通道，未接；quarantine→unknown_events 渲染已是降级可见面。
6. **双主题代码高亮**——恒深底容器语义下单主题是唯一协调解；容器改随主题浅底时回炉（highlight.ts docstring 有决策链）。
7. **tool/call_delta（部分参数）**——后端可选；不做则前端维持「args 完整才渲染摘要」降级（规格 03 §9.2）。

## 6. 后果

- 前端 319→ 测试（T1-T7 累计 +86）全绿；perf 车道 12/12（15k 逻辑节点基准，见 `docs/STREAMING_UI_10K_BENCHMARK.md`）。
- 后端 C1-C7 契约落地点均已在 T1-T7 以 fixture 先行消费；形状微调走「改完回传前端」流程（BACKEND_PROMPT §5）。
- 真事件联调验收（PRD §22 场景 A/C/D/E/F）在后端 reasoning/tool-output/detached-run 落地后执行。
