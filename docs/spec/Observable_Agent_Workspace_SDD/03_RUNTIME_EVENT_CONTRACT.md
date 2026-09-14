# Shared Runtime Event Contract

> **Hard frontend/backend boundary.**  
> Any breaking change here requires synchronized frontend/backend updates.

---

# 1. Purpose

Create one normalized runtime language for:

- Chat projection;
- Timeline;
- Inspector;
- permission surfaces;
- Changes/Artifacts;
- reconnect/replay;
- stop/retry/resume.

Transport can be SSE or WebSocket. The UI must not depend directly on transport-specific framing.

---

# 2. Domain audit first

The current backend may or may not already contain:

- Session;
- Turn;
- Run;
- event log;
- checkpoint;
- tool execution state.

Do **not** force a schema migration merely to produce the exact nouns below.

The Backend AI must map existing domain entities to this normalized external contract and document any mismatch.

The user-facing UI keeps **Session** as the primary navigation concept. Run remains primarily a runtime/Inspector concept.

---

# 3. Event envelope

Recommended normalized shape:

```ts
interface RuntimeEvent<T = unknown> {
  schema_version: string
  event_id: string
  session_id: string
  turn_id?: string | null
  run_id?: string | null
  sequence: number
  timestamp: string
  type: RuntimeEventType
  status?: RuntimeStatus
  trace_id?: string | null
  parent_event_id?: string | null
  capability?: string | null
  durability: "durable" | "transient"
  visibility?: "default" | "detailed" | "raw"
  data: T
}
```

## Requirements

- `event_id` globally unique enough for deduplication.
- `sequence` monotonic within Session stream (or another documented ordering scope).
- timestamp ISO-8601.
- durable events are replayable after reconnect.
- transient events must not be required to reconstruct settled history.

---

# 4. Canonical event families

Exact naming may adapt to existing backend conventions, but semantic coverage should include:

```text
session.created
session.updated

run.started
run.status
run.completed
run.failed
run.interrupted

assistant.chunk            (transient unless current architecture durably stores chunks)
assistant.message.settled  (durable)

reasoning.summary          (only when provider/backend safely exposes it)

llm.started
llm.completed
llm.failed

tool.started
tool.progress              (optional/transient)
tool.completed
tool.failed

permission.requested
permission.resolved

retry.scheduled
retry.started

checkpoint.created
recovery.started
recovery.completed

artifact.created
artifact.updated

change.created / change.updated (if coding capability uses explicit change events)

context.compacted
```

Do not create event types that the runtime cannot truthfully emit.

---

# 5. Run state machine

Normalized UI states:

```text
IDLE
  ↓
RUNNING
  ├─ THINKING
  ├─ CALLING_MODEL
  ├─ RUNNING_TOOL
  ├─ WAITING_APPROVAL
  ├─ RETRYING
  ├─ CHECKPOINTING
  └─ RECOVERING
  ↓
COMPLETED | FAILED | INTERRUPTED
```

Not every backend needs separate persisted state rows for every visual state; they can be event-derived.

The backend remains authoritative for terminal states and permission/cancellation state.

---

# 6. LLM Call payload

Recommended fields when known:

```ts
interface LLMCompletedData {
  provider?: string
  model: string
  input_tokens?: number
  output_tokens?: number
  cached_tokens?: number
  latency_ms?: number
  cost?: {
    value: number
    currency: string
    source: "provider" | "backend"
  }
  finish_reason?: string
}
```

Rules:

- omit unknown fields; do not send zero as “unknown”;
- frontend displays unavailable state;
- monetary cost must include source and currency when provided;
- frontend must not fabricate cost.

---

# 7. Reasoning payload

Only safe provider/backend-exposed summary is allowed.

```ts
interface ReasoningSummaryData {
  summary: string
  provider?: string
  redacted?: boolean
}
```

If unavailable, emit status only (`Thinking`) rather than synthetic reasoning prose.

---

# 8. Tool Call payload

Recommended:

```ts
interface ToolStartedData {
  tool_call_id: string
  tool_name: string
  arguments: unknown
  summary?: string
  permission_class?: string
}
```

Completion:

```ts
interface ToolCompletedData {
  tool_call_id: string
  tool_name: string
  duration_ms?: number
  result_preview?: unknown
  result_summary?: string
  result_size_bytes?: number
  artifact_id?: string
  truncated?: boolean
}
```

Failure:

```ts
interface ToolFailedData {
  tool_call_id: string
  tool_name: string
  duration_ms?: number
  error_code?: string
  message: string
  retryable?: boolean
}
```

Large results should be referenced/lazy-loaded instead of embedded in full.

---

# 9. Permission contract

The frontend requires a truthful permission workflow.

Recommended request:

```ts
interface PermissionRequestedData {
  permission_id: string
  action_type: string
  title: string
  description?: string
  risk?: "low" | "medium" | "high"
  tool_call_id?: string
  arguments_preview?: unknown
  allowed_decisions: PermissionDecision[]
}

type PermissionDecision =
  | "deny"
  | "approve_once"
  | "approve_session"
  | "approve_policy"
```

Only include decisions the backend actually supports.

Resolution:

```ts
interface PermissionResolvedData {
  permission_id: string
  decision: PermissionDecision
  resolved_at: string
}
```

Backend must enforce the result; frontend control is not security enforcement.

---

# 10. Permission modes

Composer may expose permission mode if backend supports it.

Normalized conceptual examples:

```text
ask
edit_auto
full_access
```

The exact set is backend policy-dependent.

Required endpoint/command should return the current valid modes and their descriptions. The frontend should not hardcode modes that backend cannot enforce.

---

# 11. Stop / cancellation

User requires a first-class Stop control.

Backend must expose a cancellation command with semantics documented as one of:

- cooperative cancel;
- abort current tool + run;
- mark run interrupted after safe boundary.

Recommended response/event flow:

```text
client: stop(run_id)
backend: accept/reject
runtime: run.status(interrupting)
runtime: run.interrupted
```

If a tool cannot be interrupted immediately, UI should show `Stopping…` rather than falsely claim it is stopped.

---

# 12. Retry and resume

Retry/resume support is capability/backend dependent.

Contract should expose availability:

```ts
interface RunActions {
  can_stop: boolean
  can_retry: boolean
  can_resume: boolean
  latest_checkpoint_id?: string
}
```

### Retry

Can create a new Run/attempt while retaining relation to previous failure.

### Resume

When checkpoint exists, backend should define the exact semantic boundary. UI must not claim deterministic resume if runtime cannot provide it.

---

# 13. Checkpoint

Recommended:

```ts
interface CheckpointCreatedData {
  checkpoint_id: string
  resumable: boolean
  label?: string
  step?: number
  created_at: string
}
```

Do not send opaque internal state blobs to the frontend unless explicitly needed.

---

# 14. Artifact model

Unified artifact contract:

```ts
interface Artifact {
  artifact_id: string
  session_id: string
  run_id?: string
  type: string
  name: string
  mime_type?: string
  size_bytes?: number
  uri?: string
  preview_uri?: string
  created_at: string
  created_by?: {
    kind: "agent" | "tool" | "user" | "system"
    id?: string
  }
  metadata?: Record<string, unknown>
}
```

Full content may be fetched separately.

---

# 15. Change model

When Coding capability exists, Changes should use real workspace/VCS information.

Recommended normalized shape:

```ts
interface FileChange {
  path: string
  status: "added" | "modified" | "deleted" | "renamed"
  old_path?: string
  additions?: number
  deletions?: number
  diff_available: boolean
  related_event_ids?: string[]
  artifact_id?: string
}
```

Diff data should lazy-load for large files.

---

# 16. Model metadata contract

Frontend model selector requires backend-authoritative metadata.

Recommended:

```ts
interface ModelOption {
  id: string
  display_name: string
  provider: string
  is_default?: boolean
  is_available: boolean
  context_window?: number
  speed_tier?: "fast" | "balanced" | "quality"
  supports_reasoning_summary?: boolean
  supports_tools?: boolean
  supports_vision?: boolean
  metadata_source?: string
}
```

Unknown capabilities should be omitted or null, not guessed.

---

# 17. Capability manifest

To support capability-aware tabs:

```ts
interface CapabilityManifest {
  id: string
  display_name: string
  surfaces: {
    chat: boolean
    timeline: boolean
    changes: boolean
    terminal: boolean
    artifacts: boolean
  }
  actions?: {
    permissions?: boolean
    stop?: boolean
    retry?: boolean
    resume?: boolean
  }
}
```

This may be derived server-side or client-side from backend capabilities, but there must be one authoritative mapping.

---

# 18. Context usage contract

```ts
interface ContextUsage {
  used_tokens?: number
  max_tokens?: number
  percentage?: number
  source: "provider" | "backend_estimate" | "unknown"
  compacted?: boolean
}
```

If `source = backend_estimate`, UI must label it Estimated.

---

# 19. Streaming and reconnect

## 19.1 Transport-independent semantics

Both SSE and WebSocket must support:

- initial baseline/history;
- live follow;
- monotonically orderable events;
- dedupe by event id/sequence;
- reconnect from known cursor/sequence;
- cancellation command through an appropriate request channel.

## 19.2 SSE recommendation when SSE already exists

Use `Last-Event-ID` or equivalent `after_sequence` cursor.

Example:

```text
GET /sessions/{id}/events?after_sequence=184
```

or server-sent event ID:

```text
id: 185
event: runtime
data: {...}
```

## 19.3 WebSocket recommendation when already stable

On reconnect, client sends last known sequence/cursor and receives missing durable events before following live updates.

Do not migrate stable transport solely because another product uses a different protocol.

---

# 20. Projection rules

One event store can produce different UI projections.

### Chat projection

Consumes:

- user messages;
- assistant live chunks;
- settled assistant messages;
- minimal run status.

### Timeline projection

Consumes runtime events at chosen density.

### Inspector projection

Consumes selected Run/event/tool/artifact plus summaries.

Do not duplicate separate authoritative states for the same runtime fact.

---

# 21. Search contract

Desired future search domains:

- Sessions;
- Runtime Events;
- Artifacts;
- Tool Results/file content when indexed.

Backend audit should determine what exists now. Frontend Command Palette may mix local command search with backend search results.

---

# 22. Versioning

Runtime event payloads require version discipline.

Minimum:

- `schema_version`;
- backward-compatible additive fields preferred;
- breaking event name/payload change requires coordinated frontend/backend change;
- do not silently repurpose an existing field.

---

# 23. Security and data sensitivity

Inspector/Timeline may expose tool arguments/results containing sensitive values.

Backend should support redaction policy for:

- credentials/secrets;
- authorization headers;
- known sensitive config values.

Frontend must not assume all raw event data is safe to display.

Permission UI is not a substitute for backend authorization/sandboxing.

---

# 24. Contract acceptance

Contract is complete when:

- current backend entities are mapped;
- event ordering/durability is documented;
- reconnect tested;
- stop behavior is real;
- permission enforcement is real;
- large tool results can lazy-load;
- model metadata is authoritative;
- capability tab availability is truthful;
- frontend can build Chat + Timeline + Inspector from events without inferring runtime behavior from prose.


## Phase 5 session controls (Class B amend) — runtime consumed

`POST /api/sessions` accepts the following session-level control fields. All three
are now **runtime consumed** (RUNTIME follow-up batches complete):

- `reasoning_effort`: `minimal | standard | deep | null` — injected via
  `create_chat_model` into the model's native `reasoning_effort` field (ADR-0018 D7).
- `agent_profile`: `main | coding | research_review | null` — injects `system_prompt`
  via `ContextBuilder` + narrows tool registry via `registry.filtered(spec.tool_scope)`
  (ADR-0020a).
- `context_providers`: string array or `null` — selects a subset of already-wired
  `ContextProvider` instances by their `name` attribute (`memory`, `skills`).
  `null` = all wired providers (default); `[]` = explicitly zero; unknown names
  fail-open silently. `/api/context-providers` dynamically projects the wired set
  (ADR-0020b).

All three are validated at the API boundary (closed enumerations 422 for
`reasoning_effort` / `agent_profile`; shape-only validation for `context_providers`).
Clients can rely on the selected values being active at runtime.
