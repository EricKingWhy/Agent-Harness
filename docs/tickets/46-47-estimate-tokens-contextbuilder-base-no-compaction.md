# #46 — #47: estimate_tokens + ContextBuilder base (no Compaction)

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T05:59:40Z
- **Closed**: 2026-09-04T06:42:25Z
- **Parent**: #44
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/46

---

## Parent

Phase 5 Spec #44

## What to build

Token 估算函数和 ContextBuilder 的基础骨架（不含 Compaction 逻辑）。为后续 Compaction ticket 铺好接入点。

`estimate_tokens(text) -> int`：用 tiktoken cl100k_base 精确计数。

`ContextBuilder`：`build(session) -> list[AnyMessage]`。内部调 `session.derive_messages()` 并直接返回（不做后处理）。构造参数包含 `max_context_tokens=200000` / `auto_compact_threshold=0.70` / `hard_guard_threshold=0.85`，但 Phase 5 此 ticket 不使用它们（留给 Compaction ticket）。

`ContextProvider` Protocol：定义 `select(session, token_budget) -> list[AnyMessage]`，不实现。

Settings 增加 `max_context_tokens` / threshold 配置项。

端到端：`ContextBuilder.build(session)` 返回跟 `session.derive_messages()` 完全一样的结果，但内部已经能估算 token 数（日志或断言验证）。

## Acceptance criteria

- [ ] `estimate_tokens(text: str) -> int` 用 tiktoken cl100k_base，对空串返回 0，对已知英文/中文文本返回合理 token 数
- [ ] `ContextBuilder` 类：`build(session) -> list[AnyMessage]`，内部调 derive_messages 直接返回
- [ ] ContextBuilder 构造参数：model_provider / max_context_tokens=200000 / auto_compact_threshold=0.70 / hard_guard_threshold=0.85 / context_providers=[]
- [ ] `ContextProvider` Protocol 定义（3 行），无实现
- [ ] Settings 增加 max_context_tokens (default 200000) / auto_compact_threshold (0.70) / hard_guard_threshold (0.85)
- [ ] tiktoken 加入 requirements (核心依赖)
- [ ] 单元测试：estimate_tokens 已知文本、ContextBuilder.build 返回与 derive_messages 一致

## Blocked by

None (can start immediately)
