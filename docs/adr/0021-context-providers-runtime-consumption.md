# ADR-0021 — `context_providers` 运行时消费（稳定 id 映射 + 子集 filter）

**Status**: Accepted
**Date**: 2026-09-08
**Supersedes**: Partial — supersedes the `context_providers` portion of ADR-0020's "staged" status.
**Related**: ADR-0020 (Stage Composer controls), ADR-0020a (agent_profile runtime consumption — same RUNTIME sub-batch pattern), ADR-0010 (Capability wiring Q6), ADR-0011 (Skills capability Q1)

---

## Context

ADR-0020 accepted `context_providers: list[str] | None` as a Phase 5 staged
contract field — validated at the API boundary (Pydantic accepts `list[str]`)
but runtime no-op. `build_runtime` received the parameter, logged an INFO line,
and dropped it (`assembly.py` line 130-131). `GET /api/context-providers`
returned an honest `{"providers": []}` — wiring had not yet exposed a catalog.

This is the last RUNTIME sub-ticket field. `agent_profile` (ADR-0020a) and
`reasoning_effort` (`79e2860`) landed before it.

### Pre-existing wiring gaps

1. **No stable provider ids.** `CapabilityWiring.context_providers` was a flat
   `list[Any]` of provider instances. `MemoryContextProvider` and
   `SkillCatalogContextProvider` had no public `id` / `name` attribute. The web
   layer's `list[str]` had nothing to reference.

2. **Conditional append, no registry.** `_wire_memory` and `_wire_skills`
   appended to the list only after successful capability init (config-gated).
   There was no id→instance map, so `build_runtime` could not filter a subset,
   and the GET endpoint could not project what was actually wired.

3. **Validator was a no-op.** `CreateSessionRequest.context_providers` had no
   `@field_validator` (unlike `agent_profile` / `reasoning_effort`). Any
   `list[str]` passed Pydantic parsing.

## Decision

### 1. Minimal id→provider mapping layer in wiring (§9.2 Simplicity First)

A new `ContextProviderEntry` dataclass (`id`, `provider`, `display_name`,
`description`) and a `context_provider_entries: dict[str, ContextProviderEntry]`
field on `CapabilityWiring`. A single `register_context_provider()` helper is
the only entry point — it updates both the new dict and the legacy
`context_providers` list (kept for backward compatibility with any caller that
reads the bare list).

**Why not a full provider registry subsystem?** The ticket explicitly called
out §9.2: "如果只需要在 wiring 里加一个 id 映射层，不要造一个完整的 provider
registry subsystem." Two providers today (`memory`, `skills`); the dict is the
entire mechanism. If a third arrives, it calls the same helper — no new
abstraction needed.

**Why keep the legacy `context_providers` list?** Existing callers and tests
read `wiring.context_providers` directly. `register_context_provider()` keeps
both in sync at a single source of truth; no scope-creep refactor of readers.

### 2. `build_runtime` consumes `context_providers: list[str] | None`

Three-valued semantics, consistent with the ticket acceptance criteria:

| User input              | Runtime behavior                                    |
| ----------------------- | --------------------------------------------------- |
| `None` (default)        | wiring full set (backward compatible)               |
| `[]` (empty list)       | empty set (user explicitly chose no provider)       |
| `["memory", ...]`       | subset of wired providers, in user-specified order  |

Unknown ids (e.g. user passed `"rag"` but wiring didn't assemble it due to
config degradation) are **logged and skipped**, not raised — the web layer's
422 is the primary gate; this is defensive against the race where config
changed between the catalog GET and the POST.

**Order preservation**: the output list follows the user's submitted order,
not wiring's registration order. This lets a frontend express priority without
an additional `priority` field.

### 3. `GET /api/context-providers` projects the real wired catalog

The endpoint now `await state.get_wiring()` (lazy, same as other wiring-dependent
endpoints) and projects `wiring.context_provider_entries.values()` into
`{id, display_name, description}` entries. Bare config (no capabilities) →
empty list (existing test still passes). Wired config → real catalog.

### 4. Handler-level 422 validation (not Pydantic `@field_validator`)

`context_providers` validation depends on **runtime wiring state**
(conditional, config-gated), but Pydantic `@field_validator` runs at parse
time — before the handler has access to `AppState` / `wiring`. This is the
same constraint the `model` field faces (catalog-based, resolved in the
handler via `ModelConfig.from_catalog` → 422).

The validation lives in `create_session` after `get_wiring()`: unknown ids →
`HTTPException(422)` with the available set in the detail. This keeps the
"validator accepts exactly what GET returns" invariant (id-set match) without
a Pydantic-time hook that can't see wiring.

## Consequences

### Positive

- `context_providers` is a real runtime control. The RUNTIME sub-batch is
  complete (`agent_profile` + `reasoning_effort` + `context_providers`).
- Frontend F3 (multi-select picker) now has a real GET endpoint to consume —
  it was blocked on B2.
- The honest-catalog principle holds: config-off providers never appear in GET
  and are rejected at POST (no "ghost" providers).

### Negative / Trade-offs

- **Two GET paths for wiring**: `state.wiring` property (sync, may be None) +
  `await state.get_wiring()` (async, lazily assembles). The GET endpoint checks
  the property first and only awaits if wiring is not yet assembled. This
  mirrors the laziness of other endpoints but means a cold GET (before any
  POST) will trigger full capability assembly — slightly more expensive than
  the old hardcoded `[]` return. Acceptable: GET is infrequent and the
  assembly result is cached.

- **Legacy `context_providers` list duplication**: `register_context_provider`
  maintains both the dict and the list. If a future caller mutates one without
  the other, they'd drift. Mitigated by the single-helper-entry-point rule —
  no direct `.append()` calls remain in `_wire_memory` / `_wire_skills`.

- **Unknown-id tolerance in `build_runtime`**: the runtime skips unknown ids
  rather than raising, which could mask a bug where the web layer fails to
  validate. This is intentional defense-in-depth (web 422 is primary; runtime
  is the secondary gate against config-degradation races), and it logs a
  WARNING with the offending id and the available set.

## Alternatives considered

- **Pydantic `@field_validator` with app-state injection** (e.g. via a custom
  validator that reads `request.app.state`). Rejected: Pydantic validators run
  before the handler binds `request`, and coupling request parsing to global
  app state breaks the "validator is pure" contract. The `model` field set the
  precedent of handler-level catalog validation.

- **A standalone `ContextProviderRegistry` class** wrapping the dict. Rejected
  under §9.2: `dict[str, ContextProviderEntry]` + one helper is the entire
  registry. A class would add indirection without new capability.

- **Static provider catalog** (hardcoded list of known ids, decoupled from
  wiring). Rejected: violates the honest-catalog principle — a config-off
  provider would appear in GET but be rejected at POST, creating exactly the
  "ghost provider" UX the ticket forbids.

## Implementation evidence

- `src/agent_harness/capability/wiring.py` — `ContextProviderEntry` dataclass,
  `register_context_provider()` helper, `context_provider_entries` field,
  `_wire_memory` / `_wire_skills` updated to register with stable ids.
- `src/agent_harness/assembly.py` — three-valued filter (None / [] / [ids]),
  order preservation, unknown-id skip + warning.
- `src/agent_harness/web/app.py` — GET endpoint projects real catalog;
  `create_session` handler-level 422 validation.
- Tests: `tests/test_assembly_context_providers.py` (6),
  `tests/web/test_web_context_providers_b2.py` (7 — GET projection + 422).
- Gate: 1258 passed / 9 skipped / 3 deselected (full pytest); ruff clean.
