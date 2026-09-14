# #27 — Phase 4 Ticket A: Durable Operation lifecycle for one Tool execution

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-03T16:06:39Z
- **Closed**: 2026-09-03T16:27:37Z
- **Parent**: #26
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/27

---

## Parent

#26 — Phase 4 Spec: Storage + Operation Ledger + Recovery

## What to build

让一次合法 Tool 调用从进入执行域到返回最终结果都具备持久化 Operation 生命周期。SQLite Operation Ledger 必须先于真实副作用记录状态，并在唯一 retry layer 完成后记录终态，使崩溃恢复能够判断调用实际执行到了哪里。

## Acceptance criteria

- [ ] 引入 aiosqlite 运行时依赖，SQLite I/O 不阻塞 event loop。
- [ ] 定义 Operation、OperationState 和 OperationLedger ABC；提供 SqliteOperationLedger 默认实现。
- [ ] operations schema 包含 Issue #26 冻结字段，tool_call_id 同时作为 operation_id，artifact_ref 为 nullable 预留列。
- [ ] Tool 契约提供稳定的 args_identity(args)，默认使用排序 JSON，Unicode 不转义。
- [ ] ToolExecutor 可注入 Ledger 和执行身份上下文；合法调用按 PENDING → RUNNING → SUCCEEDED/FAILED/CANCELLED 持久化。
- [ ] Ledger 更新位于 retry loop 外；中间 attempt 失败只进入 Diagnostic Log，不产生额外 Operation。
- [ ] 每次状态变更独立 commit，N 个 Tool 调用对应 N 个独立 Operation。
- [ ] Store CRUD、schema、状态转换和 Executor 写入顺序有单元测试；现有测试保持通过。

## Blocked by

None (can start immediately).
