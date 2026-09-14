# Product PRD — Observable Agent Workspace

> Shared by Frontend and Backend.  
> This document defines **what the product must do and how it should behave**, not the implementation details.

---

# 1. Product statement

Redesign the current `intelligence-agent` Web UI from a visually weak chat-first demo into a **Premium AI Workspace + Developer Workbench** centered on observable Agent execution.

The default experience should remain approachable and visually calm, while Timeline and Inspector expose genuine Harness-level technical depth.

The interface must feel closer to:

> **Agent workspace + runtime inspector + developer tool**

than:

> generic AI chat page + model dropdown.

---

# 2. Product goals

## 2.1 Primary goals

1. **Professional visual quality** comparable in polish to modern developer products.
2. **Observable by default** — important Agent actions are visible and inspectable.
3. **Real runtime data** — Timeline and Inspector reflect backend events, not UI guesses.
4. **Fast interaction** — streaming, navigation, selection, and panels must feel immediate.
5. **Composable for future capabilities** — Coding, Research, RAG, Finance, and other capabilities can surface appropriate tabs/actions without redesigning the shell.
6. **Keyboard-first** for power-user workflows.
7. **One frontend/backend runtime language** through a shared event contract.

## 2.2 Non-goals

- Mobile-first product design.
- Copying Linear/ZCode/Raycast branding.
- Building a decorative analytics dashboard.
- Showing unsupported metrics as fake data.
- Treating every runtime event as a chat bubble.
- Forcing every capability to expose Coding-only tabs.

---

# 3. Target audience

Two equal product targets are required:

1. **The owner/developer using the Agent regularly** — primary daily-use target.
2. **Future public/developer users** — architecture and interaction should not depend on hidden personal assumptions.

The UI should also present well in demos/interviews, but demo appearance must not override real usability.

---

# 4. Product identity

## 4.1 Benchmark synthesis

### Linear — adopt

- calm hierarchy;
- dense but scannable information;
- dimmer navigation chrome;
- fewer unnecessary separators;
- structure expressed through spacing/surfaces/typography before borders;
- consistent headers/navigation controls.

### ZCode — adopt

- composer as an Agent control surface, not only a text box;
- workspace/task context near the composer;
- model/execution/branch/context controls placed where the user acts;
- `@` references, commands, skills, and execution mode concepts where applicable;
- risk/permission state visible during execution.

### DeepSeek Harness — adopt

- authoritative backend state;
- runtime events as first-class data;
- Chat and Trajectory/Timeline as separate projections of execution history;
- reconnect/replay that reconstructs stable views;
- observability integrated into the main product instead of a separate debug dashboard.

### Raycast — adopt

- native-feeling overlays;
- tasteful Liquid Glass on transient/control surfaces;
- fast, keyboard-first interactions;
- no transition flicker;
- polished focus, popover, hover, and motion details.

## 4.2 Original signature

This product must not look like a collage. Its own signature is:

### Run Pulse

A unified visual language for current execution state.

Canonical states:

```text
Idle
Thinking
Calling model
Running tool
Waiting approval
Retrying
Checkpointing
Recovering
Completed
Interrupted
Failed
```

Run Pulse can appear in:

- current Session row;
- top run/status area;
- Timeline current step;
- Inspector status.

It must use icon/label/motion/subtle semantic color — never color alone.

### Observable-by-default

Every important runtime action should be:

- visible at the appropriate density;
- inspectable;
- traceable to an event;
- recoverable/replayable when supported.

---

# 5. Global information architecture

The desktop/laptop product uses one coherent shell:

```text
┌──────────────────────────────────────────────────────────────────────┐
│ App Bar / Context: workspace · run state · search · theme · command │
├──────────────┬─────────────────────────────────────┬─────────────────┤
│ Session Rail │ Chat | Timeline | Changes |          │                 │
│              │ Terminal | Artifacts                 │ Run Inspector   │
│              │                                     │                 │
│              │        Agent Workspace              │                 │
│              │                                     │                 │
│              │       Floating Composer             │                 │
└──────────────┴─────────────────────────────────────┴─────────────────┘
```

## 5.1 Three-column policy

- Preserve the **Session / Workspace / Inspector** topology.
- Both side panels are collapsible.
- Workspace is always the primary visual area.
- On narrower laptop widths, **Inspector collapses first**, then Session Rail if needed.

## 5.2 Responsive target

- Primary target: desktop/laptop.
- Fully usable at **1024px and above**.
- 1280–1600px is the main visual quality target.
- Below the complete-workspace breakpoint, use intelligent panel collapse; do not crush all three columns.
- Full mobile parity is not required for this redesign.

---

# 6. Workspace tabs

All first-level tabs belong to the product architecture:

- **Chat**
- **Timeline**
- **Changes**
- **Terminal**
- **Artifacts**

However, tab visibility is **capability-aware**.

## 6.1 Chat

Purpose: user-visible conversation and final answers.

Rules:

- Do not show every Tool/LLM event as a chat bubble.
- Streaming answer remains real-time.
- Runtime detail belongs to Timeline/Inspector.
- Keep transient execution status lightweight.

## 6.2 Timeline

Timeline is a **core, first-class feature**, equal in importance to Chat.

Density modes:

- Compact
- **Balanced (default)**
- Detailed
- Raw

Balanced view shows:

- event type;
- status;
- tool/model name when relevant;
- brief input/output preview;
- elapsed time/latency when real;
- retry/permission/checkpoint state;
- current Run Pulse.

Clicking an event changes Inspector context to that event.

## 6.3 Changes

Visible when the active capability/session can produce code/file changes.

Expected behavior:

- changed file list;
- status (A/M/D/R where available);
- line summary when real;
- expandable diff;
- links to related Tool Call / Artifact / event where available.

Hide the tab for sessions where Changes is not meaningful.

## 6.4 Terminal

Visible only when the active capability/session has a terminal/runtime shell concept.

Do not show a disabled useless tab to non-coding sessions.

## 6.5 Artifacts

Unified surface for outputs produced by any capability:

- reports;
- files;
- diffs;
- images;
- exported data;
- generated documents;
- other typed outputs.

Artifact is a shared backend concept, not a different implementation per capability.

---

# 7. Session and Run semantics in the UI

## 7.1 Session

`Session` is the primary user-facing navigation unit.

The left rail does **not** need to expose Run as a nested first-level navigation concept.

Session rows should be:

- visually minimal like Linear;
- richer only when runtime state matters;
- active/running sessions show Run Pulse/status;
- hover reveals secondary actions.

## 7.2 Run

Run is primarily an engineering/runtime concept visible in:

- Timeline;
- Inspector;
- status/header context;
- trace/debug surfaces.

The exact backend relationship `Session → Turn → Run` must be determined by current domain-model audit. The product must not invent unnecessary persistence entities solely to match this document.

---

# 8. Composer — Agent Launch/Control Surface

The existing large textarea + browser-like “default chain” select must be replaced.

The composer is a compact, adaptive, floating **Agent Control Surface**.

## 8.1 Core behavior

- relaxed/compact when idle;
- focused state progressively reveals more controls;
- textarea auto-grows within a bounded height;
- send action remains visually clear but not oversized;
- supports `Cmd/Ctrl + Enter` as configured send behavior;
- no huge focus glow.

## 8.2 Bottom/inline control row

Target conceptual controls:

```text
+ Context | Agent | Model | Reasoning | Permission | Branch | … | Send
```

Controls must be conditional on capability/backend support.

### Agent / Chain terminology

Do not lock the product into a legacy “Chain” concept yet.

Backend audit must determine current meaning. Product direction is to prefer:

```text
Agent + Capability + Tools/Skills
```

over an exposed fixed “Chain” concept when architecture supports it.

### Model selector

Must display more than a raw model string.

Example:

```text
DeepSeek V4 Flash
DeepSeek · Fast · 128K

Qwen Plus
Alibaba Cloud · Balanced · 1M
```

Metadata may include only values known from backend/provider configuration.

Supported visual flags:

- Current
- Default
- capability labels
- provider
- context size if authoritative

Never invent capability/context metadata.

### Permission Mode

Permission mode is a first-class composer control.

Examples may include:

- Ask before changes
- Auto Edit
- Full Access

The Backend AI must audit whether permission enforcement already exists. If not, permission capability becomes a backend requirement — the frontend must not ship a fake selector that does nothing.

### Branch

Visible when Coding capability/workspace exposes Git branch state.

### Context

Support contextual references appropriate to existing/future capability architecture. Reuse existing mechanisms where present.

---

# 9. Runtime streaming behavior

The product requires simultaneous real-time streaming of:

- assistant text/tokens/chunks;
- runtime events.

Transport may remain SSE or WebSocket based on current backend architecture. Do not migrate only for UI fashion.

The UI consumes a normalized transport-independent runtime event layer.

```text
SSE / WebSocket
      ↓
Transport Adapter
      ↓
Normalized Runtime Events
      ↓
Projections
 ┌────┼─────────┬───────────┐
Chat Timeline Inspector Artifacts/Changes
```

---

# 10. Timeline data truth

Timeline must come from **real runtime events**.

Forbidden:

- inferring tool calls from assistant text;
- inventing retries;
- creating fake checkpoints;
- generating fake latency/cost charts.

Runtime history should be append-only at the product contract level.

---

# 11. Tool Call / Tool Result interaction

## 11.1 Timeline

Show compact preview:

```text
read_file
src/agent/runtime.py · 120–200
42 ms
```

## 11.2 Inspector

Show full structured details:

- arguments;
- result metadata;
- result preview;
- duration;
- status;
- error;
- retry count;
- trace linkage;
- artifact/full-result link.

## 11.3 Large results

Large Tool Results must not be blindly pushed/rendered in full.

Allow backend/frontend contract to use:

- summary;
- preview;
- byte/char size;
- artifact/content id;
- lazy-load endpoint.

---

# 12. Inspector

Inspector is a **real runtime inspector**, not a decorative right-side details card.

It is open by default but collapsible.

Inspector context can be:

- current Run;
- selected Timeline event;
- selected Tool Call;
- selected Artifact;
- selected Change.

Recommended sections when data exists:

```text
RUN
status · id · start · duration · current step

MODEL
provider · model · tokens · latency · cost

TOOLS
count · active tool · retries · failures

CONTEXT
used · max · estimated/authoritative status · compaction

PERMISSION
mode · pending request · decision

ARTIFACTS
count · latest

CHECKPOINT
latest · resumable

TRACE
trace id · event count · raw jump
```

Unavailable data must display a clear `—`, `Unavailable`, or omit the section. No fake values.

---

# 13. Reasoning policy

Do not make raw hidden chain-of-thought a product requirement.

Provider-aware behavior:

- if provider/backend exposes a safe reasoning summary/event, show it in Detailed/Inspector contexts;
- otherwise show only execution status such as `Thinking`;
- frontend must not fabricate reasoning text.

---

# 14. Tokens, cost, latency, and context

## 14.1 Tokens / cost / latency

- show real values when provider/backend returns them;
- otherwise show unavailable;
- no frontend estimation of monetary cost unless contract explicitly supports it.

## 14.2 Context usage

Backend may estimate current context tokens when provider does not expose it.

Estimated values must be explicitly labeled `Estimated`.

Example:

```text
Context 86k / 200k · 43% · Estimated
```

---

# 15. Permission and approvals

High-risk action approval must appear **inside the runtime workflow**, not as a generic browser alert.

When waiting for approval:

- Run Pulse = `Waiting approval`;
- Timeline contains a permission event/surface;
- user can approve/deny;
- Inspector can show technical details;
- backend enforces the decision.

Modal may be used only when a truly blocking/high-risk decision requires it; inline contextual approval is preferred.

---

# 16. Stop, interrupt, retry, resume

## 16.1 Stop

User must be able to stop the current Agent Run through a first-class control.

If backend lacks cancellation/interrupt, it must be implemented rather than faked.

## 16.2 Failure recovery

Preferred behavior:

- Retry Run when appropriate;
- Resume from Checkpoint when supported;
- capability-aware graceful fallback when checkpoint/resume does not exist.

Exact availability must be visible to the UI.

---

# 17. Reconnect and durability

Refresh/network disconnect/reconnect must reconstruct Timeline and Chat to the last durable state.

Requirements:

- durable event history;
- monotonic ordering/sequence;
- reconnect cursor/last-event position;
- no duplicate event rendering;
- transient live chunks settle into durable history.

---

# 18. Search and Command Palette

## 18.1 Command Palette

`Cmd/Ctrl + K` is a first-class interaction.

Targets may include:

- navigation;
- sessions;
- tabs;
- model;
- Agent/capability;
- theme;
- runtime actions;
- settings;
- commands.

## 18.2 Search

Target search scope includes:

- Session;
- Event;
- Artifact;
- Command;
- Tool Result/file content when backend indexing/search capability exists.

Search capability must degrade based on backend support rather than showing fake results.

---

# 19. Empty, loading, error, feedback

## Empty

Use contextual, minimal empty states:

- why the area is empty;
- what the user can do next.

Avoid giant decorative illustrations.

## Loading

- first data load may use skeletons;
- Agent execution uses Run Pulse/event state;
- do not layer global spinners over real streaming state.

## Error

- inline at the failure location;
- Inspector for technical detail;
- global notification only for broader failures.

## Toast

Use only for transient non-critical acknowledgement such as copied/saved.

Runtime failure must not be communicated only through Toast.

---

# 20. Keyboard-first requirements

Keyboard interaction must cover:

- focus composer;
- send;
- command palette;
- navigation between major tabs;
- session navigation;
- Timeline event navigation;
- Inspector open/close;
- search;
- menu/popover operation;
- permission decisions where safe;
- Escape closes transient surfaces predictably.

All shortcuts must be discoverable by tooltip/help/command palette, not hidden tribal knowledge.

---

# 21. Visual direction

The visual identity is:

> **neutral, calm, precise, premium, slightly warm, with a very restrained pale-pink accent.**

Requirements:

- equal-priority light/dark theme token architecture;
- main work surface visually dominates chrome;
- pale pink is an accent/tint, not a neon brand wash;
- glass is tasteful and visible, closer to Raycast in quality, but used only on appropriate surfaces;
- avoid global glass;
- avoid huge rounded cards;
- avoid cyan glow-heavy focus treatment from the current screenshot.

Detailed design tokens live in `02_UI_UX_DESIGN_SPEC.md`.

---

# 22. Motion

Motion must be short, smooth, interruptible, and never delay Agent work.

Target timing:

- micro-interaction: **120–160ms**
- popover/panel: **160–220ms**
- large layout transition: **≤240ms**

Support `prefers-reduced-motion` / reduced motion policy.

---

# 23. Accessibility

Target **WCAG 2.2 AA** for the core application.

At minimum:

- keyboard operability;
- visible focus;
- semantic controls;
- contrast;
- accessible labels;
- tooltip for icon-only controls;
- reduced motion;
- correct dialog/popover focus behavior.

---

# 24. Performance as a product requirement

The product must remain responsive during long Agent runs.

Mandatory goals:

- streaming tokens/events do not rerender the whole page;
- Timeline supports long histories using virtualization/windowing where appropriate;
- Popover/menus feel immediate;
- Inspector selection does not stall the composer;
- large Tool Results lazy-load;
- no animation-induced streaming delay;
- avoid uncontrolled memory growth across long sessions.

Performance acceptance is defined in `07_ACCEPTANCE_TEST_PLAN.md`.

---

# 25. Capability-aware UI

The application shell stays stable while capabilities contribute features.

Examples:

```text
Coding
→ Changes + Terminal + Git branch

Research
→ Artifacts + sources/evidence surfaces

RAG
→ retrieval/tool events + artifacts, no Terminal unless actually available
```

A capability should declare what surfaces/actions it can support rather than the frontend hardcoding one layout for every Agent.

---

# 26. Reuse-first product requirement

Do not hand-write behavior already solved well by a compatible mature primitive or open-source implementation.

However:

- proprietary products are for design/interaction reference only;
- open-source reuse must respect licenses;
- reuse should fit this product's design system, not produce obvious mixed-component styling.

See `09_BENCHMARK_REUSE_MATRIX.md`.

---

# 27. Product acceptance summary

The redesign is accepted only when:

1. the current browser-like model/chain dropdown is gone;
2. the composer feels like a real Agent control surface;
3. Timeline is event-driven and live;
4. event click drives Inspector context;
5. reconnect reproduces history without duplicates;
6. permission/stop/retry/resume are truthful to backend capabilities;
7. capability-specific tabs appear only when meaningful;
8. light/dark are coherent;
9. 1024px+ remains usable;
10. long sessions remain responsive;
11. visual system is consistent across shell, composer, overlays, Timeline, and Inspector;
12. no fake runtime metrics or inferred Tool Calls are shipped.
