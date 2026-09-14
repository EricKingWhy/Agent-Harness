# Implementation Plan — Observable Agent Workspace

> Shared sequencing plan for Frontend and Backend worktrees.

---

# Phase 0 — Audit and benchmark freeze

## Frontend

- inspect current stack/components;
- screenshot current UI states;
- identify reusable installed primitives;
- review Linear/ZCode/Raycast visual/interaction references;
- inspect DeepSeek Harness Web UI/source patterns where useful.

## Backend

- audit Session/Run/event/transport/permission/cancel/checkpoint/artifact/model metadata.

## Shared output

- current-state audit table;
- domain mapping proposal;
- list of existing dependencies to reuse;
- list of actual missing capabilities.

**No large redesign code before this phase closes.**

---

# Phase 1 — Design system and application shell

### Frontend

- semantic light/dark tokens;
- typography/radius/border/shadow/motion tokens;
- reusable primitives wrappers;
- one coherent three-column shell;
- collapsible Inspector/Session Rail;
- workspace tab chrome;
- responsive behavior at 1024/1280/1440.

### Backend

No major visual dependency; continue contract audit if needed.

### Acceptance gate

- shell no longer looks like three floating cards;
- Workspace dominates chrome;
- theme coherent;
- no behavior regression.

---

# Phase 2 — Composer and model/agent controls

### Frontend

- replace current native-looking Chain selector;
- adaptive Floating Composer;
- Agent/Model/Reasoning/Permission/Branch controls;
- reusable Popover/Combobox;
- Stop action state reserved.

### Backend

- model catalog endpoint/contract;
- current/default metadata;
- permission mode capability metadata;
- capability manifest beginnings.

### Gate

No fake permission/model metadata.

---

# Phase 3 — Shared runtime event foundation

### Backend lead

- append-only event envelope;
- sequence;
- durable/transient distinction;
- stream replay/reconnect;
- LLM/tool lifecycle events;
- settled assistant event.

### Frontend lead

- transport adapter;
- normalized event store;
- dedupe/reconnect;
- Chat projection;
- basic Timeline projection.

### Gate

Refresh during a run reconstructs state correctly.

---

# Phase 4 — Timeline + Inspector

### Frontend

- Compact/Balanced/Detailed/Raw;
- virtualization;
- live-tail behavior;
- event selection;
- Run/Event/Tool Inspector;
- Run Pulse.

### Backend

- bounded tool result previews;
- lazy-load large results;
- token/latency/cost metadata when real;
- context usage source.

### Gate

Clicking a Tool event shows exact backend arguments/result metadata in Inspector.

---

# Phase 5 — Permission + Stop + Retry/Resume

### Backend

- permission enforcement if missing;
- stop/cancel semantics;
- retry availability;
- checkpoint/resume availability;
- state events.

### Frontend

- permission inline surface;
- Waiting Approval Run Pulse;
- Stop/Stopping/Interrupted;
- Retry/Resume controls conditionally visible.

### Gate

Every visible action changes real runtime behavior.

---

# Phase 6 — Capability-aware Changes / Terminal / Artifacts

### Shared

- capability manifest finalized.

### Frontend

- conditional tab visibility;
- Changes real diff viewer integration;
- Terminal reuse existing terminal library/implementation;
- unified Artifact surface.

### Backend

- real file changes/diff data;
- terminal availability;
- artifact listing/content.

### Gate

Non-coding session has no meaningless Terminal/Changes tabs.

---

# Phase 7 — Command Palette + Search

### Frontend

- `Cmd/Ctrl+K`;
- local command index;
- session/event/artifact result rendering;
- keyboard shortcuts.

### Backend

- available search scopes;
- add event/artifact/tool-content search only as justified.

---

# Phase 8 — Performance / Accessibility / Polish

### Frontend

- long Timeline benchmark;
- render profiling;
- lazy JSON/result viewers;
- reduced motion;
- WCAG 2.2 AA fixes;
- overlay/focus/flicker cleanup;
- responsive QA;
- light/dark visual consistency.

### Backend

- stream load/reconnect tests;
- pagination/history efficiency;
- event payload size review;
- artifact large-content behavior.

---

# Phase 9 — Integrated acceptance and merge

1. Frontend/backend contract diff review.
2. Automated tests.
3. E2E run:
   - start task;
   - model event;
   - tool event;
   - permission;
   - stop/retry/resume where applicable;
   - refresh/reconnect;
   - artifact/change.
4. Visual QA screenshots.
5. Performance QA.
6. Security/redaction check.
7. Merge only after shared contract passes.

---

# Worktree / Git collaboration rule

Suggested worktrees:

```text
intelligence-agent-fronted  → frontend branch
intelligence-agent-backed   → backend branch
intelligence-agent          → integration/main
```

Rules:

- each worktree commits focused changes;
- shared contract changes are proposed before incompatible implementation diverges;
- before merge, compare both branches against the same `03_RUNTIME_EVENT_CONTRACT.md`;
- do not merge only through remote GitHub and leave local main stale if local integrated testing is expected;
- integration branch/main must be updated and run locally before declaring completion.

---

# Change-control classes

## Class A — Product behavior

Update PRD + decision log.

## Class B — Shared contract

Update runtime contract + both affected SDDs before/with code.

## Class C — Visual implementation

Update UI spec only if it changes a reusable design rule.

## Class D — Internal implementation refactor

No PRD change if externally equivalent; normal code review/tests.
