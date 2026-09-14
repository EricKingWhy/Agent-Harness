# Benchmark & Reuse Matrix

> Purpose: turn “reference Linear / ZCode / DeepSeek Harness / Raycast” into concrete adopt/reuse/do-not-copy instructions.

---

# 1. Linear

Reference:

- https://linear.app/now/behind-the-latest-design-refresh
- https://linear.app/now/how-we-redesigned-the-linear-ui

## Adopt

- quieter/dimmer navigation;
- dense information hierarchy;
- fewer separators;
- consistent headers/tabs;
- restrained icons;
- main content wins visual attention;
- structure through hierarchy rather than card borders.

## Do not copy

- Linear logo/brand assets;
- exact proprietary CSS/DOM implementation;
- exact iconography or branded colors;
- exact page composition unrelated to Agent runtime needs.

## Practical use

Run visual benchmark comparisons after each Shell/Sidebar/Header milestone.

---

# 2. ZCode

References:

- https://zcode.z.ai/en/docs/agents
- https://zcode.z.ai/en/docs/safety-confirm
- https://zcode.z.ai/en/docs/skill

## Adopt

- composer as task/Agent control surface;
- model and execution/permission controls near input;
- workspace/branch/context awareness;
- visible risk/permission mode;
- contextual references/commands/skills concepts when architecture supports them.

## Do not copy

- proprietary component code;
- brand assets;
- ZCode-specific product concepts that this backend does not support.

## Practical use

Benchmark Composer information architecture and keyboard flow, not pixel cloning.

---

# 3. DeepSeek Harness

References:

- https://github.com/deepseek-ai/deepseek-harness
- https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/web-client.md
- https://github.com/deepseek-ai/deepseek-harness/blob/master/LICENSE

License: **MIT**.

## Strong candidates to reuse/adapt

- event-first UI architecture concepts;
- authoritative Host/backend state;
- separation of Chat and Trajectory projections;
- reconnect/replay concepts;
- event/window/projection handling patterns;
- compatible UI/component logic if it fits the current framework and saves work.

## Reuse rule

If copying/adapting substantial source:

- inspect exact file license/third-party notices;
- retain required copyright/license notice;
- do not import the entire DSH architecture merely for one component;
- prefer extracting a small compatible pattern over coupling this project to Cordis unless that is an intentional architecture decision.

## Important warning

DeepSeek Harness is developer-preview software and changes rapidly. Treat it as reference/reusable code, not an immutable upstream contract.

---

# 4. Raycast

References:

- https://www.raycast.com/blog/the-new-raycast
- https://www.raycast.com/blog/a-technical-deep-dive-into-the-new-raycast

## Adopt

- tasteful Liquid Glass on transient surfaces;
- native-feeling overlays;
- keyboard-first discipline;
- hover/focus/popover details;
- no transition flicker;
- speed as a design property.

## Do not copy

- Raycast brand/UI assets;
- exact macOS-specific visual material where it harms cross-platform Web readability;
- large portions of closed implementation.

---

# 5. Radix Primitives

References:

- https://www.radix-ui.com/primitives
- https://www.radix-ui.com/primitives/docs/components/popover

## Use when current stack is compatible

- Popover;
- Dropdown Menu;
- Tooltip;
- Dialog;
- Select/Toggle/Tabs;
- focus management;
- keyboard interaction;
- collision-aware overlay positioning.

## Benefit

Avoid hand-written accessibility/focus/positioning bugs.

---

# 6. shadcn/ui

Reference:

- https://ui.shadcn.com/docs/components/base/combobox

## Use when appropriate

- model/agent searchable Combobox;
- locally owned source components that can be visually transformed into this design language.

## Rule

Do not accept default shadcn styling as final design. Reuse behavior/source, then apply project tokens.

---

# 7. TanStack Virtual

Reference:

- https://tanstack.com/virtual/latest/docs/framework/react

## Use for

- Timeline with hundreds/thousands of rows;
- large Session/history lists if needed;
- variable row measurement when event details expand.

## Rule

Only add if current project does not already have suitable virtualization.

---

# 8. Motion for React

References:

- https://motion.dev/docs/react-use-reduced-motion
- https://motion.dev/docs/react-animate-presence

## Use for

- short overlay/panel transitions;
- Run Pulse micro-motion;
- reduced-motion support;
- presence transitions where they do not delay live event rendering.

## Avoid

- sequential animations that make new Agent events wait;
- heavy layout animation for every Timeline append.

---

# 9. Reuse decision algorithm

For every new UI behavior:

```text
Does current project already solve it well?
  ├─ yes → reuse
  └─ no
      ↓
Is there a mature open-source primitive already installed/compatible?
  ├─ yes → reuse/wrap
  └─ no
      ↓
Does DeepSeek Harness have compatible MIT code/pattern?
  ├─ yes → evaluate/adapt with license compliance
  └─ no
      ↓
Custom implement only the product-specific behavior.
```

For visual inspiration from proprietary apps:

```text
Borrow principle / hierarchy / interaction pattern
NOT proprietary code / assets / exact branded clone
```

---

# 10. Reuse audit deliverable

Before implementation, Frontend AI should create a small table like:

| Need | Current project | Candidate reuse | Decision | Reason |
|---|---|---|---|---|
| Model picker | native select | existing shadcn Combobox | reuse | searchable + keyboard |
| Popover | custom div | Radix already installed | reuse | focus/collision |
| Timeline virtual list | none | TanStack Virtual | add | long history |
| Run Pulse | none | product-specific | custom | signature interaction |
| Chat/Timeline projection | current chat-only | DSH architecture reference | adapt pattern | event-first separation |

Do this before adding new dependencies.
