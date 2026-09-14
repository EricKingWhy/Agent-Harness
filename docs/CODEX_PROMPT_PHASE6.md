# Codex Phase 6 提示词（复制粘贴给 Codex）

---

你在 `intelligence-agent-backend` 项目（分支 `feat/backend`，工作目录 `D:\intelligence-agent-backend`）。

## 你的任务

实施 Phase 6：Memory Capability / Context Provider。27 个设计决策已通过 grill-with-docs 冻结，文档已落地：

- **ADR-0008**: Memory Capability 架构（`docs/adr/0008-memory-capability-architecture.md`）
- **ADR-0009**: 多租户身份隔离（`docs/adr/0009-multitenant-identity-isolation.md`）
- **CONTEXT.md**: Memory 层术语已更新
- **HANDOFF_PHASE6.md**: 6 个 ticket 的完整实施指引（`docs/HANDOFF_PHASE6.md`）
- **GitHub Issues**: #51–#56

## 执行协议

1. **先读**：`AGENTS.md`（工程约束）→ `docs/HANDOFF_PHASE6.md`（你这次的工作手册）→ `docs/adr/0008-*.md` + `docs/adr/0009-*.md`（设计决策）→ `CONTEXT.md`（术语）。
2. **按顺序实施 6 个 ticket**：#51 → #52 → #53 → #54 → #55 → #56。每个 ticket 有前置依赖。
3. **每个 ticket 的流程**：TDD（先写测试 red → 实现 green → 重构）→ `uv run ruff check` → `uv run pytest`（全量回归）→ commit → push `feat/backend`。
4. **不 push main**。合并由集成 AI 负责。
5. **不改 Phase 1-5 已落地代码**（除非 ticket 明确要求插入点）。

## 关键约束

- LangMem 走 optional extra（`pip install intelligence-agent[memory]`），Core 禁止 import concrete class。
- 存储主权在我们：SQLite 是权威记录，Milvus 是向量索引（可重建），通过 outbox pattern 保证一致性。
- 身份隔离：IdentityContext + contextvar，中间件注入，模型不能伪造。所有 Memory 查询带 tenant_id + user_id WHERE 条件。
- Memory 故障 graceful degrade：append `memory/degraded` 事件，不阻塞 Runtime。
- LangMem 通过 BaseStore Protocol 适配我们的存储（不直接连 SQLite/Milvus）。

## 需要用户提供（ticket #56 端到端测试）

Zilliz Cloud 凭证（Milvus endpoint / token / collection 名），缺这个 ticket #56 会 skip。

## 测试命令

```bash
# 单 ticket 测试
uv run pytest tests/memory/ -v

# 全量回归
uv run pytest

# lint
uv run ruff check src/ tests/
```

## 产出预期

6 个 ticket 全部落地后：
- `tests/memory/` 目录有完整的单元测试（Fake provider）
- `tests/integration/test_phase6_memory_e2e.py` 有真实 Zilliz Cloud 端到端测试
- 全量回归全过 + ruff clean
- Phase 6 Gate 达成：使用 LangMem 正常 recall / 切换 Fake Provider 不改 Core / Memory 挂掉基础 Agent 仍运行

开始吧。从读 `docs/HANDOFF_PHASE6.md` 开始。
