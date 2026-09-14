# Research: DeepSeek Harness (`dsh`) — Web / Multi-turn Session / Streaming / Tool-approval / Replay Architecture

> Primary-source research extracted directly from the `deepseek-ai/deepseek-harness`
> repository. Every fact is cited as `file:line` against the cloned checkout
> (see Section 2). Where something could not be verified, that is stated
> explicitly. This document is a benchmark input for our Web multi-turn chat
> PRD; it is **descriptive**, not normative for `dsh`.

---

## 1. Verdict — is the repo really an agent harness?

**Yes. `deepseek-harness` (`dsh`) is a genuine, production-shaped agent
harness with a first-class Web UI.** It is not a stub, not a model demo, and
not a single-file script.

- `README.md:5-7` — “DeepSeek Harness (`dsh`) is an open-source agent harness
  developed by DeepSeek AI … built on an everything-is-a-plugin architecture
  and powered by Cordis.”
- `README.md:23-27` — ships a Web UI at `http://127.0.0.1:3080` via
  `npx @deepseek-ai/dsh web`.
- Repo layout backs the claim: `apps/web` (browser app), `apps/cli`,
  ~70 Cordis plugin packages under `packages/` (e.g. `core/session`,
  `core/agent`, `api/session-controller`, `api/gateway`, `client/connection`,
  `compaction/*`, `interaction/user-approval`, `interaction/permission-presets`,
  `host/webserver`), plus full subsystem docs under `docs/subsystems/`.
- It is explicitly a **developer preview** with breaking changes expected
  (`README.md:13`).

This is therefore a legitimate primary source for an enterprise Web agent PRD,
and worth borrowing from. Note the scope boundary: `dsh` is **single-tenant by
design** (see §9); multi-tenant concerns must be designed by us, not copied.

---

## 2. Primary-source availability

- **Cloned at**: `C:\Users\王浩宇\AppData\Local\Temp\deepseek-harness`
  (`git clone --depth 1 https://github.com/deepseek-ai/deepseek-harness`,
  full tree, ~9080 files).
- **Default branch HEAD at clone time** (2026-09-07): docs are dated
  2026-08 / 2026-09 and reference decision notes up to `2026-08-31`.
- All citations below use paths relative to the clone root, with line numbers
  from the checked-out files. The repo is MIT-licensed (`LICENSE`,
  `README.md:60-63`).

---

## 3. Conversation vs Run model (multi-turn session semantics)

A `Session` is an **append-only event log** and is the unit of a multi-turn
conversation. There is no separate “run” object persisted alongside it.

- `docs/subsystems/session.md:5` — “A `Session` is an **append-only log** of
  typed `SessionEvent`s — the single source of truth for an agent's whole
  interaction history. The LLM message history is *derived* from the log,
  never stored separately; replay is re-derivation from the same events.”
- The model-visible surface is *derived*, not stored:
  `Session.deriveMessages()` projects `Message[]` from the log
  (`docs/subsystems/session.md:557-571`).
- A **turn** is the live execution unit; a **step** is one model request plus
  its tool calls. Both are events in the same log:
  `docs/architecture.md:76-77` — “A **step** is one model request plus the
  tools it calls. A **turn** is zero or more steps.”
- Turn lifecycle events: `turn/start`, `turn/end`, `step/start`, `step/end`,
  `user/message`, `assistant/message`, `assistant/attempt`, `tool/call`,
  `tool/result` — all durable (`docs/architecture.md:97`).
- One session **persists across many user messages**. Sending a new message
  to an existing conversation does **not** create a new session; it appends a
  `user/message` event inside the existing session and opens a new turn
  (§5, §8).

> **Borrowable pattern**: a single event-sourced log per conversation; the
> message array is a pure projection (`deriveMessages()`). No duplicate
> “messages table” drifting against an “events table”.

---

## 4. HTTP API surface for sending a message to an existing conversation

### 4.1 Transport shape — `/api/<namespace>/<method>` (Typert RPC)

Remote methods are exposed by `@Remote`-decorated service methods and dispatched
through a generated Gateway. Unary calls are JSON over HTTP POST.

- `docs/api-gateway.md:121-123` — “Remote calls use the Connection's `/api`
  route. The Client Remote calls
  `connection.rpc.call('/api', '<namespace>/<method>', { args }, signal)`; the
  HTTP carrier maps this to `POST /api/<namespace>/<method>`, with a payload
  containing only a named `args` object.”
- Trust boundary: “The Connection performs the unified trust check for `/api`
  before the HTTP bridge …” (`docs/api-gateway.md:123`).
- Routes without a strict descriptor return 404
  (`docs/api-gateway.md:123`).

The **Session Controller** service (`packages/api/session-controller`, Host
namespace `session`) is the primary conversation API surface
(`docs/subsystems/session.md:678-815`).

### 4.2 Sending a message — `POST /api/session/prompt`

Request schema (`packages/api/session-controller/src/types.ts:305-313`):

```ts
interface SessionPromptRequest {
  readonly requestId: SessionRequestId   // client-minted idempotency id
  readonly sessionId: SessionId
  readonly mode: 'queue' | 'steer'       // queue = next turn; steer = next step
  readonly content: readonly PromptContentPart[]
  readonly clientTimeZone?: string       // optional IANA zone
}
```

Response: `SessionPromptValue = { accepted: true }`
(`types.ts:316-318`). The RPC returns only **acknowledgement that the prompt
entered the inbox** — it does NOT stream the assistant reply. The reply is
observed through a separate stream (§6).

Handler behaviour (`packages/api/session-controller/src/commands.ts:293-360`):

- Idempotency: `if (hasPromptRequest(agent, request.requestId)) return
  { accepted: true }` (`commands.ts:305`).
- Resolves (or cold-resumes) the Agent for the session
  (`commands.ts:304`).
- Validates that the routed provider has an adapter; else
  `RemoteError('session/model-unavailable', …)` (`commands.ts:307-313`).
- Admits attachments, builds a `UserMessage`, then dispatches by mode:
  `if (request.mode === 'steer') agent.steer(message) else
  agent.followup(message)` (`commands.ts:347-348`).
- Image admission is serialized per agent to avoid races
  (`commands.ts:359`, `serializeImageAdmission`).
- Failures map to typed `RemoteError` codes:
  `session/not-found`, `session/agent-busy`, `session/attachment-invalid`,
  `session/invalid-time-zone`, `session/model-unavailable`.

Other relevant endpoints on the same namespace
(`docs/subsystems/session.md:704-815`):

| Method | Path | Purpose |
|---|---|---|
| `create` | `POST /api/session/create` | Create or idempotently adopt a Session |
| `list` | `POST /api/session/list` | List visible sessions (no Agent activation) |
| `search` | `POST /api/session/search` | Content search over sessions |
| `inspect` | `POST /api/session/inspect` | Cold inspection of one session |
| `selectModel` | `POST /api/session/selectModel` | Switch the session's model mid-conversation |
| `rename` | `POST /api/session/rename` | Rename |
| `fork` | `POST /api/session/fork` | Fork a session at a turn boundary |
| `prompt` | `POST /api/session/prompt` | Send a message (queue or steer) |
| `updateQueue` | `POST /api/session/updateQueue` | Edit/remove/promote a still-pending inbox item |
| `cancel` | `POST /api/session/cancel` | Cancel the active turn, keep the inbox |
| `page` | `POST /api/session/page` | Read one cold backwards history page |
| `attachment` | `POST /api/session/attachment` | Read a referenced image |
| `follow` | stream (see §6) | Live follow of one session |
| `control` | stream (see §6) | Live host-wide control state |
| `modelCatalog` | `POST /api/session/modelCatalog` | List routable models |

### 4.3 Auth / tenant model

**Single-tenant, loopback-oriented.** `dsh` is a local-first desktop-style
agent; there is no user/tenant identity in the request schema above.

- `SessionPromptRequest` carries `sessionId` only — no `userId`, no org id
  (`types.ts:305-313`).
- Browser auth is an **HMAC-signed cookie keyed by Host authority**
  (`packages/client/connection/src/browser-auth.ts:106-107`):
  `cookieName = 'dsh-auth-' + base64url(sha256(authority))`.
- Loopback-only trust classification lives in
  `packages/client/connection/src/loopback-hostname.ts:8-13` (treats
  `localhost`, `[::1]`, and `127/8` as loopback).
- A process-launch token bootstrap exists for first browser open
  (`browser-auth.ts:243-261`).

> **Implication for our PRD**: `dsh` deliberately punts multi-tenancy.
> Tenant / RBAC / per-user authorization must be added by us at the Gateway
> trust boundary (`docs/api-gateway.md:91,123` lists “trust boundary” as the
> Connection's responsibility — that is the seam where a tenant check would
> go).

---

## 5. Streaming transport and reconnect/replay

`dsh` uses **two transports in parallel**, both reachable through the same
Host:

1. **HTTP POST + JSON for unary Remote calls** (`/api/...`), served by the
   `node:http` ↔ WHATWG fetch bridge (`packages/client/connection/src/http-bridge.ts`).
2. **WebSocket for streaming Remotes**, on a single fixed route
   `/api/remote.mux` (`packages/api/gateway/src/stream-protocol.ts:5-6`,
   `REMOTE_STREAM_MUX_PATH = '/api/remote.mux'`).

There is no SSE. There is no per-stream HTTP route. All `@Remote({ mode:
'stream' })` methods (notably `session/follow` and `session/control`) are
multiplexed over the single WebSocket, with the Gateway issuing logical
stream ids.

### 5.1 WebSocket mux protocol

- Server entry: `packages/api/gateway/src/stream-server.ts:1,5,26,48-58` —
  uses `ws`’s `WebSocketServer({ noServer: true })`, upgrades trusted
  requests, and runs a Ping/Pong heartbeat.
- Heartbeat default: `2000ms`, configurable via
  `websocketHeartbeatIntervalMs`; sockets exceeding
  `MAX_MISSED_HEARTBEATS` are `terminate()`d
  (`packages/api/gateway/src/index.ts:120-125`,
  `stream-server.ts:71-86`).
- Client → Host logical-stream messages (`stream-protocol.ts:243-251`):
  - `{ type: 'open', streamId, endpoint, payload }` — open a stream to a
    named Remote endpoint (e.g. `session/follow`).
  - `{ type: 'cancel', streamId }` — cancel one logical stream.
- Host → Client frames (`stream-protocol.ts:260-263`):
  - `{ type: 'item', streamId, value? }` — one streamed value.
  - `{ type: 'error', streamId, error: { code, message, details } }`.
  - `{ type: 'end', streamId }`.
- Frames are JSON text and strictly validated at the boundary
  (`stream-protocol.ts:270-313`).

### 5.2 The conversation stream — `session/follow`

`@Remote({ mode: 'stream' }) follow(request, signal)` returns an
`AsyncIterable<SessionFollowFrame>`
(`docs/subsystems/session.md:800-815`;
`packages/api/session-controller/src/index.ts:382-385`;
`packages/api/session-controller/src/history.ts:119`).

Request (`types.ts:433-439`):

```ts
interface SessionFollowRequest {
  readonly address: SessionAddress                  // session or subagent
  readonly maxMessages?: number                     // opening page budget
  readonly assistantStream?: true                   // opt in to live chunk frames
}
```

Note: **the request does not carry a client-held cursor.** The server always
emits an opening `snapshot` first (`history.ts:191-200`), then continues
gap-free from there.

Frame union (`types.ts:500-511`):

```ts
type SessionFollowFrame =
  | { type: 'snapshot', header, cursor, records, hasMore,
      projections, assistantStream? }      // exactly one opening
  | SessionEventEntry                       // { type:'event', event }
  | { type: 'assistant-stream', frame }     // live token chunks (opt-in)
```

### 5.3 Reconnect / replay semantics

The reconnect contract is implicit but clear from source:

- A new `follow` call **always opens a fresh stream** whose first frame is a
  complete `snapshot` of the current log prefix and current projections
  (`history.ts:180-200`). There is no “resume from cursor N” parameter —
  the snapshot is authoritative.
- The snapshot includes a live **assistant-stream baseline** when
  `assistantStream: true` was requested, so an in-flight token stream can be
  rejoined: `SessionAssistantStreamBaseline { revision, activeAttempt? }`
  where `activeAttempt` carries `nextIndex` and the compact stream so far
  (`types.ts:441-458`).
- After the snapshot, durable `session/event` notifications are pushed
  gap-free (`history.ts:145-149`), and, if opted in, live
  `agent/assistant-stream` frames are forwarded with an ordinal
  (`history.ts:163-173`).
- The opening observation and the watermark are deliberately synchronous to
  avoid a lost-event race: “The accumulator snapshot and this watermark are
  synchronous” (`history.ts:186-190`).
- Stream-side cancellation uses the WebSocket `cancel` message and the
  carrier-owned `AbortSignal` (`history.ts:174-175`).

> **Borrowable pattern**: a single multiplexed WS carrying many logical
> streams; each conversation opens with a server-authoritative snapshot
> (event log + projection + in-flight assistant-stream baseline) and then
> continues gap-free. Reconnect = open a new stream; no client cursor to
> corrupt.

### 5.4 Host-wide control — `session/control`

A second stream, `control(signal)`, pushes one `baseline` then replacement
frames for the entire host: per-session queues, jobs, projections
(`types.ts:537-557`). Useful as a reference for a sidebar/listings live model.

---

## 6. Tool calls and tool approval (UI surfacing)

### 6.1 Tool calls are surfaced as durable events

- `tool/call` and `tool/result` are durable `SessionEvent`s carrying
  `callId`, `name`, raw `arguments` JSON, and a model-facing result
  (`docs/subsystems/session.md:82-104`). The `callId` pairs the call with
  its result.
- The pipeline is `tools/pre-execute → tools/execute → tools/post-execute`,
  with `tool/result` events appended after each call
  (`docs/architecture.md:90`; full pipeline in
  `docs/tool-execution-pipeline.md`).

### 6.2 Approval model — `ctx.approval`

Approval is a **per-call, fail-closed, one-shot grant**. There is **no
per-tool auto-approve whitelist** in core.

- Outcome vocabulary (`docs/subsystems/approval.md:21-29`):

  ```ts
  type ApprovalOutcome = 'allowed-once' | 'rejected' | 'cancelled' | 'unavailable'
  ```

  Callers **fail closed** on `rejected`, `cancelled`, or `unavailable`.
  “A missing, non-conforming answerer becomes `unavailable` rather than
  opening the gate.”
- Per-call request (`docs/subsystems/approval.md:55-82`):

  ```ts
  interface ApprovalRequest extends ApprovalRequestEvent {
    readonly agent: Agent
    readonly toolName: string
    readonly callId?: ToolCallId   // links to the already-streamed tool call
    readonly reason?: string
    readonly signal?: AbortSignal
  }
  ```

  Tool arguments are **deliberately omitted** — the UI attaches the prompt
  to the already-streamed call via `callId` instead of duplicating args
  (`approval.md:52-54`).
- Dispatch is an `approval/request` **waterfall** over answerers; the first
  answerer to return an outcome claims the decision; others call `next()`
  (`approval.md:84-88`, `approval.md:151-165`).
- Audit pair: each ask appends `approval/asked`, then `approval/decided` —
  both log-only, NOT in the model transcript (`approval.md:11,86-88`).
  Requires an open turn (`approval.md:117-119`).
- UI answerers are scoped: “a UI answerer only answers for agents it owns”
  (`approval.md:67-69`). This is the inline-approval channel.

### 6.3 Per-session policy — only `ask` or `never`

There are exactly two session-level policies
(`docs/subsystems/approval.md:32-47`):

```ts
type ApprovalPolicy = 'ask'   // default — delegate to answerers (fail-closed if none)
                    | 'never' // deterministically reject every ask (headless/CI)
```

`setPolicy(agent, policy)` is the single write path and is itself logged as
an `approval/policy` event so it reconstructs on replay
(`approval.md:32-49`).

### 6.4 Permissions presets (the user-facing knob)

`dsh-permission-presets` bundles the **sandbox mode** and the **approval
policy** into named user-facing presets
(`packages/interaction/permission-presets/README.md:12`):

- Default table: `workspace-write` (workspace-write sandbox + `ask`) and
  `danger-full-access` (danger-full-access + `never`).
- A knob combination matching no preset reads back as derived `custom`
  (displayable, not selectable).

> **Borrowable pattern**: approval is fail-closed by construction; a UI
> answerer attaches the prompt to the streamed tool call via `callId` (no
> arg duplication); the only user-level toggles are `ask` vs `never`,
> packaged with sandbox mode into presets. If our PRD wants a richer
> auto-approve scope (per-tool, per-resource), that is **our extension**, not
> something `dsh` provides — and we should be explicit about why we are
> widening the surface.

---

## 7. Context management and compaction

Compaction is an **optional capability seam**, not part of the agent loop
(`docs/subsystems/compaction.md:5`).

- Service: `ctx.compaction` (`dsh-compaction`); default backend
  `dsh-compaction-basic`.
- Compaction produces three log-only events (`compaction/start`,
  `compaction/summary`, `compaction/end`) and **one** surface mutation:
  a `user/message` with `surfaceOp: { op: 'replace', start, end }` that
  shadows the compacted range (`compaction.md:9-22`).
- The surface itself (`SessionSurface`) supports `'append'` and
  `{ op: 'replace', start, end }` as first-class operations
  (`docs/subsystems/session.md:286-306`). Replacement ranges must reference
  existing surface nodes and must cite every shadowed seq via
  `sourceEventSeqs`.
- Triggers: `pressure` (pre-step) and `context-overflow` (post-failure).
  Failed requests recover through `agent/request-error`; a retry only fires
  if the surface replacement generation actually advanced
  (`compaction.md:86`; `docs/agent-lifecycle.md:78-80`).
- Optional `ctx.toolResultPruner` runs before summarization to drop tool
  output without rewriting the whole turn (`compaction.md:86`).
- Region boundaries preserve **tool-call/result pairing** but not whole
  turns, so early closed steps of an oversized turn can compact
  (`compaction.md:88`).
- Reconstructability invariant: “Anything that reaches a model request must
  be reconstructable from the log” (`docs/architecture.md:112`). Compaction
  preserves this — the compacted range is shadowed, not deleted.

> **Borrowable pattern**: model context is a projection (`deriveMessages`)
  over a log whose surface supports `replace`; compaction is one
  capability that uses `replace`. Token budgets and pruning are a separate,
  swappable seam (`ctx.tokenMeter`, `ctx.toolResultPruner`).

---

## 8. Session fork / branch

Yes — `dsh` supports explicit forking at a turn boundary.

- `SessionStore.fork(source, boundary?, childSessionId?)` — clones a stable
  prefix of a live source into a new live child session
  (`docs/subsystems/session.md:587-591`, catalog signature at
  `session.md:937-951`).
- The selected prefix **must end outside an open turn** (it can end at a
  previous `turn/end` or a later standalone log-only event); the API
  rejects a prefix ending inside an open turn rather than clipping silently
  (`session.md:591`).
- The child session carries `parentSession`, `isSeeded: true`, the exact
  `inheritedEventCount`, and inherited `cwd` (`session.md:589`).
- The fork boundary is recorded durably as a `session/end-seed` event
  carrying `{ inherited: true }` (`session.md:123-143`,
  `session.md:638-647`).
- Remote surface: `POST /api/session/fork`
  (`types.ts:294-303`,
  `docs/subsystems/session.md:760-762`).

> **Borrowable pattern**: fork = clone a turn-stable prefix + durable
> lineage marker. Explicit boundary avoids silently clipping an in-flight
> turn.

---

## 9. Model switching mid-conversation

Yes.

- `POST /api/session/selectModel`
  (`docs/subsystems/session.md:723-726`):
  ```ts
  interface SessionSelectModelRequest extends ModelSelection {
    readonly sessionId: SessionId
  }
  ```
  (`types.ts:272-275`).
- Implementation resumes the session explicitly before installing the
  selection (`commands.ts:124`, handler named `selectModel`).
- Model choice becomes durable through the **request/header** event:
  the full request envelope (call config + system prompt + tool schemas)
  is logged session state, so “every conversation request is a pure
  function of the log” (`docs/subsystems/session.md:148-170`).
  `foldRequestHeader(events)` reconstructs the active header by selecting
  the latest snapshot (`session.md:152`).
- A mid-conversation model change appends a `request/header` with reason
  `'change'` (or `'series'` if it also begins a new message series)
  (`session.md:152`, `docs/architecture.md:101`).
- Host-side routability: `session/modelCatalog` lists routable providers,
  the deployment default, and isolated provider failures
  (`session.md:664`; `docs/subsystems/session.md:728-732`).

> **Borrowable pattern**: model selection is part of the **request envelope**
> that is itself logged, so switching models mid-conversation is replayable
> and audit-trailable, not a side-channel setting.

---

## 10. Multi-tenant / auth / permission boundaries

As noted in §4.3, `dsh` is **single-tenant by construction**. Verbatim
evidence:

- `SessionPromptRequest` (`types.ts:305-313`) carries only `sessionId` — no
  user/tenant.
- Browser auth is a host-authority-bound HMAC cookie
  (`browser-auth.ts:106-107, 285-296`); the cookie payload is
  `{ version, authority, issuedAt, expiresAt }` signed with a stored secret
  (`browser-auth.ts:25-36`). There is no per-user identity inside the
  cookie.
- Loopback trust is the default stance (`loopback-hostname.ts:8-13`).
- The **trust boundary** is owned by the Connection
  (`docs/api-gateway.md:91, 123`); that is the seam where a tenant
  authorization layer would attach.

What `dsh` *does* provide that is reusable in a multi-tenant product:

- A single unified trust check before the HTTP bridge
  (`docs/api-gateway.md:91, 123`).
- Typed `RemoteError` codes that propagate across the wire unchanged
  (`docs/api-gateway.md:127`) — e.g. `session/not-found`,
  `session/agent-busy`, `gateway/lookup-unavailable`,
  `gateway/bad-request`. A tenant-denial code would slot in here.
- Workspace scoping: sessions can attach to a `Workspace`
  (`commands.ts:84-91`), which gives a structural unit that maps naturally
  to a tenant/project boundary.

> **Implication**: do not borrow `dsh`’s auth as our auth. Borrow its
> *seam* (one trust check at the Connection, typed errors that cross the
> wire unchanged) and put our own tenant/RBAC enforcement there.

---

## 11. Concurrency — what happens when a user sends while a run is active

`dsh` **does not reject, queue passively, or steer automatically — it lets
the caller choose** between two first-class delivery modes, both of which
land in a unified **inbox** owned by the agent.

### 11.1 The inbox — two ordered pending lists

The inbox is “two ordered pending-message lists the agent owns as a durable
projection” (`docs/subsystems/core.md:211`):

- `next-turn` — wakes a new turn after the current one ends.
- `next-step` — injects into the current turn’s next step (steering /
  continuation).

Mutations (`append`, `prepend`, `replace`, `remove`, `clear`, `splice`,
`claim`) are durable `agent/inbox/spliced` events
(`docs/subsystems/core.md:218`).

### 11.2 Two delivery modes on `prompt`

- `mode: 'queue'` → `agent.followup(message)` — queues for the next turn
  (`commands.ts:347-348`; `docs/subsystems/core.md:121`).
- `mode: 'steer'` → `agent.steer(message)` — submits steering for the
  **nearest step**; an idle driver starts a turn, while a running driver
  folds it into the next step (`docs/subsystems/core.md:124-130`).

### 11.3 Editing / promoting / removing pending items

`POST /api/session/updateQueue` lets the client mutate a still-pending
occurrence (`types.ts:332-342`):

```ts
type QueueAction =
  | { kind: 'edit'; content: readonly ContentBlock[] }
  | { kind: 'remove' }
  | { kind: 'steer' }   // promote a queued item into a steering slot
```

A `steer` promotion is rejected if the agent is no longer running or the
target is no longer `next-turn` (`commands.ts:433-434` →
`RemoteError('session/steer-unavailable', …)`).

### 11.4 Interrupt vs abort

`POST /api/session/cancel` cancels the active turn **without dropping the
pending inbox** unless `keepInbox: false` (`docs/subsystems/core.md:76-82`,
`docs/subsystems/session.md:786-790`):

```ts
interface CancelOptions { readonly keepInbox?: boolean }
```

The driver model is convergence-based: a wake submitted during cancellation
is latched and runs when the aborted activity converges to idle
(`docs/subsystems/core.md:104-109`).

### 11.5 Injected context

`agent.inject(message)` parks context in the inbox until a waking delivery
opens a turn — it does NOT wake the driver itself
(`docs/subsystems/core.md:131-140`). Useful for file-change notices,
notifications, etc.

> **Borrowable pattern**: a single inbox with explicit `queue` vs `steer`
> modes; pending items are durable and editable; cancel keeps the inbox by
> default. There is no “reject because busy” — the caller decides the
> urgency via mode.

---

## 12. Persistence format and recovery

### 12.1 Format — JSONL (one row per event)

- Default provider: `dsh-session-persistence-jsonl`
  (`docs/subsystems/persistence.md:7`).
- JSONL v0 uses `session.jsonl[.zstd]`; v1+ uses `session.vN.jsonl[.zstd]`
  (`docs/architecture.md:109`). Committed generation paths are never
  renamed, replaced, or deleted (`architecture.md:109`).
- Current logical version is v2 (one row per event, embedded compact
  assistant streams) (`docs/subsystems/persistence.md`,
  `session.md:658`).
- Adjacent migrations: each `vN → vN+1` step is owned by exactly one
  migration package (`docs/architecture.md:109`).

### 12.2 Handle-based single-writer ownership

- All log access goes through `SessionHandle` (`read` / `append` / `flush`
  / `close`), not id-addressed service methods
  (`docs/subsystems/persistence.md:11-86`).
- Single-writer: a second `open(id, 'write')` rejects with
  `SessionAlreadyOwnedError` while an owner is active
  (`persistence.md:11, 62, 99`).
- `append` is best-effort visibility; only `flush` is the durability
  barrier (`persistence.md:56-78`).

### 12.3 Bounded write-behind batching

`session/event` is synchronous; the backend routes events into a bounded
write-behind window. The first pending event starts a fixed batching
window; later events join without resetting the deadline; expiry flushes
one durable `append` (`docs/subsystems/persistence.md:93`).
`session/flush` is the loop’s ordering checkpoint before claiming the next
turn (`persistence.md:93`).

### 12.4 Crash recovery — preserve the interrupted turn

- A log crashed mid-turn ends with an open `turn/start` and no `turn/end`.
  Persistence **does not truncate or repair it** — those events were
  durably appended (`docs/subsystems/persistence.md:97`).
- It discards only the torn physical tail of an append that never resolved;
  complete records recovered from a torn Zstandard frame are rewritten
  before the handle’s first new append (`persistence.md:97`).
- Repair is the **reader’s** job: resume computes `interruptedTurnClosers`
  (missing tool errors, any open `step/end`, and a synthetic
  `turn/end { reason: { kind: 'interrupted' } }`) and appends them through
  the same write handle (`persistence.md:97`).
- `interrupted` is the one `TurnEndReason` the live loop never emits
  (`docs/subsystems/session.md:620-630`).
- Read-only observers (e.g. `session-query`) compute the same closers in
  memory only (`persistence.md:99`).

### 12.5 Per-session metadata travels separately

`SessionHeader` (version, id, createdAt, cwd, parentSession, isSeeded,
origin, delegationDepth, agentPreset) is **kept outside** the event log
(`docs/subsystems/persistence.md:122-160`).

> **Borrowable pattern**: one JSONL row per event; handle-based
> single-writer ownership prevents cross-process write races; crash recovery
> preserves the interrupted turn and synthesizes a typed closer (so a crash
> is observable as `interrupted`, not silently dropped). Format migration is
> a chain of single-step packages — directly reusable for our spec’s
> recovery requirements.

---

## 13. What is directly borrowable for our Web PRD

The following are concrete, source-verified patterns (not vibes) that map to
PRD requirements:

1. **Event-sourced conversation log as the single source of truth.** Messages
   are a projection (`deriveMessages`) over an append-only typed event log;
   there is no parallel messages table. Source: `session.md:5,557-571`.
2. **Two transports, one trust boundary.** Unary RPC over `POST /api/<ns>/<m>`
   (JSON) + one multiplexed WebSocket (`/api/remote.mux`) for all streams;
   a single trust check at the Connection is the seam for our tenant/RBAC.
   Source: `api-gateway.md:121-123`, `stream-protocol.ts:5-6`,
   `browser-auth.ts:285-296`.
3. **Prompt RPC returns acknowledgement only; the reply arrives on a separate
   stream.** `session/prompt` returns `{ accepted: true }`; the assistant
   reply (and all events) are observed via `session/follow`. This cleanly
   separates command latency from streaming latency. Source: `commands.ts:293-360`,
   `history.ts:119`.
4. **Server-authoritative snapshot + gap-free follow.** Each conversation
   stream opens with a complete snapshot (event log + projections + in-flight
   assistant-stream baseline with `nextIndex`), then continues without gaps.
   Reconnect = open a new stream; no client-held cursor to corrupt. Source:
   `history.ts:180-200`, `types.ts:441-511`.
5. **Explicit `queue` vs `steer` delivery modes for concurrent input.**
   Neither busy-reject nor silent auto-steer; the client picks urgency.
   Pending items are durable and editable (`updateQueue`). Source:
   `commands.ts:347-348`, `types.ts:153-156`, `core.md:104-140`.
6. **Cancel keeps the inbox by default** (`keepInbox: true`); cancellation is
   convergence-based with a wake latch. Source: `core.md:76-109`.
7. **Tool approval is fail-closed and one-shot**, attached to an
   already-streamed tool call via `callId` (no argument duplication). Only
   two user-level policies: `ask` or `never`, packaged with sandbox mode
   into named presets. **If we want per-tool/per-resource auto-approve, that
   is our extension and we must justify it.** Source: `approval.md:21-82`,
   `permission-presets/README.md:12`.
8. **Surface `replace` operation as the compaction primitive.** Compaction is
   one capability that emits a `user/message` with
   `surfaceOp: { op: 'replace', start, end }` shadowing the compacted range,
   preserving the reconstructability invariant. Source: `session.md:286-306`,
   `compaction.md:9-22`.
9. **Model selection is part of the logged request envelope**, so
   mid-conversation switches are replayable and auditable, not side-channel.
   Source: `session.md:148-170`, `types.ts:272-275`.
10. **Fork at a turn boundary with explicit rejection on in-turn prefixes**;
    durable lineage marker `session/end-seed { inherited: true }`. Source:
    `session.md:587-647`.
11. **Handle-based single-writer persistence with bounded write-behind batching
    and a `flush` durability barrier.** Crash recovery preserves the
    interrupted turn and synthesizes a typed `interrupted` closer. Source:
    `persistence.md:11-99`, `session.md:620-630`.
12. **Typed `RemoteError` codes that cross the wire unchanged**
    (`session/not-found`, `session/agent-busy`, `session/model-unavailable`,
    `session/steer-unavailable`, `session/attachment-invalid`, …). A clean
    error vocabulary is part of the contract, not an afterthought. Source:
    `api-gateway.md:127`, `commands.ts:298-356`.

### Things `dsh` deliberately does NOT provide (we must design ourselves)

- **Multi-tenancy and per-user identity** (§10). No userId in any request;
  auth is a single HMAC cookie for the host.
- **Per-tool / per-resource auto-approve scopes** (§6). Only `ask` vs `never`.
- **SSE transport**. `dsh` chose WebSocket mux; if our enterprise constraints
  prefer SSE (e.g. strict HTTP proxies), we are deviating, not conforming.
- **Operation ledger / side-effect reconciliation for non-session side
  effects.** `dsh` reconciles tool calls inside the session log via
  `callId` pairing; broader operation-recovery semantics (e.g. durable
  side-effect redo/idempotency across services) are out of `dsh`’s scope.

---

## Appendix A — Key file index in the clone

| Topic | File |
|---|---|
| Conversation/session model | `packages/core/session/src/types.ts`, `docs/subsystems/session.md` |
| Prompt endpoint | `packages/api/session-controller/src/commands.ts:293-360`, `types.ts:305-318` |
| Streaming follow | `packages/api/session-controller/src/history.ts:119-275`, `types.ts:433-511` |
| WebSocket mux | `packages/api/gateway/src/stream-protocol.ts`, `stream-server.ts` |
| HTTP bridge | `packages/client/connection/src/http-bridge.ts` |
| Browser auth | `packages/client/connection/src/browser-auth.ts` |
| Approval | `docs/subsystems/approval.md`, `packages/interaction/user-approval/src/index.ts` |
| Permission presets | `packages/interaction/permission-presets/README.md`, `src/index.ts` |
| Compaction | `docs/subsystems/compaction.md` |
| Persistence/recovery | `docs/subsystems/persistence.md` |
| Agent inbox/concurrency | `docs/subsystems/core.md:49-280` |
| API gateway overview | `docs/api-gateway.md` |
| Architecture | `docs/architecture.md`, `docs/agent-lifecycle.md` |
