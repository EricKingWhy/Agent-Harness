# Agent Runtime Streaming UI Redesign — Product PRD v2

> **Authority**: This document is the authoritative product/UX requirement for the Agent Runtime Web UI redesign. It supersedes the earlier `Agent_Runtime_Web_UI_Redesign_PRD_UX_Spec.md` where conflicts exist and inherits all non-conflicting frozen requirements from that document.
>
> **Purpose**: Upstream input for SDD. The implementing AI must read this document first, then the runtime protocol specification and frontend implementation specification, run an implementation-level `grill-me`, generate tickets, implement in small reversible steps, and perform code review after each meaningful phase.
>
> **Status**: Product direction frozen; implementation details may still be clarified during SDD.

---

## 0. Executive Summary

The product is not a chat demo and not a generic admin dashboard. It is a production-grade **Agent Runtime Developer Tool** with two simultaneous views of the same execution:

1. **Center: Continuous Agent Stream** — human-readable, elegant, high-signal narrative of what the Agent is doing.
2. **Right: Run Inspector** — DeepSeek-Harness-style, machine-readable, more detailed, complete runtime debugger.

The central redesign in v2 is **true streaming runtime UX**.

Reasoning/progress, assistant text, tool calls, tool output, search/read, MCP, skills, subagents, plan/todo, and runtime events must be able to appear incrementally as the run progresses. The UI must not wait for a full model call to complete before revealing activity, and it must not fake streaming by replaying already-completed text with a fixed typewriter delay.

The target product feeling is:

> **Apple-level polish**  
> **ZCode-level continuous agent narration**  
> **DeepSeek Harness-level observability**  
> **Linear / Raycast-level information hierarchy**  
> **Production-grade latency, resilience, replayability, and accessibility**

The visual philosophy is **Digital Humanism**: technology is visible and precise, but human comprehension, rhythm, typography, calmness, and control dominate the interface.

---

# 1. Product Principles

## 1.1 Production, not demo

The feature is considered incomplete unless it is suitable for long-running real sessions and adverse conditions.

Required qualities:

- low perceived latency;
- no artificial typing delay;
- graceful reconnect and resume;
- idempotent event handling;
- long-session performance;
- replayable history;
- robust malformed-event handling;
- backpressure strategy;
- accessibility;
- telemetry and performance measurement;
- stable interaction state when events continue to arrive.

A visually attractive implementation that fails under long streams, reconnects, large tool output, or history replay is a failed implementation.

## 1.2 Reuse before build

**Buy / reuse / compose before custom-building.**

Before implementing infrastructure or UI primitives, inspect existing project dependencies and evaluate mature libraries. Reuse is preferred when it:

- preserves the project's canonical runtime event model;
- does not weaken Inspector depth or replay;
- meets visual customization requirements;
- meets performance and bundle constraints;
- has acceptable maintenance health.

Custom work should be concentrated on genuine differentiators:

- Runtime Event Projection;
- cross-event relationship modeling;
- Run Inspector;
- streaming state machines;
- replay / resume integration;
- product-specific semantic iconography;
- product visual language.

## 1.3 One runtime, two projections

The center stream and right Inspector **must not maintain separate truth**.

Both derive from the same canonical run/event state:

```text
Canonical Runtime Events
          │
          ├── Human Projection → Continuous Agent Stream
          │
          └── Debug Projection → Run Inspector
```

The center answers:

> What is the Agent doing?

The Inspector answers:

> What exactly happened in the Runtime?

## 1.4 User control beats automation

Auto-follow, auto-open, auto-collapse, and active-event selection are defaults only. Once the user deliberately interacts, the interface must stop fighting them.

Examples:

- manually collapsed active reasoning remains collapsed while streaming continues;
- manually scrolled-up content does not snap to bottom on every delta;
- manually selected historical Inspector event disables automatic active-event following;
- manually opened completed reasoning is not auto-closed.

---

# 2. Inherited Frozen Product Decisions

The following decisions from v1 remain mandatory.

| ID | Requirement |
|---|---|
| D1 | Right-side **Run Inspector remains a core product highlight** and must be more detailed than the center stream. |
| D2 | **Compact / Balanced / Detailed / Raw** modes all remain. |
| D3 | Center uses a **ZCode-style Continuous Agent Stream**; right side remains a **Harness-style Runtime Debugger**. |
| D4 | Tool default visibility is **semantic/tool-type-aware**, not one rule for every tool. |
| D5 | Multi-level **Progressive Disclosure** is mandatory. |
| D6 | Failed tools are not forced fully open; failure is obvious at summary level. |
| D7 | User-visible reasoning/progress may be shown, but private hidden Chain of Thought must not be exposed. |
| D8 | Skill / MCP / Subagent are first-class runtime event types. |
| D9 | Todo / Plan is a native first-class stream component. |
| D10 | Existing top-bar Inspector toggle remains; click opens/closes the right panel. |
| D11 | Existing Inspector capabilities are preserved; redesign may add capabilities but not remove them. |
| D12 | Repetitive generic circular Agent avatars are replaced by semantic event icons. |
| D13 | Visual direction: clean Apple/ZCode surfaces, typography + spacing + hairline hierarchy, minimal cardification. |
| D14 | Information density should be close to ZCode, not a low-density marketing UI. |
| D15 | Top-bar functions remain; visual hierarchy improves without feature deletion. |
| D16 | User prompt remains a light, right-aligned prompt surface. |
| D17 | Final answer receives stronger visual contrast than runtime activity. |
| D18 | Code/Shell/JSON surfaces support high-quality highlight, copy, wrap, bounded scrolling, and enlargement/fullscreen where useful. |
| D19 | Command Palette is included. |
| D20 | Default experience is clean; deep Debug is one action away. |

---

# 3. Streaming Decisions Frozen in v2

| ID | Requirement |
|---|---|
| S1 | Support both **provider-exposed user-visible reasoning stream** and **Agent progress summary stream** through one UI abstraction. |
| S2 | Reasoning is segmented around tools: `reasoning → tool → reasoning` are sibling stream blocks, not one giant thought block. |
| S3 | Collapsed reasoning shows a **forward-reading one-line viewport** progressing from the beginning through the currently received reasoning; no extra model call is allowed. |
| S4 | Collapsed reasoning updates live while hidden details continue streaming. |
| S5 | Header changes live: `正在思考 · 12 秒` → `思考 · 持续了 12 秒` with a smooth state transition. |
| S6 | Active reasoning auto-opens by default; completed reasoning auto-collapses unless the user manually interacted. |
| S7 | Manual collapse during streaming is respected; stream continues in background. |
| S8 | Expanded long reasoning uses a bounded scroll surface with auto-follow while the user is at the bottom. |
| S9 | User scrolling upward suspends auto-follow and exposes a subtle “Jump to latest” control. |
| S10 | Streaming phase uses lightweight rendering; full Markdown/highlighting is applied when the block is stable/completed. |
| S11 | Thinking, Search/Read, Terminal, Skill, MCP, Subagent, Todo all use semantic event rows and icons. |
| S12 | Use mature icon libraries for generic UI and a small custom semantic glyph set for product-defining Agent activities. |
| S13 | Tools are siblings of reasoning blocks in the narrative stream. |
| S14 | Tool stdout/stderr and other supported outputs stream live. |
| S15 | Final assistant answer streams through the same true streaming architecture. |
| S16 | Right Run Inspector updates live as runtime activity happens. |
| S17 | Inspector default timeline groups micro-deltas into logical nodes; Raw mode can expose underlying chunks. |
| S18 | Historical sessions restore reasoning, timing, tool order, and stream block structure. |
| S19 | Persist coalesced chunks and assembled blocks rather than one permanent database row per token. |
| S20 | Visual “typing” is data-driven with lightweight smoothing/catch-up, never fixed-character fake playback. |
| S21 | Active state uses subtle breathing/liveness, not aggressive loaders. |
| S22 | Short periods without delta remain “thinking/running”; only actual timeout policy changes state. |
| S23 | Input/Output payloads do not dominate Balanced mode; they remain progressively disclosed. |
| S24 | Compact / Balanced / Detailed / Raw remain global modes and are redefined for streaming content. |
| S25 | This v2 is the single authoritative product PRD for the redesign. |
| S26 | Backend and frontend may both change as needed for true streaming, while **Agent Loop decision semantics remain out of scope**. |

---

# 4. Product Information Architecture

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Top Bar: Run ID · Status · Compact · Balanced · Detailed · Raw · Actions  │
├───────────────┬───────────────────────────────────────┬────────────────────┤
│ Session       │ Continuous Agent Stream               │ Run Inspector      │
│ Navigator     │                                       │                    │
│               │ User Prompt                           │ Logical Timeline   │
│               │ Streaming Reasoning / Progress        │ Event Detail       │
│               │ Search / Read / Skill / MCP           │ Input / Output     │
│               │ Tool / Tool Output                    │ Raw Chunks         │
│               │ Subagent / Todo                       │ IDs / Timing       │
│               │ Streaming Final Answer                │ Metrics / Links    │
├───────────────┴───────────────────────────────────────┴────────────────────┤
│ Floating Composer                                                          │
└────────────────────────────────────────────────────────────────────────────┘
```

The layout does not become a generic “three-column dashboard”. Visual continuity must make the center feel like a document/workspace and the Inspector feel like a contextual debugging instrument.

---

# 5. Continuous Agent Stream

## 5.1 First-class semantic block types

At minimum:

- UserMessage
- ReasoningBlock
- ProgressBlock
- SearchBlock
- ReadBlock
- ToolBlock
- ToolOutputBlock
- SkillBlock
- MCPBlock
- SubagentBlock
- TodoPlanBlock
- ModelMetaBlock
- RuntimeNoticeBlock
- ErrorBlock
- FinalAnswerBlock

Future capabilities such as Memory, RAG, Checkpoint, Replay, Approval and Sandbox should plug into the same projection registry without redesigning the whole stream.

## 5.2 Semantic event rows

Examples:

```text
🧠 正在思考 · 12 秒    正在检查 Runtime Event Schema…
⌕  查阅 · 3 文件
⌘  终端   npm run test                                     4.8s
✦  技能   code-review
⌁  MCP    Chrome DevTools · Take screenshot
◈  子智能体   general-purpose · Standards review
☷  待办   UI 验收 2/5
```

These are not “cute decoration”. They form a stable visual grammar that lets the user parse a run without reading every payload.

## 5.3 Low-noise hierarchy

Runtime rows use reduced contrast relative to the final answer. The result should feel closer to ZCode/Linear than terminal logs.

Avoid:

- every row inside a card;
- large colored badges;
- repeating avatars;
- neon accents;
- large filled status pills;
- heavy separators.

Prefer:

- typography;
- semantic glyphs;
- whitespace rhythm;
- subtle indentation;
- thin hairlines only where necessary;
- low-saturation status hints.

---

# 6. Reasoning / Progress Streaming UX

## 6.1 Privacy and source contract

The UI may show only:

1. reasoning explicitly exposed by the provider as user-visible; or
2. Agent-generated progress/reasoning summaries designed for UI display.

The UI and protocol must have a `visibility/source` distinction so hidden provider/internal Chain of Thought is never accidentally surfaced.

## 6.2 Reasoning lifecycle

```text
idle
  ↓
streaming
  ↓
completed

streaming → interrupted
streaming → failed (only if the reasoning block itself fails)
```

Header examples:

```text
Streaming:   🧠 正在思考 · 36 秒
Completed:   🧠 思考 · 持续了 36 秒
Interrupted: 🧠 思考 · 中断于 36 秒
```

Duration must update from a monotonic client/server timing basis without triggering heavy re-render of the full content tree.

## 6.3 Collapsed live reasoning

Collapsed mode is not static.

Target structure:

```text
[Brain] 正在思考 · 36 秒   <one-line forward-reading viewport>     [chevron]
```

Behavior:

- it consumes the same accumulated block buffer as expanded view;
- it progresses **from the beginning forward** through the incoming reasoning text;
- it does not invoke a summary model;
- it does not restart from the beginning on every new delta;
- it does not jump discontinuously to the last token;
- the viewport advances in reading order as new text arrives;
- overflow fades at edges using a subtle mask;
- animation must be transform/mask based or equivalent lightweight compositor-friendly implementation;
- no marquee loop; no continuously repeating text;
- if backlog grows, the viewport may accelerate within defined limits to avoid becoming minutes behind actual progress.

This should feel like a calm reading window, not a ticker tape.

## 6.4 Expanded live reasoning

Expanded form:

```text
🧠 正在思考 · 36 秒                                  ⌃
│
│ Actually wait — the summary said Phase 12...
│ And the projection already exists...
│ ...new text continues...
```

Requirements:

- text appears incrementally as real deltas arrive;
- short blocks expand naturally;
- long blocks transition to a bounded max-height viewport;
- when the user is at/near bottom, content follows incoming text;
- when the user scrolls upward, follow suspends immediately;
- a subtle “↓ 跳到最新” control appears while suspended;
- returning to latest resumes follow;
- collapsed/expanded transition must not interrupt the stream or reconstruct data.

## 6.5 Auto-open / auto-collapse

Default behavior:

```text
Reasoning A streaming → open
Tool starts            → A may close when completed
Reasoning B streaming → B opens
```

But `user_interacted = true` overrides automation for that block for the remainder of the current page lifecycle.

## 6.6 Rendering strategy

During streaming:

- lightweight text / minimal Markdown parsing;
- no syntax highlighting on every delta;
- no full AST rebuild per token;
- no Motion animation per token.

After a block stabilizes/completes:

- full Markdown;
- lazy syntax highlighting;
- richer code surfaces;
- post-processing links if needed.

---

# 7. Tool Streaming UX

## 7.1 Tool row

```text
[status] [semantic icon] [tool] [human summary]                      [duration]
```

Examples:

```text
✓  ⌘ bash    npm run test                                            8.2s
✓  ✎ write   秋天的三个意象.md                                       12ms
×  ⌘ bash    sleep 25                                                10.0s
```

## 7.2 Tool args streaming

Partial function arguments must not pollute the center stream with malformed half-JSON.

Center while arguments are incomplete:

```text
⌘ Preparing bash…
```

Inspector may expose partial args in a developer-oriented view.

Once args are syntactically meaningful, the center summary updates naturally.

## 7.3 stdout / stderr live output

Where the backend/provider/tool runner supports it:

```text
tool/call_started
stdout delta
stdout delta
stderr delta
...
tool/result
```

stdout and stderr remain separate logical channels even when visually unified.

The UI must support:

- live append;
- copy;
- wrap/no-wrap;
- bounded viewport;
- auto-follow when at bottom;
- “jump to latest” when follow is suspended;
- error semantics;
- output truncation/load-full strategy for very large output.

## 7.4 Large output

The DOM must never contain unbounded tens of thousands of terminal rows solely because the tool emitted them.

Use:

- virtualized/bounded viewport;
- tail window;
- server-retained or persisted complete output;
- explicit “load full output”/search/download/copy affordances where appropriate.

Thresholds are implementation/benchmark decisions, not hard-coded product values.

---

# 8. Streaming Final Answer

The final answer must be true streaming text, using the same event pipeline but a higher-contrast presentation.

```text
Runtime activity (low contrast)
        ↓
Final answer starts
        ↓
High-contrast prose streams live
```

Requirements:

- no wait for full answer completion;
- no fake typewriter playback;
- light rendering while streaming;
- full Markdown pass after stabilization;
- code blocks lazily receive syntax highlighting;
- selection/copy should remain usable during/after streaming.

---

# 9. Four Global Modes

All four existing modes remain.

## 9.1 Compact

Purpose: scan a long run quickly.

Default:

- Reasoning: one live line, collapsed;
- Search/Read: one line;
- Tool: one line;
- Todo: header/progress only;
- Model meta: hidden/aggregated;
- Final answer: full.

## 9.2 Balanced — recommended default

Purpose: best everyday experience.

Default:

- active reasoning may auto-open; completed reasoning collapses;
- reasoning remains manually expandable;
- Search/Read shows concise summary;
- Tool displays meaningful args summary but not large payloads;
- Tool result success stays concise; errors show summary;
- Todo shows progress and is expandable;
- important model latency/token metadata available but not dominant.

## 9.3 Detailed

Purpose: debug without living entirely in Inspector.

Default:

- reasoning expanded more aggressively;
- Tool Input/Output at L1;
- search file lists visible;
- model timing/token metadata visible;
- Skill/MCP/Subagent metadata visible;
- Todo expanded.

## 9.4 Raw

Purpose: low-level event debugging.

- center can expose raw payloads;
- JSON tree/fold/copy/wrap;
- Inspector remains present and still offers the deepest context;
- micro-delta visibility may be enabled here without changing canonical storage.

Manual local disclosure state should be preserved sensibly across mode changes and must not unexpectedly close what the user is actively reading.

---

# 10. Run Inspector — Product Differentiator

## 10.1 Position

The Inspector is not secondary decoration. It is the project's Harness signature.

It must remain available through the existing top-bar toggle and contain **more detail than the center**.

## 10.2 Dual-layer timeline

Default timeline is **logical**, not a raw packet flood.

Example:

```text
184  Reasoning     Streaming · 4.2s
185  Bash          npm test · Running
186  Tool Result   17 tests passed · 8.2s
187  Reasoning     Completed · 3.1s
188  Answer        Streaming
```

Clicking a logical node can reveal raw chunks/events:

```text
Reasoning #184
  ├─ raw delta seq 810
  ├─ raw delta seq 811
  ├─ raw delta seq 812
  └─ ...
```

Raw mode may directly expose low-level events, but the normal Inspector should remain readable even during token-heavy streams.

## 10.3 Live follow

Default: Inspector follows active logical event.

If user selects an old event:

```text
followActive = false
```

Show a subtle control:

```text
↘ Follow current activity
```

Do not steal selection on every new delta.

## 10.4 Detail tabs

Existing capability is preserved and refined:

- Overview
- Input
- Output
- Raw

Additional useful contextual sections may be added without removing current information.

Raw view supports:

- JSON tree fold;
- copy object;
- copy field/path;
- wrap toggle;
- relevant IDs;
- parent/child/paired event navigation.

## 10.5 Pairing and relationships

Support visual/logical linkage when data exists:

- model start ↔ reasoning/text ↔ model complete;
- tool call ↔ streamed output ↔ result;
- delegation start ↔ child run ↔ delegation finish;
- skill/MCP start ↔ completion;
- plan update lineage.

---

# 11. Cross-Navigation

## Center → Inspector

Hover/select/Inspect from a stream event:

1. open Inspector if closed;
2. locate logical runtime node;
3. select it;
4. show detail.

## Inspector → Center

Select logical node:

1. scroll center to projected block;
2. briefly highlight 600–900ms;
3. do not open all hidden payloads unless user requests.

“selected event” and “expanded block” are separate states.

---

# 12. Todo / Plan

Native stream component:

```text
☷ 待办   浏览器活体验收 UI 效果   2/5   ▾
```

Expanded:

```text
✓ 收集改动范围
→ 浏览器活体验收 UI 效果
○ Standards + Spec review
○ vitest + tsc + lint
○ Aggregate report
```

State changes should animate lightly and never reorder unpredictably without a runtime reason.

---

# 13. Top Bar and Command Palette

Existing top-bar functionality is preserved:

- Run ID;
- Run status;
- Compact;
- Balanced;
- Detailed;
- Raw;
- Inspector toggle;
- theme toggle;
- existing actions.

The four modes remain a refined segmented control, not oversized tabs.

Command Palette (`Ctrl+K` / `⌘K`) should include at least:

- Toggle Run Inspector;
- switch display mode;
- Search Runtime Events;
- Jump to latest;
- Follow current activity;
- Copy Run ID;
- Copy Trace ID if available;
- Toggle Theme;
- Focus Composer.

Use a mature command-menu primitive when available rather than custom keyboard plumbing.

---

# 14. Visual Design — Digital Humanism

## 14.1 Philosophy

The product should feel engineered, but not sterile.

Characteristics:

- typography is the dominant organizing system;
- low-saturation neutral palette;
- calm negative space;
- high information density with breathing room;
- semantic icons with personality;
- motion that implies liveness rather than spectacle;
- code/debug surfaces remain precise;
- minimal reliance on borders/cards;
- no generic “AI purple glow”.

Reference qualities may be learned from Apple, ZCode, Linear, Raycast, Claude, Pi and similar mature tools, but assets/layouts should not be copied literally.

## 14.2 Surfaces

Use:

> Clean Surface + Typography + Spacing + Hairline + Selective Glass

Glass is reserved for high-value floating surfaces such as:

- Composer;
- Command Palette;
- Top Bar if performance allows;
- temporary overlays.

Do not apply expensive backdrop filters to every runtime row.

## 14.3 Semantic iconography

Use a mature icon library for generic controls.

Create/commission only a small product-specific semantic glyph set for:

- Thinking;
- Search/Read;
- Skill;
- Delegation/Subagent;
- Memory;
- RAG if needed.

Thinking icon may use a brain-like glyph with subtle breathing/stroke-opacity life while active.

## 14.4 Motion

Allowed:

- disclosure open/close;
- active reasoning breathing;
- state label transition;
- selection/highlight;
- Inspector open/close;
- list reflow where meaningful.

Forbidden:

- token-by-token Motion animations;
- bouncing rows;
- constant glow;
- decorative infinite movement unrelated to state.

Respect `prefers-reduced-motion`.

---

# 15. Performance and Responsiveness SLOs

These are product-level targets. Final thresholds may be tuned after baseline measurement, but deviations require evidence and explicit review.

## 15.1 Streaming latency

After the browser/client receives a server delta:

- P50 visible update target: **<100ms**;
- P95 visible update target: **<250ms**.

The implementation should normally render through a 16–32ms or requestAnimationFrame-aware batching strategy without deliberately holding data for visual effect.

## 15.2 Interaction

- disclosure interaction perceived response P95 target: **<100ms**;
- Inspector toggle should feel immediate;
- mode switching must not reconstruct the whole session synchronously;
- no sustained long tasks >50ms caused by streaming projection under normal load.

## 15.3 Long sessions

- 10,000 logical runtime nodes must remain scrollable/responsive with virtualization or equivalent strategy;
- no uncontrolled linear DOM growth;
- no unbounded terminal DOM output;
- background tabs reduce render work;
- returning to foreground reconciles quickly instead of replaying every visual delta.

## 15.4 Bundle/runtime cost

New libraries must be measured. Large syntax highlighters/renderers should be lazy-loaded if possible.

---

# 16. Resilience Requirements

## 16.1 Reconnect

A transient network disconnect must not destroy the current run UI.

Client resumes from an event cursor/sequence or reconciles from a snapshot, depending on the chosen transport and backlog size.

## 16.2 At-least-once tolerance

Duplicate delivery must not duplicate UI blocks. Projection is idempotent.

## 16.3 Sequence gap

Malformed event or seq gap must not white-screen the app.

Expected behavior:

```text
validate
→ quarantine/report invalid input
→ attempt cursor/snapshot recovery
→ continue projection where safe
→ degrade gracefully if recovery fails
```

## 16.4 Interrupted reasoning

Already streamed content stays visible:

```text
🧠 思考 · 中断于 18 秒
```

Do not erase partial text merely because the provider failed later.

---

# 17. Persistence and History

Historical sessions must preserve the narrative order:

```text
reasoning
→ tool
→ reasoning
→ search
→ subagent
→ reasoning
→ final answer
```

History must retain:

- assembled user-visible reasoning/progress;
- duration;
- tool order;
- tool result/error;
- stream block boundaries;
- Inspector logical timeline;
- Raw data availability according to retention policy.

Presentation state such as “the user manually opened reasoning block X” is normally page-local and does not need to pollute persistent runtime truth.

---

# 18. Telemetry / Observability for the UI

Do **not** record private reasoning content in telemetry merely for metrics.

Measure technical signals such as:

- `stream_first_delta_ms`;
- `stream_gap_ms`;
- `client_render_lag_ms`;
- `event_queue_depth`;
- reconnect count;
- coalesced delta count;
- dropped/invalid event count;
- projection error;
- long task;
- current logical node count;
- virtualized/rendered node count.

Integrate with the project's observability stack where appropriate. Langfuse may track run/model/tool relationships, while client performance telemetry may require a dedicated frontend metric channel; do not misuse Langfuse if it is not the correct sink.

---

# 19. Accessibility

P0, not polish-later.

Required:

- keyboard disclosure;
- semantic buttons;
- clear focus states;
- accessible labels for icons;
- status not communicated by color alone;
- `aria-expanded` for disclosure;
- screen-reader-safe live regions used sparingly (do not announce every token);
- reduced-motion support;
- sufficient contrast in both themes;
- Command Palette keyboard-first.

Streaming text must not cause screen readers to announce every micro-delta. Announce meaningful state transitions or coarse chunks only.

---

# 20. Library / Platform Strategy

Before implementation, perform a short technical spike.

Candidates:

- **assistant-ui**: evaluate reasoning/tool disclosure primitives and architecture; reuse if it does not constrain visual design/runtime event model.
- **Vercel AI SDK / AI SDK UI**: strongly evaluate. If migrating meaningfully improves protocol/runtime/client quality without weakening the Harness event model, Inspector, replay, provider compatibility, or Python backend integration, migration is acceptable even if work is substantial.
- **TanStack Virtual**: default virtualization candidate.
- **Motion**: high-value structural micro-interactions only.
- **Zod / Valibot / existing validator**: validate network events at runtime.
- Existing project Markdown/highlighting packages should be reused before introducing new ones.

### AI SDK decision rule

Do not reject migration merely because it is work. Do not migrate merely because it is popular.

The implementation team must compare at least:

1. existing transport + canonical event model;
2. AI SDK data-stream/UI integration layered on current backend;
3. broader AI SDK migration if practical.

Choose the option that gives the best combination of:

- latency;
- provider support;
- tool/reasoning streaming;
- reconnection/recovery;
- extensibility;
- Inspector compatibility;
- replayability;
- testability;
- maintainability.

The canonical Harness event model remains authoritative even if AI SDK is used as transport/UI machinery.

---

# 21. Out of Scope

This redesign may modify provider adapters, streaming transport, event schema, persistence/projection, and frontend architecture.

It must **not** silently change:

- Agent decision policy;
- tool selection semantics;
- retry policy unless required by an explicitly approved reliability ticket;
- authorization/permission behavior;
- model routing intent;
- business behavior unrelated to streaming/runtime representation.

If implementation requires such changes, stop and raise a scope change.

---

# 22. Acceptance Scenarios

The implementation is not accepted until at least the following are demonstrated in a real browser.

## A. Reasoning streaming

1. Start a run with provider-visible reasoning.
2. Reasoning header appears quickly.
3. Collapsed line progresses live from the beginning in reading order.
4. Open it while streaming; full content continues without reset.
5. Collapse it while streaming; one-line stream continues.
6. Complete reasoning; header changes smoothly to duration state.

## B. Reasoning → Tool → Reasoning

Expected center order exactly matches runtime narrative.

Inspector shows paired logical events and can expose raw chunks.

## C. Tool stdout

Run a command producing output over several seconds.

- output appears incrementally;
- scroll-follow behaves correctly;
- user scroll upward stops follow;
- jump-to-latest restores it;
- large output does not freeze the UI.

## D. Interrupted provider

Interrupt during reasoning.

- partial content remains;
- block becomes interrupted;
- Inspector records error;
- app remains usable.

## E. Reconnect

Disconnect network temporarily during a live run.

- no duplicate stream blocks after reconnect;
- missing data is resumed/reconciled;
- UI does not replay a huge fake animation backlog.

## F. History replay

Reopen a completed historical session.

- same logical sequence is reconstructed;
- reasoning/tool boundaries are preserved;
- Inspector linkage still works.

## G. 10k logical nodes

Use synthetic fixture/benchmark.

- scroll remains responsive;
- DOM is bounded;
- Inspector and center navigation continue to function.

## H. Four modes

Compact/Balanced/Detailed/Raw each produce visibly distinct and documented disclosure behavior without losing data.

## I. Accessibility

Keyboard-only user can:

- open/close reasoning;
- inspect events;
- open Command Palette;
- switch mode;
- navigate focus meaningfully.

---

# 23. Failure Conditions

The redesign fails if any of these are true:

- reasoning is displayed only after model completion;
- “streaming” is simulated with a fixed `setInterval` typewriter after the full text is already known;
- every token causes a heavy Markdown parse or React subtree rebuild;
- collapsed/expanded use different data and lose sync;
- Inspector is simplified or loses existing Raw/Input/Output capabilities;
- large tool output grows DOM without bound;
- reconnect duplicates blocks;
- user manual scroll/collapse is overridden continuously;
- all events look like identical cards;
- design becomes neon/cyberpunk/AI-purple;
- visual polish is achieved by expensive blur everywhere;
- hidden private Chain of Thought is surfaced;
- history loses execution order;
- dark mode is simply pure black and white;
- UI is attractive only on a short happy-path demo.

---

# 24. SDD Handoff Rules

The next implementation AI must:

1. read this file;
2. read `02_RUNTIME_STREAMING_PROTOCOL_SPEC.md`;
3. read `03_FRONTEND_STREAMING_UI_IMPLEMENTATION_SPEC.md`;
4. audit the current project transport (WebSocket vs SSE vs other), provider adapters, event schema, persistence, frontend store, Inspector, and current dependencies;
5. run implementation-specific `grill-me` only on unresolved codebase facts or choices;
6. write tickets with small, independently testable, reversible scopes;
7. implement one ticket at a time;
8. run unit/integration/browser/performance checks appropriate to each ticket;
9. perform code review after each phase;
10. do not “helpfully” rewrite unrelated Agent behavior.

The product decisions above are frozen unless the user explicitly changes them.
