# #51 — Phase 6 #1: IdentityContext + middleware + contextvar 基础设施

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: phase-6
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T12:27:11Z
- **Closed**: 2026-09-04T14:05:58Z
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/51

---

Phase 6 第一个 ticket。多租户身份隔离基础设施。

## 交付物

- `IdentityContext` dataclass (frozen=True): `tenant_id: str`, `user_id: str`, `scopes: list[str]`
- `identity_context_var`: `contextvars.ContextVar[IdentityContext | None]`
- `get_identity_context() -> IdentityContext`: 读 contextvar，未设置时返回默认值 `(local, local)`
- `web/app.py` 的 `auth_seam` 实现：解析 JWT（可选）→ 创建 IdentityContext → 设进 contextvar
- config 新增 `jwt_secret: str | None = None`（可选，无则用 local 默认值）

## 测试

- contextvar 设置后子任务可读
- 未设 contextvar 时默认值正确
- auth_seam 设置后 MemoryStore 可读到 identity（集成验证）

## 依赖

无前置依赖。这是 Phase 6 的第一个 ticket。

## 约束

- Runtime 签名零侵入（不改 run/run_stream 签名）
- 身份不进 SessionEvent（请求级 vs 持久级分离）

## 参考

- ADR-0009: 多租户身份隔离
- CONTEXT.md: IdentityContext
