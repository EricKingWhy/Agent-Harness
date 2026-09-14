# Intelligence Agent Web UI Design Brief

> **Audience:** Frontend AI / Coding Agent responsible for `intelligence-agent-frontend`  
> **Purpose:** Define the product-level UI/UX direction before implementation.  
> **Mode:** Design-first, evidence-first, no blind coding.  
> **Required next step after reading:** Use **grill-me** to interrogate the user on unresolved design/product decisions before changing the UI.

---

# 0. Mission

Redesign the current `intelligence-agent` Web UI into a professional **Agent Runtime Workspace / Harness Console**.

The target is **not** another generic AI chat page, dashboard template, or “ChatGPT clone with glassmorphism”.

The product should synthesize four reference systems:

- **Visual language:** Linear
- **Interaction architecture:** Cursor 3 / Cursor Web Agents
- **Agent Trace / Observability:** DeepSeek Harness
- **Liquid Glass / material treatment:** Raycast

But the result must **not look like a collage of four products** and must not become a direct clone of any one product.

The final identity should be:

> **A calm, premium, observable, developer-first Agent Runtime Workspace.**

Core product keywords:

`Calm · Precise · Observable · Dense · Native-feeling · Developer-first · Keyboard-first · Inspectable · Fast`

Avoid these visual clichés:

`AI purple · neon cyberpunk · gradients everywhere · giant cards · glass everywhere · huge rounded corners · decorative dashboards · excessive shadows`

---

# 1. Product Positioning

This UI represents a real Agent Harness, not a pure chat interface.

The underlying system includes concepts such as:

- Session
- SessionEvent
- Agent Run
- LLM Call
- Tool Call / Tool Result
- Tool Permission
- Retry
- Checkpoint
- Artifact
- Context
- Recovery
- SubAgent
- Trace
- JSONL / observability
- Coding / Research / future capabilities

Therefore the UI must make runtime behavior visible without forcing users to open an external observability platform for basic inspection.

The interface should answer, at a glance:

1. **What is the Agent doing now?**
2. **What happened in this run?**
3. **Why did it do that?**
4. **Which tools/models were involved?**
5. **What changed?**
6. **Where did it fail?**
7. **Can I inspect the exact event / trace / artifact?**
8. **What is the current session/run state?**

The UI should feel closer to an **IDE + runtime inspector + agent workspace** than to a messaging app.

---

# 2. Existing UI: Preserve the Good Skeleton, Replace the Demo Feel

The existing UI already has a useful three-column skeleton:

```text
Left: Sessions
Center: Conversation / main workspace
Right: Inspector
```

Do **not** throw this away by default.

The main issue is not layout topology. The issue is visual hierarchy, information architecture, surface treatment, density, and runtime observability.

Current problems to eliminate:

- Every region looks like an independent floating card.
- Excessive border radius.
- Large soft shadows everywhere.
- Too much empty white space.
- Weak distinction between application chrome and content.
- Inspector is too shallow and does not feel like a runtime inspector.
- Agent execution is hidden inside chat instead of treated as first-class UI.
- Input composer is visually louder than the actual runtime state.
- Too much “AI demo” styling, not enough “professional developer tool”.

Target transformation:

```text
BEFORE
Card + Card + Card + Glow Input

AFTER
One coherent Application Shell
  ├─ Navigation / Session rail
  ├─ Agent Workspace
  └─ Runtime Inspector
```

---

# 3. Design Synthesis: What to Take from Each Reference

## 3.1 Linear — Visual System

Use Linear as the primary reference for **visual restraint and hierarchy**, not for business layout.

Extract and adapt:

- Calm low-contrast application chrome.
- Clear separation between navigation surfaces and primary content.
- Dense but readable lists.
- Precise typography hierarchy.
- Small, subtle borders.
- Very restrained shadows.
- Neutral surfaces with controlled accent color.
- Strong selected / hover / focus states without visual noise.
- Compact controls.
- Consistent spacing rhythm.
- Dark mode that is not pure black.

Do not imitate:

- Linear branding.
- Exact icons/logo.
- Exact proprietary page structures.
- Exact colors if they do not fit this product.

**Principle:**

> Low-contrast chrome, high-clarity content.

Primary panels should usually be separated by border, tone, or layout—not giant floating shadows.

---

## 3.2 Cursor 3 — Agent Workspace Architecture

Use Cursor as the main reference for **how an Agent product becomes a workspace rather than a chat box**.

The center column should become a multi-mode workspace.

Recommended top-level workspace tabs:

```text
Chat | Timeline | Changes | Terminal | Artifacts
```

Optional future tabs:

```text
Context | Memory | Evaluation | SubAgents
```

### Chat

Normal user/agent conversation, but tool activity is embedded as structured execution blocks—not raw log spam.

### Timeline

A chronological runtime view of SessionEvents:

```text
13:42:11  LLM Request
13:42:13  LLM Response      1.8s   2.1k tokens
13:42:13  Tool Call         read_file
13:42:14  Tool Result       success  84ms
13:42:18  Checkpoint Saved
13:42:19  Artifact Created
```

### Changes

For coding workflows:

- changed files
- diff summary
- patch/diff viewer
- additions/deletions
- staged-like review surface if relevant

### Terminal

A clean command execution surface for Bash/PowerShell/Tool output.

### Artifacts

File outputs, reports, generated assets, raw outputs, snapshots, exported documents.

Cursor inspiration should also influence:

- run/status awareness
- multiple agent/session navigation
- background execution awareness
- task state
- compact activity representations

---

## 3.3 DeepSeek Harness — Agent Trace / Observability

Do not primarily copy its visual look.

Copy its **observability semantics**.

Runtime events must be first-class objects.

Examples:

```text
Session Start
User Message
LLM Request
LLM Response
Tool Call
Tool Result
Permission Request
Retry
Checkpoint
Artifact Created
SubAgent Spawned
SubAgent Completed
Error
Recovery / Resume
Session Completed
```

Each event should be inspectable.

### Trace Density Modes

Introduce a product-specific control:

```text
Compact | Balanced | Detailed | Raw
```

This can become one of the distinctive features of the product.

#### Compact

```text
✓ Read 3 files
✓ Edited tool_executor.py
✓ Tests passed
```

#### Balanced

```text
▼ read_file
  src/runtime/tool_executor.py
  84 ms
```

#### Detailed

```text
Tool Call
────────────────
tool_call_id   tc_0184
tool           read_file
permission     READ_ONLY
duration       84 ms
retry          0
status         SUCCESS

Input
{ ... }

Output
{ ... }
```

#### Raw

Show the underlying event / JSON when useful.

The product should support moving from **human-readable summary → engineering detail → raw event** without leaving the run.

That progressive disclosure is important.

---

## 3.4 Raycast — Liquid Glass / Material Treatment

Use Raycast as a reference for **tasteful glass**, not “glass everywhere”.

Liquid Glass is a **material hierarchy tool**, not the core visual theme.

Good places for glass:

- top application bar
- floating composer
- command palette
- popovers
- context menus
- lightweight modal surfaces
- floating quick inspector

Avoid glass for:

- code diff
- terminal
- timeline event bodies
- JSON/raw trace
- long-form text
- dense inspector tables

These must remain highly readable.

**Rule:**

> Glass for transient / floating / control surfaces. Solid surfaces for information-dense work surfaces.

---

# 4. Original Product Identity: “Observable Agent Workspace”

The redesign must add a recognizable identity of its own.

Recommended product signature:

## 4.1 Run Pulse

A small, consistent runtime status indicator used across header, session list, and inspector.

States:

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
Failed
```

Do not use arbitrary rainbow colors.

The visual system should make state obvious with:

- icon
- subtle color
- optional motion
- label

Never rely on color alone.

---

## 4.2 Trace Ladder

A vertical or grouped event representation that makes the Agent execution chain visually understandable:

```text
User
 ↓
LLM
 ↓
Tool
 ↓
Tool Result
 ↓
Checkpoint
 ↓
LLM
 ↓
Complete
```

This is not a decorative flowchart. It should be a real projection of SessionEvents.

---

## 4.3 Inspector as a Real Runtime Inspector

The right panel should evolve from a simple “details card” into a professional inspector.

Recommended sections:

```text
RUN
- status
- run/session id
- started at
- duration
- current step

MODEL
- provider
- model
- input tokens
- output tokens
- latency
- cost (if available)

TOOLS
- count
- active tool
- retries
- failures

CONTEXT
- context tokens
- max tokens
- context usage
- compaction state

ARTIFACTS
- count
- latest

CHECKPOINT
- latest checkpoint
- resumable state

TRACE
- trace_id
- event count
- raw event jump
```

Sections should be collapsible or density-aware.

---

## 4.4 “Observable by Default”

The unique product promise should be visible in the interface:

> Every important runtime action is observable, inspectable, and explainable.

Avoid building an external “debug page” that duplicates the main product.

Observability should be integrated into the main workspace.

---

# 5. Information Architecture

Recommended desktop hierarchy:

```text
┌────────────────────────────────────────────────────────────────────┐
│ App Bar: Product / Workspace / Run / Model / Search / Theme / Cmd │
├──────────────┬────────────────────────────────────┬────────────────┤
│              │ Chat Timeline Changes Terminal... │                │
│ Session Rail │                                    │ Run Inspector  │
│              │           Agent Workspace          │                │
│              │                                    │                │
│              │                                    │                │
│              │                                    │                │
│              │       Floating Composer            │                │
└──────────────┴────────────────────────────────────┴────────────────┘
```

Suggested desktop proportions (starting point only):

- Session rail: 220–260px
- Inspector: 280–340px
- Workspace: flexible remainder
- App bar: compact, not oversized

Do not hardcode without validating against actual content.

The AI should test at multiple widths.

---

# 6. Application Shell Rules

## 6.1 One Shell, Not Three Cards

Use one coherent page frame.

Avoid surrounding each major column with large outer shadows.

Prefer:

- subtle divider
- neutral surface shifts
- 1px border
- inset distinction where necessary

## 6.2 Radius Hierarchy

Do not use one giant radius everywhere.

Recommended semantic radius system:

```text
xs: chips / tags
sm: inputs / compact controls
md: cards / popovers
lg: command palette / floating composer
xl: only rare hero/floating surfaces
```

The actual token values should be derived from benchmark research and project fit.

## 6.3 Shadow Hierarchy

Main layout panels:

- no shadow or nearly invisible shadow

Floating surfaces:

- soft elevation shadow
- subtle inner highlight if glass

Never make every surface float.

---

# 7. Typography

Typography should communicate hierarchy more than borders do.

Required levels:

```text
Product / Page title
Section title
Primary body
Secondary metadata
Monospace identifiers
Status labels
Code / JSON / terminal
```

Rules:

- Session IDs, trace IDs, tool_call_id, hashes → monospace.
- Long IDs should support copy and truncation.
- Metadata should be visually secondary.
- Do not make everything 14px gray.
- Avoid overly bold typography everywhere.
- Chinese and English mixed content must remain balanced.

The frontend AI must verify Chinese rendering quality.

---

# 8. Color System

The product should use a restrained neutral system plus one primary accent.

Do not define the final accent blindly before grill-me.

The AI should ask the user about:

- preference for blue / indigo / cyan / neutral accent
- whether existing brand color must be preserved
- light-first vs dark-first priority

Recommended semantic tokens:

```text
--bg-app
--bg-sidebar
--bg-workspace
--bg-inspector
--surface-1
--surface-2
--surface-overlay
--surface-glass
--border-subtle
--border-strong
--text-primary
--text-secondary
--text-tertiary
--accent
--success
--warning
--danger
--info
```

Do not bind runtime meaning directly to arbitrary component colors.

Use semantic state tokens.

---

# 9. Liquid Glass Specification

Glass must be implemented as a controlled design token/system, not one-off CSS.

Conceptual token set:

```text
--glass-bg
--glass-border
--glass-blur
--glass-saturation
--glass-shadow
--glass-highlight
```

Potential treatment:

```css
background: rgba(...);
backdrop-filter: blur(...) saturate(...);
border: 1px solid rgba(...);
box-shadow: ...;
```

But the AI must derive values through actual visual iteration.

Do not copy one CSS snippet and apply globally.

Required behavior:

- readable over light and dark backgrounds
- no muddy text
- reduced transparency mode if browser/platform constraints require
- no excessive GPU-heavy blur on dozens of components

---

# 10. Session Rail

The left rail should become closer to a professional activity/session navigator.

Each session row may include:

```text
status dot/icon
short title or run description
short id
relative time
event count
optional agent/profile/model indicator
```

Selected state should be obvious but not loud.

Hover actions may include:

- more menu
- rename
- copy id
- archive/delete if supported

Do not permanently show too many controls.

Add grouping only if supported by real product semantics, for example:

```text
Running
Today
Yesterday
Older
```

Do not invent fake organization just for aesthetics.

---

# 11. Conversation / Chat

The chat should avoid looking like consumer messaging bubbles.

### User message

Can use a compact aligned surface or subtle bubble.

### Agent message

Prefer document-like content flow with embedded execution blocks.

Agent output should support:

- Markdown
- code blocks
- citations/artifact references
- tool execution summaries
- expandable details

Tool activity should be visually integrated into the response stream.

Example:

```text
Agent
I’ll inspect the runtime path first.

┌ Read File ────────────────────────────┐
│ src/runtime/tool_executor.py    84ms  │
│ Success                              │
└──────────────────────────────────────┘

The retry path is currently centralized...
```

Avoid giant tool cards for trivial operations.

Density mode should control detail.

---

# 12. Timeline / Trace View

This is one of the most important product screens.

Required design goals:

- chronological readability
- event-type scanning
- expandable detail
- duration visibility
- failure visibility
- relationship between call/result
- correlation IDs where useful

Potential structure:

```text
13:42:11  ● User Message
13:42:11  ◇ LLM Request
13:42:13  ◇ LLM Response        1.8s
13:42:13  ◈ Tool Call           read_file
13:42:14  ✓ Tool Result         84ms
13:42:18  ◆ Checkpoint Saved
```

The actual icon system must be cohesive.

Do not use random emoji in production UI unless deliberately chosen.

---

# 13. Inspector Interaction

The inspector should support two scopes:

## Run-level Inspector

Shows aggregate state for the current run.

## Event-level Inspector

When the user clicks a Timeline event or Tool block, the inspector switches to that event.

Example event inspector:

```text
Tool Call
status: success
tool: read_file
call id: tc_0184
duration: 84ms
permission: read-only
retry: 0

Input
...

Output
...

Raw Event
...
```

Provide a clear way to return to Run-level Inspector.

This contextual inspector behavior is preferable to opening endless modals.

---

# 14. Composer

The composer can be a signature Liquid Glass surface.

It should feel lightweight and capable.

Potential controls:

- main text input
- send
- model/profile selector if needed
- attachment/artifact input
- command/skill trigger
- approval state if current Agent action requires user confirmation

Do not permanently expose every control.

Use progressive disclosure.

The composer should not dominate the entire viewport.

---

# 15. Command Palette / Keyboard-First UX

The product should support a command-first professional workflow.

Recommended command palette actions:

```text
New Session
Switch Session
Search Sessions
Open Timeline
Open Changes
Open Artifacts
Toggle Inspector
Change Trace Density
Toggle Theme
Copy Session ID
Copy Trace ID
```

Keyboard behavior should be discoverable but unobtrusive.

If command palette is not yet implemented, design the system so it can be added cleanly later.

---

# 16. Motion

Motion should communicate state, not decorate.

Good uses:

- Run Pulse state transition
- tool running spinner/progress
- inspector context switch
- expand/collapse event
- command palette entrance
- subtle tab/content transitions
- streaming response state

Avoid:

- large floating animations
- bouncing cards
- constant gradient motion
- excessive spring everywhere

Motion must respect `prefers-reduced-motion`.

---

# 17. Dark Mode

Dark mode is required as a first-class design system, not an inversion afterthought.

Principles:

- avoid pure black everywhere
- maintain surface hierarchy
- borders remain subtle but visible
- glass remains legible
- code/terminal remain comfortable for long use
- status colors must remain accessible

The AI should inspect Linear / Cursor dark mode behavior using Chrome DevTools MCP where accessible.

---

# 18. Accessibility

Minimum requirements:

- keyboard navigation
- visible focus state
- semantic buttons/controls
- ARIA where needed
- adequate contrast
- no color-only status meaning
- readable Chinese/English typography
- resizable panels must remain usable
- tooltips for icon-only controls
- reduced motion support

Accessibility must not be treated as a final polish pass.

---

# 19. Responsive Strategy

Desktop is primary.

The product is a developer tool, so do not force a consumer-mobile-first design.

Recommended behavior:

### Wide desktop

Three columns visible.

### Medium desktop/laptop

Inspector collapsible or overlay.

### Narrow

Session rail becomes drawer / collapsible navigation.

Workspace remains primary.

Do not compress three columns until all become unusable.

---

# 20. Chrome DevTools MCP Benchmark Workflow

Before implementation, use **Chrome DevTools MCP** to study references.

Do not copy source bundles or proprietary assets.

Extract design principles and measurable patterns.

## Linear

Inspect:

- application shell
- sidebar width
- sidebar/background contrast
- list row height
- typography
- hover/selected state
- borders
- corner radii
- command palette
- popovers
- dark mode
- spacing rhythm

## Cursor Web / Agents

Inspect:

- agent/task workspace architecture
- tabs
- task/run state
- diff/change surfaces
- session navigation
- inspector-like patterns
- density

## DeepSeek Harness

Prefer local UI and source-level architecture study.

Inspect:

- session rendering
- trajectory / trace rendering
- tool call presentation
- streaming state
- layout and inspector concepts

## Raycast

Study public visual references and interaction principles.

Focus on:

- glass placement
- floating surfaces
- command palette feeling
- control density
- lighting/highlight treatment

### Required output from benchmark phase

Create a short internal report:

```text
Benchmark Findings
- Linear: what to adopt / not adopt
- Cursor: what to adopt / not adopt
- DSH: what to adopt / not adopt
- Raycast: what to adopt / not adopt
- Intelligence Agent unique synthesis
```

No code change before this analysis and grill-me clarification are complete.

---

# 21. Matt Pocock Skills Workflow

Use installed Matt Pocock frontend-related skills where they improve the work.

Do not invoke skills mechanically.

Recommended sequence:

```text
1. Read this Design Brief
2. Inspect current frontend architecture
3. Use Chrome DevTools MCP for benchmark research
4. Produce benchmark findings
5. Run grill-me with the user
6. Freeze design decisions
7. Produce implementation plan
8. Implement Design System / Shell first
9. Implement Workspace IA
10. Implement Trace / Inspector
11. Implement Liquid Glass overlays
12. Run browser QA / visual review
13. Code review and cleanup
```

If available and relevant, use skills for:

- frontend design
- component/API design
- React patterns
- accessibility
- testing
- code review

Do not let a skill replace product judgment.

---

# 22. grill-me Is Mandatory Before Coding

After reading this document and inspecting the current UI/benchmark references, **do not start the redesign immediately**.

Run **grill-me** against the user.

The goal is to resolve product/design ambiguity, not to ask trivial questions that can be decided by the frontend engineer.

Ask in grouped rounds, prioritizing decisions that materially affect the design.

## Required grill-me topics

### A. Product identity

- Should the UI feel more like an IDE/workbench, or more like a polished AI product?
- How technical should the default view be?
- Is the primary audience currently the user himself, interview/demo viewers, or future public users?

### B. Visual tone

- Light-first, dark-first, or equal priority?
- Preferred accent family?
- How much glass is acceptable?
- More minimal/quiet or more visually expressive?

### C. Workspace structure

- Confirm `Chat / Timeline / Changes / Terminal / Artifacts` as first-level tabs.
- Which tabs must exist in V1?
- Should terminal and changes exist even for non-coding sessions?

### D. Inspector

- Which metrics are genuinely available now?
- Tokens/cost/model/trace/checkpoint/artifact — which are real vs future?
- Should event click switch the inspector context?

### E. Session model

- How sessions should be named?
- Whether runs and sessions are separate UI concepts?
- Whether multiple agents should be visible in the session rail?

### F. Trace density

- Is `Compact / Balanced / Detailed / Raw` desired?
- Which mode should be default?
- Should users be able to set this globally?

### G. Original signature

Validate whether to adopt:

- Run Pulse
- Trace Ladder
- Contextual Inspector
- Observable-by-default workspace

If the user dislikes one, replace it rather than forcing it.

### H. Scope

- Redesign only visuals, or also restructure IA?
- Can components be replaced/recomposed?
- Is backward compatibility with current UI state/data required?
- Which pages/components are explicitly out of scope?

---

# 23. After grill-me: Freeze a Design Decision Record

Before coding, write a concise decision record containing:

```text
# UI Design Decision Record

## Product Positioning
## Visual Direction
## Layout / IA
## V1 Tabs
## Inspector Scope
## Trace Density
## Glass Usage
## Theme Strategy
## Unique Product Signatures
## Out of Scope
## Acceptance Criteria
```

Only then begin implementation.

---

# 24. Implementation Order

Do not attempt the whole redesign in one giant patch.

Recommended phases:

## Phase 1 — Design System Foundation

- tokens
- typography
- spacing
- borders
- radius
- shadows
- glass tokens
- light/dark theme

## Phase 2 — Application Shell

- app bar
- session rail
- workspace frame
- inspector frame
- responsive/collapsible behavior

## Phase 3 — Chat Refinement

- user/agent message hierarchy
- tool activity blocks
- composer

## Phase 4 — Timeline / Trace

- event rows
- event grouping
- status/duration
- density modes
- selection

## Phase 5 — Inspector

- run-level inspector
- event-level inspector
- contextual switch

## Phase 6 — Changes / Terminal / Artifacts

Only if they exist in current scope.

## Phase 7 — Motion / Glass / Polish

Glass and animation are polish after hierarchy works.

Do not use glass to hide weak layout.

---

# 25. Technical / Code Quality Constraints

The redesign must not destroy the project architecture.

Requirements:

- Reuse existing data contracts where possible.
- Do not duplicate Session truth in frontend-only state.
- UI should project real backend/runtime events.
- Avoid fake placeholder metrics in production surfaces.
- No hard-coded demo state masquerading as runtime truth.
- Keep component boundaries understandable.
- Avoid one giant page component.
- Avoid premature generic component abstraction.
- Preserve accessibility semantics.
- Avoid introducing a heavy UI framework solely for visual similarity.

If current architecture blocks the desired IA, report the mismatch before large refactors.

---

# 26. Performance Constraints

Professional feel requires performance.

Watch for:

- excessive blur layers
- giant DOM timelines
- frequent re-render during streaming
- large JSON rendering
- huge diff rendering
- animated shadows

Potential techniques:

- virtualized long event lists
- lazy raw JSON
- collapsed tool output by default
- memoized event rows
- progressive disclosure

Do not prematurely optimize without evidence, but avoid obviously expensive visual patterns.

---

# 27. Acceptance Criteria

The redesign is successful only if all of these are true:

## Visual

- The UI no longer looks like three floating cards.
- Linear-like calm hierarchy is visible.
- Main content is stronger than chrome.
- Shadows/radii are restrained.
- Glass is limited to appropriate floating surfaces.

## Interaction

- Center area feels like an Agent Workspace, not just Chat.
- Runtime status is easy to understand.
- Important information is discoverable without overwhelming default view.

## Observability

- Tool/LLM/checkpoint/artifact events are first-class or clearly planned.
- Users can drill from summary to detail.
- Inspector is meaningful.

## Identity

- It does not look like a direct Linear/Cursor/Raycast clone.
- The product has a distinct Observable Agent Workspace identity.

## Engineering

- Existing real functionality remains working.
- No fake metrics are introduced as if they were real.
- Light/dark theme works.
- Keyboard/focus behavior is acceptable.
- Layout remains usable at common laptop widths.

---

# 28. Explicit Anti-Patterns

Do not do these unless the user explicitly asks:

- global glassmorphism
- giant 20–24px radius on every panel
- strong blue glow around every input
- gradients as primary hierarchy
- random neon accent colors
- card-per-section dashboard layout
- excessive empty whitespace in a developer tool
- icon-only controls without tooltip
- chat bubbles for every agent message
- fake charts/metrics to make the UI “look rich”
- copying Linear/Cursor brand assets
- copying proprietary DOM/CSS bundles directly
- rewriting the frontend framework just for visual polish

---

# 29. Final Design Principle

When choosing between “more beautiful” and “more understandable”, prefer understandable.

When choosing between “more effects” and “more hierarchy”, prefer hierarchy.

When choosing between “more information” and “better progressive disclosure”, prefer progressive disclosure.

When choosing between “copying a benchmark” and “expressing the Agent Harness identity”, prefer the Agent Harness identity.

The finished product should communicate:

> **This is not a chat wrapper. This is an observable Agent Runtime Workspace.**

---

# 30. Immediate Instruction to the Frontend AI

After reading this document:

1. Inspect the current frontend and current UI implementation.
2. Use Chrome DevTools MCP to benchmark Linear and Cursor Web where accessible.
3. Inspect DeepSeek Harness local Web UI / source structure for trace and trajectory ideas.
4. Review Raycast visual references for tasteful Liquid Glass usage.
5. Produce a concise benchmark synthesis.
6. **Run grill-me with the user before implementation.**
7. After answers are complete, freeze a `UI Design Decision Record`.
8. Only then create the implementation plan.
9. Do not write redesign code before steps 1–7 are complete.

