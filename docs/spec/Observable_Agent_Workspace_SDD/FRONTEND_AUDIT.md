# Frontend Audit — Observable Agent Workspace Redesign

> Branch: `feat/frontend-c` (from `main`, commit `6335066`)
> Date: 2026-09-07
> Author: Frontend AI (ZCode)
> Status: Phase 0 deliverable. Blocks code changes until reviewed.

This audit follows `04_FRONTEND_SDD.md §1` (audit before rewrite) and
`09_BENCHMARK_REUSE_MATRIX.md §10` (reuse audit deliverable). It is the
single input to the implementation sequence in §Implementation Plan below.

---

## 1. Existing stack

| Concern | Current | Reuse verdict |
|---|---|---|
| Framework | React 19.2 (`react`, `react-dom`) | **keep** — no blocker |
| Build / dev | Vite 8.2, `@vitejs/plugin-react` 6 | **keep** |
| Language | TypeScript 6.0 (`tsc -b`) | **keep** |
| Router | **none** — single-page `App.tsx`, session is in-app state | **keep** (PRD has no routes; Command Palette is the nav surface) |
| State mgmt | Local React state in `App.tsx` + custom hooks (`useSession`, `useDisclosure`, `useReasoningDisclosure`). **No Redux/Zustand/Jotai.** | **keep** — projection is the source of truth, not a store lib |
| Styling | Plain CSS in `index.css` (tokens) + `styles/app.css` (components). **No Tailwind, no CSS-in-JS, no styled-components.** | **keep** — token-driven CSS matches SDD §22 "Tokens mandatory, no large design-system project" |
| Component primitives | Radix UI: `collapsible`, `dialog`, `dropdown-menu`, `scroll-area`, `separator`, `tooltip`. **No popover, no select, no tabs, no toggle-group, no command.** | **extend** — add `popover`, `select`/`combobox`, `tabs`, `toggle-group` (see §4) |
| Headless / virtualization | `@tanstack/react-virtual` 3.14 | **keep** — already the SDD-preferred virtualizer |
| Markdown | Custom minimal renderer `lib/markdown.tsx` (paragraph/heading/list/code, no tables/strikethrough/inline-code nesting depth) | **extend or replace** — current renderer is intentionally tiny; rich assistant output may need `react-markdown` + `rehype-raw`/`remark-gfm` (evaluate before adding) |
| Code / syntax highlight | `shiki` 4.4 (already integrated in `lib/highlight.ts`) | **keep** |
| Motion | **None.** Pure CSS `transition` + `@keyframes` + `prefers-reduced-motion` block in `index.css`. | **decide** — SDD §10 permits CSS-only; defer `motion` unless AnimatePresence-style presence is genuinely needed |
| Icons | `lucide-react` 1.40 | **keep** |
| SSE / WS client | Custom fetch + ReadableStream SSE parser (`lib/sse.ts`). No EventSource, no WebSocket. POST-stream + GET-reconnect hybrid. | **keep** — SDD §22 "keep current stable transport" |
| Transport reconnect | `streamSession(afterSeq)` + `Last-Event-ID`-style cursor + seq dedupe (`seenSeqs`) already implemented | **keep** |
| Event types | Generated from backend `session/event.py` via `scripts/gen_event_types.py` → `generated/event-types.ts` | **keep** — single source of truth with backend |
| Projection | `lib/projection.ts` is the **only** event→view-model reducer (`applyEvent`). Components never mutate state directly. Satisfies invariant #22. | **keep** — this IS the architecture SDD §2 asks for |
| Theme | CSS custom properties on `:root` + `[data-theme='light']`. JS sets `data-theme` before paint (`lib/theme.ts`). Equal-priority light/dark tokens exist. | **keep** — matches SDD §22 token architecture |
| Density | 4-tier `TraceDensity` (`compact|balanced|detailed|raw`) via `lib/density.ts`, persisted, applied as `[data-density]`. | **keep** — matches SDD Timeline density modes |
| Keyboard | Cmd/Ctrl+K palette, Cmd/Ctrl+Enter send, Esc interrupt (global), Tab order via DOM. | **extend** — Timeline arrow nav, model picker keyboard nav missing |
| Tests | Vitest (`projection`, `sse`, `runState`, `toolShapes`, `density`, `disclosure`, `eventKind`, `eventValidate`, `followLatest`, `format`, `highlight`, `markdown`, `reasoningCursor`, `commands`, `api`, `JsonTree`, `StepDetail`, `ToolCard`, `Composer`, `Conversation`) + perf suite (`vitest.perf.config.ts`) + Playwright E2E (`e2e/`) | **keep + extend** |

**Verdict: the framework is healthy and already implements the projection architecture the SDD mandates. There is no framework-level blocker and no reason to migrate.**

---

## 2. Current architectural shape (vs SDD target)

The projection pipeline SDD §2/§4 asks for is **already in place**:

```
SSE (lib/sse.ts)
  ↓
useSession hook (lib/sse → applyEvent)
  ↓
projection.ts  ← ONLY reducer, satisfies invariant #22
  ↓
ConversationState { turns, events, tools, run_status, ... }
  ↓
Conversation / StepDetail / Composer (read projections, never mutate)
```

What exists today:

- `App.tsx`: three-column shell (`SessionList` | `app-workspace{Conversation+Composer}` | `StepDetail`). Inspector collapses <1200px, rail collapses <820px. Matches PRD §5 IA.
- `Conversation.tsx`: chat + per-turn "Trace Ladder" (model↔tool interleaved execution chain) with the 4 density tiers applied inline.
- `StepDetail.tsx` (right Inspector): has its own 5 tabs — `timeline | chat | changes | terminal | artifacts` — plus a Run-level overview and event-level drill-down. **This is the key structural mismatch** (see §3).
- `Composer.tsx`: floating dock, send/stop, Esc hint. **Model picker is a native `<select>`** — the exact failure mode SDD §10/§C calls out.
- `CommandPalette.tsx`: Cmd/Ctrl+K, grouped items, keyboard nav, glass surface. Already exists.
- Run Pulse: implemented in `TopBar` + `SessionList` + `StepDetail` (icon+label+motion, never color-only). Matches SDD §4.2.

---

## 3. Current architectural problems (must fix for SDD)

### P1 — Workspace tabs vs Inspector tabs are inverted
**Today:** the *right Inspector* owns the 5 workspace tabs (Chat/Timeline/Changes/Terminal/Artifacts). The *center Workspace* is Chat-only with an embedded Trace Ladder.
**SDD target (`01_PRD §6`, `04_FRONTEND_SDD §6`):** the *center Workspace* owns the tabs (Chat | Timeline | Changes | Terminal | Artifacts). The *right Inspector* is a **contextual runtime inspector** (Run / selected Event / Tool / Artifact / Change detail) driven by selection.
**Impact:** Timeline is not first-class today; it lives as an inspector side-panel and as an inline trace ladder. This is the single largest structural change. It does not require rewriting the projection — Timeline already consumes `ConversationState.events` verbatim; it needs to be lifted into the workspace as its own surface.

### P2 — Composer is not an Agent Control Surface
- Model picker = native `<select>` (SDD §C explicit anti-pattern).
- No Agent / Reasoning / Permission / Branch controls. Composer is "textarea + select + send".
- No progressive disclosure (idle vs focused state).
- Permission mode selector is entirely absent — and the backend does not yet expose permission modes (see Contract Gap P-1).

### P3 — Capability awareness is hardcoded, not manifest-driven
`StepDetail` tabs are a fixed array. SDD §6/§25 requires tab visibility be driven by a `CapabilityManifest` so non-coding sessions don't show Terminal/Changes. Today this is implicit (tabs just render empty states). Needs `CapabilityManifest` from backend (Contract Gap C-1).

### P4 — Timeline virtualization is not wired for long histories
`@tanstack/react-virtual` is installed but the inspector-side Timeline does not use it. SDD §11/`07_ACCEPTANCE` requires bounded DOM for hundreds–thousands of events.

### P5 — Visual identity diverges from frozen decision
Current accent is **cool cyan** (`--accent: #56b8c9` dark / `#0e7f93` light). Frozen decision (`01_PRD §21`, `02_UI_UX §4`, `08_DECISIONS #14`) mandates a **neutral, slightly warm palette with a restrained pale-pink accent** (`#f1b3ca`/`#f4a5c4` dark; `#c96990`/`#b95680` light). This is a deliberate re-token, not a tweak. Surface token names also diverge from SDD §3's semantic model (`surface.canvas/chrome/workspace/elevated/overlay/glass/selected/hover/danger` vs current `bg-app/sidebar/workspace/inspector + surface-1/2/overlay`).

---

## 4. Missing capabilities (frontend)

| Need | Status | Decision |
|---|---|---|
| Popover / Combobox primitive | Radix `popover` NOT installed | **add** `@radix-ui/react-popover` (reuse, per §6) |
| Tabs primitive (workspace) | Radix `tabs` NOT installed | **add** `@radix-ui/react-tabs` |
| Toggle group (density, permission) | not installed | **add** `@radix-ui/react-toggle-group` (optional — current segmented control works) |
| Command primitive (palette/model picker) | custom `CommandPalette` exists | **extend existing** — do not pull in `cmdk` unless model picker needs richer fuzzy search than current palette provides |
| Timeline virtualization | lib installed, not wired | **wire `useVirtualizer` into Timeline workspace tab** |
| Capability manifest client | none | **defer** until backend exposes (Contract Gap C-1) |
| Permission mode client | none | **defer** until backend exposes modes (Contract Gap P-1); render placeholder "Unavailable" |
| Motion / presence | none | **decide per surface** — defer `motion` unless crossfade presence on tab/inspector transitions demands it |

**No duplicate dependencies.** The audit confirms no second icon lib, no second virtualizer, no second SSE client. Reuse-first is already the house style.

---

## 5. SDD gaps (where current frontend under-delivers vs spec)

1. No `RuntimeEvent.schema_version` / `durability` / `visibility` / `parent_event_id` / `capability` passthrough — current `AgentEvent` envelope is `{type,data,seq,run_id,step_id,time?,event_id?,session_id?,block_id?}`. Additive, non-breaking.
2. No unified Artifact surface in the workspace (artifacts only appear inside Inspector + tool results). SDD §6.5 wants a first-class Artifacts workspace tab.
3. No Changes workspace surface driven by real `FileChange[]` (Contract Gap CH-1).
4. No Terminal workspace surface (Contract Gap T-1 — backend has no terminal capability).
5. No `RunActions` (can_stop/can_retry/can_resume/latest_checkpoint_id) consumption — Stop is implemented ad hoc; Retry/Resume are not.
6. No `ContextUsage` with `source` labeling (Estimated tag missing).
7. No `ModelOption` rich metadata consumption (context_window/speed_tier/supports_*).
8. Inspector contextual precedence (event > run > session, SDD `04_FRONTSDD §12`) is partially implemented (`InspectorFocus` has run/tool/event/child kinds) but not artifact/change kinds.

---

## 6. Reuse candidates table (per `09_BENCHMARK §10`)

| Need | Current project | Candidate reuse | Decision | Reason |
|---|---|---|---|---|
| Model picker | native `<select>` | Radix Popover + custom list | **reuse Radix + custom** | searchable + keyboard nav + collision-aware; SDD §6/§C |
| Workspace Tabs | none (inspector has custom tabs) | Radix Tabs | **reuse** | accessible, keyboard, no hand-rolled focus trap |
| Popover (controls) | none | Radix Popover | **reuse** | collision-aware positioning, focus |
| Timeline virtual list | lib installed, unused | `@tanstack/react-virtual` | **reuse (wire it)** | long histories, SDD §11 |
| Command Palette | custom exists | keep custom | **keep** | already keyboard-first + glass; extend for model/agent actions |
| Run Pulse | custom exists | keep custom | **keep** | signature interaction (SDD §C custom-only) |
| Chat/Timeline projection | `projection.ts` | keep | **keep** | already event-first, single reducer |
| Markdown | custom minimal | evaluate `react-markdown`+`remark-gfm` | **evaluate** | only if rich output (tables, nested lists) becomes a real gap |
| Motion | CSS only | CSS only (defer `motion`) | **defer** | SDD §10 permits CSS; add `motion` only if presence animations prove insufficient |

---

## 7. Contract Gap report (`03_RUNTIME_EVENT_CONTRACT.md` vs current backend)

Per SDD §13 and AGENTS.md §13, frontend must NOT invent a second truth. The following are **CONTRACT GAP** items the Backend AI must resolve. Frontend will render `Unavailable`/`—` for each until the contract is met.

### CG-1 — Event envelope missing normalized fields
- **Current backend envelope:** `{type, data, seq, run_id, step_id, time?, event_id?, session_id?, block_id?}`
- **Contract (`03_CONTRACT §3`):** adds `schema_version`, `turn_id`, `status`, `trace_id`, `parent_event_id`, `capability`, `durability: "durable"|"transient"`, `visibility`.
- **Frontend impact:** cannot distinguish durable vs transient at the envelope level (currently inferred from `STREAM_ONLY_TYPES`); cannot build capability-aware UI from envelope; trace_id only available in `run/completed` data, not on every event.
- **Proposed backend change:** add additive optional fields to the envelope emitted by `session/event.py`; regenerate `event-types.ts`. Non-breaking.

### CG-2 — Event family naming + coverage
- **Contract families (`03_CONTRACT §4`):** `session.created/updated`, `run.status/interrupted`, `llm.started/completed/failed`, `tool.started/completed/failed/progress`, `permission.requested/resolved`, `retry.scheduled/started`, `checkpoint.created`, `recovery.started/completed`, `artifact.created/updated`, `change.created/updated`, `context.compacted`.
- **Current backend (`generated/event-types.ts`):** `session/started|resumed|forked`, `run/started|completed|failed`, `user/message`, `model/started|delta|completed|failed`, `tool/call|result`, `operation/reconcile-required`, `artifact/created`, `context/compacted`, `memory/degraded`, `tool/failure-guard`, `model/fallback`, `agent/delegation-*`, `reasoning/*`, `tool/output_delta`, `text/delta`.
- **Gaps:** No `permission.requested/resolved` events (approval is a blocking POST, not an event). No `retry.*`. No `checkpoint.created`. No `recovery.*` events (POST /recover returns full event array, no lifecycle events). No `change.*`. No `run.interrupted` (cancellation surfaces as `run/failed` with `reason='cancelled'`).
- **Frontend impact:** cannot render Waiting-Approval Run Pulse from events; cannot show retry/checkpoint in Timeline; cannot show recovery lifecycle.
- **Proposed backend change:** (a) emit `permission.requested`/`permission.resolved` as stream events (keep POST /approve as the decision channel); (b) decide whether to add `run/interrupted` or keep `run/failed.reason='cancelled'` (frontend already handles the latter — document the choice); (c) add `retry.*`/`checkpoint.*`/`recovery.*` if/when those features ship.

### CG-3 — Permission mode selector (Composer)
- **Contract (`03_CONTRACT §9/§10`):** `PermissionRequestedData{allowed_decisions[]}`, `PermissionDecision` enum, permission modes (`ask`/`edit_auto`/`full_access`) exposed via an endpoint.
- **Current backend:** blocking `POST /api/sessions/{id}/approve {approved: bool}`. No modes endpoint. No `allowed_decisions`.
- **Frontend impact:** SDD §8.2 requires a Permission control in the Composer. **Frontend will NOT ship a fake selector.** It will render a permission placeholder labelled "Unavailable — backend does not expose permission modes" until the contract is implemented.
- **Proposed backend change:** expose `GET /api/permission-modes` (or include in capability manifest); emit `permission.requested`/`resolved` events with `allowed_decisions`.

### CG-4 — Model metadata richness
- **Contract (`03_CONTRACT §16`):** `ModelOption{id, display_name, provider, is_default, is_available, context_window?, speed_tier?, supports_reasoning_summary?, supports_tools?, supports_vision?, metadata_source?}`.
- **Current backend (`GET /api/models`):** `{name, provider, model, default}[]` only.
- **Frontend impact:** ModelPicker cannot show "Provider · Speed · Context" row (SDD §11 visual). Will show name + provider only; other metadata hidden.
- **Proposed backend change:** extend `/api/models` payload additively.

### CG-5 — CapabilityManifest
- **Contract (`03_CONTRACT §17`):** `CapabilityManifest{id, display_name, surfaces{chat,timeline,changes,terminal,artifacts}, actions?{permissions,stop,retry,resume}}`.
- **Current backend:** none. Tabs are hardcoded in `StepDetail.tsx`.
- **Frontend impact:** cannot do capability-aware tab visibility (SDD §6/§25). Frontend will keep current implicit hiding (empty states) and wire the manifest client as soon as backend exposes it.
- **Proposed backend change:** expose `GET /api/capabilities` (or derive from session metadata).

### CG-6 — RunActions / Retry / Resume / Checkpoint
- **Contract (`03_CONTRACT §12/§13`):** `RunActions{can_stop, can_retry, can_resume, latest_checkpoint_id?}` + `CheckpointCreatedData`.
- **Current backend:** Stop = `POST /cancel` (works). Recover = `POST /recover` (works, returns events). No retry. No checkpoint events. No `RunActions` endpoint.
- **Frontend impact:** Retry/Resume controls cannot be shown truthfully. Stop is already wired.
- **Proposed backend change:** expose `RunActions` per run (could be derived and attached to `run/started` data); add `checkpoint.created` if checkpointing ships.

### CG-7 — ContextUsage
- **Contract (`03_CONTRACT §18`):** `ContextUsage{used_tokens?, max_tokens?, percentage?, source: "provider"|"backend_estimate"|"unknown", compacted?}`.
- **Current backend:** `context/compacted` event exists (post-compaction only). No live usage.
- **Frontend impact:** Inspector Context section will show "—" / "Estimated unavailable" until live usage ships.

---

## 8. Required frontend changes (summary, ordered by phase)

1. **Tokens realignment (Phase 1).** Introduce SDD §3 semantic surface tokens (`surface.canvas/chrome/workspace/elevated/overlay/glass/selected/hover/danger`), switch accent to pale-pink (`#f1b3ca`/`#c96990`), warm the neutrals. Keep existing token names as legacy aliases (already partially done in `index.css`) to avoid a flag-day rewrite.
2. **Workspace tabs (Phase 1/4).** Lift Chat / Timeline / Changes / Terminal / Artifacts into a workspace `Tabs` surface. Move the contextual runtime detail into a slimmer Inspector. Reuse `projection.ts` unchanged.
3. **Composer rebuild (Phase 2).** Replace `<select>` with Radix Popover + custom ModelPicker. Add control row (Context/Agent/Model/Reasoning/Permission placeholders). Progressive disclosure on focus. Stop stays.
4. **Timeline virtualization (Phase 4).** Wire `@tanstack/react-virtual` into the workspace Timeline tab with variable row height and live-tail behavior.
5. **Capability-aware tabs (Phase 6, gated on CG-5).** Hardcoded today; wire to manifest when backend ships.
6. **Permission inline surface (Phase 5, gated on CG-3).** Placeholder now; real surface when backend emits permission events.
7. **Perf / a11y / visual QA (Phase 8).** Long-timeline benchmark, reduced-motion audit, WCAG 2.2 AA pass, light/dark coherence at 1024/1280/1440.

---

## 9. Backend dependencies / blockers

| Blocker | Blocks | Mitigation on frontend while waiting |
|---|---|---|
| CG-3 permission modes + events | Composer permission control; inline approval surface; Waiting-Approval Run Pulse | Render placeholder "Unavailable"; keep current blocking approval card (it works today) |
| CG-5 CapabilityManifest | Capability-aware tab visibility | Keep implicit hiding via empty states |
| CG-4 rich model metadata | ModelPicker "Provider · Speed · Context" row | Show name + provider only |
| CG-6 RunActions / checkpoint events | Retry/Resume controls | Hide controls (do not fake) |
| CG-7 ContextUsage | Live context meter in Inspector | Show "—" / "Unavailable" |
| CG-2 retry/checkpoint/recovery/permission events | Timeline rows for those lifecycle events | Omit (do not fabricate) |

None of these block Phase 1 (tokens/shell) or Phase 2 (Composer structure with placeholders). They block the *real* data behind specific controls, which the frontend will truthfully mark unavailable per SDD §13.

---

## 10. Implementation sequence (this branch, `feat/frontend-c`)

Derived from `06_IMPLEMENTATION_PLAN.md`, adapted to the audit findings above. Each phase = implement → lint/typecheck → tests → browser QA → visual QA → diff review → commit.

- **Phase 0 — Audit (this doc).** ✅ Done.
- **Phase 1 — Design tokens + shell refinement.** Realign tokens to SDD §3/§4 (pink accent, warm neutrals, semantic surface model). Refine the three-column shell geometry. Lift workspace tabs into the center. No behavior regression. Gate: Workspace dominates chrome; theme coherent; light/dark equal.
- **Phase 2 — Composer as Agent Control Surface.** Radix Popover ModelPicker (searchable, keyboard nav). Control row with Context/Agent/Model/Reasoning/Permission. Permission = placeholder (CG-3). Progressive disclosure. Gate: no native `<select>` remains; model metadata from backend only.
- **Phase 3 — Runtime event foundation (already mostly there).** Add envelope passthrough for `schema_version`/`durability`/`visibility` where backend emits them (additive). Confirm reconnect/dedupe still green.
- **Phase 4 — Timeline workspace tab + Inspector contextual.** Move Timeline to workspace. Wire TanStack Virtual. Inspector becomes Run/Event/Tool/Artifact/Change contextual. Selection drives Inspector. Gate: click Tool event → exact args/result in Inspector; long history scrolls smoothly.
- **Phase 5 — Permission/Stop/Retry/Resume (gated on CG-3/CG-6).** Inline approval surface when permission events ship. Retry/Resume when RunActions ship. Until then: truthful "Unavailable".
- **Phase 6 — Capability-aware Changes/Terminal/Artifacts (gated on CG-5).** Tab visibility from manifest. Real Changes/Terminal/Artifacts surfaces.
- **Phase 7 — Command Palette + Search.** Extend existing palette with model/agent actions and backend search (gated on backend search scopes).
- **Phase 8 — Perf / A11y / Polish.** Long-timeline benchmark, reduced-motion, WCAG 2.2 AA, responsive QA at 1024/1280/1440, light/dark coherence.
- **Phase 9 — Integrated acceptance + merge.** Per `06_PLAN §9`.

**Starting point:** Phase 1 (tokens + shell), because every later surface depends on the token realignment and no SDD-aligned visual can be produced on the current cyan/purple accent.
