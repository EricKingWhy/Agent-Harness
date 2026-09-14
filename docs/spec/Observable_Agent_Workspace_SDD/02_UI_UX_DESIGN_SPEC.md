# UI/UX Design Specification — Observable Agent Workspace

> Frontend-focused, but Backend AI should understand sections related to runtime states and data availability.

---

# 1. Design thesis

The product should not be “a ChatGPT clone with glassmorphism.”

Visual hierarchy must come from:

1. surface hierarchy;
2. spacing/density;
3. typography;
4. state;
5. subtle borders;
6. motion;
7. only then decorative material.

Core design words:

`Calm · Precise · Dense · Premium · Observable · Native-feeling · Developer-first · Fast`

---

# 2. Benchmark principles to adopt

## Linear

- main work area gets more contrast than navigation;
- supporting chrome recedes;
- reduce unnecessary borders/icons;
- consistent header geometry;
- structure is perceptible without every area becoming a card.

## ZCode

- composer is a control center for Agent execution;
- model/mode/context/branch are close to the task input;
- permission/risk mode remains visible;
- controls appear only when useful.

## DeepSeek Harness

- Timeline/Trajectory is an execution view, not decorated chat;
- Chat and Timeline can project the same authoritative event history differently;
- durable and transient states are visually distinct;
- runtime state is first-class.

## Raycast

- floating surfaces feel like real product chrome;
- glass is tasteful and functional;
- keyboard and focus behaviors are polished;
- transitions avoid flicker.

---

# 3. Surface model

Use a small number of semantic surfaces rather than arbitrary cards.

Recommended semantic tokens:

```text
surface.canvas
surface.chrome
surface.workspace
surface.elevated
surface.overlay
surface.glass
surface.selected
surface.hover
surface.danger
```

Rules:

- `workspace` is primarily solid and readable.
- `chrome` is slightly quieter than workspace.
- `overlay/glass` may use blur/translucency.
- `selected` may use a faint pink-tinted neutral, not saturated pink.
- avoid large outer shadows on Session/Workspace/Inspector columns.

---

# 4. Initial theme tokens

These values are **starting points**, not immutable brand law. Visual QA may tune them while preserving hierarchy and contrast.

## 4.1 Dark

```css
--bg-canvas:       #0c0c0f;
--bg-chrome:       #101014;
--bg-workspace:    #121217;
--bg-elevated:     #17171d;
--bg-hover:        rgba(255,255,255,.045);
--bg-selected:     rgba(245, 174, 201, .08);

--text-primary:    rgba(255,255,255,.92);
--text-secondary:  rgba(255,255,255,.64);
--text-tertiary:   rgba(255,255,255,.42);

--border-subtle:   rgba(255,255,255,.075);
--border-strong:   rgba(255,255,255,.13);

--accent:          #f1b3ca;
--accent-strong:   #f4a5c4;
--accent-soft:     rgba(241,179,202,.12);
```

## 4.2 Light

```css
--bg-canvas:       #f6f6f8;
--bg-chrome:       #f1f1f4;
--bg-workspace:    #fbfbfc;
--bg-elevated:     #ffffff;
--bg-hover:        rgba(20,20,28,.04);
--bg-selected:     rgba(207, 91, 139, .07);

--text-primary:    rgba(18,18,24,.92);
--text-secondary:  rgba(18,18,24,.62);
--text-tertiary:   rgba(18,18,24,.42);

--border-subtle:   rgba(18,18,24,.08);
--border-strong:   rgba(18,18,24,.14);

--accent:          #c96990;
--accent-strong:   #b95680;
--accent-soft:     rgba(201,105,144,.10);
```

### Accent rule

Pink should feel like a subtle signature in:

- selected state;
- small focus emphasis;
- current run indicator details;
- active control highlight;
- occasional glass tint.

Do not use broad pink gradients as backgrounds.

---

# 5. Typography

Use the project's existing high-quality UI font stack when possible.

Hierarchy should be compact:

- App/section title: 13–15px, medium/semibold.
- Standard body: 13–14px.
- Metadata: 11–12px.
- Code/IDs: mono 11–13px.
- Avoid oversized 18–24px headings inside routine panels.

Runtime metadata should feel IDE-like: precise, aligned, quiet.

---

# 6. Radius hierarchy

Do not use one giant radius everywhere.

Suggested hierarchy:

```text
2–4px  tiny inline states / code chips
6px    compact buttons / row selection
8px    inputs / menus / controls
10px   composer / primary overlay
12px   larger floating panel only when justified
```

Avoid 20–28px dashboard-card radii.

---

# 7. Borders and shadows

## Borders

- Use 1px low-contrast borders sparingly.
- Prefer surface shifts and spacing.
- Stronger border reserved for focus/active/drag states.

## Shadows

- No broad fluffy shadow around every column/card.
- Overlays may use a tight two-layer shadow.
- Glass surface may use subtle inner highlight + narrow shadow.

---

# 8. Liquid Glass policy

User chose **Raycast-quality material with constrained placement**.

Allowed:

- Command Palette;
- Popover/Combobox;
- floating Composer control strip;
- transient tooltips/menus;
- compact overlay surfaces;
- optional top contextual control surface.

Not allowed as default:

- entire Timeline;
- entire Inspector;
- every Session row;
- terminal/diff body;
- huge page-sized glass cards.

Glass should preserve readable contrast in both themes.

---

# 9. Application shell

## Session Rail

Target width: ~220–260px starting point.

Behavior:

- dimmer than Workspace;
- active row has restrained selected treatment;
- Run Pulse only where meaningful;
- hover reveals menu/action affordances;
- titles truncate cleanly;
- avoid card-per-session.

## Workspace

- owns primary visual contrast;
- tab/header is compact;
- no oversized empty top chrome;
- scroll behavior is predictable;
- Composer visually anchors the bottom without overwhelming content.

## Inspector

Target width: ~280–340px starting point.

- open by default;
- collapsible;
- sections may collapse;
- selected event changes content without full-panel remount/flicker;
- dense key/value visual language.

---

# 10. Composer visual spec

Current UI failure mode to eliminate:

```text
Huge rounded textarea
+ cyan glow
+ isolated browser-like select
+ oversized send circle
```

Target:

```text
┌──────────────────────────────────────────────────────────────┐
│ Describe a task…                                             │
│                                                              │
│ +  Agent ▾  Model ▾  Reasoning ▾  Ask ▾  Branch ▾       ↑   │
└──────────────────────────────────────────────────────────────┘
```

### Idle

- compact height;
- low visual noise;
- only essential controls visible.

### Focus

- expand naturally;
- reveal secondary controls;
- border/accent lift is subtle;
- no bright outer halo.

### Controls

Prefer owned primitives/Popover/Combobox; never ship unstyled browser-native select appearance for model/agent controls.

### Send

- compact icon button;
- clear enabled/disabled state;
- during active run, primary action may transition to Stop.

---

# 11. Model/Agent picker

Use searchable Combobox/Command-like picker for more than a handful of models.

Row structure:

```text
[provider icon?] Model Display Name                ✓
                 Provider · Speed · Context
```

Metadata is optional and conditional.

Sections may include:

- Recommended / Default
- Recent
- Provider groups

Do not visually over-brand providers.

---

# 12. Runtime state visuals — Run Pulse

Use restrained semantic state mapping.

Do not assign a unique neon color to every state.

Suggested classes:

- neutral animated pulse: Thinking/Calling model;
- active accent: Running tool;
- warm attention: Waiting approval/Retrying;
- quiet success: Completed;
- neutral interruption: Interrupted;
- danger: Failed.

Motion should be subtle and short; continuous pulse must not be distracting.

---

# 13. Timeline

Balanced density is default.

Recommended row/event anatomy:

```text
│ icon  Tool Call · read_file          42 ms
│       src/agent/runtime.py
│       120–200 lines
```

or

```text
│ icon  LLM · DeepSeek V4 Flash        1.8 s
│       2.1k in · 640 out
```

or

```text
│ icon  Waiting for approval
│       bash: npm test
│       [Deny] [Approve once] [Approve]
```

### Trace Ladder

Trace Ladder belongs in Timeline, not as a decorative widget in Chat.

Use a subtle vertical guide only where it helps sequence scanning.

### Selection

Selected event:

- faint accent-tinted surface;
- no large glow;
- Inspector updates context.

### Raw mode

Raw mode can expose structured event JSON in a code-like viewer.

---

# 14. Inspector visual language

Use clear grouped sections with compact headers:

```text
RUN
Status           Running tool
Duration         12.4s
Current step     7

MODEL
Model            qwen-plus
Tokens           12.8k / 820
Latency          1.7s
```

Use mono where IDs/trace values benefit.

Do not wrap every section in a large card. Prefer section dividers and spacing.

---

# 15. Command Palette

`Cmd/Ctrl + K`.

Raycast/Linear-inspired characteristics:

- centered or top-biased floating overlay;
- glass/elevated surface allowed;
- fast opening;
- immediate input focus;
- grouped results;
- keyboard navigation;
- shortcut hints;
- no route-changing flicker.

Use a mature command/combobox primitive where compatible.

---

# 16. Empty states

Example Timeline empty:

```text
No runtime events yet
Send a task to start a run. Tool calls, model steps, retries, and checkpoints will appear here.
```

Example Artifacts empty:

```text
No artifacts for this session
Generated files, reports, diffs, or other outputs will appear here.
```

No oversized illustration necessary.

---

# 17. Error and approval surfaces

## Error

Inline event failure:

```text
Tool failed · bash
Exit code 1
View details →
```

## Approval

Approval surface should feel native to Timeline/Run flow:

```text
Permission required
Run `npm test` in project workspace?

[Deny] [Approve once] [Approve for session]
```

Buttons and policy text depend on real backend modes.

---

# 18. Motion system

Create tokens, not ad-hoc durations.

```css
--motion-fast: 140ms;
--motion-base: 190ms;
--motion-layout: 230ms;
```

Use easing curves appropriate to platform feel.

Rules:

- motion is interruptible;
- no wait-mode sequencing that blocks a new real-time event;
- streaming event arrival renders immediately;
- panel transitions do not lock input;
- reduced-motion keeps essential context transitions but removes large transforms.

---

# 19. Keyboard and focus

- visible focus ring must be restrained but clear;
- use focus-visible, not permanent mouse-click ring;
- Esc closes topmost transient surface;
- arrow keys navigate menus/listboxes;
- Tab order follows visual hierarchy;
- no keyboard trap except correct modal/dialog semantics.

---

# 20. Responsive behavior

### ≥1440px

All three columns visible comfortably.

### ~1180–1439px

All three may remain visible with narrower rails.

### ~1024–1179px

Inspector can auto-collapse to a toggle/drawer-like side panel; Session remains until necessary.

### narrower fallback

Session Rail may collapse; Workspace remains fully usable.

Do not simply shrink text/controls until unreadable.

---

# 21. Accessibility target

WCAG 2.2 AA target.

Required visual checks:

- text contrast;
- focus contrast;
- error state not color-only;
- Run Pulse not color-only;
- selected event not color-only;
- icon-only buttons have labels/tooltips;
- reduced motion supported.

---

# 22. Design-system layering

The user explicitly chose **shared Design Tokens as the mandatory foundation**, not a large bespoke design-system project. Use the following as a **conceptual organization when those layers already exist or are needed**, not as a mandate to hand-build all layers:

```text
Tokens  ← mandatory
  ↓
Existing/reused Primitives  ← prefer reuse
  ↓
Minimal product Components  ← only where needed
  ↓
Feature Surfaces
```

Examples:

### Tokens

color, spacing, radius, motion, type, shadow, z-index.

### Primitives

Button, IconButton, TextField, Popover, Tooltip, Menu, Dialog, Tabs, ScrollArea.

### Components

ModelPicker, PermissionPicker, SessionRow, RunPulse, EventRow, InspectorSection.

### Feature Surfaces

Composer, SessionRail, Timeline, RunInspector, CommandPalette.

Do not create a large custom primitive library merely to satisfy this diagram. The key rule is consistency: feature pages must use shared tokens and existing/reused primitives where available rather than inventing incompatible local styles.

---

# 23. Reuse directive

Before implementing each primitive, audit current dependencies.

Prefer existing/mature primitives for difficult behavior:

- focus management;
- collision-aware popovers;
- keyboard menus;
- accessible dialogs;
- list virtualization;
- animation presence/reduced motion.

A custom wrapper styled to this design system is expected. A custom reimplementation of accessibility/positioning behavior is not preferred.

---

# 24. Visual QA loop

Frontend AI must not declare completion from code inspection alone.

Required loop:

1. run app;
2. inspect at 1024 / 1280 / 1440+;
3. light and dark;
4. empty, active streaming, long Timeline, error, approval, selected event;
5. compare visual hierarchy to benchmark principles;
6. inspect focus/keyboard behavior;
7. inspect animations for flicker/input delay;
8. fix design drift;
9. screenshot before/after for review.

Use Chrome DevTools/browser automation available in the development environment for objective QA.
