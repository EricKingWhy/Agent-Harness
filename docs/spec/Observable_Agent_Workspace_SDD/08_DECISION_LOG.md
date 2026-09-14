# Frozen Decision Log — grill-me Round 1–3

> This is the authoritative record of user decisions used by the SDD package.

---

# Round 1 — Product / Visual / IA

| # | Decision |
|---|---|
| 1 | **C** — Premium AI Workspace + Developer Workbench middle route. |
| 2 | **A + C** — primary daily user + future public/developer users. |
| 3 | **A + C** — preserve three-column topology; collapsible sides; Workspace primary. |
| 4 | **A** — Chat / Timeline / Changes / Terminal / Artifacts all belong to architecture. |
| 5 | **A** — Timeline is core and first-class. |
| 6 | **D** — Compact/Balanced/Detailed/Raw; Balanced default. |
| 7 | **A** — event click switches Inspector context. |
| 8 | **B/C** — Run not primary navigation; final backend entity mapping decided after audit. |
| 9 | **C** — Linear-minimal Session list + active Run Pulse/status. |
| 10 | **A** — replace “default chain” native-like Select with full composer control surface. |
| 11 | Uncertain, leaning **A** — Agent chooses capabilities/tools; backend audit required. |
| 12 | **A** — adaptive Floating Composer with progressive disclosure. |
| 13 | **C** — light/dark equal priority. |
| 14 | **D** — original accent, with subtle pale-pink character. |
| 15 | **B + C** — Raycast-level material quality, but constrained rather than global glass. |
| 16 | **A** — animations must never make Agent feel slower. |
| 17 | **A** — Run Pulse adopted. |
| 18 | **B** — Trace Ladder belongs to Timeline; do not pollute Chat. |
| 19 | **B** — Inspector open by default, collapsible. |
| 20 | **C** — redesign entire Web UI foundation, not only composer. |

---

# Round 2 — Runtime / Backend Contract

| # | Decision |
|---|---|
| 21 | **A** — assistant chunks + runtime events both stream in real time. |
| 22 | **C** — keep current stable SSE/WS; no needless transport migration. |
| 23 | **C** — audit backend domain model before deciding Session/Turn/Run entities. |
| 24 | **A** — Run is engineering detail, not left-nav unit. |
| 25 | **A** — Timeline must be driven by real runtime events. |
| 26 | **A** — append-only Runtime Event log. |
| 27 | **A** — refresh/disconnect/reconnect must restore Timeline state. |
| 28 | **A** — Tool args summarized in Timeline, full in Inspector. |
| 29 | **A** — Tool Result preview in Timeline, full in Inspector/lazy detail. |
| 30 | **A** — large results lazy-load. |
| 31 | **B/C** — safe reasoning summary where provider supports it; otherwise Thinking state only. |
| 32 | **A** — tokens/cost/latency only when real; otherwise unavailable. |
| 33 | **A** — backend may estimate context usage, clearly label Estimated. |
| 34 | **C** — audit backend before deprecating Chain terminology. |
| 35 | **A** — richer model selector metadata. |
| 36 | **A** — Permission Mode belongs in Composer; if backend lacks it, Backend AI must implement real support. |
| 37 | **C** — Changes only when Coding capability exists. |
| 38 | **B** — hide Terminal when unavailable. |
| 39 | **A** — unified Artifact model. |
| 40 | **C** — mocks allowed for Storybook/fixtures only; production pages use real runtime data. |

---

# Round 3 — UX / Performance / Engineering

| # | Decision |
|---|---|
| 41 | **B** — desktop/laptop first; 1024px+ complete; narrower uses intelligent collapse. |
| 42 | **A** — collapse Inspector first, then Session Rail. |
| 43 | **A** — Command Palette is first-class. |
| 44 | **B** — broad keyboard-first support across navigation/tabs/composer/timeline/inspector. |
| 45 | **B + C** — search Session/Event/Artifact/Command and extend to Tool Result/file content when backend supports it. |
| 46 | **B** — contextual minimal empty states. |
| 47 | **B** — contextual inline errors + Inspector detail; serious global error can notify. |
| 48 | **B** — skeleton for initial loading; Run Pulse/events for runtime execution. |
| 49 | **A** — first-class Stop current Run. |
| 50 | **B** — Retry Run / Resume checkpoint where backend supports. |
| 51 | **B** — inline runtime approval surface + Waiting approval state. |
| 52 | **A** — Modal only for genuinely blocking/high-risk decisions. |
| 53 | **B** — Toast only for transient non-critical acknowledgement. |
| 54 | **A** — motion target: 120–160ms micro, 160–220ms overlay, ≤240ms layout. |
| 55 | **A** — reduced-motion support. |
| 56 | **B** — WCAG 2.2 AA target. |
| 57 | **A** — performance budget is a hard acceptance concern. |
| 58 | **C** — audit current frontend stack first; default no framework rewrite. |
| 59 | **C** from final answer mapping? User answered Round-3 item 19 as **C** — retain at least Design Tokens; however user additionally requires reuse-first and overall product needs a coherent component system. See clarification below. |
| 60 | **A** — strict shared PRD/Contract + separate worktrees + contract verification before merge. |

### Clarification for Decision 59

The Round-3 question offered:

- A: direct per-page styling;
- B: Tokens → Primitives → Components → Feature Surfaces + Storybook/fixtures;
- C: only Tokens.

The user's final response sequence was `...18.C。19.C。20.A`.

Therefore literal answer is **C**. However the same user message adds a strong requirement:

> When designs/implementations can be borrowed or reused from Linear, DeepSeek Harness, ZCode, etc., do not hand-write unnecessarily; reuse them.

To reconcile without overriding the user:

- **Mandatory shared Design Tokens** are frozen.
- Do **not** require building a large bespoke design-system project from scratch.
- Where the current stack already has primitives/components or mature open-source primitives exist, **reuse/wrap them**.
- Build only the minimal product-specific component layer necessary for visual consistency.
- Storybook/fixtures are encouraged where already supported or cheap, but not a mandatory platform rewrite.

This preserves the user's C choice while preventing page-level inconsistency and unnecessary hand-written UI infrastructure.

---

# Additional frozen user directive — reuse first

The user explicitly requires:

> Many designs can be referenced from Linear, DeepSeek Harness, ZCode, etc. If something can be directly borrowed/reused appropriately, do not hand-write it unnecessarily.

Interpretation:

1. reuse current project dependencies first;
2. reuse mature open-source primitives second;
3. inspect MIT-licensed DeepSeek Harness implementation where compatible;
4. borrow proprietary products' interaction/design principles, not proprietary source/assets;
5. custom-code only the product-specific layer.


### ADR-0020 — Stage Composer controls before runtime consumption

Phase 5 accepts `reasoning_effort`, `agent_profile`, and `context_providers` as
validated session contract fields while keeping runtime behavior unchanged. This
avoids a frontend/backend contract mismatch without pretending provider-specific
reasoning switches, profile tool scoping, or provider filtering are implemented.
Runtime consumption is a follow-up batch with explicit capability/status evidence.

**RUNTIME follow-up batches complete (all three fields consumed):**
- `reasoning_effort` → injected via `create_chat_model` (ADR-0018 D7).
- `agent_profile` → `system_prompt` via ContextBuilder + `tool_scope` via
  `registry.filtered` (ADR-0020a).
- `context_providers` → session-level subset selection by provider `name`,
  dynamic discovery endpoint projection (ADR-0020b).
