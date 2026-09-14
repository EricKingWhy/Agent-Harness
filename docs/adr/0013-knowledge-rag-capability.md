# ADR-0013: Knowledge / RAG Capability（Phase 11）

- 状态：Accepted（grill 2026-09-05，用户逐项拍板）
- 关联：spec 00_PROJECT_VISION（NOT-DO 清单）/ 08_PLUGIN_CAPABILITY_SYSTEM / 14_IMPLEMENTATION_ROADMAP Phase 11 / 13_REUSE_MATRIX（Milvus REUSE+ADAPT）/ ADR-0008（Memory，平行域）/ ADR-0010（capability registry）/ ADR-0012（MCP，同款集成模式）

## 背景

Roadmap Phase 11 冻结交付：VectorStore abstraction、MilvusProvider、ingestion、chunk/metadata、incremental index、retrieve_knowledge、citation、sufficient。Gate 三条：restart 后 persistent search；证据不足明确 false；Citation 可追溯。Vision 约束：Knowledge 是 Capability 不是 Core 特判（不变量 #7 统一 Tool Runtime）；NOT-DO 复杂多查询 CRAG / 学术式 Evidence Grader。Phase 6 已交付 Memory 域的向量地基（VectorIndexStore / MilvusVectorStore / embeddings 工厂 / IdentityContext 隔离），本 ADR 决定 Knowledge 域如何与之平行而不纠缠。

## 决策

1. **Knowledge ≠ Memory（领域边界）**：Memory = 用户/会话个性化事实（随对话自动抽取、ContextProvider 被动注入）；Knowledge = 显式摄入的文档语料（只在模型调用检索工具时被查询、带引用）。两个 Capability 平行、互不依赖、互不 import。
2. **Agentic RAG**：检索是一个工具（retrieve_knowledge），模型自主判断当前问题是否需要检索——不做每轮自动注入（DEFER）。与 Memory 的被动注入形成设计对照。
3. **独立 Collection**：`knowledge_chunks`（tenant partition key，V1 单租户），与 memory collection 物理分开；共享同一 Milvus 部署与 `EMBEDDING_*` 配置（同模型同维度）。schema 独立：chunk 形状 `{source_id, source_name, chunk_index, content_hash, content}`。
4. **Knowledge 域专用协议**：`KnowledgeVectorStore`（upsert_chunks / delete_source / search / get_chunk），不泛化 memory 的 `VectorIndexStore`——改已过真实验收的 memory 接口成本高、两个小协议好过一个胖协议。Milvus client / embeddings 工厂复用。
5. **Chunk 策略**：递归字符切分（~800 字符，overlap ~100，stdlib 自实现，不引 LangChain text-splitter——复用矩阵限定 LangChain 只做 model/embeddings compatibility）。metadata 带 `content_hash`。
6. **Ingestion 入口**：`ingest_document` 工具（MUTATING / WORKSPACE_WRITE 审批域）+ CLI 子命令，同一服务函数。双输入形态：`path`（sandbox workspace 内相对路径，走 sandbox 边界读，不变量 #11）或 `text` + `source_name`。V1 仅 UTF-8 文本类；二进制/PDF 检测到即显式失败（PDF 解析 DEFER）。
7. **增量索引 = source 级 hash**：source 内容 hash 未变 → 整篇跳过；变了 → 整篇重建（新 chunk 入库后删旧 chunk）。chunk 级 diff 复杂度买不来 V1 价值；chunk 的 content_hash 仍存 metadata 为未来留路。
8. **Source 注册表**：SQLite `knowledge_sources` 表（harness.db，ADR-0004 布局）：source_id ↔ name/path/hash/chunk_count/时间。source 是一等实体（citation 溯源、去重判定、list 都靠它）。
9. **retrieve_knowledge**：参数 `query / k(默认 5、上限 20) / source_id?(可选过滤) `；返回 `{hits: [{citation, content, score}], is_sufficient, query}`。score 如实透传绝不伪造。**sufficient = 语义**：最高分 ≥ `KNOWLEDGE_MIN_SCORE`（默认 **0.6**，用户拍板：低于此的证据太弱、宁可如实标记不足防幻觉；可配，真实验收分数分布若显示过严再调）。阈值以下 hits 照返——标记是证据质量的诚实信号，不是结果开关。
10. **Citation**：`kb:<source_name>#<chunk_index>`（人类可读 + 机器可解析）。`read_knowledge_source(citation, with_context?)` 只读工具回读原文；`with_context=true` 附带前后各 1 chunk（标注位置）。"citation → source 元数据 → 原文"链路即 Gate 3。
11. **权限**：retrieve_knowledge / read_knowledge_source = READ_ONLY；ingest_document = MUTATING / WORKSPACE_WRITE。**不暴露删除工具**（prompt 注入即可清空语料的危险面）：删除仅内部方法 + CLI 子命令。DEFER 对外删除工具。
12. **规模防呆**：单文件解码后 2MB 字符、单 source 2000 chunks 上限——超限**显式失败**（静默截断 = "以为建全了其实缺半篇"的静默语料损坏）。
13. **集成**：`CAPABILITIES` env 新增 `"knowledge"` 条目（provider builtin）；collection 名走 `KNOWLEDGE_COLLECTION` env（必填无默认——不配 = OPTIONAL_RUNTIME 缺席降级，不静默写默认库）；接线走 wire_capabilities + assembly（Phase 8 同款）；lifecycle 挂 `CapabilityWiring.lifecycle`。
14. **测试**：in-process fake store 进 CI；真实 Zilliz gate 覆盖三条 Gate（restart persistent search / 证据不足明确 false / citation 可追溯），memory Phase 6 同款模式。

## 后果

- 正面：模型获得可自主调用的证据工具；citation 链路让回答可审计；source 级增量让重建成本可控。
- 权衡：阈值 0.6 偏严（真实分布待 gate 验证，可配可调）；无 PDF 支持意味着 V1 语料只能来自文本类文件；删除不暴露给模型，语料治理靠 CLI/人。
- DEFER 新增：PDF/Office 解析、自动注入（每轮检索）、对外删除工具、chunk 级 diff、HTTP ingest 端点、多租户语料管理面。

## 参考来源

- 用户逐项拍板记录：Round 1（Q1-Q10）+ Round 2（Q1-Q9），2026-09-05
- 现有地基：src/agent_harness/memory/（VectorIndexStore / MilvusVectorStore / embeddings）、src/agent_harness/assembly.py
