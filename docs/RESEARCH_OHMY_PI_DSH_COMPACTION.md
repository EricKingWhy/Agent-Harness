# Research: oh-my-pi CLI + DeepSeek Harness (dsh) Compaction — Fusion Inputs for PRD

Primary sources (read-only):
- oh-my-pi: `C:\Users\王浩宇\AppData\Local\Temp\oh-my-pi`
- dsh: `C:\Users\王浩宇\AppData\Local\Temp\deepseek-harness`
- Ours: `D:\intelligence-agent-backend\src\agent_harness\context\builder.py` + `compactor.py`

All citations are `file:line`. Where a fact is not present in source, it is marked **(not found)** rather than invented.

---

## Section 1 — oh-my-pi CLI Session Lifecycle

### 1.1 How the "current session" is held

- The interactive agent runtime is a long-lived **`Agent` class** instantiated once per process and holding all session state in private fields, **not** a fresh session per prompt.
  - `packages/agent/src/agent.ts:355` — `export class Agent {`
  - `packages/agent/src/agent.ts:356-367` — `#state: AgentState = { systemPrompt, model, thinkingLevel, ..., messages: [], isStreaming: false, ... }` — the persistent in-memory session transcript.
  - `packages/agent/src/agent.ts:374-376` — separate queues: `#steeringQueue`, `#followUpQueue`, `#steeringWaiters`.
- Sending a normal prompt **appends to the current session**, it does not fork one: `prompt()` validates the agent is not streaming, wraps the input into a single `user` message, and calls `#runLoop(msgs, ...)`.
  - `packages/agent/src/agent.ts:1155-1157` — `if (this.#state.isStreaming) throw new AgentBusyError();`
  - `packages/agent/src/agent.ts:1180-1186` — building the `{role:"user", content, timestamp}` message.
  - `packages/agent/src/agent.ts:1192` — `await this.#runLoop(msgs, promptOptions);`
- Appending to transcript on each assistant/toolResult event: `emitExternalEvent` → `case "message_end": ... this.appendMessage(event.message)` (`agent.ts:906-909`), and the loop body at `agent.ts:1559` (`this.appendMessage(event.message)`).
- `Agent.replaceMessages(ms)` (`agent.ts:967-971`) and `reset()` (`agent.ts:1134-1144`) are the explicit "swap transcript / wipe" entry points the session layer uses for `/new`, `/resume`, `/clear`.
- Per-session identity for provider prefix caching: `sessionId` getter/setter (`agent.ts:519-529`) — "Set the session ID for provider caching. Call this when switching sessions (new session, branch, resume)." Plus `promptCacheKey` (`agent.ts:534-543`).

### 1.2 Storage format and location

- **JSONL on local disk**, one file per session, organized under a per-cwd hashed directory inside a sessions root.
  - `packages/coding-agent/src/session/session-paths.ts:188-194` — `createSessionLayout(cwd, sessionId, sessionsRoot = getSessionsDir())` → `path.join(sessionsRoot, encodedDirName)`.
  - `packages/coding-agent/src/session/session-paths.ts:94-122` — `migrateHomeSessionDirs(sessionsRoot)` renames legacy entries inside the root.
  - `packages/coding-agent/src/session/session-paths.ts:5` — `getSessionsDir` is imported from `@oh-my-pi/pi-utils` (the canonical root; not the legacy per-cwd absolute layout).
- Persistence writes entries line-by-line; the comment at `session-persistence.ts:106` states entries are fsync'd to the **kernel page cache before the JSONL line referencing them is written** (durability ordering).
- Session file breadcrumb per terminal: `session-paths.ts:217-223` writes `${cwd}\n${sessionFile}\n[fresh]\n` to `getTerminalSessionsDir()/terminalId`, and `session-paths.ts:255-275` reads it back to resume. The "fresh" flag (`session-paths.ts:208`, `:242`, `:253`) marks a `/new` lazy session whose JSONL may not exist yet.
- Large binary content (images, raw tool blobs) is **externalized to a content-addressed BlobStore** and referenced by a `blob:` ref inside the JSONL — not embedded inline:
  - `packages/coding-agent/src/session/blob-store.ts:8` — "Canonical blob hash shape: exactly 64 lowercase hex chars (a SHA-256 digest)."
  - `blob-store.ts:95-114` — `class BlobStore { async put(data): {hash, ref: `${BLOB_PREFIX}${hash}`} }` writes to `path.join(this.dir, hash)`.
  - `blob-store.ts:213-222` — `externalizeImageDataUrl(blobStore, dataUrl)` → `const { ref } = await blobStore.put(Buffer.from(dataUrl, "utf8"))`.
  - `blob-store.ts:230-245` — `externalizeImageData(blobStore, base64, mimeType)` likewise.

### 1.3 Slash commands (registry evidence)

- Slash commands are aggregated from multiple `builtin-*.ts` files and surfaced via `available-commands.ts`. Definitions follow `{ name, description, subcommands?: [...] }`.
- **Lifecycle / session** (`packages/coding-agent/src/slash-commands/builtin-lifecycle.ts`):
  - `/new` "Start a new session" (`:173-175`)
  - `/fresh` "Reset provider stream state without changing the local transcript" (`:184`)
  - `/clear` "Clear the conversation context in place, keeping the session" (`:204-206`) — corresponds to the `reset_boundary` marker consumed by compaction at `agent/src/compaction/compaction.ts:1342-1352`.
  - `/drop` "Delete the current session and start a new one" (`:217`)
  - `/compact` "Manually compact the session context" (`:226`) with mode subcommands generated at `:229-230`.
  - `/shake` "Drop heavy content from context (tool results, large blocks)" with subcommands `elide | images | thinking` (`:290-297`).
  - `/handoff` "Hand off session context to a new session" (`:319-321`).
  - `/resume` "Resume a different session" (`:386-388`).
  - `/pin` "Pin or unpin a session at the top of the resume list" (`:417-419`).
  - `/retry` "Retry the last failed agent turn" (`:496-498`).
- **Session management group** (`builtin-session.ts`):
  - `/session` with `info | delete | pin` (`:179-189`).
  - `/todo`, `/jobs`, `/usage`, `/stats`, `/changelog`, `/hotkeys`, `/tools`, `/context` ("Show estimated context usage breakdown", `:426-428`), `/extensions`, `/agents`.
- **Modes** (`builtin-modes.ts`):
  - `/model` "Switch model for this session" (`:321-324`) and `/switch` fuzzy alias (`:365-367`).
  - `/plan` (`:201-203`), `/plan-review` (`:222-224`), `/vibe` (`:233-235`), `/goal` (`:251-260`), `/guided-goal` (`:277-279`), `/loop` (`:289-291`), `/queue` "Queue a message for after the agent yields" (`:311-313`), `/fast` (`:414`), `/skillful` (`:484-492`), `/extended-context` (`:540-548`), `/prewalk` (`:612-614`), `/settings` (`:174`), `/setup` (`:183-188`), `/security` (`:153-169`).
- **Collaboration** (`builtin-collaboration.ts`):
  - `/advisor` "Toggle the advisor (a second model that reviews each turn and injects notes)" (`:55-65`).
  - `/export` "Export session to HTML file" (`:172-174`).
  - `/trace` "Open this session's trace in the stats dashboard" (`:196-198`).
  - `/dump` "Copy session transcript to clipboard ..." (`:223-225`).
- **Control** (`builtin-control.ts`):
  - `/force` "Force next turn to use a specific tool" (`:8-10`).
  - `/live` "Start Codex-backed realtime voice mode" (`:58-60`).
  - `/pause` "Freeze all agents (main, subagents, advisor) until resumed" (`:67-69`).
  - `/quit` "Quit the application" (`:76-79`).
- **Help**: The exact token `/help` as a command was **(not found)** as a registered slash command in the scanned files; help is instead delivered via the `launch` CLI subcommand surface (`packages/coding-agent/src/cli-commands.ts:20-23`, `launchHelp`). `/help` may exist as a TUI keybinding; not confirmed in source.
- `/list`, `/tree`, `/clone`, `/history`, `/cancel` as slash commands: **(not found)** in the builtin files. `/history`-like listing is delivered through `/session info` and `/context`; cancellation is via keyboard (`popLastSteer`/`abort`) rather than a named slash command.
- The full flat `commands` array (CLI subcommands, distinct from slash commands) lives at `cli-commands.ts:22-228`.

### 1.4 Normal prompt vs new session

- A plain text prompt never creates a new session. It throws `AgentBusyError` if streaming (`agent.ts:91-98`, `:1155-1157`) and otherwise appends one user turn to `#state.messages`.
- New-session creation is exclusively the `/new` (`:173`) and `/drop` (`:217`) command paths; `/resume` (`:386`) swaps in a different session via `replaceMessages` (`agent.ts:967`).

---

## Section 2 — oh-my-pi Compaction

Source: `packages/agent/src/compaction/compaction.ts` (1933 lines, fully read). Plus `compaction-v2-streaming.ts`, `openai.ts`, `prompts/*.md`.

### 2.1 Trigger

- **Token-budget trigger**, configurable percentage OR fixed tokens, plus a manual `/compact`.
  - `compaction.ts:343-347` — `shouldCompact(contextTokens, contextWindow, settings)` returns `contextTokens > thresholdTokens` (after `enabled` / `off` guards).
  - `compaction.ts:368-392` — `resolveThresholdTokens`:
    - fixed `thresholdTokens` wins if set, clamped to `[1, contextWindow-1]` (`:371-373`);
    - else if `thresholdPercent` set, `floor(contextWindow * clamp(pct,1,99)/100)` (`:390-391`);
    - else **default** = `contextWindow - resolveBudgetReserveTokens(...)` (`:384-388`). I.e., trigger when occupancy leaves less than the reserve.
- **mid-turn compaction enabled by default** — `midTurnEnabled: true` (`compaction.ts:219`).
- The trigger is **floored by a local estimate** of the stored conversation so on-wire compression cannot mask runaway history: `compactionContextTokens(providerContextTokens, storedConversationEstimate)` returns the max (`compaction.ts:364-366`).

### 2.2 Thresholds / parameters (exact defaults)

`DEFAULT_COMPACTION_SETTINGS` (`compaction.ts:214-225`):
- `enabled: true`
- `strategy: "context-full"`
- `thresholdPercent: -1` and `thresholdTokens: -1` → both mean "use reserve-based default" (sentinel, see `:384`).
- `midTurnEnabled: true`
- `keepRecentTokens: 20000` — the verbatim tail retained.
- `autoContinue: true`
- `remoteEnabled: true`
- `remoteStreamingV2Enabled: true`
- `v2RetainedMessageBudget: V2_RETAINED_MESSAGE_TOKEN_BUDGET` (imported from `compaction-v2-streaming.ts:52`).

Reserve tokens:
- `DEFAULT_RESERVE_TOKENS = 16384` (`compaction.ts:197`).
- `MAX_SUMMARY_TOKENS = 16384` (mirrors reserve; `:209`).
- **Effective reserve** = `max(floor(contextWindow * 0.15), settings.reserveTokens ?? DEFAULT_RESERVE_TOKENS)` — `effectiveReserveTokens` (`:313-315`). I.e. at least **15% of the window**, never below the 16 384 floor.
- `resolveBudgetReserveTokens` (`:329-338`) recovers a *defaulted* reserve that is impossible for tiny windows by falling back to the 15% proportional reserve.
- Summary budget per call: `maxTokens = min(floor(0.8 * reserveTokens), MAX_SUMMARY_TOKENS)` (`:864`).
- Short summary cap: `min(512, floor(0.2 * reserveTokens))` (`:1173`).
- Turn-prefix summary cap: `min(floor(0.5 * reserveTokens), MAX_SUMMARY_TOKENS)` (`:1887`).
- Summary **input** budget (one window): `max(minSummaryInputTokens, floor(window*0.8) - maxTokens - MAX_SUMMARY_TOKENS)` (`:797-803`). `MIN_SUMMARY_INPUT_TOKENS = 16384` (`:783`).

### 2.3 What gets compacted

- All entries between the previous compaction boundary (or the latest `/clear` reset boundary) and the cut point are summarized; the recent tail (`keepRecentTokens`) is kept verbatim.
  - `prepareCompaction` (`compaction.ts:1322-1436`):
    - skips if the last entry is already a compaction (`:1328-1330`).
    - honors `/clear` `reset_boundary` (`:1342-1352`).
    - `keepRecentTokens` is dynamically **scaled down** by `promptTokens / estimatedTokens` ratio when the provider counts hotter than local estimate (`:1358-1365`).
    - `findCutPoint` walks backwards accumulating sizes until `>= keepRecentTokens` (`:505-568`).
- Cut-point safety: **never cut at a tool result** (its tool call must precede it).
  - `findValidCutPoints` (`:421-456`) accepts `user | assistant | bashExecution | hookMessage | branchSummary | compactionSummary | branch_summary | custom_message` and explicitly **skips `toolResult`** (`:437-438`).
  - `findTurnStartIndex` (`:463-478`) finds the user/bash message opening the turn being split.
- Split-turn handling: when the cut lands mid-turn, a separate **turn-prefix summary** is generated (`:1386-1392`, `:1803-1821`, `generateTurnPrefixSummary` at `:1879-1932`) and merged into the final summary with a `--- **Turn Context (split turn):**` separator (`:1821`).
- File-operation tracking: read/modified file lists are extracted from tool calls and previous compaction details and **upserted into the summary** (`extractFileOperations` `:99-126`; `computeFileLists` + `upsertFileOperations` at `:1850-1852`). This is a notably enterprise-grade touch — the post-compaction summary always carries an up-to-date file ledger.

### 2.4 Large tool results / artifacts

- oh-my-pi does **not** externalize large tool results to object storage as a compaction step. Instead:
  1. **Inline in transcript**, but with **`/shake`** as a manual heavy-content stripper: `builtin-lifecycle.ts:290-297` — modes `elide` (strip tool results + large blocks), `images`, `thinking`.
  2. **Snapcompact** (`packages/snapcompact`) archives history onto dense bitmap images the model reads back — `/compact snapcompact` (`compact-modes.ts:55-60`); no LLM call; carried forward via `preserveData` (`compaction.ts:1590-1600`, `snapcompact.getPreservedArchive`).
  3. **Images / binary data** are externalized to the BlobStore at *ingest* time (`blob-store.ts:213-245`), so the JSONL only ever holds `blob:` refs — this is an ingest-time invariant, not a compaction-time one.
- Compaction modes surfaced via `/compact <mode>` (`compact-modes.ts:39-60`): `soft` (local LLM only), `remote` (OpenAI-compatible server compaction then fall back to local), `snapcompact`.

### 2.5 Provider-native ("remote") compaction

- When the active model supports it, oh-my-pi prefers **provider-native compaction** (OpenAI Responses/Codex V2 streaming, or V1) which preserves provider-native history as an opaque replay blob and writes only a placeholder summary.
  - `shouldUseProviderNativeCompaction` (`compaction.ts:228-237`).
  - V2 streaming branch: `compaction.ts:1611-1733`; on failure it logs `"OpenAI V2 remote compaction failed, falling back to V1 remote compaction"` (`:1726`) and tries V1 (`:1735-1785`).
  - If both native paths fail and no remoteEndpoint is set, throws `NativeCompactionError` (`:1787-1789`).
  - `remotePreserveReusable` (`:1278-1289`) and `findReadableCompactionIndex` (`:1303-1315`) handle the model-switch case: a remote blob only replays under the same provider; otherwise prepareCompaction re-expands the originals and summarizes locally.

### 2.6 Fallback when summarization fails

- **Transient retry** is enabled by default for one-shot summarizers so a single overloaded/429/529 cannot abort compaction: `summaryOneshotRetry` (`compaction.ts:738-742`), with the note that auto-compaction passes `oneshotRetry: false` because it already owns an outer retry loop (`:720-730`).
- **ContextOverflow** on a too-big summary window → halve the window and re-plan rather than fail (`:904-931`); gives up only when `halved < minSummaryInputTokens(model)`.
- A **single oversized message** is clamped proportionally with a `[... N more characters truncated]` marker rather than rejecting (`clampConversationToBudget` `:811-816`).
- Hard summary-size ceiling `MAX_SUMMARY_TOKENS = 16384` keeps compression ratio improving with window size instead of degrading (`:199-209`).
- Native compaction auth vs protocol failure ordering: `selectNativeCompactionError` (`:1515-1518`) keeps any non-auth failure ahead of auth so downstream retry can pick another provider.
- **No mechanical deterministic fallback** analogous to ours: oh-my-pi does not serialize a structured extract when the LLM errors; instead it relies on transient retry + window-halving + `/shake` manual stripping. If summarization ultimately fails, the turn-level error propagates.

---

## Section 3 — oh-my-pi Queue / Steer

### 3.1 Send while a run is active — yes, both queue and steer

- Two distinct queues on the `Agent`:
  - `#steeringQueue` — interrupts mid-run, delivered after current tool execution, skips remaining tools.
    - `steer(m)` (`agent.ts:995-998`): pushes + notifies waiters.
    - Docstring at `:992-994`: "Queue a steering message to interrupt the agent mid-run. Delivered after current tool execution, skips remaining tools."
  - `#followUpQueue` — processed only after the agent finishes (no more tool calls or steers).
    - `followUp(m)` (`:1004-1006`).
    - Docstring `:1000-1003`: "Queue a follow-up message to be processed after the agent finishes. Delivered only when agent has no more tool calls or steering messages."
- A direct `prompt()` while streaming **throws `AgentBusyError`** with the message "Use steer() or followUp() to queue messages, or wait for completion." (`agent.ts:91-98`, `:1155-1157`).

### 3.2 Modes

- `steeringMode` and `followUpMode`: `"all"` (drain everything queued at each boundary) or `"one-at-a-time"` (one message per turn) — defaults **one-at-a-time** (`agent.ts:467-469`, setters at `:939-953`).
- `interruptMode`: `"immediate"` (check after each tool call, default) or `"wait"` (defer until current turn completes) (`agent.ts:469`, `:955-961`).

### 3.3 Storage / durability / editability / cancellability

- **In-memory only** — both queues live on the `Agent` instance (`agent.ts:374-375`), not persisted to JSONL. There is no durability across process restart.
- **Editable / inspectable**: live non-consuming views `peekSteeringQueue()` and `peekFollowUpQueue()` (`agent.ts:1041-1049`) — explicitly "the agent-core queue stays the single source of truth" for UI display.
- **LIFO pop** for dequeue keybinding: `popLastSteer()` and `popLastFollowUp()` (`agent.ts:1087-1097`).
- **Clearable**: `clearSteeringQueue()` (`:1008`), `clearFollowUpQueue()` (`:1013`), `clearAllQueues()` (`:1026-1031`); `replaceQueues(steering, followUp)` for session swap (`:973-977`).
- `/queue` slash command exposes queuing to the user (`builtin-modes.ts:311-313`).
- Loop integration: `getSteeringMessages`, `hasSteeringMessages`, `waitForSteeringMessages`, `getFollowUpMessages` are threaded into `AgentLoopConfig` (`agent.ts:1487-1517`).
- `hasSteeringMessages` reports the source (`user | agent | system`) so the loop can decide whether to yield to a user steer vs. continue (`agent.ts:1494-1514`).

---

## Section 4 — oh-my-pi Notable "Enterprise-Grade" UX

1. **Steer + follow-up as first-class, distinct semantics** with one-at-a-time vs all, immediate vs wait — and live peek views for the UI (`agent.ts:992-1049`). Lets users redirect a long run without aborting.
2. **Per-terminal session breadcrumbs** with a "fresh" lazy-session marker so a new terminal starts instantly and writes JSONL only when needed (`session-paths.ts:217-275`).
3. **Content-addressed BlobStore** (SHA-256 hex) externalizing images and binary tool payloads at ingest, keeping the JSONL small and replay fast (`blob-store.ts:8-114, 213-245`).
4. **Compaction trigger floored by local estimate**, defeating on-wire compression tricks that would otherwise let real history grow unbounded (`compaction.ts:351-366`).
5. **Dynamic `keepRecentTokens` scaling** by provider-vs-local token ratio, so the verbatim tail shrinks correctly when the provider counts hotter than the local tokenizer (`compaction.ts:1358-1365`).
6. **File-operation ledger preserved across compaction** — every summary upserts an up-to-date read/modified file list (`compaction.ts:99-126, 1850-1852`). Survives compact→resume.
7. **Split-turn safety**: cutting mid-turn produces a dedicated turn-prefix summary so partial tool-call/result pairs never orphan (`compaction.ts:1386-1392, 1803-1821`).
8. **Provider-native remote compaction** with V2→V1→local fallback and model-switch awareness via `remotePreserveReusable` (`compaction.ts:1278-1289, 1611-1789`) — preserves provider prefix cache and replay payload when possible.
9. **Multiple manual compaction modes** exposed as `/compact soft|remote|snapcompact` plus `/shake elide|images|thinking` for non-LLM heavy stripping (`compact-modes.ts:39-60`, `builtin-lifecycle.ts:290-297`).
10. **Per-call reasoning-effort threading** so `/model` thinking dial is honored on every fan-out summarizer, not silently overridden (`compaction.ts:1574-1579`, `resolveCompactionEffort` `:632-637`).
11. **Slash-command surface is genuinely huge and consistent** — `/context` for live usage breakdown, `/session info|delete|pin`, `/advisor` second-model review, `/handoff`, `/export` to HTML, `/trace` to stats dashboard, `/pin` for resume-list pinning — the polish breadth is itself the enterprise signal.

---

## Section 5 — DeepSeek Harness (dsh) Compaction — Exact Parameters

Sources: `packages/compaction/compaction-basic/src/{config,region,summarizer}.ts`, `packages/compaction/compaction/src/{index,types,invariant,tool-pairing}.ts`, `packages/compaction/compaction-tool-result-pruner/src/{config,index}.ts`, `packages/compaction/command-compact/src/index.ts`.

### 5.1 Trigger thresholds (exact)

`packages/compaction/compaction-basic/src/config.ts`:
- `DEFAULT_THRESHOLD_RATIO = 0.8` (`:20`) — "Default request-pressure fraction for every routed model."
- `DEFAULT_RETAIN_RATIO = 0.16` (`:23`) — "Default verbatim-tail fraction for every routed model."
- `maxTokens` default `8192` (`:91`).
- `compactionRetries` default `1` (`:92`).
- `maxOverflowRetries` default `1` (`:93`).
- `auto` default `true` (`:95`).
- `resolveCompactSpec(policy, contextWindow)` (`:133-167`):
  - `thresholdTokens = floor(contextWindow * thresholdRatio)` (`:144`).
  - `retainTokens = floor(contextWindow * retainRatio)` if ratio form, else explicit (`:145-147`).
  - validates `retainTokens < thresholdTokens` (`:148-154`).
- Per-model policy overrides via `modelPolicies[]` keyed by exact `provider\u0000model` (`:194-212`).
- Both `thresholdRatio` and `retainRatio` must be in `(0,1]` (`:306-310`); `retainRatio` must be `< thresholdRatio` (`:180-191`).
- **No separate hard-guard constant**: the only thresholds are `thresholdRatio` (auto trigger) and the implicit overflow path (`maxOverflowRetries`). After context overflow, compaction condenses and retries up to `maxOverflowRetries` (`README.md:12` "after a context-overflow error it condenses and retries").

For a 200k window with defaults: trigger at **160 000 tokens**, retain **32 000 tokens** verbatim tail, summary `maxTokens` **8192**.

### 5.2 What gets compacted

`packages/compaction/compaction-basic/src/region.ts`:
- `selectCompactableRange(session, measurement, retainTokens)` (`:100-136`):
  - walks tail backwards accumulating priced tokens until `>= retainTokens` (`:114-121`);
  - then **expands the cut backwards while the boundary would split a tool-call/result pair**: `while (keepFromIdx > 0) { if (toolPairingBalancedBefore(session, surfaceNodes[keepFromIdx])) break; keepFromIdx -= 1; }` (`:124-129`);
  - returns the head-anchored range `[first surface node, cutoff]` (`:131-135`).
- Compacted material = the messages **shadowed** by the selected surface span (`shadowedSeqs`), replayed in surface order with the conversation's own system prompt and tools prepended so the summarizer call **reuses the provider's warm prefix cache** (`:498-523`, plus `summarizer.ts:28-30, 78-85`).
- Both user/assistant messages and tool results in the span are summarized into one structured checkpoint; only the summary text survives on the surface (`region.ts:437-488`).
- Cannot shrink the system prompt, tools, or session prefix, and cannot split one indivisible unit such as a single huge tool call (`compaction-basic/README.md:12`).

### 5.3 Large tool results / artifacts

- dsh handles oversized tool outputs via a **separate, deterministic pruner plugin**, not externalization to object storage.
- `packages/compaction/compaction-tool-result-pruner/src/config.ts`:
  - `PRUNE_MARKER = "\n\n[... tool result middle pruned ...]\n\n"` (`:7`).
  - `DEFAULTS`: `thresholdChars: 8192`, `headChars: 4096`, `tailChars: 1024` (`:10-14`).
  - Validates `headChars + marker + tailChars <= thresholdChars` (`:55-63`).
- `packages/compaction/compaction-tool-result-pruner/src/index.ts`:
  - `ToolResultPruner.pruneContent(blocks)` returns `null` when within budget, else keeps `headChars` head + `tailChars` tail with the marker between (`:81-121`); throws if the replacement is not strictly smaller (`:118-120`).
  - `pruneSession(session)` walks tool-result entries, appends a `compaction/prune` shadow-price event before each replacement (`:128-183`).
- There is **no MinIO / blob externalization** in the dsh compaction packages. The `packages/spill` family exists separately (`spill`, `spill-local`, `spill-policy`) but is **not wired into the compaction packages scanned here** — compaction prunes in place by character budget. (Spill is a distinct subsystem not part of the compaction transaction.)

### 5.4 Fallback on summarization failure

`packages/compaction/compaction-basic/src/summarizer.ts`:
- `summarizeWithLlm` runs the default `ctx.llm.stream()` summarization; on terminal finish maps to errors:
  - `error` / `aborted` finish → throw with provider failure message + code (`:198-205`).
  - `max-tokens` finish → throw `"summarization truncated at the token cap (incomplete checkpoint)"` with code `MAX_TOKENS` (`:206-210`). I.e. **a truncated summary is rejected, not accepted**.
- Image output in summary → throw `LlmError('compaction summary cannot contain image output', 'UNSUPPORTED_CONTENT')` (`:217-223`).
- Empty text summary → throw `'summarization produced no text summary content'` (`:170-172`).
- **Shrink check** in `region.ts:383-388`: after framing, if the framed-summary token count is `>=` the route-priced shadowed token count, throw `"summary is not smaller than the shadowed content"`. Compaction only commits if it actually reduces pressure.
- **Retries**: `compactionRetries` (default 1) on the summarization call; `maxOverflowRetries` (default 1) for the post-overflow condense-and-retry path (`config.ts:92-93`).
- **Manual-compaction failure classification** — `ManualCompactionError` codes: `busy | cancelled | changed | summary | commit | persistence` (`compaction/src/index.ts:27-60`), surfaced to humans by `command-compact/src/index.ts:23-55`.
- **No deterministic mechanical fallback** like ours: a failed summarization either retries within budget or surfaces as a `summary` failure code; the conversation is left unchanged and the failed attempt is recorded in the log.

### 5.5 Manual compaction API

- `CompactionEngine.compactNow(agent, signal, sourceCommandId?)` — explicit idle-session compaction even below auto thresholds (`packages/compaction/compaction/src/index.ts:130-162`):
  - "Implementations synchronously start an idle task before any asynchronous work, select a useful range without writing on a no-op, then append a standalone `compaction/start` before summarization."
  - Returns `CompactionResult | null` (null = no safe useful range).
  - Requires the agent to be **idle** (`region.ts:173-176`: manual compaction throws `busy` if there is an open turn).
- `CompactionEngine.compactRegion(start, end, agent, signal?)` — force-compact an explicit inclusive surface span (`index.ts:164-172`); both edges must be tool-balanced.
- Human surface: **`/compact`** with **no arguments** — `packages/compaction/command-compact/src/index.ts:13` (`USAGE = 'Usage: /compact (no arguments)'`); rejects any input (`:62-64`); maps capability failures to concise user strings (`:23-55`).

### 5.6 Append-only event log interaction

- Compaction is a **multi-event bracket** in the append-only log, never a mutation of prior events:
  - `compaction/start` (`region.ts:191`)
  - `compaction/summary` (records summary text, shadowed range + seqs, token count, provider/model, usage) (`:457-471`)
  - the actual surface replacement is a `user/message` append with `surfaceOp: { op: 'replace', start, end }` and `sourceEventSeqs` pointing back at the bracket (`:472-475`)
  - `compaction/end` (`:217`)
- The shadowed events **stay in the raw log**; replay is deterministic because `deriveMessages()` renders the summary as a user-role message followed by the retained nodes (`packages/compaction/compaction/README.md:95`).
- A crash between `compaction/start` and `compaction/end` leaves a **detectable orphaned lock** rather than a false success (`README.md:95`; `region.ts:220-231` always attempts exactly one `compaction/end`, including an error-bearing one on failure).
- Invariants are enforced by `packages/compaction/compaction/src/invariant.ts`:
  - `compaction/start` shadowed seqs must name an earlier current surface span (`:56-80`).
  - `compaction/summary` must reference the matching open `compaction/start` id (`:97-125`, `:223-225`).
  - `compaction/start` while the same owner is still compacting is rejected (`:207`).
  - Per-owner turn enclosure check (`:168-175`): auto compaction events must be inside an open turn; manual (`owner: null`) must not be.
- Tool-call/result pairing is validated independently via `toolPairingBalancedBefore` / `toolPairingBalancedAfter` (`compaction/src/tool-pairing.ts`, exported at `index.ts:17`), consumed at `region.ts:126, 329-335`.

---

## Section 6 — Fusion Recommendation

Our current design (`builder.py`, `compactor.py`): token-budget trigger; auto-compact at **70%**, hard guard at **85%**; summarize early messages via LLM with **mechanical deterministic fallback**; cut at the earliest `HumanMessage`; validate tool-call/result pairing upfront; emit a single `CONTEXT_COMPACTED` event post-hoc. Defaults: `max_context_tokens=200_000`, `summary_timeout_seconds=30`.

| Parameter | Ours | oh-my-pi | dsh | Recommended | Why |
|---|---|---|---|---|---|
| Trigger basis | Token budget | Token budget (percent **or** fixed tokens **or** reserve-based default) | Token budget (ratio only) | **Keep token budget, add optional fixed-token override** | Matches both. Fixed-token override (oh-my-pi `:368-373`) is cheap and useful for capping cost on huge windows. |
| Auto threshold | 70% | Reserve-based default ≈ contextWindow − max(15% window, 16384); with default 200k window that is ~**92%** (trigger when <17k headroom) | **80%** (`DEFAULT_THRESHOLD_RATIO`) | **Adopt dsh's 80%** | Our 70% is more conservative than both proven systems; 80% gives more usable context without losing safety (dsh ships it). oh-my-pi's reserve-form is equivalent on large windows. |
| Hard guard | 85% | Implicit: only the trigger; no separate hard guard (effectively reserve = 15% floor) | Implicit: overflow path retries `maxOverflowRetries=1`; no separate hard guard | **Keep 85% hard guard** | A two-tier (soft/hard) guard is a genuine improvement over both upstream designs; gives the loop a deterministic stop before context_window_exceeded. dsh effectively relies on the model call failing first. |
| Retain recent (tail) | Implicit: keep everything from earliest HumanMessage onward — **no token tail cap** | `keepRecentTokens = 20000` default, dynamically scaled by provider/local ratio | `retainRatio = 0.16` → 32k on 200k window | **Adopt an explicit retain tail ≈ dsh's 16% or oh-my-pi's 20k, whichever is larger** | Our current "keep from earliest human" can keep a huge tail and force repeated compaction. Both upstream systems retain a bounded tail. Pick `max(20k, 16% window)`. |
| Cut-point safety | `_validate_tool_blocks` rejects orphan tool messages upfront (`compactor.py:163-181`) | Never cut at tool results; expand to balanced boundary (`compaction.ts:421-456`) | `toolPairingBalancedBefore/After`; expand cut backwards to balance (`region.ts:124-129, 329-335`) | **Keep ours; add oh-my-pi/dsh-style balanced-boundary expansion at cut time** | Our upfront validation is good but operates on the projected block, not the cut decision. Borrow the "walk backwards until boundary is balanced" rule so compaction never proposes a split that orphans a tool call. |
| Split-turn handling | None — cuts at earliest HumanMessage, ignoring mid-turn | Dedicated turn-prefix summary for split turns (`compaction.ts:1386-1392, 1803-1821`) | Rejects unbalanced ranges outright (`region.ts:329-335`) | **Adopt oh-my-pi's split-turn summary** | Lets compaction fire more often without wasting a whole turn; dsh's reject-and-skip can leave a session uncompactable until the turn closes. |
| What is summarized | Early messages (everything before earliest HumanMessage kept-as-is is wrong — actually `early = messages[prefix_end:cut]`, `recent = messages[cut:]`, `compactor.py:65`) | All entries between boundary and cut point (`compaction.ts:1376-1399`) | Head-anchored shadowed span (`region.ts:100-136`) | **Keep ours, but fix cut to be turn-aligned** | Same intent. Our cut at earliest HumanMessage is a degenerate version of oh-my-pi's cut-point walk; aligning them is the single biggest win. |
| Large tool results | Inline; truncated to 100 chars only in mechanical fallback (`compactor.py:130`) | Inline in transcript; images/binaries externalized at ingest via BlobStore; `/shake elide` manual stripper | Inline; deterministic pruner plugin `thresholdChars=8192, head=4096, tail=1024` + `[... tool result middle pruned ...]` marker | **Adopt proposed default: externalize tool result >2k tokens to MinIO with summary+ref in-session; plus dsh-style head/tail pruner as the in-session fallback** | Matches the PRD proposal. oh-my-pi's BlobStore proves the ingest-time externalization pattern; dsh's pruner proves the deterministic in-place fallback. Combine: large → externalize; medium → prune. Our 100-char mechanical cap is too aggressive for production. |
| Summary format | Structured JSON `{facts, decisions, constraints, failed_attempts, unresolved, artifact_refs, citations, tool_outcomes}` (`compactor.py:24-32`) | Free-form prose from prompts (`prompts/compaction-summary.md` etc.) + file-op ledger upsert | Structured Markdown template (Primary Request, Key Concepts, Files and Code, Errors and Fixes, Pending Jobs, Current Work, Next Step, Critical Context) (`summarizer.ts:31-66`) | **Keep structured; align field set with dsh's template** | Our JSON is machine-parseable (good for downstream tooling); dsh's section list is field-tested for resumption quality. Adding `current_work`, `next_step`, `files_and_code` improves resume fidelity. |
| Fallback on summarization failure | Deterministic mechanical extract (truncated rows per message) (`compactor.py:114-138`) | Transient retry + window-halving + clamp; no deterministic extract | Retry within `compactionRetries`; else surface `summary` failure code; conversation unchanged | **Keep mechanical fallback; add dsh's "summary must be strictly smaller" shrink check** | Our mechanical fallback preserves forward progress when the provider is down — a real enterprise property both upstream systems lack. But add dsh's shrink check (`region.ts:383-388`) so we never persist a "summary" larger than what it replaced. |
| Manual compaction API | None (only auto) | `/compact [soft|remote|snapcompact]` + `/shake` + `/handoff` | `/compact` (no args) → `compactNow()` | **Adopt `/compact` manual trigger (dsh-style, arg-free) as the MVP; add oh-my-pi modes later** | Manual trigger is essential for enterprise UX (user sees pressure, compacts now). dsh's arg-free design is the right MVP; oh-my-pi's mode matrix is a Phase-2 enrichment. |
| Event log interaction | Single `CONTEXT_COMPACTED` event appended after the fact (`builder.py:71-77`) — the projection is mutated in-memory, only a marker is logged | Compaction is itself an entry type in the append-only log; session is reloaded after (`compaction.ts:6-7` docstring) | Multi-event bracket `compaction/start | compaction/summary | user/message(replace) | compaction/end` (`region.ts:191-217`); shadowed events stay in raw log | **Align with dsh's bracket model** | Our single-marker approach is replay-ambiguous (the projection change is not derivable from the log alone). dsh's bracket is the enterprise pattern: durable, detectable orphan lock on crash, deterministic replay. This is the single largest architectural gap vs. both upstream systems. |
| Tool-result externalization threshold | n/a | Ingest-time, all images/binaries (`blob-store.ts:213-245`) | Pruner `thresholdChars=8192` | **Adopt proposed >2k tokens (≈8k chars) to MinIO** | Sits between oh-my-pi (all binary at ingest) and dsh (8k char prune). Token-based aligns with our budget model. |
| Optional turns-based strategy | None | Not turn-based | Not turn-based | **Defer** | Neither proven system uses turn count as a trigger; both correctly use tokens. Add only as a non-default escape hatch. |
| Mid-turn compaction | No (compaction runs at `build()` before the call) | `midTurnEnabled: true` default (`compaction.ts:219`) | Yes via open-turn bracket (`invariant.ts:168-175`) | **Defer mid-turn; keep pre-call compaction for MVP** | Mid-turn adds real-time pressure handling but requires the bracket event model first. Phase 2. |
| Queue / steer | Not in scope of these files | First-class steer + followUp (`agent.ts:992-1049`) | Out of scope here | **Out of scope for compaction PRD** | Belongs in the session/event-model spec (`03_SESSION_EVENT_MODEL.md`), not compaction. Note oh-my-pi's design as a reference. |

### Net recommendation for the PRD

1. **Keep** token-budget trigger, mechanical fallback, tool-block validation, structured summary JSON, hard guard — these are genuine strengths.
2. **Adopt from dsh**: 80% auto threshold; retain tail ≈16% of window; multi-event compaction bracket in the append-only log with detectable orphan lock; `compactNow()` manual API; "summary must be strictly smaller" shrink check.
3. **Adopt from oh-my-pi**: balanced-boundary cut-point walk + split-turn summary; per-message head/tail truncation rather than whole-message drop; BlobStore-style ingest-time externalization extended to large tool results (>2k tokens → MinIO + summary+ref); `/context` live usage display as UX parity.
4. **Sequence**: (a) move to the dsh-style event bracket first (architectural); (b) then add bounded retain tail + cut-point walk; (c) then MinIO externalization + head/tail pruner; (d) then `/compact` manual API; (e) split-turn and mid-turn as Phase 2.

---

### Honest gaps / not-found notes

- oh-my-pi `/help` as a registered slash command: **(not found)** in `builtin-*.ts`. Likely a TUI keybinding.
- oh-my-pi `/list`, `/tree`, `/clone`, `/history`, `/cancel` as slash commands: **(not found)**. Equivalent functionality is delivered via `/session info`, `/context`, keyboard shortcuts (`popLastSteer`, `abort`).
- oh-my-pi deterministic mechanical-summary fallback: **(not found)** — it relies on retry + window halving + `/shake`, not a structured extract.
- dsh MinIO / object-storage externalization wired into compaction: **(not found)**. The `packages/spill/*` family exists but is not referenced by the compaction packages; dsh compaction prunes in place by character budget.
- dsh separate hard-guard constant: **(not found)** — only `thresholdRatio` and the overflow-retry path exist.
