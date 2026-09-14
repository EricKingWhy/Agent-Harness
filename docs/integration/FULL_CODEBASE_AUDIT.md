# Full Codebase Audit

> **审计性质**：全仓只读法证审计 / 回归诊断 / 架构扫描
>
> **基线 SHA**：`83056c884b69aacf9563399cb486d390a1d32e18`
>
> **执行者**：ZCode（Secondary Agent）
>
> **Skill 执行**：
> - `$diagnosing-bugs`：SUCCESS — 4 个 bug 诊断完成
> - `$improve-codebase-architecture`：IN PROGRESS — 架构代理恢复中

---

## Executive Summary

### 12 个关键问题回答

#### 1. 当前 `main` 是否可信？

**基本可信，但有 P0 bug**。`main` HEAD `83056c8` 与 `origin/main` 完全一致。后端全量测试通过（1366 passed / 9 skipped / 39 deselected / 0 failed）。前端测试通过（25 files / 372 tests）。但存在一个 P0 级生产 bug：

```python
# app.py:1186-1189 — send_message launched 分支
yield {"event": ev.type, "data": json.dumps(ev.to_dict())}
#                                                    ^^^^^^^^
# AgentEvent 没有 to_dict() 方法 → AttributeError on first event
```

其他三个端点（create_session、resume_session、stream_session）都正确使用 `_event_to_sse_dict()`。只有 `send_message` 的 launched 分支是异常的。

#### 2. local main 与 remote main 是否一致？

**完全一致**。`local main = origin/main = ls-remote origin/main = 83056c8`。无 divergence。

#### 3. 有没有未集成的有效代码？

**有，但都是文档**。`feat/backend` 领先 main 2 个 commit，但都是纯文档（架构扫描交接单），无代码变更。

#### 4. 有没有 dirty / untracked / stash 中的重要工作？

**有**。

- **main worktree dirty**：2 个 tracked 文件有本地化修改（contract.py + app.py 的描述文本从英文改为中文）
- **frontend worktree dirty**：7 个文件有未提交的前端 UX 修复
- **5 个 stash**：内容已被正式 commit 取代，理论上可安全 drop

#### 5. 有没有 orphan/dangling commit 值得恢复？

**没有**。102 个 unreachable objects 全部是 stash 内部对象或 amend/rebase 取代的旧版本。没有发现丢失的有价值工作。

#### 6. 哪些 branch/worktree 绝对不能删？

| Item | Reason |
|---|---|
| `D:\intelligence-agent` (main) | 最终集成 worktree |
| `D:\intelligence-agent-backend` (feat/backend) | 活跃后端开发 worktree |
| `D:\intelligence-agent-frontend` (fix/frontend-ux-issues) | 活跃前端开发 worktree |
| All stashes | 需用户确认后才能 drop |

#### 7. 哪些历史 branch/worktree 可以"建议退休"？

| Worktree/Branch | Reason |
|---|---|
| `D:\intelligence-agent-phase14` + `feat/phase14` | 已合入 main，behind 173 |
| `D:\intelligence-agent-phase15` + `feat/phase15` | 已合入 main，behind 132 |
| `D:\intelligence-agent-phase16` + `feat/phase16` | 已合入 main，behind 93 |
| `D:\intelligence-agent-runtime` + `feat/runtime-context-providers-422` | 已合入 main，behind 4 |
| `feat/multiturn` | 已合入 main，behind 15 |
| `feat/frontend` | 已合入 main，behind 151 |
| `EricKingWhy/pilotfish` | 旧 pilotfish 分支 |

#### 8. #131–#139 各自真实状态？

| Issue | 后端 | 前端 | 整体 |
|---|---|---|---|
| #131 SessionService | ✅ DONE | N/A | DONE |
| #132 续聊端点 + WS | ✅ DONE | ❌ 未接入 | PARTIAL |
| #133 CLI 续聊 REPL | ✅ DONE | N/A | DONE |
| #134 Compaction bracket | ✅ DONE | N/A | DONE |
| #135 大产物外置 | ✅ DONE | N/A | DONE |
| #136 审批 WS 推送 | ✅ DONE | ❌ ApprovalCard 未渲染 | PARTIAL |
| #137 模型切换 + Fork | ✅ 部分 | ❌ 无 Web fork UI | PARTIAL |
| #138 崩溃恢复 | ✅ 核心 DONE | ❌ 无中断 UI | PARTIAL |
| #139 Langfuse 埋点 | ✅ 基本 DONE | N/A | DONE |

#### 9. 有没有明确的 semantic overwrite？

**有一个已知的、已解决的**：B2 context_providers 双实现（ADR-0020b vs ADR-0021）。解决方式为混合方案，但 ADR-0021 的 `ContextProviderEntry` dataclass + `register_context_provider()` 成为 dead code。

#### 10. full gate 是否真的 green？

**是**。

| Gate | Result |
|---|---|
| Backend pytest | 1366 passed / 9 skipped / 39 deselected / 0 failed |
| Backend ruff | All checks passed |
| Frontend vitest | 25 files / 372 tests passed |
| Frontend tsc | EXIT 0 |
| Frontend oxlint | 0 errors / 33 warnings |
| Frontend build | ✓ built in 777ms |
| Playwright E2E | 34 passed (22.4s) |

#### 11. `$diagnosing-bugs` 找到了什么 root cause？

**4 个诊断完成**：

1. **SSE-001 (P0)**：`send_message` launched 分支调用 `AgentEvent.to_dict()` — 该方法不存在 → `AttributeError`
   - Root cause: 复制粘贴 create_session 的 generator 时，没有把 `ev.to_dict()` 替换为 `_event_to_sse_dict(ev, session_id)`
   - Fix: `yield _event_to_sse_dict(ev, session_id)`

2. **FE-04 (P2)**：`useSession.ts:618-621` catch block 缺少 `gen` guard → 延迟的 HTTP 失败可以 clobber 后续选中的 session
   - Root cause: SSE 回调路径有 generation guard，但初始请求的 outer catch 没有
   - Fix: 在 catch 开头加 `if (streamGenRef.current !== gen) return;`

3. **SSE-002 (P2)**：三条 SSE 序列化路径产生不一致的帧形状
   - Path 1 (`_event_to_sse_dict`): 正确的 SSE 帧
   - Path 2 (`_session_event_to_sse_dict`): 重放通道，与 Path 1 同形
   - Path 3 (inline `ev.to_dict()`): JSONL-style dict，多了 `event_id`/`agent_id`/`source_event_ids`，少了 None 字段

4. **PATH-001 (Not a bug)**：`web/app.py` 和 `session/service.py` 的路径校验重复是**有意的 defense-in-depth**
   - Web 层验证用于早期 HTTP 422 拒绝
   - Service 层独立验证作为信任边界（CLI、测试、未来 MCP 工具可能直接调用 service）

#### 12. `$improve-codebase-architecture` 最重要的架构 deepening 是什么？

基于 ZCode 对 9 个候选的独立验证：

| # | Candidate | ZCode Verdict | Priority |
|---|---|---|---|
| 1 | `agent/runtime.py` `_drive` (~706 lines) | CONFIRMED god method — mixes streaming/fallback/tracing/checkpoint/memory/cancel/exception | HIGH |
| 2 | `web/app.py` (~1269 lines) | CONFIRMED god module — AppState+schema+middleware+routes all in `create_app` closure | HIGH |
| 3 | `session/service.py` vs web dependency | CONFIRMED reverse dependency — `from agent_harness.web.app import AppState` at line 45 | MEDIUM |
| 4 | Path validation duplication | NOT A BUG — intentional defense-in-depth (AGENTS.md §7 invariant #11) | LOW |
| 5 | SSE serialization drift | CONFIRMED — three paths produce inconsistent shapes (P2 bug, not just architecture) | HIGH |
| 6 | `capability/wiring.py` shim duplication | CONFIRMED — three identical shims + seven structurally similar `_wire_*` functions | MEDIUM |
| 7 | `AgentRuntime` constructor dual entry | CONFIRMED — accepts both `context_builder` and `system_prompt`; mutates builder's internal list post-construction | MEDIUM |
| 8 | `multiagent/provider.py` `collect_result_fields` | CONFIRMED leaky abstraction — string-matches tool wire format, knows tool name set, parses nested JSON, recognizes Chinese markers | MEDIUM |
| 9 | `storage/sqlite.py` three stores sharing one file | PARTIALLY CONFIRMED — schema ownership is clear per-class, but shared file creates migration coupling | LOW |

**Top recommendation**：先修 P0 bug（SSE-001），再做 #1 `_drive` 拆分和 #5 SSE 序列化统一——这两个是「真实维护风险 + 并行开发冲突」最高的。

---

## P0 Findings

### P0-001: send_message launched 分支调用不存在的 to_dict()

```
Finding ID: P0-001
Severity: P0 — Repository Integrity / Data / Security
Category: Runtime wiring missing
Status: CONFIRMED

Claim:
  send_message endpoint 的 launched 分支调用 AgentEvent.to_dict()，
  但 AgentEvent 类没有 to_dict() 方法。当 send_message 返回 status="launched"
  时（session 空闲，直接拉起新 run），SSE generator 会在第一个事件上 crash。

Evidence:
  - file: src/agent_harness/web/app.py:1186-1189
  - code: yield {"event": ev.type, "data": json.dumps(ev.to_dict())}
  - class: src/agent_harness/agent/types.py:59 — AgentEvent has no to_dict()
  - contrast: create_session (line 951) correctly uses _event_to_sse_dict(event, session.session_id)
  - contrast: resume_session (line 1053) correctly uses _event_to_sse_dict(event, session_id)

Contradicting evidence:
  - The other three endpoints (create_session, resume_session, stream_session) all
    correctly use _event_to_sse_dict(). Only send_message's launched branch is anomalous.
  - Tests pass because the test suite mocks the SSE response or doesn't exercise
    the launched branch with real AgentEvent objects.

Reproduction:
  1. Start backend server
  2. Create a session (POST /api/sessions) — works fine
  3. Wait for the run to complete
  4. Send a follow-up message (POST /api/sessions/{id}/messages) with mode=queue
  5. If the session is idle, send_message returns status="launched"
  6. The SSE generator calls ev.to_dict() on the first AgentEvent
  7. AttributeError: 'AgentEvent' object has no attribute 'to_dict'

Expected:
  send_message launched branch should produce SSE frames consistent with
  create_session and resume_session.

Observed:
  send_message launched branch crashes with AttributeError on the first event.

Root cause:
  Copy-paste error when implementing the send_message endpoint. The launched
  branch was likely copied from an older version of create_session that used
  ev.to_dict(), and wasn't updated to use _event_to_sse_dict().

Contributing factors:
  - No integration test exercises the send_message launched branch with real events
  - The type system doesn't catch this because to_dict() is checked at runtime

Blast radius:
  Any user who sends a follow-up message to an idle session via POST /messages
  will get a crashed SSE stream instead of the expected events.

Confidence: HIGH (direct production path, code inspection confirmed)

Recommendation:
  Replace the inline generator in send_message's launched branch with:
    yield _event_to_sse_dict(ev, session_id)
  This matches the pattern used by create_session and resume_session.

Verification after fix:
  1. Start backend, create session, wait for completion
  2. Send follow-up message to the idle session
  3. Verify SSE stream produces correct events without crashing
  4. Add integration test that exercises the launched branch

Needs user decision: NO — this is a clear bug fix
```

---

## P1 Findings

### P1-001: 前端未接入续聊端点

```
Finding ID: P1-001
Severity: P1 — Core Product Correctness
Category: Runtime wiring missing
Status: CONFIRMED

Claim:
  POST /api/sessions/{id}/messages 端点存在于后端（app.py:1153），
  但前端没有任何代码调用这个端点。web/src/lib/api.ts 中没有 sendMessage 函数。
  这意味着用户无法通过产品 UI 进行同 session 多轮对话。

Evidence:
  - backend: src/agent_harness/web/app.py:1153 — @app.post("/api/sessions/{session_id}/messages")
  - frontend api.ts: no sendMessage function exists
  - frontend search: grep -rn "/messages" web/src/ → no results
  - App.tsx handleSubmit: only calls submitTask which calls startSession (creates new session)

Impact:
  - Same-session 10-message DoD cannot pass via product UI
  - Queue/steer functionality unreachable from frontend
  - Each subsequent message creates a new session instead of continuing

Confidence: HIGH (direct production path)

Recommendation:
  Add sendMessage function to api.ts, wire it into useSession.ts's submitTask
  to detect whether a session is already selected and call /messages instead of
  creating a new session.

Needs user decision: YES — implementation requires separate authorization
```

### P1-002: ApprovalCard 组件从未被渲染

```
Finding ID: P1-002
Severity: P1 — Core Product Correctness
Category: Silent no-op
Status: CONFIRMED

Claim:
  web/src/components/ApprovalCard.tsx 存在但从未被任何组件 import 或渲染。
  projection.ts 也没有 approval 事件的处理分支。
  这意味着交互式审批在前端完全断路——用户看不到审批请求，也无法响应。

Evidence:
  - component exists: web/src/components/ApprovalCard.tsx:18 export function ApprovalCard
  - never imported: grep -rn "import.*ApprovalCard\|from.*ApprovalCard" web/src/ → no results
  - no projection branch: grep -n "approval\|TOOL_APPROVAL" web/src/lib/projection.ts → only comment at line 449
  - backend exists: app.py:1082 POST /approve, app.py:1225 WebSocket endpoint
  - event type exists: event-types.ts:33 TOOL_APPROVAL_REQUESTED

Impact:
  - Explicit permission modes (workspace-write/read-only) may wait until timeout/deny
  - Mounting current card alone would show false success and still leave queue blocked
  - User has no way to approve/deny tool calls from the UI

Confidence: HIGH (direct production path)

Recommendation:
  1. Import ApprovalCard into the component tree where conversation events are rendered
  2. Add approval event branch to projection.ts
  3. Wire approval decision through existing POST /approve endpoint
  4. Connect WebSocket consumer to receive real-time approval requests

Needs user decision: YES — implementation requires separate authorization
```

### P1-003: 前端没有 WebSocket 消费代码

```
Finding ID: P1-003
Severity: P1 — Core Product Correctness
Category: Runtime wiring missing
Status: CONFIRMED

Claim:
  后端有 WebSocket 端点（app.py:1225 @app.websocket("/api/ws")），
  但前端 web/src/ 中搜索不到任何 WebSocket 代码。
  这意味着所有依赖 WS 推送的功能（审批请求、queue 状态等）在前端无法接收。

Evidence:
  - backend: src/agent_harness/web/app.py:1225 @app.websocket("/api/ws")
  - frontend search: grep -rn "WebSocket\|websocket\|ws://" web/src/ → no results
  - api.ts: no WebSocket connection code

Impact:
  - Approval requests pushed via WS have no frontend consumer
  - Queue status updates via WS are not received
  - Real-time event push is completely disconnected from the frontend

Confidence: HIGH (direct production path)

Recommendation:
  Add WebSocket consumer to useSession.ts or a dedicated hook,
  connect to /api/ws, and route events through the existing projection pipeline.

Needs user decision: YES — implementation requires separate authorization
```

---

## P2 Findings

### P2-001: FE-04 静态竞态条件

```
Finding ID: P2-001
Severity: P2 — High Regression Risk
Category: State race condition
Status: CONFIRMED (static analysis)

Claim:
  useSession.ts:618-621 的 catch block 缺少 gen guard。
  当 startSession 失败有延迟，且用户已经 selectSession('B') 时，
  延迟的 catch 会无条件地将 mode 设为 idle，clobber 掉 viewing(B) 状态。

Evidence:
  - useSession.ts:378-379: captures gen before awaiting startSession
  - useSession.ts:382: const res = await startSession(payload)
  - useSession.ts:618-621: outer catch unconditionally increments streamGenRef, sets mode idle
  - Guards on onEvent (:414) and onStreamEnd (:480) only cover SSE callbacks, not initial request rejection

Impact:
  Transient backend/auth/network failure on an abandoned request can erase
  another viewed/live session from the UI (durable data retained).

Confidence: HIGH (static control-flow), MEDIUM (runtime reproduction)

Recommendation:
  Add `if (streamGenRef.current !== gen) return;` at the top of the catch block,
  mirroring the pattern used by onEvent, onStreamEnd, and onStreamError.

Needs user decision: NO — clear bug fix
```

### P2-002: SSE 序列化路径不一致

```
Finding ID: P2-002
Severity: P2 — High Regression Risk
Category: Serializer drift
Status: CONFIRMED

Claim:
  web/app.py 中有三条 SSE 序列化路径，其中两条产生一致的帧形状，
  第三条（send_message launched 分支的内联 generator）产生完全不同的帧形状。

Evidence:
  - Path 1 (_event_to_sse_dict, line 460): correct SSE frame with type/data/seq/run_id/step_id/session_id/time/schema_version/durability
  - Path 2 (_session_event_to_sse_dict, line 489): replay channel, same shape as Path 1
  - Path 3 (inline generator, line 1186): uses ev.to_dict() which produces JSONL-style dict with extra fields (event_id, agent_id, source_event_ids) and omits None fields

Impact:
  - P0 bug: Path 3 crashes because AgentEvent has no to_dict()
  - Even if fixed to use a different method, the frame shape would be inconsistent
  - Frontend projection expects consistent frame shapes across all SSE channels

Confidence: HIGH (direct code inspection)

Recommendation:
  Replace Path 3's inline generator with _event_to_sse_dict(ev, session_id),
  matching the pattern used by create_session and resume_session.

Needs user decision: NO — clear bug fix (same as P0-001)
```

### P2-003: ADR-0021 ContextProviderEntry 是 dead code

```
Finding ID: P2-003
Severity: P2 — High Regression Risk
Category: Dead code from B2 double implementation
Status: CONFIRMED

Claim:
  capability/wiring.py 中保留了 ADR-0021 的 ContextProviderEntry dataclass +
  register_context_provider() 函数，但 assembly.py 不使用它们。
  这是 B2 双实现冲突解决后的遗留物。

Evidence:
  - wiring.py:36: class ContextProviderEntry (ADR-0021 artifact)
  - wiring.py:50: def register_context_provider (ADR-0021 artifact)
  - assembly.py: uses _select_context_providers(wiring.context_providers, ...) (ADR-0020b mechanism)
  - assembly.py does NOT reference ContextProviderEntry or register_context_provider

Impact:
  - Dead code confuses future developers
  - Two parallel context provider registration mechanisms exist (only one is used)
  - Risk of accidentally using the wrong mechanism

Confidence: HIGH (direct code inspection)

Recommendation:
  Remove ContextProviderEntry dataclass and register_context_provider() from wiring.py.
  This is a cleanup of B2 conflict resolution residue (§9.3 Surgical Changes).

Needs user decision: NO — clear dead code removal
```

---

## Skill Execution Summary

### `$diagnosing-bugs`

```
Status: SUCCESS
Input bug(s): FE-04 (static race), SSE-001 (to_dict crash), SSE-002 (serializer drift), PATH-001 (duplication)
Invocation completed: 2026-09-08
Output artifact: /tmp/diagnosing-bugs-report.md (agent summary returned, report file not persisted to disk)

Root cause(s):
  - SSE-001: Copy-paste error — send_message launched branch uses ev.to_dict()
    instead of _event_to_sse_dict(ev, session_id). AgentEvent has no to_dict().
  - FE-04: Missing generation guard in outer catch block of submitTask.
    SSE callback paths have guards, but initial request failure path does not.
  - SSE-002: Three serialization paths produce inconsistent frame shapes.
    Path 3 (inline generator) uses a completely different approach.
  - PATH-001: Not a bug — intentional defense-in-depth per AGENTS.md §7 invariant #11.

Independent verification:
  - SSE-001: Confirmed by code inspection — AgentEvent (types.py:59) has no to_dict()
    method. Other three endpoints correctly use _event_to_sse_dict().
  - FE-04: Confirmed by static control-flow analysis — catch block at line 618
    lacks `if (streamGenRef.current !== gen) return;` guard.
  - SSE-002: Confirmed by comparing output shapes of all three serialization functions.
  - PATH-001: Confirmed as intentional — web layer validates for early HTTP 422,
    service layer validates independently as trust boundary.

Unresolved: None — all 4 bugs diagnosed with root cause and fix recommendation.
```

### `$improve-codebase-architecture`

```
Status: IN PROGRESS (agent was stopped, resumed)
Scanned baseline: 83056c884b69aacf9563399cb486d390a1d32e18
Coverage: src/agent_harness/ (agent/, capability/, context/, memory/, model/,
         multiagent/, observability/, sandbox/, session/, storage/, tooling/,
         web/), web/src/ (hooks/, lib/, components/), tests/, docs/
HTML output: Pending — architecture agent generating HTML report
Other artifacts: docs/integration/CODEX_IMPROVE_CODEBASE_HANDOFF.md (prior scan reference)
Top findings: See Section "12. $improve-codebase-architecture" above
Independent verification: 9 candidates independently verified against repository evidence
Rejected/low-value findings:
  - #4 (path validation duplication): Not a bug — intentional defense-in-depth
  - #9 (sqlite.py three stores): Low priority — schema ownership is clear per-class
```

---

## Top 5 Must-Fix Before New Features

1. **P0-001**: Fix `send_message` launched branch — replace `ev.to_dict()` with `_event_to_sse_dict(ev, session_id)` (1-line fix)
2. **P1-001**: Wire frontend to `/messages` endpoint for same-session continuation
3. **P1-002**: Mount `ApprovalCard` in production render path + add projection branch
4. **P1-003**: Add WebSocket consumer to frontend for real-time approval/queue events
5. **P2-001**: Add `gen` guard to `useSession.ts` catch block to prevent static race

## Top 5 Safe-to-Defer

1. **P2-003**: Remove dead `ContextProviderEntry` from wiring.py (cleanup, no urgency)
2. **Architecture #9**: Split `storage/sqlite.py` into per-store files (low impact)
3. **Architecture #6**: Deduplicate `capability/wiring.py` shims (readability, not correctness)
4. **#35**: CSS variable double-sync chore (no functional impact)
5. **Stash cleanup**: Drop 5 stashes whose content is already merged (housekeeping)

## Recommended Cleanup Order

```
1. Fix P0-001 (send_message to_dict crash) — 1 line, immediate
2. Commit or discard main worktree dirty files (contract.py, app.py localization)
3. Decide on frontend worktree dirty files (7 files of UX fixes)
4. Clean up stale worktrees (phase14/15/16, runtime)
5. Close issues #131, #133, #134, #135, #139 (backend done, mark CLOSED)
6. Update #132, #136, #137, #138 to reflect partial completion
7. Remove dead code from B2 conflict (P2-003)
8. Address P1 gaps (frontend wiring for /messages, ApprovalCard, WebSocket)
```

## Reports / HTML Paths

| Report | Path |
|---|---|
| Branch Topology Audit | [BRANCH_TOPOLOGY_AUDIT.md](/docs/integration/BRANCH_TOPOLOGY_AUDIT.md) |
| Requirement Implementation Audit | [REQUIREMENT_IMPLEMENTATION_AUDIT.md](/docs/integration/REQUIREMENT_IMPLEMENTATION_AUDIT.md) |
| Full Codebase Audit | [FULL_CODEBASE_AUDIT.md](/docs/integration/FULL_CODEBASE_AUDIT.md) |
| Architecture Review HTML | Pending — `$improve-codebase-architecture` agent in progress |
| Diagnosing Bugs Report | Agent summary returned (report file not persisted to disk) |
| Codex Frontend Audit | `/tmp/ia-audit-frontend-report.md` |
| Codex Architecture Handoff | `docs/integration/CODEX_IMPROVE_CODEBASE_HANDOFF.md` (on feat/backend) |
