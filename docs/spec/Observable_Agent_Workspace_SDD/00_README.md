# Observable Agent Workspace — SDD Documentation Set

> Status: **Frozen baseline after grill-me Round 1–3**  
> Audience: Frontend AI, Backend AI, reviewers, coding agents  
> Product: `intelligence-agent` Web UI / Agent Harness Workspace redesign  
> Development mode: **SDD (Specification-Driven Development)**  
> Core principle: **One product truth, one shared runtime contract, separate implementation specs.**

---

## 1. Why this document set exists

This redesign is not a cosmetic pass over the current chat input. It is a product-level rebuild of the Web UI foundation into a professional **Observable Agent Workspace / Harness Console**.

The redesign combines four benchmark families without becoming a collage or direct clone:

- **Linear** — visual hierarchy, density, calmer chrome, structure without excessive borders.
- **ZCode** — agent-oriented composer, model/execution controls, context references, task/workspace interaction.
- **DeepSeek Harness** — durable runtime events, chat/trajectory projection separation, observability-first execution surfaces.
- **Raycast** — tasteful Liquid Glass, native-feeling floating surfaces, keyboard-first interaction, high polish.

The product must have its own identity:

> **A calm, premium, developer-first, observable Agent Runtime Workspace.**

---

## 2. Canonical document structure

```text
docs/spec/observable-agent-workspace/
├── 00_README.md
├── 01_PRODUCT_PRD.md
├── 02_UI_UX_DESIGN_SPEC.md
├── 03_RUNTIME_EVENT_CONTRACT.md
├── 04_FRONTEND_SDD.md
├── 05_BACKEND_SDD.md
├── 06_IMPLEMENTATION_PLAN.md
├── 07_ACCEPTANCE_TEST_PLAN.md
├── 08_DECISION_LOG.md
└── 09_BENCHMARK_REUSE_MATRIX.md
```

This set is designed to be copied into the project and used as the authoritative SDD package.

---

## 3. Read order

### Frontend AI — mandatory read order

1. `00_README.md`
2. `01_PRODUCT_PRD.md`
3. `08_DECISION_LOG.md`
4. `02_UI_UX_DESIGN_SPEC.md`
5. `03_RUNTIME_EVENT_CONTRACT.md`
6. `04_FRONTEND_SDD.md`
7. `06_IMPLEMENTATION_PLAN.md`
8. `07_ACCEPTANCE_TEST_PLAN.md`
9. `09_BENCHMARK_REUSE_MATRIX.md`

### Backend AI — mandatory read order

1. `00_README.md`
2. `01_PRODUCT_PRD.md`
3. `08_DECISION_LOG.md`
4. `03_RUNTIME_EVENT_CONTRACT.md`
5. `05_BACKEND_SDD.md`
6. `06_IMPLEMENTATION_PLAN.md`
7. `07_ACCEPTANCE_TEST_PLAN.md`
8. `09_BENCHMARK_REUSE_MATRIX.md`

### Reviewer / integrator

Read all files, with special attention to:

- product behavior: `01_PRODUCT_PRD.md`
- cross-boundary semantics: `03_RUNTIME_EVENT_CONTRACT.md`
- acceptance: `07_ACCEPTANCE_TEST_PLAN.md`
- unresolved/current-code-dependent decisions: `08_DECISION_LOG.md`

---

## 4. Authority and conflict rules

When documents disagree, use this order:

1. **Latest explicit user decision in `08_DECISION_LOG.md`**
2. **`01_PRODUCT_PRD.md`** for product behavior and scope
3. **`03_RUNTIME_EVENT_CONTRACT.md`** for frontend/backend semantics and runtime protocol
4. **`02_UI_UX_DESIGN_SPEC.md`** for visual and interaction behavior
5. **Frontend/Backend SDD** for implementation detail
6. **Implementation Plan** for sequencing only

Never silently choose one side when a contradiction affects product behavior or the shared contract.

---

## 5. Non-negotiable collaboration rule

The Frontend AI and Backend AI may work in separate worktrees/branches, but they do **not** own separate product truths.

```text
Shared Product PRD
        │
Shared Runtime Contract
        │
   ┌────┴────┐
   ↓         ↓
Frontend    Backend
   │         │
   └────┬────┘
        ↓
Contract Verification
        ↓
Test + Visual QA + Diff Review
        ↓
Merge
```

Any change to the following is a **shared-contract change**:

- Session / Turn / Run semantics
- Runtime event names or payloads
- stream framing or reconnect behavior
- Tool Call / Tool Result payload
- permission request / approval flow
- stop/cancel/resume/retry behavior
- artifact metadata
- checkpoint/recovery semantics
- model capability metadata
- token/cost/latency fields
- capability availability

No frontend-only or backend-only private version of these concepts is allowed.

---

## 6. Reuse-first engineering policy

The user explicitly prefers **reuse over hand-written reinvention** when an existing design/component/implementation is suitable.

### Required behavior

Before writing a custom primitive, the Frontend AI must inspect:

1. what the current project already uses;
2. whether a mature open-source primitive already solves the behavior;
3. whether DeepSeek Harness contains compatible MIT-licensed implementation ideas/code;
4. only then write custom code.

Preferred reusable categories include:

- Radix UI / existing project primitives for Popover, Dropdown, Tooltip, Dialog, Tabs, ScrollArea, Select.
- shadcn/ui source components when they fit the current React stack and can be owned/customized locally.
- TanStack Virtual for large Timeline/Session/event lists.
- Motion for React for short, interruptible transitions and reduced-motion support.
- Existing project icon system before adding another icon package.

### Important distinction

**Linear, ZCode, and Raycast are design/interaction references, not code sources.**

Do not copy proprietary DOM/CSS bundles, brand assets, icons, logos, exact proprietary visual assets, or private implementation code.

**DeepSeek Harness is open source under MIT**. Compatible code may be reused/adapted when this reduces risk or implementation cost, but license notices must be preserved where required and the code must still fit this project's architecture.

Reuse is not an excuse to import a large framework blindly. Every new dependency must have a specific need.

---

## 7. Mandatory pre-coding audit

Before changing implementation, each AI must inspect the current codebase and write a concise audit in its task/branch notes:

### Frontend audit

- framework/version
- styling system
- installed component primitives
- animation library
- state management
- query/data fetching layer
- current session/conversation components
- current model selector/composer implementation
- routing
- existing light/dark theme tokens
- existing tests

### Backend audit

- current Session domain model
- whether Turn/Run already exist
- existing SSE/WebSocket transport
- event/log persistence
- checkpoint model
- cancellation/interrupt support
- permission system
- artifact representation
- model metadata source
- token/cost/latency availability
- current search/history APIs

The audit determines **migration strategy**, not product goals.

---

## 8. Do not do these

- Do not start with a visual-only rewrite of the screenshot.
- Do not create fake runtime metrics to make the UI look rich.
- Do not invent backend capabilities silently.
- Do not make the frontend infer Tool Calls from assistant prose.
- Do not display raw private chain-of-thought as a product requirement.
- Do not rebuild primitives already solved by a suitable dependency.
- Do not globally apply glassmorphism.
- Do not use giant radius + glow + gradient as the hierarchy system.
- Do not add a second source of truth for Session/Run/Event state.
- Do not rewrite the framework solely for styling.
- Do not let animation delay model/tool streaming.

---

## 9. Definition of success

The redesign succeeds when a user can answer these questions quickly:

1. What is the Agent doing now?
2. What happened during this run?
3. Why did the UI enter this state?
4. Which model/tool/capability was used?
5. Where did a failure occur?
6. What changed or was produced?
7. Can I inspect exact runtime evidence?
8. Can I stop, approve, retry, or resume safely?

And, visually:

> It should look and feel like a deliberate developer product — not a browser `<select>` pasted under a large chat textarea.
