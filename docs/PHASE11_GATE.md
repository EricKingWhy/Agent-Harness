# Phase 11 Gate 证据 — Knowledge / RAG

- 日期：2026-09-05 · 分支：feat/backend · 环境：真实 Zilliz Cloud + SiliconFlow `Qwen/Qwen3-Embedding-8B`（1024 维）+ 真实 SQLite 注册表
- 运行：`uv run pytest tests/integration/test_phase11_knowledge_gate.py -m integration` — **1 passed**
- 专用 gate collection：`knowledge_gate_test`（gate 结束即 drop / 逐 source 清理，零残留）；全程凭证零泄漏

## 三条 Gate

1. **restart 后 persistent search** ✅ —— ingest → 关闭 client → 新实例重连 → 同查询命中且 is_sufficient=true。
2. **证据不足明确 false** ✅ —— 与语料无关查询（"量子纠缠态…"）is_sufficient=false，hits 照返（标记是诚实信号不是开关）。
3. **Citation 可追溯** ✅ —— hit.citation（`kb:python-doc#<idx>`）→ read_source 回读原文与检索内容一致，with_context ±1 chunk 可用。

## 真实分数分布（KNOWLEDGE_MIN_SCORE=0.6 的合理性证据）

| 查询 | top 分数 | is_sufficient |
|---|---|---|
| "python typing 类型标注"（相关） | **0.730 / 0.664** | true |
| "rust 系统编程语言"（重建后新增内容） | 命中 | — |
| "量子纠缠态的希尔伯特空间测度不变性"（无关） | 0.290 / 0.162 / 0.142 / 0.127 | false |

相关证据 0.66–0.73，噪声 ≤0.29——**0.6 阈值两侧干净分离**（用户拍板值，实测支持；仍可经 `KNOWLEDGE_MIN_SCORE` 调整）。

## 其余覆盖

- source 级增量：同内容重 ingest → skipped（零向量写）；内容变更 → rebuilt，新增内容可检索。
- 多租户隔离：异租户 tenant partition（upsert/search 按租户过滤，CI 层已钉）。
- 统一执行链（T5 结构测试）：retrieve/ingest 经统一 ToolRegistry + Ledger（SUCCEEDED）+ SessionEvent 镜像，READ_ONLY/MUTATING(WORKSPACE_WRITE) 审批域生效。
- 清理：注册表行逐条删除 + gate collection drop + 断言。
