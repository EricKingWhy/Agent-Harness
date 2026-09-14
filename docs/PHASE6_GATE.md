# Real Zilliz Cloud Gate Result

2026-09-05：**PASS。#56 闭环完成，Phase 6 COMPLETED。**

## Environment

- Provider: Zilliz Cloud / Milvus Compatible
- Deployment: Free / Serverless
- Region: aws-eu-central-1
- Endpoint: https://in03-6d682da1f42feea.serverless.aws-eu-central-1.cloud.zilliz.com
- Database: default（SDK 默认，无新增 database 配置）
- Collection: memory_gate_test
- Embedding: Qwen/Qwen3-Embedding-8B @ SiliconFlow（`EMBEDDING_*` 配置，维度 1024）
- Token / API Key: REDACTED（`.env` 已 git ignore，`git check-ignore .env` 确认）

## Connection

Client initialization / TLS / network / authentication / list_collections：PASS。

## CRUD（真实闭环，本轮全量执行）

- Insert / Query / Get / Vector Search / TopK / metadata filter / Delete：**PASS**（真实 Zilliz + 真实 SiliconFlow 嵌入）。
- 缺失 Collection 的 Query：PASS，映射 `collection_not_found`。
- 无效 token：PASS，映射 `authentication`（沿 gRPC cause 链读结构化错误码，不解析原始文本）。
- Schema 维度不匹配（64/128 vs 实际 1024）：PASS，映射 `schema_mismatch`。
- Cleanup：测试创建的记录逐条 delete 并验证不可见；创建的 collection drop 并验证列表消失。无遗留。

## Runtime 语义闭环

- Runtime 跑真实 session → Extractor 抽取偏好 → Writeback 后台写 SQLite（事务 outbox）→ relay flush 同步 Zilliz。
- 语义检索排序：偏好记忆得分 > 低重要性事实，COSINE 分值域校验通过。
- 多租户/多用户隔离：bob 与异租户 alice 检索均返回空、get 不可见、ContextProvider 不注入。
- Outbox 瞬态失败语义：真实云厂商负载波动下，失败条目被保留、重试排空后一致（本轮 Gate 已按该语义验证）。

## Validation

- 真实 Gate：`python -X utf8 -m pytest tests/integration/test_phase6_memory_e2e.py -m integration` → **3 passed**（连续两轮）。
- 离线全量：503 passed、8 skipped、8 deselected；ruff clean。
- Web 入口接线：`_build_runtime` 惰性装配 Memory 子系统；SSE endpoint 绑定 `memory_session_var`；lifespan 统一关闭（`96d02bf`）。

## Notes

- 生产嵌入策略保持快失败（`request_timeout=15, max_retries=0`）+ `memory/degraded` 事件兜底；Gate 内使用带重试的嵌入客户端（验证语义而非重试策略）。
- Outbox relay 对真实云厂商瞬态失败的重试排空语义，即 ADR-0008 持久 outbox 的核心保证。
