# 09 — MCP / Skills / Knowledge / Web

## 1. MCP

主链：

```text
Remote MCP Server
→ official/mature MCP Python Client
→ Tool Discovery
→ schema/metadata
→ MCPToolAdapter
→ ToolRegistry
→ ToolExecutor
→ remote invoke
→ ToolResult
```

原则：
- Agent 是 MCP Client；
- 不自研 wire protocol；
- MCP Tool 必须走统一 Runtime；
- MCP SDK retry 与 ToolExecutor retry 不得叠加失控；
- remote side effect 不能靠 Tool Name 猜，必须映射 metadata/policy。

## 2. Skills

参考 Pi 的 progressive disclosure 思路。

Skill 采用 `SKILL.md`：

```text
discover
→ read name + description
→ expose catalog to model
→ task requires skill
→ load full SKILL.md on demand
→ inject into Context
```

V1：
- 支持 global/project skill directories；
- 支持发现和解析；
- 支持按需 load；
- 支持手动指定 Skill；
- 不做 Marketplace；
- 不做复杂自动推荐系统。

Skill 是 Context Capability，不等于 Tool。

## 3. Knowledge Capability

Knowledge/RAG 是插件，不是固定 Runtime Pipeline。

### Ingestion

```text
source docs
→ parse/sections
→ chunk
→ embedding
→ VectorStore Provider (Milvus default)
→ metadata persistence
```

Ingestion 与 Agent Runtime MUST 分离。

Agent 启动不得每次重新扫描、重 embedding 全部文档。

### VectorStore 抽象

Milvus 是默认 Provider，不绑定接口。

## 4. Chunk / Metadata

基本要求：
- token-window chunk；
- `overlap < chunk_size`；
- 保留 `heading_path + content` 作为检索文本设计选项；
- metadata 保留 doc_id/source/heading/hash/version。

## 5. retrieve_knowledge Tool

至少：

```text
query
kb_id
top_k
```

返回：

```text
chunk_id
doc_id
source/file_name
heading_path
score
content or artifact_ref
sufficient
```

模型自己决定何时调用，禁止关键词 if/else 强制 RAG。

## 6. Citation

Citation 必须从 Tool Result 一路携带。

```text
Vector/Web result + source metadata
→ ToolResult
→ SessionEvent
→ model
→ final citation
```

不得把预训练知识伪装成检索证据。

## 7. Incremental Index

```text
scan
→ doc identity
→ mtime/hash
→ unchanged: skip
→ changed: new version
```

生产型更新 SHOULD：

```text
write N+1
→ embed/insert
→ verify
→ switch active
→ cleanup N
```

避免 `delete old → insert new` 窗口风险。

## 8. Web Search / Retrieval Fallback

Web Search MUST 是独立 Tool，不允许藏进 `retrieve_knowledge()`。

策略：

```text
retrieve_knowledge
→ sufficient=true: answer, no web
→ sufficient=false
→ rewrite one query
→ web_search
→ synthesis + Web Citation
```

这只是轻量 Retrieval Fallback Policy，不实现复杂学术式 CRAG。

## 9. Failure Semantics

- Embedding failure：metadata 不得标记 INDEXED；
- Milvus unavailable：Knowledge Tool 返回明确错误；
- KB 无证据：`sufficient=false`；
- KB 足够：不得无意义联网；
- Web provider failure：明确失败，不伪造来源；
- Citation 只能指向真实 Tool Result。

## 10. Acceptance Criteria

- MCP Tool 走统一 Executor；
- Skill 只在需要时加载完整内容；
- 重启后 Knowledge 可直接 search；
- KB sufficient 时不联网；
- insufficient 时可以 web fallback；
- Knowledge/Web Citation 可验证；
- VectorStore Provider 可替换；
- ingestion 与 chat runtime 独立。
