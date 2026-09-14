# Frontend SDD — Observable Agent Workspace

> Implementation spec for the Frontend AI.

---

# 1. First task: audit, do not rewrite blindly

Before changing code, inspect and record:

- React/framework version;
- router;
- Tailwind/CSS/modules/styled solution;
- current theme implementation;
- current component libraries;
- state/query libraries;
- WebSocket/SSE client;
- current Session/chat data flow;
- current composer/model selector components;
- existing Storybook/visual fixtures;
- existing test stack;
- existing icon/motion libraries.

Default decision: **preserve the current frontend framework**, unless the audit demonstrates a concrete blocker.

---

# 2. Architecture target

Use a projection-based frontend:

```text
Transport
  ↓
Runtime Event Adapter
  ↓
Normalized Event Store
  ├── Chat Projection
  ├── Timeline Projection
  ├── Inspector Projection
  ├── Artifact Projection
  └── Change Projection
```

Do not put raw transport logic inside UI components.

---

# 3. State boundaries

Recommended conceptual state groups:

## Durable Session State

- session metadata;
- durable runtime events;
- settled assistant messages;
- artifacts;
- change metadata.

## Live Transient State

- current assistant chunks;
- active runtime status;
- temporary tool progress;
- in-flight approval;
- reconnect state.

## UI State

- selected session;
- active tab;
- selected event;
- panel collapse state;
- Timeline density;
- open menus/command palette;
- draft composer text.

Never mix UI selection state into backend domain objects.

---

# 4. Event ingestion

Implement one adapter layer for current transport.

Responsibilities:

- parse payload;
- validate/minimally guard shape;
- dedupe event ids;
- enforce ordering by sequence;
- merge replay + live stream;
- reconcile transient assistant chunks with durable settled messages;
- expose connection/reconnect status;
- provide event selectors/projections.

Transport switch SSE ↔ WS should not require rewriting Timeline components.

---

# 5. Rendering performance

Token/event streaming must not rerender the whole application shell.

Guidelines:

- subscribe components to narrow selectors;
- keep live text buffer localized;
- batch high-frequency transient chunks if necessary without adding perceptible latency;
- memoize expensive event rendering only where meaningful;
- virtualize long Timeline lists;
- lazy-render raw JSON/large result views;
- use stable keys from `event_id`;
- do not reconstruct the full projection array from scratch for every token if avoidable.

---

# 6. Component hierarchy

Suggested feature hierarchy, adapted to actual project structure:

```text
AppShell
├── AppBar
├── SessionRail
│   ├── SessionSearch / filter
│   └── SessionRow*
├── Workspace
│   ├── WorkspaceHeader / Tabs
│   ├── ChatView
│   ├── TimelineView
│   ├── ChangesView
│   ├── TerminalView
│   ├── ArtifactsView
│   └── Composer
└── Inspector
    ├── RunInspector
    ├── EventInspector
    ├── ToolInspector
    ├── ArtifactInspector
    └── ChangeInspector
```

Avoid a monolithic AgentPage containing all behavior.

---

# 7. Design-system implementation

**Shared Design Tokens are mandatory.** Do not turn this redesign into a separate project to hand-build a full design system.

Preferred organization when compatible with the existing repo:

```text
tokens/                 ← mandatory shared source
existing/reused primitives/
minimal product components/
features/
```

If the current project already uses shadcn/Radix/etc., extend/reuse it. Do not install duplicate primitives and do not recreate equivalent primitives solely for architectural purity.

## Prefer reuse for

- Popover
- Combobox
- Dropdown Menu
- Tooltip
- Dialog
- Tabs
- ScrollArea
- Toggle Group
- Command Palette
- accessible focus management

## Custom implementation reserved for

- Run Pulse;
- Timeline/EventRow presentation;
- Inspector layouts;
- capability-aware Workspace behavior;
- product-specific Composer composition.

---

# 8. Composer implementation

Replace current browser-like select.

Subcomponents may include:

```text
Composer
├── ContextButton
├── AgentPicker
├── ModelPicker
├── ReasoningControl
├── PermissionPicker
├── BranchPicker
├── MoreMenu
└── SendStopButton
```

## Progressive disclosure

Idle state shows essentials. Focus/expanded state reveals secondary controls without layout jump/flicker.

## Conditional controls

- Branch only for relevant workspace/capability.
- Permission shown because it is required, but values come from backend.
- Reasoning control only if meaningful in current provider/runtime.
- Agent/Chain label determined after backend audit.

---

# 9. ModelPicker

Requirements:

- searchable;
- keyboard navigable;
- provider grouping optional;
- current/default badges;
- metadata from backend only;
- collision-aware overlay;
- consistent width/alignment;
- no browser-native dropdown styling.

Reuse a compatible Combobox/Command primitive instead of implementing accessibility from scratch.

---

# 10. Session Rail

- minimal row;
- active/running Run Pulse;
- hover actions;
- search/filter integrated with Command/Search strategy;
- pinned/grouping only if current product supports or later PRD adds it;
- collapse state persisted locally if useful.

Do not add unsupported Session features merely because ZCode has them.

---

# 11. Timeline

## Data

Input: normalized events/projection.

## Density

Global or per-view setting:

- Compact
- Balanced default
- Detailed
- Raw

## Selection

- single selected event;
- selection drives Inspector;
- keyboard arrow navigation;
- selection remains stable on new streamed events unless user explicitly follows live tail.

## Live-tail behavior

If user is at bottom, continue following new events.

If user scrolls up, do not yank viewport down; show “new events” affordance.

## Virtualization

Use existing virtualization library if present; otherwise prefer TanStack Virtual or equivalent mature headless virtualizer.

Handle variable event row height.

---

# 12. Inspector

Inspector context selection precedence:

1. explicit selected event/artifact/change;
2. active Run;
3. Session summary.

Avoid remount flicker when selection changes.

Sections are compact, collapsible where necessary, and display only real data.

Large JSON/result content can open in expandable code viewer or dedicated detail panel.

---

# 13. Chat projection

Chat should render conversation, not every execution event.

It may show:

- user messages;
- streaming assistant text;
- settled assistant messages;
- a compact active-run indicator;
- inline approval only if product flow requires it near current task, while Timeline remains canonical runtime surface.

Do not expose raw trace ladder in Chat.

---

# 14. Changes

Visible only if capability manifest supports it.

- file list virtualized if needed;
- diff lazy-load;
- selected file/change can drive Inspector;
- link to related runtime event when available.

Prefer existing diff viewer/library if already present and suitable; do not build a syntax diff engine unnecessarily.

---

# 15. Terminal

Visible only if backend/capability exposes terminal.

Reuse an established terminal renderer (e.g., existing xterm integration) if already in the project. Do not create a fake terminal using `<pre>`.

---

# 16. Artifacts

- grid/list choice should prioritize developer utility, likely dense list first;
- type icon/preview;
- metadata;
- open/download/view based on actual artifact URI/capability;
- lazy preview for large assets.

---

# 17. Command Palette

First-class `Cmd/Ctrl + K`.

Data sources can combine:

- local commands;
- session results;
- backend search results;
- model/agent actions.

Must open fast and retain keyboard focus.

Reuse mature command palette primitive if compatible.

---

# 18. Search

V1 desired scope includes Session/Event/Artifact/Command, plus Tool Result/file content if backend supports it.

Search UI must disclose scope/type and not fake unavailable search domains.

---

# 19. Stop/permission/retry/resume UI

## Stop

During active run, send icon/action may switch to a Stop control or provide a nearby first-class Stop action.

Show `Stopping…` until backend confirms interrupted state.

## Permission

Render `permission.requested` event as actionable surface.

Buttons come from backend `allowed_decisions`.

## Retry/resume

Show only when backend `RunActions` says available.

---

# 20. Error handling

Map errors to nearest context:

- connection error → shell/run status;
- tool error → Timeline event;
- model error → corresponding event;
- artifact fetch error → artifact surface;
- global app failure → broader notification.

Do not hide runtime failures in Toast.

---

# 21. Motion implementation

If current stack has Motion/Framer Motion, reuse it. If not, decide whether CSS transitions are sufficient before adding dependency.

Targets:

- 120–160ms micro;
- 160–220ms popover/panel;
- ≤240ms layout.

Use reduced motion.

Avoid sequential `wait` animations for live data surfaces where they would delay rendering.

---

# 22. Theme

Light and dark are equal-priority token outputs.

Theme switching should not cause uncontrolled flash.

Do not hardcode colors inside feature components. Use semantic tokens.

---

# 23. Accessibility implementation

- semantic buttons, tabs, listboxes;
- accessible labels;
- tooltip on icon-only controls;
- focus-visible;
- correct aria/current/selected state;
- keyboard navigation;
- WCAG 2.2 AA target;
- reduced motion.

Use accessible primitives rather than recreating keyboard/focus logic.

---

# 24. Storybook / fixtures / mocks

User allows mocks **only for component development and Storybook/fixtures**.

Create realistic fixture sets for:

- idle session;
- running model;
- tool call success;
- tool failure + retry;
- permission requested;
- large tool result;
- checkpoint/resume;
- completed run;
- failed run;
- long Timeline.

Production screens must use real APIs/events.

---

# 25. Tests

Minimum frontend tests:

- projection reducer/event ordering;
- dedupe on reconnect;
- Composer conditional controls;
- model picker keyboard interaction;
- Timeline density selection;
- selected event → Inspector;
- permission actions;
- Stop state;
- panel collapse at target breakpoints;
- reduced motion handling;
- capability tab visibility.

Add E2E coverage for core workflow if current stack supports it.

---

# 26. Visual QA acceptance

Before completion:

- compare old/new screenshots;
- inspect no native `<select>` visual leakage;
- no giant blue/cyan focus glow;
- no global glass;
- Session rail quieter than Workspace;
- Timeline readable at Balanced density;
- Inspector looks like a runtime inspector;
- 1024px remains usable;
- light/dark coherent;
- no hover/focus flicker;
- streaming remains responsive during animations.

---

# 27. Frontend implementation rule

Do not optimize for “looks good in one screenshot.”

Optimize for the full state matrix:

```text
idle
focused composer
streaming
running tool
waiting approval
retrying
completed
failed
interrupted
reconnecting
long history
selected event
light/dark
1024/1280/1440
```
