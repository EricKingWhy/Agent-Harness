# Runtime Streaming Protocol Specification

> **Audience**: Backend/runtime engineers and frontend runtime/infrastructure engineers.
>
> **Authority**: Shared frontend/backend contract. Product behavior is defined in `01_AGENT_RUNTIME_STREAMING_UI_PRD_v2.md`; this document defines the runtime event semantics, transport expectations, ordering, reconnect, persistence, replay, backpressure, validation, and versioning required to realize that product safely.
>
> **Important**: Do not infer that SSE or WebSocket is mandatory before auditing the current codebase. Preserve the existing production-capable transport unless evidence shows a migration is materially better.

---

# 1. Goals

The protocol must support:

- true reasoning/progress streaming;
- true assistant text streaming;
- tool call state and partial args where supported;
- streaming stdout/stderr/tool output;
- Search/Read/Skill/MCP/Subagent/Todo progress;
- live Run Inspector projection;
- history reconstruction;
- reconnect/resume;
- idempotent at-least-once handling;
- provider abstraction;
- bounded micro-event overhead;
- robust validation/error recovery;
- schema evolution.

---

# 2. Non-goals

This protocol does not redefine:

- Agent policy;
- planning quality;
- tool selection logic;
- model routing intent;
- business permissions;
- hidden model Chain of Thought.

It transports runtime facts and user-visible stream content.

---

# 3. Recommended Architecture

```text
Provider / Agent / Tool Runner
           │
           ▼
Provider Adapter / Runtime Adapter
           │
           ▼
Canonical Runtime Event Bus
           │
           ├── Append-only Runtime Event Log
           ├── Coalesced Stream Block Store
           ├── Projection Snapshot Builder
           │
           ▼
Transport Gateway (existing WS or SSE; AI SDK protocol may be evaluated)
           │
           ▼
Browser Event Ingress
           │
           ▼
Canonical Client Event Store
```

No provider-specific event format should leak directly into presentation components.

---

# 4. Transport Decision Gate

The project owner is uncertain whether the current implementation uses WebSocket or SSE. The implementation team must inspect the code first.

## 4.1 Preserve-first rule

If current transport already provides:

- ordered server→client delivery;
- connection lifecycle;
- practical reconnect/resume support or can be extended;
- authentication/authorization compatibility;
- acceptable proxy/load-balancer behavior;
- production monitoring;

then keep it unless migration yields a clear measurable benefit.

## 4.2 SSE is appropriate when

- traffic is predominantly server→browser;
- client actions use normal HTTP endpoints;
- simple HTTP infrastructure/proxies are desired;
- Last-Event-ID/cursor replay fits the persistence model.

## 4.3 WebSocket is appropriate when

- project already relies on it successfully;
- bi-directional control/approval/cancel traffic benefits from one channel;
- reconnect/session machinery is already mature;
- proxy/infrastructure is configured correctly.

## 4.4 AI SDK migration/spike

AI SDK is explicitly allowed and should be seriously evaluated, including broader migration if it improves quality.

But migration must preserve the Harness requirements:

- canonical runtime event semantics;
- Inspector raw/logical event depth;
- replay/history;
- provider abstraction;
- tool output streaming;
- model/progress relationships;
- Python/backend compatibility if backend remains Python.

AI SDK transport/client machinery may be used while still projecting into the canonical event model below.

## 4.5 Decision artifact

Before migration, produce a short ADR comparing:

| Axis | Existing Transport | Enhanced Existing | AI SDK Layer | Broader AI SDK Migration |
|---|---|---|---|---|
| First-delta latency | | | | |
| Reconnect/resume | | | | |
| Tool streaming | | | | |
| Reasoning streaming | | | | |
| Inspector compatibility | | | | |
| Replay | | | | |
| Provider support | | | | |
| Complexity | | | | |
| Operational risk | | | | |
| Testability | | | | |

Migration must be evidence-based, not preference-only.

---

# 5. Canonical Event Envelope

Every logical/raw runtime event should be normalizable to an envelope equivalent to:

```ts
interface RuntimeEventEnvelope<T = unknown> {
  schema_version: string
  event_id: string
  type: string
  seq: number

  session_id: string
  run_id: string
  step_id?: number | string | null
  block_id?: string | null

  parent_event_id?: string | null
  parent_block_id?: string | null
  tool_call_id?: string | null
  span_id?: string | null
  trace_id?: string | null

  timestamp: string
  source: 'model' | 'agent' | 'tool' | 'runtime' | 'system' | string
  visibility: 'user' | 'debug' | 'internal'

  payload: T
}
```

Names may map to existing schema conventions. Semantics matter more than exact spelling.

## 5.1 Required invariants

- `event_id` globally/adequately unique;
- `seq` monotonically increases **within a run**;
- events from a replay retain original ordering identity where possible;
- `visibility=internal` must never be projected into user-visible reasoning;
- `block_id` identifies an assembled stream block such as reasoning/text/tool output;
- `tool_call_id` links tool lifecycle events.

---

# 6. Delivery Semantics

## 6.1 At-least-once

Prefer **at-least-once delivery + idempotent projection**.

Client dedupe key priority:

1. `event_id`;
2. `(run_id, seq)` fallback where safe.

Do not attempt expensive distributed exactly-once semantics merely for UI rendering.

## 6.2 Ordering

The canonical ordering for a run is `seq`.

Timestamp is informational and not the primary sort key because clocks may differ.

If a later sequence arrives before an earlier one:

- small reorder window may buffer briefly;
- persistent gap triggers recovery strategy;
- UI must not crash.

## 6.3 Duplicate events

Duplicate event delivery must be ignored at projection level without duplicating:

- text;
- reasoning;
- tool rows;
- output;
- Inspector logical nodes.

---

# 7. Core Event Semantics

Exact names may be mapped to existing runtime names during SDD.

## 7.1 Run lifecycle

```text
run/started
run/completed
run/failed
run/cancelled
```

Payload includes status, timing, model/provider context where appropriate.

## 7.2 Model lifecycle

```text
model/started
model/completed
model/failed
```

Model completion metadata may include:

- provider;
- model;
- usage;
- latency;
- finish reason;
- fallback metadata if the runtime already supports it.

## 7.3 Reasoning lifecycle

```text
reasoning/started
reasoning/delta
reasoning/completed
reasoning/interrupted
```

Example:

```json
{
  "schema_version": "2",
  "event_id": "evt_184",
  "type": "reasoning/delta",
  "seq": 184,
  "session_id": "...",
  "run_id": "...",
  "step_id": 7,
  "block_id": "reasoning_07",
  "timestamp": "...",
  "source": "model",
  "visibility": "user",
  "payload": {
    "delta": "Let me inspect the projection..."
  }
}
```

Provider-exposed reasoning must be marked user-visible only when the provider contract allows it.

Agent progress fallback can use either `progress/*` or normalized reasoning blocks with `source=agent`, but the distinction must remain inspectable.

## 7.4 Assistant text lifecycle

```text
text/started
text/delta
text/completed
text/interrupted
```

`block_id` must remain stable for a single contiguous answer block.

## 7.5 Tool lifecycle

Recommended logical states:

```text
tool/call_started
tool/call_delta        # optional partial args
tool/call_completed    # args complete / invocation accepted
tool/output_delta      # stream output
tool/result            # terminal result
tool/error             # optional explicit terminal error event
```

`tool/output_delta` payload should distinguish channel:

```json
{
  "channel": "stdout",
  "delta": "RUN src/foo.test.ts\n"
}
```

or:

```json
{
  "channel": "stderr",
  "delta": "warning...\n"
}
```

Do not require every tool to stream. Non-streaming tools emit call/result normally.

## 7.6 Search / Read

May remain Tool events internally, but semantic projection should have enough metadata to classify them as Search/Read in the UI.

Optional dedicated events:

```text
search/started
search/result
read/started
read/completed
```

The implementation should reuse existing tool schema where practical rather than duplicate facts.

## 7.7 Skill / MCP / Delegation

```text
skill/started
skill/completed
mcp/started
mcp/completed
agent/delegation_started
agent/delegation_completed
```

Child run/session linkage should be explicit when available.

## 7.8 Todo / Plan

```text
plan/updated
progress/updated
```

Updates should include stable item IDs where possible so the UI can update in place rather than recreate lists.

## 7.9 Heartbeat

Transport may use a protocol-native ping/pong or logical heartbeat.

Heartbeat is transport health, not a visible Agent event.

---

# 8. Block State Machines

## 8.1 Reasoning block

```text
created
  ↓ reasoning/started
streaming
  ├─ reasoning/delta → streaming
  ├─ reasoning/completed → completed
  └─ provider/runtime failure → interrupted
```

Invariants:

- deltas append in sequence;
- completed block is immutable except metadata correction;
- interrupted block preserves assembled text;
- a new post-tool reasoning segment receives a new `block_id`.

## 8.2 Text block

Same structure as reasoning.

## 8.3 Tool block

```text
preparing
  ↓ call_started
args_streaming (optional)
  ↓ call_completed
running
  ├─ output_delta*
  └─ result/error
terminal
```

Inspector may expose all states; center stream shows simplified human semantics.

---

# 9. Delta Coalescing

## 9.1 Server-side micro-coalescing

Providers may emit tiny deltas such as individual tokens. The runtime may coalesce them into small chunks before transport.

Goal:

- reduce event overhead;
- reduce persistence rows;
- reduce React/store churn;
- preserve perceived immediacy.

Suggested starting policy for benchmarking:

- flush at ~10–30ms;
- or size threshold;
- flush immediately on lifecycle boundary;
- flush immediately before tool transition;
- never hold data merely to create a typewriter effect.

Actual values should be benchmark-driven.

## 9.2 Persistence coalescing

Do **not** create one durable database row per token unless a specific compliance/debug requirement justifies it.

Persist:

- meaningful raw/coalesced runtime chunks;
- final assembled block;
- logical event metadata.

---

# 10. Reconnect and Resume

## 10.1 Cursor

Client maintains latest successfully applied cursor:

```text
(run_id, seq, event_id)
```

## 10.2 SSE

If SSE is used:

- use `id:`/Last-Event-ID or explicit query cursor;
- on reconnect request events after cursor;
- send heartbeat comments/events as needed for proxies.

## 10.3 WebSocket

If WebSocket is used:

- reconnect handshake includes last applied cursor;
- server returns missing events or snapshot/reconcile instruction;
- client dedupes replay.

## 10.4 Large backlog

If the client is far behind (e.g. background/offline 30 minutes), do not force replay of every micro-delta visually.

Preferred:

```text
fetch/current projection snapshot
→ hydrate quickly
→ fetch/apply required tail events
→ resume live stream
```

Raw historical events remain accessible according to retention.

---

# 11. Persistence Model

Three layers are recommended.

## 11.1 Append-only Runtime Event Log

Purpose:

- audit/debug;
- replay;
- relationship reconstruction;
- recovery.

Can store coalesced raw chunks rather than tokens.

## 11.2 Coalesced Streaming Blocks

Stores assembled/recoverable objects:

- ReasoningBlock;
- TextBlock;
- ToolOutput block(s);
- plan/subagent state where useful.

Example conceptual row/object:

```text
block_id
run_id
kind
status
source
visibility
started_at
completed_at
duration_ms
assembled_text / assembled_payload
last_seq
```

## 11.3 Projection Snapshot

Purpose:

- fast historical load;
- fast reconnect after long backlog;
- avoid replaying thousands of events before first paint.

Snapshot includes logical projection state, not presentation-only toggles.

---

# 12. Replay Invariants

Replay of stored runtime truth must reconstruct the same logical ordering:

```text
reasoning block A
→ tool X
→ reasoning block B
→ subagent Y
→ answer
```

It need not re-enact the original typing animation speed.

Historical UI should hydrate to stable completed state quickly, while still permitting Raw event inspection.

---

# 13. Backpressure

Backpressure exists at multiple layers.

## 13.1 Provider → runtime

Use bounded queues where appropriate. A slow UI client must not block the core Agent loop indefinitely.

## 13.2 Runtime → transport

If a client falls behind:

- coalesce compatible deltas;
- switch to snapshot/reconcile if backlog exceeds safe threshold;
- preserve lifecycle boundaries and errors;
- never drop terminal state.

## 13.3 Browser

Client render scheduler may reduce frame frequency while retaining canonical state.

---

# 14. Validation and Malformed Events

Network events must be runtime-validated; TypeScript types alone are insufficient.

Use the project's existing schema validation library if present. Otherwise evaluate a mature option such as Zod/Valibot.

On invalid event:

1. do not crash the whole UI;
2. record telemetry;
3. quarantine/log the malformed event;
4. if ordering is affected, trigger gap recovery/snapshot reconciliation;
5. show a developer-visible degradation notice only when needed.

---

# 15. Privacy / Reasoning Visibility

This is a hard boundary.

The protocol must distinguish:

- provider user-visible reasoning;
- Agent-generated progress summary;
- internal/hidden reasoning metadata.

`visibility=internal` must never be rendered in the user-visible reasoning component.

Do not create a feature that asks models to dump hidden chain-of-thought solely to imitate another product's UI.

---

# 16. Schema Versioning

Every event envelope carries `schema_version`.

Rules:

- additive changes preferred;
- client should tolerate unknown optional fields;
- unknown event type should project to a safe generic RuntimeNotice in Debug/Raw, not crash;
- breaking changes require migration/version mapping;
- history replay must record enough version context to decode old events.

---

# 17. Error Semantics

Differentiate:

- provider error;
- tool error;
- timeout;
- transport disconnect;
- malformed event;
- projection/client error;
- cancelled run.

Do not collapse everything to “failed”.

Partial streamed data remains available after terminal failure.

---

# 18. Observability Metrics

Backend/runtime should expose or log at least:

- provider first-delta latency;
- server coalescing delay;
- transport send lag;
- reconnect count;
- resume backlog size;
- snapshot reconciliation count;
- invalid event count;
- seq gap count;
- event queue depth;
- coalesced chunk ratio;
- dropped noncritical delta count if any;
- tool output bytes;
- long-run event count.

Correlate with `session_id`, `run_id`, `trace_id` where safe.

---

# 19. Security

- Auth on reconnect must be equivalent to initial connection.
- A cursor cannot be used to read a run/session the caller cannot access.
- Tool output/raw payload may contain secrets; existing redaction policy must continue to apply.
- Raw Inspector access must respect authorization.
- Do not write secret-bearing payloads to client telemetry.

---

# 20. Testing Requirements

## Unit

- event normalization per provider;
- reasoning block reducer;
- text block reducer;
- tool lifecycle reducer;
- idempotent duplicate handling;
- sequence gap handling;
- schema validation;
- visibility filtering.

## Integration

- provider reasoning → canonical reasoning events;
- provider no-reasoning → progress fallback;
- tool stdout/stderr streaming;
- reasoning → tool → reasoning ordering;
- reconnect after cursor;
- snapshot reconcile;
- interrupted provider preserves partial block.

## Load/soak

- long run;
- many deltas;
- large terminal output;
- reconnect storms bounded by sane retry/backoff;
- slow client does not stall Agent core loop.

---

# 21. Backend Implementation Ownership

Backend/runtime owns:

- provider normalization;
- visibility classification;
- canonical event envelope;
- monotonic sequence;
- durable event/block/snapshot persistence;
- reconnect/resume cursor support;
- tool stdout/stderr streaming where runner supports it;
- backpressure boundaries;
- server telemetry;
- migration/version compatibility.

Frontend owns presentation behavior but may not invent runtime facts that backend never emitted.

---

# 22. Backend AI Handoff Prompt

Use this if a separate backend AI works on the implementation:

> Read `01_AGENT_RUNTIME_STREAMING_UI_PRD_v2.md` and `02_RUNTIME_STREAMING_PROTOCOL_SPEC.md` completely. Audit the current backend/runtime before changing code: determine whether transport is WebSocket, SSE, or other; identify provider adapters, model streaming support, event schema, event persistence, run/session recovery, tool runner stdout/stderr behavior, and existing tests. Do not modify Agent decision semantics. First run implementation-level grill-me only for unresolved facts, then produce small tickets. Preserve existing transport if it is production-capable; otherwise write an ADR before migrating. AI SDK integration/migration is allowed if it measurably improves streaming/recovery without weakening the canonical Harness event model, Inspector, replay, or provider compatibility. Implement canonical reasoning/text/tool-output streaming, reconnect/resume, idempotency, persistence and telemetry in small reversible steps. Every ticket must include tests and migration/rollback notes where relevant.
