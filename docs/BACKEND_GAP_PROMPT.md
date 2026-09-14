# 后端 Gap Prompt（Phase 9 SSE / REST 扩展）

> 这是前端 UI 重设计完成后，集成 AI 交给**后端 Agent** 的自包含任务提示。
> 目标：补齐前端七阶段 UI 依赖、但目前后端尚未暴露的字段与端点。
> **执行者**：后端工作树（`D:\intelligence-agent` 或 `D:\intelligence-agent-backend`，`feat/backend` 分支）的 Coding Agent。
> **约束**：不动 `web/` 目录；不改已冻结的 SessionEvent schema 语义（只**扩展**，不**破坏**）；遵守 AGENTS.md §8 Scope Lock——不顺手改无关代码。

---

## 背景

前端 `feat/frontend` 七阶段 UI 重设计已完成（commit `6183d3f` → `38fc775` + 收尾 fix）。前端依赖以下三个后端能力，目前在 StepDetail 显示"后端未暴露"空槽（graceful degradation，不崩溃，但产品体验不完整）。本任务补齐它们。

前端单一投影源是 `web/src/lib/projection.ts`（不变量 #22 守护）；扩展字段需通过 SessionEvent → AgentEvent 映射进入前端，**不在前端开第二套 fetch 真相**。

## 工程依据

- 规格：`docs/spec/11_STREAMING_API_WEB_UI.md`（SSE / REST）、`docs/spec/12_OBSERVABILITY_EVALUATION.md`（usage / trace_id / Langfuse 关联）
- 不变量：#4（Event ≠ Diagnostic Log——usage 等进 SessionEvent.data，不进日志）、#22（前端单一真相源）
- 前端消费者：`web/src/components/StepDetail.tsx`（MODEL 空槽 §250 / CHECKPOINT 空槽 §256）、`web/src/hooks/useSession.ts`（titlesById 缓存来自首条 user/message event）

## Gap 1：usage / model / cost 字段（Observability 规格落地）

**现状**：`run/completed` 事件 `data` 不含 token usage；`model/completed` 不含 model 名 / cost。
**前端需求**：Run Inspector 概览 tab 的 MODEL 空槽要显示「模型 · 用量 · 成本」。

**任务**：
1. 扩展 `model/completed` 事件 `data`（**新增字段，不破坏现有**）：
   ```json
   {
     "content": "...",
     "model": "qwen-plus-0911",          // 新增：本次推理所用模型
     "usage": {                            // 新增：usage 协议
       "prompt_tokens": 1234,
       "completion_tokens": 567,
       "total_tokens": 1801
     }
   }
   ```
2. 扩展 `run/completed` 事件 `data`（**新增**）：
   ```json
   {
     "cost_usd": 0.0024,                   // 新增：本轮总成本（美元）
     "usage_total": { ... },               // 新增：本轮聚合 usage
     "trace_id": "lf-xxxxxx"               // 新增（与 Gap 2 复用）
   }
   ```
3. 后端从阿里云百炼 API 响应直接抽取（已有 `model` 字段，usage 在响应 `usage` key）；cost 按 `docs/spec/12_OBSERVABILITY_EVALUATION.md` 定义的费率表计算（若无费率表，先记 `cost_usd: null` + 加 TODO，不伪造）
4. 前端 `types.ts` `EventType.MODEL_COMPLETED` / `RUN_COMPLETED` 的 `data` 类型同步扩展为可选字段；`projection.ts` summarizeEvent 增加这些字段的摘要逻辑
5. **绝不伪造**：字段缺失时返回 `null` / 省略，不要默认值填零（不变量 #22 + 零伪造指标冻结决策）

**验收**：
- 一个真实跑通的 session，前端 Run Inspector MODEL 空槽显示「qwen-plus-0911 · 1801 tok · $0.0024」
- 缺字段时显示「—」而非 0
- 新增字段不破坏现有 345 passed 后端测试 + 前端 73/73 测试

## Gap 2：trace_id（Langfuse 关联）

**现状**：session 元数据无 Langfuse trace_id；前端无入口跳转 trace。
**前端需求**：StepDetail 概览 tab 显示 trace_id（点击跳 Langfuse URL，若配置了 `LANGFUSE_HOST`）。

**任务**：
1. session 创建时，若启用 Langfuse（`LANGFUSE_PUBLIC_KEY` 已配置），记录 `trace_id`
2. `GET /api/sessions` 返回的每行扩展：
   ```json
   {
     "session_id": "...",
     "event_count": 42,
     "first_event_time": "...",
     "last_event_time": "...",
     "trace_id": "lf-xxxxxx"              // 新增：可 null
   }
   ```
3. 前端 `SessionSummary` 类型加 `trace_id: string | null`；StepDetail 渲染时若有 `LANGFUSE_HOST` 环境变量（Vite 注入），链到 `${LANGFUSE_HOST}/trace/${trace_id}`
4. Langfuse 故障不能拖垮 Core（不变量 #21）——trace_id 缺失时前端显示「未追踪」，不报错

**验收**：
- 启用 Langfuse 时 trace_id 非空，前端可点跳转
- 禁用 Langfuse 时 trace_id 为 null，前端显示「未追踪」灰字
- Langfuse 服务挂掉不影响 session 创建主路径

## Gap 3：历史 session 列表携带首条用户消息

**现状**：`GET /api/sessions` 只返回 `session_id / event_count / first_event_time / last_event_time`。前端 SessionList 渲染标题必须额外 `GET /api/sessions/:id/events` 扫描首条 user/message event 才能拿到标题（titlesById 缓存）——N 个 session 要 N 次额外请求。
**前端需求**：列表 payload 每行带上首条 user/message 的 content（截断），前端零额外请求渲染标题。

**任务**：
1. `GET /api/sessions` 返回扩展（**新增字段**）：
   ```json
   {
     "session_id": "...",
     "event_count": 42,
     "first_event_time": "...",
     "last_event_time": "...",
     "first_user_message": "帮我写一个 Python 函数..."   // 新增：截断到前 128 字符；无则 null
   }
   ```
2. 后端实现：扫该 session 的 SessionEvent store，找第一条 `type == user/message` 的 `data.content`，截断到 128 字符；空 session 或无 user message 返回 `null`
3. 性能：若 `list_sessions` 已遍历 event store，顺手抽取；若走 index，加一条「首条 user/message」反查（建议在 session 元数据表加列缓存，避免每次 list 全量扫 events）
4. 前端 `SessionSummary` 类型加 `first_user_message: string | null`；`useSession.ts` 用它直接填 titlesById，**跳过 events 扫描**（保留 events 扫描作为后端未返回时的 fallback——优雅降级）

**验收**：
- 列表 API 一次请求即拿到所有标题
- 空 session / 无 user message 的 session 返回 `first_user_message: null`，前端回退短 ID 渲染
- 前端 SessionList 渲染标题与点开后的 chat 首条消息一致（单一真相，不分裂）

## 优先级与依赖

| Gap | 优先级 | 依赖 | 前端空槽位置 |
| --- | --- | --- | --- |
| 3（首条消息） | P0 | 无（独立可做） | SessionList 标题缓存 |
| 1（usage/model/cost） | P1 | 阿里云百炼 API 响应字段确认 | StepDetail MODEL 空槽 |
| 2（trace_id） | P2 | Langfuse 启用与配置 | StepDetail 概览 |

## 完成定义（Definition of Done）

- [ ] 三个 Gap 字段全部在 SessionEvent / REST payload 中暴露
- [ ] 后端 `python -X utf8 -m pytest tests/ -q --tb=short` 全绿（不破坏现有 345 passed）
- [ ] 前端 `npx tsc --noEmit` + `npx vitest run` 73/73 + `npm run build` 全绿
- [ ] 集成联调：一次真实 session 端到端跑通，Run Inspector MODEL/CHECKPOINT 无空槽
- [ ] 不变量守护自查（#4 / #21 / #22）通过

## 与前端协作约定

- 后端只扩字段，不改语义——前端 `EventType` enum 和 `data` schema 同步加可选字段
- 字段命名用 snake_case（Python 端）→ 前端直接消费（前端不转 camelCase，守 SSE 契约单一）
- 任何无法解决的规格冲突，报告而不擅自修改冻结 schema——交给 Primary Developer 决策（AGENTS.md §5）
