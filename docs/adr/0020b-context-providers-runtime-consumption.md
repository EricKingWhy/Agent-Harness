# ADR-0020b — `context_providers` 运行时消费（按名字筛选已装配 provider 子集）

**Status**: Accepted
**Date**: 2026-09-08
**Supersedes**: Partial — supersedes the `context_providers` portion of ADR-0020's "staged" status.
**Related**: ADR-0020 (Stage Composer controls), ADR-0020a (`agent_profile` runtime consumption), ADR-0010 (Capability Registry & Plugin Config)

---

## Context

ADR-0020 accepted `context_providers: list[str] | None` as a Phase 5 staged contract
field — accepted at the API boundary, passed through `build_runtime`, but only logged
an INFO message and ignored. This is the third and final RUNTIME follow-up batch
(after `agent_profile` [ADR-0020a] and `reasoning_effort`), consuming the field for real.

### Pre-existing state

1. **Two ContextProviders were already wired by capability assembly.** When CAPABILITIES
   configures `memory` or `skills`, `wire_capabilities` appends `MemoryContextProvider`
   (`capability/wiring.py:105`) and `SkillCatalogContextProvider`
   (`capability/wiring.py:165`) to `wiring.context_providers`. These were **already
   consumed at runtime** — `ContextBuilder._with_providers` (`context/builder.py:149`)
   iterates them and calls `select(session, token_budget)` per provider.

2. **The session request field was disconnected from this wiring.** `build_runtime`
   received `context_providers: list[str] | None` and logged it, but always passed
   `list(wiring.context_providers)` (the full set) to `ContextBuilder` — the session
   request had zero effect on which providers were active.

3. **Providers had no stable identifier.** The `ContextProvider` Protocol
   (`context/provider.py:10`) only declares `select()`. There was no `name` attribute
   to match against the request's `list[str]`.

4. **The discovery endpoint was hardcoded empty.** `GET /api/context-providers`
   returned `{"providers": []}` regardless of actual assembly state — a misleading
   "no providers wired" message even when `wiring.context_providers` had content.

## Decision

### 1. Stable `name` class attribute on each concrete provider

`MemoryContextProvider.name = "memory"` and `SkillCatalogContextProvider.name = "skills"`
as class-level string constants. These are the stable identifiers used by:
- The session request field (`context_providers: list[str]`) for selection;
- The `/api/context-providers` endpoint for projection.

**Why class attribute, not Protocol method?** The `ContextProvider` Protocol only
declares `select()`. Adding `name: str` to the Protocol would require all future
providers to declare it at the same time — a broader change than this batch needs.
Instead, `getattr(p, "name", None)` reads it defensively: future unnamed providers
simply won't be matched by any request name (fail-open, consistent with optional
capability degradation). The Protocol can be tightened in a later batch if desired.

**Why these specific strings?** They match the capability names ("memory", "skills")
already used in `CapabilityDescriptor.name` (`wiring.py:99,161`). Consistency makes
the mental model simple: "the memory capability contributes a context provider named
'memory'."

### 2. Session-level filtering in `build_runtime`

A module-level `_select_context_providers(wired, requested)` helper applies the
session request before constructing `ContextBuilder`:

- **`requested is None`** (default) → full wired set (backward compatible);
- **`requested == []`** → empty (user explicitly chose zero providers — semantically
  distinct from None's "default all");
- **`requested` non-empty** → only providers whose `name ∈ requested`;
- **Unknown names** → silently skipped (fail-open).

**Why not 422 on unknown names (unlike `agent_profile` / `reasoning_effort`)?**
Those fields are closed enumerations (3 profiles / 3 efforts) — an unknown value is
unambiguously a configuration error. `context_providers` is an open set whose
membership depends on runtime capability assembly state. A validator cannot statically
determine whether a name will be wired at request time (CAPABILITIES may be configured
differently across deployments). Fail-open at the assembly layer is consistent with
invariant #21 (Optional Capability failure ≠ Core failure) and the OPTIONAL_RUNTIME
degradation pattern already used by `wire_capabilities`.

**Why `None` ≠ `[]`?** `None` means "I didn't specify, use the default" (all providers).
`[]` means "I explicitly want no providers" (a "clean" context without memory/skills
injection). Conflating them would make it impossible to request a zero-provider run
without also implying "give me everything." This mirrors how Python conventionally
treats `None` (unset) vs empty container (explicitly empty).

### 3. Discovery endpoint projects actual assembly state

`GET /api/context-providers` now reads `wiring.context_providers` and projects each
provider's `name` with `display_name` / `description` from a new
`CONTEXT_PROVIDER_DESCRIPTIONS` constant. Bare config (no CAPABILITIES) still returns
`{"providers": []}` — the existing `test_empty_by_default_is_honest` continues to pass.

**Why dynamic projection, not static enumeration?** The endpoint already claimed it
would "naturally return the real catalog once provider assembly lands" — this batch
fulfills that contract. Static enumeration would lie when capabilities aren't wired;
dynamic projection is honest (empty when bare, populated when configured), matching
the `/api/capabilities` pattern.

### 4. Request validator (shape only)

`CreateSessionRequest._validate_context_providers` checks that each entry is a
non-empty string. It does **not** reject unknown names (fail-open at assembly layer).
Pydantic's type annotation `list[str] | None` handles the type coercion; the validator
only adds the non-empty-string semantic check.

## Consequences

- **Three Phase 5 RUNTIME fields fully consumed.** `reasoning_effort` (model param),
  `agent_profile` (system_prompt + tool_scope), and now `context_providers` (provider
  subset selection) — all three staged fields are now runtime-active.

- **Future providers need a `name`.** Any new ContextProvider that should be
  selectable via the session request must declare a `name` class attribute and add
  an entry to `CONTEXT_PROVIDER_DESCRIPTIONS`. Providers without `name` are wired but
  never matched (fail-open) and invisible in the discovery endpoint.

- **Backward compatible.** `context_providers=None` (default) preserves the prior
  behavior of injecting all wired providers. Existing callers that don't send the
  field are unaffected.

- **No change to ContextBuilder / AgentRuntime internals.** The filtering happens at
  the assembly layer before `ContextBuilder` is constructed — the builder and runtime
  remain unchanged.

## Risks

| Risk | Mitigation |
| --- | --- |
| Renaming a provider's `name` breaks request compatibility | Documented as a stability contract; the comment on each `name` attribute warns against changing it |
| Provider without `name` silently invisible in endpoint | `getattr(p, "name", None)` defensive read; endpoint skips anonymous providers (consistent fail-open) |
| `None` vs `[]` confusion causes unintended zero-provider runs | Distinct test cases (F1 for None=all, F2 for []=none); GOAL spec explicitly documents the distinction |
