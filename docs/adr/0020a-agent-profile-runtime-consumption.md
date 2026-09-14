# ADR-0020a — `agent_profile` 运行时消费（system_prompt 注入 + tool_scope 收窄）

**Status**: Accepted
**Date**: 2026-09-08
**Supersedes**: Partial — supersedes the `agent_profile` portion of ADR-0020's "staged" status.
**Related**: ADR-0015 (Phase 13 Multi-Agent, AgentFactory), ADR-0020 (Stage Composer controls)

---

## Context

ADR-0020 accepted `agent_profile` (`main | coding | research_review | null`) as a
Phase 5 staged contract field — validated at the API boundary but runtime no-op.
The RUNTIME follow-up batch (per the integration AI's handoff roadmap) consumes
this field for real.

### Pre-existing wiring gaps discovered during implementation

1. **`AgentSpec.system_prompt` was an orphan field.** `BUILTIN_PROFILES` defined
   `system_prompt` for each profile, but no code path consumed it — neither parent
   runs (via `build_runtime`) nor child runs (via `AgentFactory.create`). The entire
   project had **no system prompt injection path**: `derive_messages()` only projects
   `USER_MESSAGE` / `MODEL_COMPLETED` / `TOOL_RESULT` events.

2. **`AgentSpec.tool_scope` only filtered child runs.** `AgentFactory.create()`
   used `tool_scope` to narrow the child's registry, but parent runs registered all
   tools unconditionally — `build_runtime` ignored the profile.

## Decision

### 1. `system_prompt` injection via `ContextBuilder`

`ContextBuilder` gains an optional `system_prompt: str | None`. In `build()`, after
`derive_messages()` and token estimation, if `system_prompt` is non-empty it is
prepended as a `SystemMessage` to the returned message list (after `_with_providers`
runs, so provider content stays after the system prompt).

**Why ContextBuilder, not `derive_messages`?** `system_prompt` is runtime assembly
context (determined by `agent_profile`), not a durable event (invariant #4/#5:
Event ≠ Diagnostic Log; Persistent History ≠ Runtime Context). It must not be
written to JSONL. `ContextBuilder.build()` is already the single entry point for
"session events → model-visible messages" — adding system prompt there is consistent
with its existing responsibility (projection + budget compression + provider injection).

**Token estimation**: `system_prompt` tokens are cached once (`_system_prompt_tokens`)
and added to the total `token_estimate` — they do not enter `derive_messages()` so the
`_estimate_tokens_cached` event-to-message 1:1 invariant is not broken.

### 2. `tool_scope` narrowing in `build_runtime`

`build_runtime` looks up `BUILTIN_PROFILES[agent_profile]` (KeyError = loud failure,
web layer already 422s unknown names). After all tools are registered, if the profile
is not `main` or `None`, the registry is narrowed via `registry.filtered(spec.tool_scope)`.
The narrowed registry flows to all downstream consumers: `ToolExecutor`, `AgentRuntime`,
and the multiagent `activate`'s `source_registry`.

**Why `None` and `main` skip filtering**: `main`'s `_MAIN_TOOLS` is a superset, so
filtering is a no-op in practice — but if a future tool is added without updating
`_MAIN_TOOLS`, filtering would silently narrow it. `None`/`main` take the original
path (no filter) to preserve backward compatibility exactly. Only `coding` and
`research_review` narrow.

### 3. `AgentFactory.create` also consumes `system_prompt`

Child runs now receive `spec.system_prompt` via `AgentRuntime(system_prompt=...)`,
making child and parent paths consistent.

### 4. Default behavior unchanged

- `agent_profile=None` (default) → no system prompt, full registry (backward compatible).
- `agent_profile="main"` → injects `main`'s system prompt + full registry (explicit selection).
- `agent_profile="coding"` → injects coding system prompt + narrows to `_CODING_TOOLS`.
- `agent_profile="research_review"` → injects research system prompt + narrows to `_RESEARCH_TOOLS`.

## Consequences

### Positive

- `agent_profile` is now a real runtime control, not a placebo — frontend Composer
  control row (F1) can offer genuine profile selection.
- System prompt injection is a reusable `ContextBuilder` capability (not hardcoded
  to profiles — future system prompts from other sources can use the same seam).

### Negative / Trade-offs

- **Multiagent `activate` no-op for non-main profiles**: `build_runtime` unconditionally
  activates `wiring.multiagent_provider`, but a narrowed registry (coding/research)
  won't contain `delegate`. The activation runs but the model can't see or call
  `delegate`. This is semantically correct (coding profile shouldn't delegate) but
  wastes a small amount of setup work. **Not optimized this batch** (Scope Lock §8);
  a follow-up could gate activation on `"delegate" in spec.tool_scope`.

- **Token budget grows by system_prompt size**: each run now carries the profile's
  system prompt (~50-100 tokens). This is accounted in token estimation (compression
  triggers correctly), but reduces available context budget slightly.

## Implementation evidence

- `src/agent_harness/context/builder.py` — `system_prompt` param + `_prepend_system_prompt` + cached token estimation
- `src/agent_harness/agent/runtime.py` — `system_prompt` param passthrough
- `src/agent_harness/agent/factory.py` — `AgentFactory.create` passes `spec.system_prompt`
- `src/agent_harness/assembly.py` — profile lookup + registry narrowing + `system_prompt` to `ContextBuilder`
- `src/agent_harness/web/app.py` — comment/docstring accuracy updates (no-op → consumed)
- Tests: `tests/context/test_builder_system_prompt.py` (5), `tests/agent/test_system_prompt_wiring.py` (3), `tests/test_assembly_agent_profile.py` (7)
