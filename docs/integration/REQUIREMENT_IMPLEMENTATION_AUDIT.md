# Requirement Implementation Audit

> **审计性质**：需求实现矩阵 / AC 级验证
>
> **基线 SHA**：`83056c884b69aacf9563399cb486d390a1d32e18`
>
> **审计范围**：#131–#139（Phase Multiturn T1–T9）+ #37 + #35

---

## 1. Issue Status Summary

| Issue | Title | State | Labels |
|---|---|---|---|
| #35 | chore(web): 主题亮色变量组双份手工同步 | OPEN | — |
| #37 | feat(web): 交互式审批走通 | OPEN | — |
| #131 | Phase Multiturn T1: SessionService 领域层抽离 | OPEN | ready-for-agent, phase-multiturn |
| #132 | Phase Multiturn T2: 续聊端点 + WebSocket + queue/steer | OPEN | ready-for-agent, phase-multiturn |
| #133 | Phase Multiturn T3: CLI 续聊重构 + slash 命令 | OPEN | ready-for-agent, phase-multiturn |
| #134 | Phase Multiturn T4: 压缩 bracket 升级 + 六段式摘要 | OPEN | ready-for-agent, phase-multiturn |
| #135 | Phase Multiturn T5: 大产物外置对象存储（MinIO + artifact 引用） | OPEN | ready-for-agent, phase-multiturn |
| #136 | Phase Multiturn T6: 审批 WS 推送 + HTTP 回传 | OPEN | ready-for-agent, phase-multiturn |
| #137 | Phase Multiturn T7: 模型切换 + Fork API/UI/CLI | OPEN | ready-for-agent, phase-multiturn |
| #138 | Phase Multiturn T8: 崩溃恢复 + Ledger reconcile | OPEN | ready-for-agent, phase-multiturn |
| #139 | Phase Multiturn T9: Langfuse 多轮埋点 + 长期记忆验证 + DoD 全量回归 | OPEN | ready-for-agent, phase-multiturn |

**关键发现**：所有 11 个 issue 都是 OPEN 状态。但代码中已经存在大量实现——这说明 **issue 状态与实际实现严重脱节**。

---

## 2. #131 SessionService 领域层抽离

### AC 级验证

| AC | Production | Wiring | Tests | Main | Status |
|---|---|---|---|---|---|
| SessionService 类存在 | `session/service.py:168` | ✓ | ✓ | ✓ | DONE |
| create_and_launch 方法 | `service.py:254` | ✓ Web 调用 | ✓ | ✓ | DONE |
| resume_and_launch 方法 | `service.py:346` | ✓ Web 调用 | ✓ | ✓ | DONE |
| send_message 方法 | `service.py:446` | ✓ Web 调用 | ✓ | ✓ | DONE |
| list_sessions 方法 | `service.py:206` | ✓ Web 调用 | ✓ | ✓ | DONE |
| cancel 方法 | `service.py:559` | ✓ Web 调用 | ✓ | ✓ | DONE |
| recover 方法 | `service.py:651` | ✓ Web 调用 | ✓ | ✓ | DONE |
| CLI 使用 SessionService | `cli.py` imports | ✓ | — | ✓ | DONE |
| Web 使用 SessionService | `app.py` delegates | ✓ | ✓ | ✓ | DONE |

**结论**：#131 的核心交付物已全部落地 main。Issue 应标记为 CLOSED 或明确剩余 AC。

### 注意事项

- `session/service.py` 第 45-46 行有 `from agent_harness.web.app import AppState` 的 TYPE_CHECKING import，这是 domain → web 的反向依赖。
- 但第 335 行的 `isinstance(approval_callback, _InteractiveCallbackHolder)` 检查表明 service 层确实知道 web 层的类型。

---

## 3. #132 续聊端点 + WebSocket + queue/steer

### AC 级验证

| AC | Production | Wiring | Tests | Main | Status |
|---|---|---|---|---|---|
| POST /api/sessions/{id}/messages | `app.py:1153` | ✓ | ✓ | ✓ | DONE |
| mode=queue（空闲→直接拉起） | `service.py:446` send_message | ✓ | ✓ | ✓ | DONE |
| mode=steer（在途→注入引导） | `service.py` SteerRequest | ✓ | ✓ | ✓ | DONE |
| WebSocket mux /api/ws | `app.py:1225` websocket_endpoint | ✓ | — | ✓ | DONE |
| MessageQueueManager | `web/app.py:49` imports | ✓ | ✓ | ✓ | DONE |
| queue/cancelled 事件 | `event.py:79` QUEUE_CANCELLED | ✓ | ✓ | ✓ | DONE |
| steer/requested 事件 | `event.py:80` STEER_REQUESTED | ✓ | ✓ | ✓ | DONE |
| 前端调用 send_message | **未找到** | ✗ | — | — | NOT_STARTED |

**结论**：后端 #132 已完成。前端未接入续聊端点——`web/src/lib/api.ts` 中没有 `sendMessage` 函数，也没有 `/messages` 的 fetch 调用。

### ⚠️ P0 Bug 发现：send_message launched 分支调用不存在的 to_dict()

```python
# app.py:1186-1189 (send_message 的 launched 分支)
async def event_generator():
    try:
        async for ev in subscriber:
            yield {"event": ev.type, "data": json.dumps(ev.to_dict())}  # ← BUG
            if ev.type in {"run/completed", "run/failed"}:
                break
    finally:
        run.unsubscribe(subscriber)
```

**问题**：`ev` 是 `AgentEvent` 类型（来自 `subscriber`），但 `AgentEvent` 没有 `to_dict()` 方法。只有 `SessionEvent` 有 `to_dict()`。

**影响**：当 `send_message` 返回 `status == "launched"` 时（即 session 空闲，直接拉起新 run），SSE generator 会在第一个事件上 crash with `AttributeError: 'AgentEvent' object has no attribute 'to_dict'`。

**对比**：
- `create_session`（line 951）：使用 `_event_to_sse_dict(event, session.session_id)` ✓
- `resume_session`（line 1053）：使用 `_event_to_sse_dict(event, session_id)` ✓
- `send_message` launched（line 1186）：使用 `ev.to_dict()` ✗ ← **唯一的异常**

**修复建议**：
```python
yield _event_to_sse_dict(ev, session_id)
```

---

## 4. #133 CLI 续聊重构 + slash 命令

### AC 级验证

| AC | Production | Tests | Main | Status |
|---|---|---|---|---|
| demo/live_agent_repl.py 存在 | ✓ `demo/live_agent_repl.py` | — | ✓ | DONE |
| slash 命令集定义 | ✓ `SLASH_COMMANDS` list | — | ✓ | DONE |
| /new 命令 | ✓ SlashCommand("new", ...) | — | ✓ | DONE |
| /resume 命令 | ✓ SlashCommand("resume", ...) | — | ✓ | DONE |
| /fork 命令 | ✓ `cli.py:328` fork_command | — | ✓ | DONE |
| /compact 命令 | ✓ SlashCommand("compact", ...) | — | ✓ | DONE |
| /model 命令 | ✓ SlashCommand("model", ...) | — | ✓ | DONE |
| /history 命令 | ✓ SlashCommand("history", ...) | — | ✓ | DONE |
| /cancel 命令 | ✓ SlashCommand("cancel", ...) | — | ✓ | DONE |
| /clear 命令 | ✓ SlashCommand("clear", ...) | — | ✓ | DONE |
| /help 命令 | ✓ SlashCommand("help", ...) | — | ✓ | DONE |

**结论**：#133 已完成。CLI 续聊 REPL + 全部 9 个 slash 命令已在 main 中。

---

## 5. #134 压缩 bracket 升级 + 六段式摘要

### AC 级验证

| AC | Production | Tests | Main | Status |
|---|---|---|---|---|
| COMPACTION_START 事件 | ✓ `event.py:71` | ✓ | ✓ | DONE |
| CONTEXT_COMPACTED 事件 | ✓ `event.py:39` | ✓ | ✓ | DONE |
| COMPACTION_END 事件 | ✓ `event.py:72` | ✓ | ✓ | DONE |
| 六段式摘要（facts/decisions/constraints/failed_attempts/unresolved/artifact_refs） | ✓ `context/compactor.py` | ✓ | ✓ | DONE |
| auto_compact_threshold = 0.80 | ✓ `compactor.py:67` | ✓ | ✓ | DONE |
| hard_guard_threshold = 0.90 | ✓ `compactor.py:68` | ✓ | ✓ | DONE |

**结论**：#134 已完成。4-event compaction bracket + 六段式摘要 + 阈值参数全部在 main 中。

---

## 6. #135 大产物外置对象存储

### AC 级验证

| AC | Production | Tests | Main | Status |
|---|---|---|---|---|
| MinioArtifactStore | ✓ `storage/minio_artifact.py` | ✓ | ✓ | DONE |
| S3ArtifactStore | ✓ `storage/s3_artifact.py` | ✓ | ✓ | DONE |
| ARTIFACT_EXTERNALIZED 事件 | ✓ `event.py:38` | ✓ | ✓ | DONE |
| ReadArtifactTool | ✓ `assembly.py:187` 注册 | ✓ | ✓ | DONE |
| inspect_artifact 工具 | ✓ profiles.py `inspect_artifact` in _MAIN_TOOLS | ✓ | ✓ | DONE |
| ArtifactOverflowHandler | ✓ fail-open 设计 | ✓ | ✓ | DONE |
| assembly.py 注册 MinIO store | ✓ `assembly.py:197` 条件注册 | ✓ | ✓ | DONE |

**结论**：#135 已完成。MinIO 大产物外置 + artifact_ref + inspect_artifact 全链路在 main 中。

---

## 7. #136 审批 WS 推送 + HTTP 回传

### AC 级验证

| AC | Production | Tests | Main | Status |
|---|---|---|---|---|
| TOOL_APPROVAL_REQUESTED 事件 | ✓ `event.py:59` | ✓ | ✓ | DONE |
| POST /api/sessions/{id}/approve | ✓ `app.py:1082` | ✓ | ✓ | DONE |
| ApprovalCard 组件存在 | ✓ `web/src/components/ApprovalCard.tsx` | — | ✓ | PARTIAL |
| ApprovalCard 生产渲染路径 | ✗ **未被任何组件 import** | — | — | NOT_STARTED |
| WebSocket 推送审批请求 | ✓ `app.py:1225` ws_endpoint | — | ✓ | DONE |
| 前端 WS 消费 | ✗ **前端无 WebSocket 代码** | — | — | NOT_STARTED |

**结论**：#136 后端已完成（approval queue + WS push + HTTP resolve）。但前端缺失关键部分：
1. `ApprovalCard` 组件存在但**从未被渲染**——没有任何文件 import 它
2. 前端**没有 WebSocket 消费代码**——`web/src/` 中搜索不到 `WebSocket` 或 `ws://`

---

## 8. #137 模型切换 + Fork API/UI/CLI

### AC 级验证

| AC | Production | Tests | Main | Status |
|---|---|---|---|---|
| GET /api/models 端点 | ✓ `app.py:715` | ✓ | ✓ | DONE |
| POST /api/sessions 支持 model 参数 | ✓ `CreateSessionRequest` | ✓ | ✓ | DONE |
| ModelPicker UI 组件 | ✓ `web/src/components/ModelPicker.tsx` | ✓ | ✓ | DONE |
| CLI fork 命令 | ✓ `cli.py:328` | ✓ | ✓ | DONE |
| session/forked 事件 | ✓ `event.py:21` | ✓ | ✓ | DONE |
| Lineage 树构建 | ✓ `session/lineage.py` | ✓ | ✓ | DONE |
| Web lineage API | ✓ `web/lineage.py` register_lineage_routes | ✓ | ✓ | DONE |
| **POST /api/sessions/{id}/model**（会话级切换） | ✗ **不存在** | — | — | NOT_STARTED |
| **Web 模型切换 UI** | ✗ **不存在** | — | — | NOT_STARTED |
| **Web fork UI** | ✗ **不存在** | — | — | NOT_STARTED |

**结论**：#137 部分完成。模型选择（创建时）+ fork CLI + lineage API 已完成。但**会话级模型切换端点不存在**，**Web fork UI 不存在**。

---

## 9. #138 崩溃恢复 + Ledger reconcile

### AC 级验证

| AC | Production | Tests | Main | Status |
|---|---|---|---|---|
| RecoveryCoordinator 8 步恢复 | ✓ `recovery/coordinator.py:209` | ✓ | ✓ | DONE |
| Operation Ledger (SQLite) | ✓ `storage/sqlite.py:96` SqliteOperationLedger | ✓ | ✓ | DONE |
| UNKNOWN → NEED_RECONCILE 状态机 | ✓ `recovery/reconcile.py` | ✓ | ✓ | DONE |
| ReconcileHint / ReconcileCallback | ✓ `recovery/reconcile.py` | ✓ | ✓ | DONE |
| Checkpoint 持久化 | ✓ `storage/sqlite.py:291` SqliteCheckpointStore | ✓ | ✓ | DONE |
| WorkspaceRegistry 恢复 | ✓ `sandbox/registry.py` | ✓ | ✓ | DONE |
| POST /api/sessions/{id}/recover | ✓ `app.py:1130` | ✓ | ✓ | DONE |
| RUN_INTERRUPTED 事件 | ✗ **不存在** | — | — | NOT_STARTED |
| 前端 interrupted 状态 UI | ✗ **不存在** | — | — | NOT_STARTED |

**结论**：#138 的核心恢复机制已完成（Phase 4 交付物）。但 PRD 要求的 `RUN_INTERRUPTED` 事件和前端中断状态 UI 不存在。

---

## 10. #139 Langfuse 多轮埋点 + DoD 全量回归

### AC 级验证

| AC | Production | Tests | Main | Status |
|---|---|---|---|---|
| LangfuseSink 旁路骨架 | ✓ `observability/sink.py` | ✓ | ✓ | DONE |
| RunTracer per-turn root span | ✓ `observability/tracer.py:86` | ✓ | ✓ | DONE |
| session_id / trace_id 映射 | ✓ `tracer.py` TraceBinding | ✓ | ✓ | DONE |
| tool span（attempt 链） | ✓ `tracer.py` tool_span_started | ✓ | ✓ | DONE |
| SubAgent 嵌套 trace | ✓ `tracer.py` | ✓ | ✓ | DONE |
| flush 生命周期 | ✓ CLI 退出 + Web shutdown | ✓ | ✓ | DONE |
| 真实云 Gate | ✓ Phase 15 Gate | ✓ | ✓ | DONE |

**结论**：#139 的 Langfuse 埋点已基本完成（Phase 15 交付物）。DoD 全量回归需要 multiturn 全部完成后执行。

---

## 11. #37 交互式审批走通

### AC 级验证

| AC | Production | Tests | Main | Status |
|---|---|---|---|---|
| PendingApprovalQueue | ✓ `tooling/approval_queue.py` | ✓ | ✓ | DONE |
| TOOL_APPROVAL_REQUESTED 事件 | ✓ `event.py:59` | ✓ | ✓ | DONE |
| POST /approve 端点 | ✓ `app.py:1082` | ✓ | ✓ | DONE |
| ApprovalCard 组件 | ✓ 存在但不渲染 | — | ✓ | PARTIAL |
| 前端 approval 事件消费 | ✗ projection.ts 无 approval 分支 | — | — | NOT_STARTED |

**结论**：#37 后端已完成。前端 `ApprovalCard` 存在但**没有生产渲染路径**——它从未被任何组件 import。projection.ts 也没有 approval 事件的处理分支。

---

## 12. #35 主题亮色变量组双份手工同步

### AC 级验证

这是一个 chore issue，涉及 CSS 变量的手工同步维护。当前 `web/src/styles/app.css` 中存在 `--surface-*` 和 `--bg-*` 双份变量。

**结论**：低优先级 chore，不影响功能。

---

## 13. 总体需求实现状态

| Issue | 后端状态 | 前端状态 | 整体 |
|---|---|---|---|
| #131 SessionService | ✅ DONE | N/A | DONE |
| #132 续聊端点 + WS | ✅ DONE | ❌ 前端未接入 | PARTIAL |
| #133 CLI 续聊 REPL | ✅ DONE | N/A | DONE |
| #134 Compaction bracket | ✅ DONE | N/A | DONE |
| #135 大产物外置 | ✅ DONE | N/A | DONE |
| #136 审批 WS 推送 | ✅ DONE | ❌ ApprovalCard 未渲染 + 无 WS 消费 | PARTIAL |
| #137 模型切换 + Fork | ✅ 部分 DONE | ❌ 无 Web fork UI + 无会话级切换 | PARTIAL |
| #138 崩溃恢复 | ✅ 核心 DONE | ❌ 无 RUN_INTERRUPTED + 无中断 UI | PARTIAL |
| #139 Langfuse 埋点 | ✅ 基本 DONE | N/A | DONE |
| #37 交互式审批 | ✅ DONE | ❌ ApprovalCard 未渲染 + projection 无分支 | PARTIAL |
| #35 CSS 变量同步 | N/A | chore | DEFER |

### 关键 Gap

1. **P0 Bug**：`send_message` launched 分支调用 `AgentEvent.to_dict()` — `AgentEvent` 没有此方法，会 crash
2. **P1 Gap**：前端未接入续聊端点（`/messages`），无法实现同 session 多轮对话
3. **P1 Gap**：`ApprovalCard` 组件存在但从未被渲染——交互式审批在前端完全断路
4. **P1 Gap**：前端没有 WebSocket 消费代码——WS 推送的审批请求无人接收
5. **P2 Gap**：会话级模型切换端点不存在（`POST /api/sessions/{id}/model`）
6. **P2 Gap**：Web fork UI 不存在
7. **P2 Gap**：`RUN_INTERRUPTED` 事件不存在，前端无中断状态 UI
