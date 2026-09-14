# Frontend Streaming UI Implementation Specification

> **Audience**: Frontend engineers / coding agents.
>
> **Read order**: `01_AGENT_RUNTIME_STREAMING_UI_PRD_v2.md` → `02_RUNTIME_STREAMING_PROTOCOL_SPEC.md` → this file.
>
> **Purpose**: Define frontend architecture, component boundaries, streaming state machines, library strategy, visual behavior, performance constraints, accessibility, and testing. This is not permission to rewrite backend/business logic.

---

# 1. Frontend Architectural Goal

Move from “completed events rendered as logs” to a **live projection system**:

```text
Transport (WS/SSE/AI SDK stream)
        ↓
Ingress Adapter
        ↓
Runtime Schema Validation
        ↓
Canonical Event Store
        ↓
Incremental Projection Reducers
        ↓
Render Scheduler / Batching
        ↓
Logical Runtime Blocks
        ├── Continuous Agent Stream
        └── Run Inspector
```

Presentation components must not parse provider-specific network events directly.

---

# 2. Audit Before Implementation

Before coding, identify:

- React/framework/version;
- state management library;
- current transport client;
- event type definitions;
- Run Inspector component tree;
- existing Compact/Balanced/Detailed/Raw behavior;
- Markdown renderer;
- syntax highlighter;
- icon package;
- animation package;
- command menu package;
- virtualization package;
- runtime schema validator;
- theme/tokens system;
- testing stack;
- browser E2E tooling;
- bundle tooling.

Do not add a package that duplicates a mature dependency already present.

---

# 3. Library Strategy / Technical Spikes

## 3.1 assistant-ui

Perform a spike, not a blind migration.

Evaluate whether its primitives/architecture can provide:

- streaming reasoning disclosure;
- tool states;
- streaming args/result surfaces;
- custom renderers;
- accessibility;
- controlled/open state;
- styling freedom.

Adopt useful primitives if they can be fully themed and can consume the project's canonical runtime projection without constraining the Run Inspector.

If not, borrow architecture patterns and keep custom product components.

## 3.2 AI SDK / AI SDK UI

The owner is willing to perform a broader migration if the outcome is better.

Frontend team must evaluate:

- existing runtime transport;
- AI SDK data stream protocol/client;
- `useChat`/streaming parts where applicable;
- tool part state;
- reasoning part support;
- reconnect behavior;
- compatibility with a Python/FastAPI backend if applicable;
- ability to preserve canonical event log and Inspector.

### Decision rule

If AI SDK can become the primary streaming client/protocol layer **without losing Harness semantics**, prefer it even if migration is nontrivial.

If AI SDK requires flattening or discarding the project's richer event model, keep the canonical event architecture and use AI SDK only selectively or not at all.

The UI component tree should depend on **logical projected blocks**, not directly on a vendor SDK's raw message object.

## 3.3 Virtualization

Default candidate: **TanStack Virtual**.

Reasons:

- headless;
- styling independent;
- dynamic-size support;
- suitable for long runtime streams.

React Virtuoso may be chosen if codebase spike shows materially better dynamic-height/follow behavior.

Document the choice with measured evidence.

## 3.4 Motion

Use Motion (if already present or justified) only for structural interactions:

- disclosure height/layout transition;
- Inspector drawer/panel;
- selection pulse;
- semantic state transition;
- Todo item state.

Never animate each token/delta with Motion.

## 3.5 Runtime validation

Use current validator; otherwise a mature library such as Zod/Valibot.

Validation happens at ingress boundary, not inside every component.

---

# 4. Canonical Client State

Conceptual store:

```ts
interface RuntimeClientState {
  sessions: Record<string, SessionProjection>
  runs: Record<string, RunProjection>
  activeSessionId?: string
  activeRunId?: string
  ui: RuntimeUIState
}

interface RunProjection {
  runId: string
  status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'
  lastAppliedSeq: number
  logicalBlocks: LogicalRuntimeBlock[]
  blockById: Record<string, LogicalRuntimeBlock>
  rawEventIndex: RawEventIndex
  inspectorNodes: InspectorLogicalNode[]
}
```

Do not store one giant mutable message blob that is reparsed wholesale on every delta.

---

# 5. Projection Reducers

Use incremental reducers keyed by event/block ID.

Examples:

```text
reasoning/started   → create ReasoningBlock
reasoning/delta     → append chunk to existing block
reasoning/completed → finalize block metadata

tool/call_started  → create ToolBlock
tool/output_delta  → append to output channel buffer
tool/result        → terminalize ToolBlock

text/delta          → append FinalAnswer block
```

Requirements:

- idempotent by `event_id`/seq;
- no duplicate append on reconnect;
- no O(n) full-list rewrite for every token if avoidable;
- stable block object identity where practical;
- derived Inspector logical nodes updated incrementally.

---

# 6. Render Scheduler

The event store should receive/apply canonical events immediately, but React DOM updates should be batched.

Recommended pattern:

```text
network event
  ↓
validate + reducer immediately
  ↓
mark block dirty
  ↓
requestAnimationFrame / 16–32ms scheduler
  ↓
notify/render dirty projections
```

Requirements:

- flush immediately on important lifecycle boundary if needed;
- avoid deliberate “typing delay”;
- backlog catch-up may increase chunk size / reduce animation work;
- background tabs lower render frequency;
- when foreground resumes, reconcile current projection quickly.

Do not use a fixed `setInterval(showNextCharacter)` as the primary stream mechanism.

---

# 7. ReasoningBlock Component

Recommended component structure:

```text
<ReasoningBlock>
  <ReasoningHeader />
  <CollapsedReasoningViewport /> or <ExpandedReasoningSurface />
</ReasoningBlock>
```

Both views consume the same block buffer.

## 7.1 Header

Streaming:

```text
[brain] 正在思考 · 36 秒                                  [chevron]
```

Completed:

```text
[brain] 思考 · 持续了 36 秒                               [chevron]
```

Interrupted:

```text
[brain] 思考 · 中断于 36 秒                               [chevron]
```

Duration ticker must be isolated so updating seconds does not rerender the full reasoning text subtree.

## 7.2 Active brain icon

Use a custom semantic glyph or carefully themed mature icon.

Active liveness:

- subtle 1.5–2.5s breathing/stroke-opacity;
- no continuous rotation;
- no bright glow;
- disabled/reduced under `prefers-reduced-motion`.

## 7.3 Collapsed forward-reading viewport

This is a key differentiating interaction.

Target behavior:

- one line only;
- source is the accumulated live reasoning text;
- viewing cursor begins at the beginning and advances forward in reading order;
- incoming text extends the readable timeline;
- viewport movement is continuous/lightweight rather than discrete jumpy replacements;
- do not loop/repeat earlier text;
- do not call another LLM for summary;
- edge fade via CSS mask/gradient or equivalent;
- prefer compositor-friendly `transform`/mask;
- avoid measuring every character repeatedly.

### Suggested implementation concept

Maintain presentation-only state:

```ts
collapsedReadCursor
collapsedVelocity
```

The source buffer remains canonical. The cursor advances based on time/available text and may accelerate modestly when backlog grows.

Do not mutate canonical content to implement the animation.

### Backlog policy

The visual viewport should not become unboundedly behind a rapidly streaming model.

Implement bounded catch-up behavior, e.g.:

- normal reading velocity while backlog small;
- faster transform progression while backlog exceeds threshold;
- on block completion, settle to latest relevant segment within a short bounded interval;
- opening the block always exposes full accumulated text immediately.

Exact thresholds are benchmark/UX tuning parameters.

## 7.4 Expanded surface

- render incoming text in a stable text container;
- natural height for short content;
- transition to max-height scrolling after threshold;
- auto-follow only while user is near bottom;
- user scroll-up immediately suspends follow;
- show subtle “↓ 跳到最新” control;
- jump action scrolls to latest and reenables follow.

## 7.5 Auto disclosure state

Suggested state:

```ts
interface DisclosureState {
  open: boolean
  userInteracted: boolean
  followLatest: boolean
}
```

Rules:

- new active reasoning opens in Balanced/Detailed by default;
- completed reasoning may auto-collapse if `userInteracted=false`;
- manual toggle sets `userInteracted=true`;
- incoming delta never reopens a manually collapsed block;
- local presentation state resets when historical session is reopened unless product later chooses persistence.

---

# 8. Markdown Strategy

## Streaming phase

Use one of:

- plain rich text;
- lightweight incremental Markdown subset;
- renderer known to avoid full expensive parse on every micro-delta.

Avoid:

- syntax highlighting on every token;
- full document AST reconstruction per event;
- layout-heavy plugins while block is unstable.

## Completed phase

After stabilization:

- full Markdown parse;
- lazy syntax highlighting;
- final link processing;
- high-quality code block controls.

Prefer existing project packages. If adding a highlighter such as Shiki, lazy-load it and do not route every live delta through it.

---

# 9. ToolBlock Component

Recommended:

```text
<ToolBlock>
  <ToolSummaryRow />
  <ToolInputSection />
  <ToolOutputSection />
  <ToolRawLink />
</ToolBlock>
```

## 9.1 Summary row

```text
✓  ⌘ bash    npm run test                                      8.2s
```

Use semantic icon by tool kind:

- Search/Read → magnifier/document;
- Bash/Terminal → terminal;
- Write/Edit → pencil/file edit;
- generic → wrench;
- MCP → connector;
- Skill → sparkle/wand;
- Delegation → custom agent glyph.

## 9.2 Partial args

Center row while args are incomplete:

```text
⌘ Preparing bash…
```

Do not render broken JSON.

Inspector may display partial args with explicit “streaming/incomplete” state.

## 9.3 Output renderer

Tool outputs may be:

- plain text;
- terminal stdout/stderr;
- JSON;
- code/diff;
- file list;
- structured result.

Use a renderer registry, not one giant conditional component.

```ts
rendererFor(toolKind, outputType)
```

## 9.4 Streaming terminal

Maintain separate buffers:

```ts
stdoutChunks
stderrChunks
```

Display can interleave according to event sequence while preserving channel metadata.

Requirements:

- bounded DOM;
- virtualized/tail view for huge output;
- auto-follow semantics matching reasoning;
- wrap toggle;
- copy;
- search/full-output affordance if supported;
- no layout jank on every newline.

---

# 10. Semantic Event Renderer Registry

Avoid hardcoding every runtime type in a monolithic `Message.tsx`.

Concept:

```ts
const runtimeRenderers = {
  reasoning: ReasoningBlock,
  progress: ProgressBlock,
  search: SearchBlock,
  read: ReadBlock,
  tool: ToolBlock,
  skill: SkillBlock,
  mcp: MCPBlock,
  delegation: SubagentBlock,
  plan: TodoPlanBlock,
  answer: FinalAnswerBlock,
  notice: RuntimeNoticeBlock,
}
```

Unknown event types degrade to a generic debug-safe block rather than crash.

---

# 11. Run Inspector Frontend

## 11.1 Logical node model

Do not render each token delta as a top-level timeline row in normal mode.

Projection groups raw events into logical nodes:

```ts
interface InspectorLogicalNode {
  id: string
  kind: 'reasoning' | 'tool' | 'model' | 'answer' | 'delegation' | ...
  status: string
  startSeq: number
  endSeq?: number
  rawEventIds: string[]
  summary: string
  durationMs?: number
}
```

## 11.2 Raw drill-down

Raw mode or detail drawer exposes raw events/chunks.

This preserves the project's deeper Harness observability without flooding the default timeline.

## 11.3 Follow active state

```ts
followActive: boolean
selectedNodeId?: string
```

- default true;
- manual node selection sets false;
- explicit “Follow current activity” restores true;
- new delta does not steal historical selection.

## 11.4 Cross-navigation

Maintain mapping:

```text
logicalBlockId ↔ InspectorNodeId ↔ raw event IDs
```

Center “Inspect” selects Inspector node.

Inspector selection scrolls center to block and emits a short highlight.

---

# 12. Virtualization Strategy

The center and Inspector can both become long.

Requirements:

- virtualization must support dynamic row height because disclosures change height;
- expansion/collapse remeasurement must not jump scroll position unexpectedly;
- auto-follow to latest must work with virtualization;
- search/jump-to-event must be able to scroll to an offscreen logical node;
- overscan tuned for smoothness without huge DOM;
- active streaming block may be pinned/treated specially if virtualization library needs it.

Benchmark with:

- 1k nodes;
- 10k nodes;
- mixed expanded heights;
- active bottom streaming;
- rapid Inspector updates.

---

# 13. Compact / Balanced / Detailed / Raw Projection Policy

The global mode should be a policy layer, not four separate component trees.

Concept:

```ts
const modePolicy = {
  compact: { ... },
  balanced: { ... },
  detailed: { ... },
  raw: { ... },
}
```

Policy may control:

- default disclosure;
- metadata visibility;
- model event visibility;
- Tool Input/Output level;
- reasoning default open state;
- Raw event exposure.

Manual local user disclosure overrides defaults.

---

# 14. Visual System

## 14.1 Tokens

Use/extend a centralized token system for:

- canvas/surface colors;
- text primary/secondary/tertiary;
- semantic success/error/warning/accent;
- hairlines;
- spacing;
- radius;
- shadow/elevation;
- typography;
- motion duration/easing;
- z-index layers.

Do not scatter magic colors/radii through components.

## 14.2 Typography

Priorities:

1. user prompt and final answer readability;
2. runtime event scanability;
3. monospace technical metadata precision.

Use system-quality UI fonts; keep code/IDs in a readable monospace.

Runtime metadata should not be so light that it fails contrast.

## 14.3 Cards

Default question:

> Does this information actually require a card?

Most event rows should not.

Use enclosed surfaces mainly for:

- expanded Input/Output;
- bounded terminal/code/JSON;
- Todo when expanded;
- Command Palette;
- temporary floating controls.

## 14.4 Light and Dark

Both are first-class.

Dark:

- not pure black;
- multiple surface elevations;
- muted separators;
- restrained cyan/accent if the product already uses it.

Light:

- not a gray enterprise dashboard;
- near-white canvas;
- soft neutral hierarchy;
- restrained blue/cyan accents.

---

# 15. Iconography

## Generic controls

Reuse a mature library (e.g. existing Lucide/Iconify set).

## Product semantic glyphs

A small consistent custom set may be created for:

- Thinking brain;
- Search/Read character;
- Skill;
- Delegation/Subagent;
- Memory/RAG later.

Requirements:

- 16–18px default visual size;
- consistent stroke/optical weight;
- recognizable at small size;
- not enclosed in repeated circles by default;
- active animation subtle only.

Do not copy proprietary icon assets from reference products.

---

# 16. Animation / Transition

Suggested ranges (tune visually):

- hover/focus: ~100–160ms;
- disclosure/layout: ~160–240ms;
- Inspector panel: ~180–280ms;
- state text crossfade: ~120–200ms;
- highlight pulse: ~600–900ms.

Use spring only where it feels controlled; do not make dense developer UI bounce.

Reasoning state transition:

```text
正在思考 · 35 秒
       ↓ smooth crossfade/width-stable change
思考 · 持续了 36 秒
```

Avoid layout shifts by reserving sensible header space/tabular numerals.

---

# 17. Auto-follow Primitive

Reasoning, terminal output, and long answer views can share a reusable follow controller.

Concept:

```ts
useFollowLatest({
  thresholdPx,
  onUserScrollAway,
  onJumpToLatest,
})
```

State:

- following;
- suspended-by-user;
- catch-up/reconcile.

This should be a reusable primitive, not duplicated fragile scroll code in each component.

---

# 18. Performance Engineering

## 18.1 Avoid expensive per-delta work

Do not per token:

- call Motion;
- parse full Markdown;
- syntax highlight;
- measure entire text;
- rebuild full event list;
- serialize huge JSON.

## 18.2 Store design

Use selectors so only dirty blocks rerender.

Bad:

```text
one delta → replace entire run object → every row rerenders
```

Good:

```text
one delta → update block buffer → notify block selector + lightweight Inspector aggregate
```

Exact state library should match current project unless benchmark shows it is the bottleneck.

## 18.3 Background tab

When `document.visibilityState !== 'visible'`:

- continue canonical event ingestion if transport permits;
- reduce render notifications;
- avoid 60fps decorative animation;
- reconcile current state on foreground.

## 18.4 Memory

Use bounded/raw event caches where possible. Raw events that can be refetched from backend need not all remain deeply duplicated in React state forever.

---

# 19. Accessibility Implementation

- disclosure headers are buttons;
- `aria-expanded` + `aria-controls`;
- icon-only controls have accessible names;
- status icon + text, never color-only;
- Command Palette focus trap;
- keyboard navigation in Inspector;
- avoid `aria-live` on every token; announce coarse status transitions;
- reduced-motion disables reading-viewport movement or changes to non-animated updates while preserving information;
- ensure focus remains stable when virtualized rows mount/unmount.

---

# 20. Error and Degraded UI States

## Invalid event

Do not white-screen. Log/report and optionally expose a small Debug notice.

## Seq gap

Show normal UI while recovery occurs if current projection is still coherent. Inspector may display a subtle “reconciling” state.

## Provider interrupted

Reasoning/text block remains with interrupted status.

## Reconnect

Do not clear stream. Show minimal transport status only if reconnect lasts long enough to matter.

Avoid aggressive toast spam for transient reconnects.

---

# 21. Browser Test Matrix

At minimum verify:

- Chromium/Chrome current;
- Windows desktop at 1280/1440/1600/1920 widths;
- light/dark;
- Inspector open/closed;
- all four modes;
- keyboard-only interaction;
- reduced motion.

If the product supports additional browsers, add them to the matrix.

---

# 22. Frontend Tests

## Unit

- reducer idempotency;
- block lifecycle;
- disclosure auto/manual rules;
- follow-latest state;
- mode policy;
- semantic renderer selection;
- Inspector grouping;
- malformed event fallback.

## Component

- collapsed live reasoning updates;
- expand while streaming without reset;
- collapse while streaming without stopping;
- completed header transition;
- Tool partial args state;
- stdout/stderr streaming;
- Todo updates;
- Raw JSON folding.

## E2E

- full reasoning → tool → reasoning → answer scenario;
- Inspector center cross-navigation;
- reconnect/resume;
- history reopening;
- user scroll away and jump-to-latest;
- mode switching during active stream;
- large output;
- Command Palette.

## Performance

- first visible delta;
- 10k logical nodes;
- large terminal output;
- memory growth during 30–60 minute synthetic session;
- CPU usage background tab;
- mode switch and Inspector toggle latency.

Critical tests enter CI; heavier browser performance runs may be nightly/release-gated.

---

# 23. Suggested Implementation Phases

These are dependency boundaries, not final tickets. `/tickets` should split them further.

## Phase 0 — Audit / ADR / Baseline

- identify current transport;
- identify provider streaming support;
- benchmark current UI;
- dependency audit;
- AI SDK/assistant-ui/virtualization spikes;
- transport ADR.

No visual rewrite yet.

## Phase 1 — Canonical Event Ingress + Projection

- runtime schema validator;
- canonical event store;
- reasoning/text/tool reducers;
- compatibility adapter for existing events;
- unit tests.

## Phase 2 — Reasoning Streaming UI

- ReasoningBlock;
- live header;
- forward-reading collapsed viewport;
- expanded stream;
- disclosure state;
- follow latest;
- performance tests.

## Phase 3 — Tool Streaming

- partial args state;
- stdout/stderr;
- bounded terminal;
- large-output strategy;
- semantic tool row.

## Phase 4 — Inspector Logical/Raw Dual Layer

- logical grouping;
- raw drill-down;
- live follow;
- cross-navigation.

## Phase 5 — Semantic Event System

- Search/Read;
- Skill;
- MCP;
- Subagent;
- Todo;
- custom semantic glyphs.

## Phase 6 — Four Modes + Visual Polish

- policy layer;
- Light/Dark tokens;
- typography/spacing;
- selective motion;
- top bar;
- Command Palette.

## Phase 7 — Virtualization / Reconnect / History Hardening

- 10k nodes;
- snapshot reconcile;
- history replay;
- background tab;
- memory/performance fixes.

## Phase 8 — Production Gates

- E2E;
- accessibility;
- telemetry;
- bundle/performance regression gate;
- final code review.

---

# 24. Code Review Checklist

Every frontend code review should ask:

### Runtime correctness

- Is the event handled idempotently?
- Can reconnect duplicate it?
- Does sequence/order remain correct?
- Does history replay the same logical block?

### Streaming

- Is this true stream data or fake playback?
- Does collapse/open preserve the same buffer?
- Does user interaction override auto behavior?

### Performance

- Does a delta rerender only what is needed?
- Is Markdown/highlighting deferred appropriately?
- Is DOM bounded?
- Is expensive motion avoided?

### UX

- Is the summary understandable without opening Raw?
- Does the event use the correct semantic glyph?
- Is the center less detailed than Inspector but still useful?
- Are states visually calm and clear?

### Accessibility

- Is it keyboard accessible?
- Is state communicated beyond color?
- Does streaming avoid screen-reader spam?

### Scope

- Did this ticket modify unrelated Agent logic?
- Did it introduce a new dependency unnecessarily?

---

# 25. Frontend AI Handoff Prompt

> Read `01_AGENT_RUNTIME_STREAMING_UI_PRD_v2.md`, `02_RUNTIME_STREAMING_PROTOCOL_SPEC.md`, and `03_FRONTEND_STREAMING_UI_IMPLEMENTATION_SPEC.md` completely. Do not start by editing CSS. First audit the existing frontend architecture, runtime event types, WebSocket/SSE client, state store, Run Inspector, four display modes, theme/tokens, Markdown renderer, icon/animation/virtualization packages and tests. Run an implementation-level grill-me only for facts that cannot be resolved by reading the repo. Perform technical spikes for assistant-ui and AI SDK; a broader AI SDK migration is acceptable if it measurably improves the system and preserves the Harness canonical event model, Inspector, replay and provider compatibility. Prefer TanStack Virtual unless a measured spike favors another library. Reuse mature components instead of hand-writing generic infrastructure. Then generate small reversible tickets. Implement true reasoning/text/tool streaming first; do not fake it with fixed typewriter playback. Keep the right Run Inspector more detailed than the center stream. Treat latency, reconnect, long-session performance, accessibility and visual polish as release requirements, not optional cleanup.
