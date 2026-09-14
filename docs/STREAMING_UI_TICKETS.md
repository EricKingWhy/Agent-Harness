# Streaming UI 生产级改造 — Tickets（feat/backend 侧，ADR-0016 驱动）

> 依据：`docs/adr/0016-streaming-ui-detached-run.md`（决策 + 数值）+ 前端 prompt C1-C7。
> 纪律：逐票红测先行；每票 pytest 新旧全绿 + ruff clean；不动 `web/`（例外：`web/src/generated/event-types.ts` 为 gen_event_types.py 生成产物，测试门强制同步，重生成并在报告中知会）。
> 生命周期托管 ≠ 决策语义；Agent 决策/工具选择/授权/模型路由意图零改动。

## T1 — 事件词汇 + block_id 信封基座
- `session/event.py`（**只做加法**——Phase 14 并行协作约定）：新增 `REASONING_STARTED/DELTA/COMPLETED/INTERRUPTED`、`TOOL_OUTPUT_DELTA`、`TEXT_DELTA`（均 durable）；`MODEL_DELTA`/STREAM_ONLY 词汇原样不动（text/delta 承接，运行时不再发射）；`block_id` 字段进 SessionEvent（to_dict/from_dict 往返）。ADR 编号分账：0016=流式改造，0017=Phase 14。
- `agent/types.py`：AgentEvent + `to_agent_event` 透传 block_id。
- `web/app.py::_event_to_sse_dict`：帧补 `event_id` / `block_id`。
- 重跑 `scripts/gen_event_types.py`。
- 测试：词汇注册自洽（既有守卫）、append 接受新类型、stream-only 仍拒、block_id 往返、SSE 帧新字段。

## T2 — 合帧器 + reasoning 事件族（runtime）
- `model/provider.py`：`ReasoningChatOpenAI` 子类抬 `reasoning_content` 进 additional_kwargs；assembly 换用它。
- runtime：`StreamCoalescer`（30ms/4096/生命周期边界 flush）；流式循环思考块状态机（started/delta/completed）；思考与文本交错切块。
- 取消臂/异常臂：flush 残余 + `reasoning/interrupted`（先于 model/failed）。
- 测试：ScriptedModel 思考剧本 → 事件族 + 合帧不为逐 token；无思考 → 零 reasoning 事件（零伪造）；中断保内容；provider 子类单测（fake chunk dict）。

## T3 — 工具输出流 + tool/call 预持久化
- `sandbox/base.py` + `local.py`：`exec(..., on_output=None)`；reader 线程逐段回调。
- `tooling`：`tool_output_sink` contextvar + Sink（线程安全入队 + drain task 合帧落盘 `tool/output_delta`，8KB/帧、64KB/channel 上限）；executor 执行期接线 + 收口。
- `emit_call_events` 拆 `emit_call_event` + `emit_pending_events`；runtime step-7 改预持久化时序；`_flush_committed_events` 去 TOOL_CALL。
- BashTool 读 sink 转发 sandbox。
- 测试：时序（call → delta* → pending → result）、channel 保真、截断、非流式工具零 delta、abort flush 零重复、R6-7/Kill 族回归绿。

## T4 — RunManager + detached-run
- web 新增 `runmanager.py`：start/subscribe/unsubscribe/cancel/孤儿回收（300s，Settings）；session listener 实时捕获 durable 事件；seq 幂等合并；有界队列（2000）溢出踢出；sentinel 收尾。
- `POST /api/sessions` 改 detached：create_task + 订阅 + 返回 SSE；memory_session_var 移 run task。
- `test_sse_disconnect.py` 语义反转改写（断连 → run 继续至终态）。
- 测试：断连不杀 run、慢/踢 subscriber 不阻塞 run、listener 实时性（执行期间事件即时可达）、孤儿回收（短宽限期注入）。

## T5 — POST /cancel
- 路由 + RunManager.cancel；200 cancelling / 200 no_active_run / 404。
- 测试：在途取消 → run/failed(reason=cancelled) 落盘 + 流收尾；幂等双击；404。

## T6 — GET /stream?after_seq
- 重放 durable（seq>N）→ backlog>1000 发 `stream/truncated` 控制帧收流 → 在途 attach（幂等）→ 终态 run 重放即收尾；404。
- 测试：重放序、续传无重复无丢失、attach 竞态（重放与 live 交叉）、阈值分支、404、终态重连。

## T7 — 多模型
- Settings.agent_models JSON + `model/config.py` catalog 解析（密钥回落、未知 provider 报错、名字冲突报错）。
- `POST /api/sessions` 可选 model 参数（422 未知名）；`GET /api/models`；build_runtime 接 model 覆盖（fallback 链不动）。
- 测试：catalog 解析、选择生效（fake 模型按名注入）、默认行为逐字节不变、422、/api/models 形状。

## T8 — 契约回传 + 收尾
- `docs/BACKEND_CONTRACT_STREAMING_UI.md`（最终帧形状/端点/语义，回传前端）。
- PHASE_STATUS 条目 + changelog；全量 pytest + ruff + gen_event_types 门；commit/push origin feat/backend。
