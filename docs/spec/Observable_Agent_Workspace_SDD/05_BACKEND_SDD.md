# Backend SDD — Observable Agent Workspace

> Implementation spec for the Backend AI.  
> Goal: make every visible runtime capability truthful, durable enough, and consumable through the shared contract.

---

# 1. First task: backend capability audit

Before coding, document:

- Session model;
- Turn model if any;
- Run/attempt model if any;
- event/log model;
- current SSE/WS flow;
- persistence and sequence ordering;
- retry system;
- tool runtime;
- cancellation/interrupt support;
- permission enforcement;
- checkpoint/recovery;
- artifacts;
- Git/change data;
- terminal capability;
- model configuration/metadata;
- token/cost/latency availability;
- context token calculation;
- search/history APIs.

Classify each requirement:

```text
SUPPORTED
PARTIAL
MISSING
NOT_APPLICABLE
```

Do not alter domain topology until this audit is complete.

---

# 2. Domain mapping

The UI needs stable normalized concepts, but backend may retain existing internal entities.

Create a mapping table:

```text
Product concept     Existing backend concept      Action
Session             ?                             keep/map/change
Turn                ?                             optional
Run                 ?                             keep/map/derived
RuntimeEvent         ?                             keep/introduce
Artifact             ?                             keep/normalize
Checkpoint           ?                             keep/add
```

If current Session model already captures Run semantics adequately, do not invent redundant tables just to match terminology.

---

# 3. Append-only runtime event log

User requires append-only runtime events.

Minimum properties:

- stable `event_id`;
- `session_id`;
- sequence/order;
- timestamp;
- type;
- data;
- optional run/trace linkage;
- durable/transient classification.

Important runtime actions should produce events at their natural boundaries.

Do not repeatedly overwrite one giant mutable run JSON as the only audit history.

A materialized summary can coexist for fast queries, but event history remains the trace source.

---

# 4. Event production boundaries

Emit events for meaningful lifecycle changes:

- run start/finish/failure/interrupt;
- LLM start/finish/failure;
- Tool start/finish/failure;
- permission request/resolution;
- retry;
- checkpoint;
- recovery;
- artifact creation;
- context compaction;
- assistant settled message.

High-frequency tokens/progress may remain transient streams rather than durable rows.

---

# 5. Streaming

Keep the current stable transport unless audit proves it inadequate.

### If SSE

- include event ids/sequence;
- support reconnect cursor/Last-Event-ID;
- replay missed durable events before following live stream;
- cancellation uses normal HTTP command endpoint.

### If WebSocket

- client reconnect includes last sequence;
- server replays missing durable events;
- then switches to follow/live mode.

Do not create separate semantic protocols for SSE and WS.

---

# 6. Reconnect/replay

Required correctness:

1. client records last durable sequence;
2. connection drops;
3. client reconnects;
4. backend sends missed durable events;
5. duplicate ids/sequences are not produced as distinct events;
6. transient chunks are reconciled by settled assistant/event history.

Test refresh mid-tool-call and mid-LLM-stream.

---

# 7. Assistant streaming

Support simultaneous:

- assistant text/token chunks;
- runtime events.

Do not serialize execution so Timeline updates appear only after the final answer.

Settled assistant message should be durable enough to restore Chat without durable storage of every token chunk.

---

# 8. Tool results and large payloads

Tool completion event should contain bounded preview/summary.

For large output:

- persist/store content through existing artifact/blob/log mechanism;
- return size + truncation + content/artifact id;
- expose lazy-fetch endpoint.

Do not push tens/hundreds of KB into every runtime event if not needed.

---

# 9. Permission system — required

The user explicitly requires permission mode in Composer.

Audit first.

## If permission enforcement already exists

Normalize it into the shared contract.

## If missing

Implement a backend-owned permission layer before claiming UI support.

At minimum:

- permission mode associated with session/run/user context;
- policy decision before protected tool action;
- `permission.requested` event;
- run enters waiting state;
- API/command to resolve;
- backend validates allowed decisions;
- runtime resumes/denies safely;
- `permission.resolved` event;
- decision audit trail.

Frontend is never the enforcement boundary.

---

# 10. Stop / interrupt — required

User must be able to stop an active run.

Audit tool/runtime cancellation semantics.

Implement the strongest safe behavior feasible:

- cancel generation;
- cancel/terminate cancellable tool;
- stop scheduling further steps;
- mark Run interrupted after current non-cancellable boundary.

Expose status transitions so UI can distinguish:

```text
Stop requested
Stopping
Interrupted
```

Avoid false immediate success when work continues in background.

---

# 11. Retry / resume

Backend exposes action availability.

## Retry

Prefer creating a related new attempt/run rather than mutating failure history.

## Resume

Use checkpoint only when runtime state is actually resumable.

If checkpoint is descriptive only, `can_resume=false`.

---

# 12. Checkpoints

If current system already persists phase state/checkpoints, expose metadata:

- checkpoint id;
- timestamp;
- run/session relation;
- resumable flag;
- step/label.

Do not expose internal serialized secrets/state blobs to UI.

---

# 13. Model catalog API

Frontend requires authoritative model options.

Source from existing provider/model configuration.

Return:

- id;
- display name;
- provider;
- default;
- availability;
- context window if known;
- tool/vision/reasoning support if known;
- optional speed tier.

Do not guess model metadata from name strings.

---

# 14. Context token estimate

When provider gives usage, prefer provider data.

When not available, backend may estimate with tokenizer/approximation.

Return explicit source:

```text
provider
backend_estimate
unknown
```

Frontend labels estimate accordingly.

---

# 15. Cost

Return real provider-reported or backend-calculated cost only if pricing/input is authoritative enough.

Include:

- value;
- currency;
- source.

If not available, omit.

Do not return placeholder `$0.00`.

---

# 16. Artifacts

Implement/normalize unified Artifact model.

Capabilities can create typed artifacts without frontend-specific schemas.

Required operations:

- list artifacts for Session/Run;
- fetch metadata;
- fetch/open content or URI;
- preview when feasible;
- size/mime type.

---

# 17. Capability manifest

Expose enough information for UI to determine:

- Changes visible?
- Terminal visible?
- Artifacts visible?
- permission modes?
- stop/retry/resume?
- Git branch selector?

Avoid hardcoding capability assumptions in frontend.

---

# 18. Coding changes

If Coding capability exists, backend/API must expose real changes/diffs.

Prefer integrating with existing workspace/git layer.

Do not ask frontend to parse terminal output to infer changed files.

---

# 19. Terminal

Expose only if real terminal/session backend exists.

If no backend terminal exists for a session, capability manifest must say false so frontend hides the tab.

---

# 20. Search

Desired eventual search:

- sessions;
- runtime events;
- artifacts;
- tool results/file content when indexed.

Audit current search. Implement the highest-value missing scope only after core runtime contract is stable.

---

# 21. Redaction and safety

Runtime events can contain secrets.

Implement server-side redaction for common sensitive values before sending events to normal UI:

- API keys;
- auth headers;
- secret environment values;
- known credential fields.

Raw debugging access, if ever added, still requires explicit policy.

---

# 22. APIs — conceptual, adapt to current routing

Do not force these exact paths if the project has established conventions.

Conceptual operations:

```text
GET  sessions
GET  session detail/history
GET  session runtime events + follow/reconnect
POST session message / start run
POST run stop
POST permission resolve
POST run retry
POST run resume
GET  models
GET  capabilities
GET  artifacts
GET  artifact content/preview
GET  changes/diff
GET  search
```

The contract semantics matter more than path spelling.

---

# 23. Observability alignment

The runtime event stream should align with existing JSONL/Langfuse/trace concepts where possible, but the product UI contract must not be tightly coupled to a vendor-specific trace SDK.

Use shared ids where helpful:

- trace_id;
- session_id;
- run_id;
- tool_call_id.

---

# 24. Backend tests

Required tests:

- event order/sequence;
- append-only persistence;
- reconnect replay;
- duplicate prevention;
- LLM + event concurrent stream;
- tool large result truncation/lazy fetch;
- permission requested → resolve → resume/deny;
- stop/interrupt;
- retry relation;
- checkpoint resume availability;
- model metadata truthfulness;
- context estimate source;
- capability manifest;
- secret redaction.

---

# 25. Backend completion rule

Backend is not complete merely when endpoints return 200.

It is complete when the Frontend AI can render a live, reload-safe Timeline/Inspector with no runtime inference and all interactive controls correspond to real backend actions.
