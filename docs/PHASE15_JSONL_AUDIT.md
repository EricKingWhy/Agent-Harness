# Phase 15 — JSONL 诊断层审计（spec 12 §2 对照）

> 诊断 JSONL 层（`agent_harness/logging.py`，schema 1.0）在早期 Phase 建成；
> 本审计按 spec 12 §2 字段清单逐项核对，记录每字段的现状来源与状态。
> 结论日期：2026-09-07（feat/phase15，T4 #120）。

## 字段对照表

| spec 12 §2 字段 | 来源（现状） | 状态 |
| --- | --- | --- |
| model request/response metadata | runtime `llm_call` 行：`model_id` / `provider_request_id` / `finish_reason` / `llm_input` / `llm_output` / `fallback_reason` / `fallback_from` / `fallback_to`（ADR-0014 决策 18） | ✅ 已覆盖 |
| tool input/output | `tool_operation` 行：`tool_input` / `tool_output`（截断 200）；Langfuse 侧 full 模式带全文 | ✅ 已覆盖 |
| attempt | `tool_operation` 行 `attempt` / `max_attempts`（每 attempt 一条） | ✅ 已覆盖 |
| error_code | `tool_operation` 行 `error_code` / `retryable`；`error` 行 `error_type` / `error_message` / `error_code` | ✅ 已覆盖 |
| duration | `llm_call` 行 `duration_ms`（严格闭合模型调用区间）；`tool_operation` 行 `duration_ms` / `total_duration_ms` | ✅ 已覆盖 |
| provider latency | 同 `duration_ms` 语义（spec 12 §2 对齐注释在 runtime 埋点处） | ✅ 已覆盖 |
| token usage | `llm_call` 行 `token_usage`（响应如实抽取，负值丢弃） | ✅ 已覆盖 |
| cost | 事件流 `cost_usd` 恒 null（spec 12 未定义费率表，不伪造）；Langfuse 侧按 model+usage 自动计算 | ✅ 语义明确化（观测侧由 Langfuse 承担，ADR-0018 D8） |
| stack trace | `error` 行 `stack_trace`（JsonlFormatter exc_info） | ✅ 已覆盖 |
| fallback reason | `llm_call` 行 `fallback_reason` / `fallback_from` / `fallback_to` | ✅ 已覆盖 |
| reconcile reason | **本轮补**（T4 #120）：recovery 协调器裁决完成时写 `system_log` 诊断行——`reconcile_verdict` / `ledger_state` / `tool_call_id` / `session_id`（recovery/coordinator.py） | ✅ 本轮补齐 |

## 语义归位说明

spec 12 §2 的「reconcile reason」落在 **recovery 协调器的 `system_log` 诊断行**，
而不是 `tool_operation` 行：reconcile_meta（verdict + reconciled_at）由 Recovery
在恢复期写入 Operation Ledger，与工具执行期的 `tool_operation`（每 attempt 一条）
是两个时点、两个事件源。诊断链靠 `tool_call_id` + `session_id` 对账串联。
与发布票 AC 的表述差异（"tool_operation 行补 reconcile 字段"）以此为准——
语义归位而非字段搬运，理由如上。

## 大输出边界

spec 12 §2「大输出转 Artifact，不直接写数百 KB 单行日志」：JSONL 侧
`tool_output` 截断 200 字符；完整输出走 Artifact overflow handler（项目既有）；
Langfuse 侧 redacted 模式截断 500 字符、full 模式按 D6 约定带全文（自有 dev 项目）。

## redaction hook

`agent_harness.observability.tracer._redact` 是单一函数边界（D6）；
JSONL 层按 spec 12 §2 保留未来 redaction hook（当前 dev 默认不脱敏，不变）。
