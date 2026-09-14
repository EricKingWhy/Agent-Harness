# Acceptance Test Plan — Observable Agent Workspace

---

# 1. Functional acceptance matrix

## Composer

- [ ] no browser-native-looking model/chain dropdown remains;
- [ ] composer auto-grows within bounds;
- [ ] focus reveals progressive controls without giant glow;
- [ ] Agent/Model/Permission/Reasoning/Branch are conditionally correct;
- [ ] model metadata comes from backend;
- [ ] send works;
- [ ] active run exposes Stop.

## Session Rail

- [ ] active/running session has Run Pulse;
- [ ] inactive chrome is visually quiet;
- [ ] collapse works;
- [ ] no card-per-row styling.

## Chat

- [ ] assistant text streams live;
- [ ] runtime tool events are not duplicated as chat bubbles;
- [ ] refresh restores settled conversation.

## Timeline

- [ ] live runtime events stream concurrently with text;
- [ ] Compact/Balanced/Detailed/Raw work;
- [ ] Balanced is default;
- [ ] click event selects Inspector context;
- [ ] keyboard navigation works;
- [ ] live-tail does not yank user after manual scroll-up;
- [ ] retry/checkpoint/permission events render correctly.

## Inspector

- [ ] Run context works;
- [ ] Tool event shows exact arguments/result metadata;
- [ ] unavailable data is not faked;
- [ ] estimated context explicitly labeled;
- [ ] collapse works.

## Permission

- [ ] permission mode selector maps to backend-supported modes;
- [ ] protected action produces permission request;
- [ ] Run Pulse enters waiting state;
- [ ] approve/deny changes backend behavior;
- [ ] decision is reflected in Timeline.

## Stop / Retry / Resume

- [ ] Stop sends a real backend cancel request;
- [ ] UI shows Stopping until confirmation;
- [ ] run becomes Interrupted when backend confirms;
- [ ] Retry only visible when available;
- [ ] Resume only visible with resumable checkpoint.

## Capability tabs

- [ ] Chat/Timeline always where relevant;
- [ ] Changes appears only for supported sessions;
- [ ] Terminal hidden if unavailable;
- [ ] Artifacts use unified model.

---

# 2. Reconnect acceptance

Test scenario:

1. start session;
2. assistant begins streaming;
3. tool starts;
4. disconnect browser/network;
5. backend completes/moves forward;
6. reconnect;
7. client requests from last sequence;
8. missing events replay;
9. no duplicates;
10. Chat/Timeline/Inspector converge to correct durable state.

Pass criteria:

- no duplicate events;
- no lost settled assistant message;
- no stale “Running tool” after completion;
- selected event behavior remains sane;
- active Run state is backend-authoritative.

---

# 3. Large data acceptance

## Long Timeline

Create fixture/integration run with at least hundreds to thousands of events.

Pass:

- scrolling remains responsive;
- DOM size remains bounded when virtualization active;
- new event append does not block typing;
- Inspector selection stays responsive.

## Large Tool Result

Use result large enough to trigger truncation/lazy load.

Pass:

- event payload remains bounded;
- Timeline shows preview;
- full content opens on demand;
- no browser freeze.

---

# 4. Performance budget

These are product budgets, not synthetic benchmark guarantees. Measure on a normal developer laptop and record results.

### Interaction

- menu/Popover open should feel immediate; target input-to-visible response < ~100ms for local UI action;
- Composer typing must remain responsive during stream;
- selected Timeline event → Inspector update should normally be < ~100ms excluding network fetch for lazy content.

### Rendering

- animations target 60fps on normal hardware;
- avoid repeated full-page rerender during token streaming;
- no long main-thread tasks caused by rendering a normal event append;
- large result JSON viewer may defer/lazy render.

### Network/data

- runtime event preview payload bounded;
- history pagination or windowing available for very long sessions;
- reconnect does not resend unbounded full history when cursor is available.

If a budget cannot be met, document profiler evidence and mitigation rather than silently accepting regressions.

---

# 5. Visual acceptance

Test widths:

- 1024px
- 1280px
- 1440px+

Test themes:

- Light
- Dark

Test states:

- idle;
- focused composer;
- model picker open;
- command palette open;
- streaming LLM;
- running tool;
- waiting approval;
- retrying;
- completed;
- failed;
- interrupted;
- selected event;
- long Timeline;
- Inspector collapsed;
- Session collapsed.

Pass criteria:

- Workspace has strongest task focus;
- navigation/chrome recedes;
- no giant rounded dashboard cards;
- no global glass;
- pale pink accent stays restrained;
- menus/overlays feel cohesive;
- no cyan glow-dominant focus ring;
- no flicker on panel/menu transitions;
- visual language consistent across all feature surfaces.

---

# 6. Accessibility acceptance

Target WCAG 2.2 AA.

Verify:

- keyboard-only task creation;
- keyboard model picker;
- keyboard tab navigation;
- keyboard Timeline selection;
- Command Palette;
- Escape behavior;
- visible focus;
- semantic labels;
- icon-only tooltips;
- no state conveyed only by color;
- reduced motion.

Use automated accessibility tooling if already present, but perform manual keyboard testing too.

---

# 7. Error-state acceptance

Simulate:

- model failure;
- tool failure;
- permission denial;
- stream disconnect;
- artifact fetch failure;
- stop failure/timeout;
- retry failure.

Pass:

- failure appears at correct context;
- Inspector has technical details where available;
- critical errors are not Toast-only;
- user can understand next action.

---

# 8. Data-truth acceptance

Reject build if any of these are found in production UI:

- fake tokens;
- fake cost;
- fake latency;
- fake model context window;
- inferred Tool Call created from assistant prose;
- visual Retry with no backend retry;
- permission mode that backend does not enforce;
- Resume button with no resumable checkpoint;
- Terminal tab with no terminal capability.

---

# 9. Security acceptance

- secrets are redacted in normal event payloads;
- permission decisions are enforced server-side;
- raw result display respects backend redaction;
- Tool Result lazy endpoints follow existing auth rules;
- no credential included in screenshots/fixtures.

---

# 10. Regression acceptance

Existing real functionality must remain operational unless PRD explicitly replaces it.

Check:

- session creation;
- message send;
- model selection;
- existing tool execution;
- existing history;
- existing backend routing;
- existing auth if any.

The redesign is not accepted if it only improves the screenshot while breaking Agent behavior.
