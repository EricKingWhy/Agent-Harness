# ADR-0014: Web Search / Reliability（Phase 12）

- 状态：Accepted（grill 2026-09-06，用户逐项拍板，5 轮）
- 关联：spec 09_MCP_SKILLS_KNOWLEDGE_WEB §8 Web Search/Retrieval Fallback / 14_IMPLEMENTATION_ROADMAP Phase 12 / ADR-0013（Knowledge，平行域）/ ADR-0009（identity 隔离）/ issue #69（同错熔断，前端实测回执）
- 研究：pi-mono + oh-my-pi（github.com/badlogic/pi-mono、can1357/oh-my-pi）的 retry/fallback 链与 web search schema；OpenAI Codex + Anthropic Claude hosted web_search schema；Tavily/Serper/Brave/Google/Bocha API 对比

## 背景

Roadmap Phase 12 冻结交付 5 项：WebSearchProvider、独立 `web_search` Tool、Retrieval Fallback、Repeated Tool Guard（#69）、Model Fallback。Gate：KB 足够不联网；不足才 fallback；provider 瞬时有 fallback reason。#69 来自前端实测：模型在工具受限环境下反复重试同一失败工具，烧穿步数/token——当前 Runtime 仅有 `max_steps`（默认 20）兜底，无中间护栏。Phase 11 已交付 Knowledge 域（ADR-0013），本 ADR 决定 Web Search 如何与 Knowledge 平行（统一检索接口）、以及 Reliability 三项（同错熔断 + Model Fallback + Fallback 透明事件）如何落地。

## 决策

### 范围

1. **5 项全做，Model Fallback 收窄到瞬时故障转移**：不做质量型 fallback（需要 LLM judge，复杂度跳级，DEFER）。瞬时 = timeout / 5xx / 429 / 连接失败；非瞬时（认证错 / 参数错 / 不支持 tool）不切、直接报错。

### #69 同错熔断（Repeated Tool Guard）

2. **检测点 + 指纹**：AgentRuntime 主循环（工具回填后、下一轮模型调用前）。指纹 = `(tool_name, canonical_args)` 精确匹配（`json.dumps(args, sort_keys=True, ensure_ascii=False)`）。开始严格零误伤——规范化等真出现「args 抖动漏检」实测案例再加。
3. **两级熔断 + 计数器重置**：连续 N=3 次同指纹 `ok=False` → **软熔断**；再 N=3 仍同指纹 → **硬熔断**。计数器在**指纹变化时清零**（不是任意成功调用清零——振荡场景每个指纹各自计数更公平）。
4. **软熔断动作**：注入 **user 角色**消息（「同一调用已连续失败 3 次，请改变策略或向用户说明」）——给模型自纠机会。user 角色而非 system（oh-my-pi `modelFallbackMessage` 同款姿势；护栏是 runtime 行为不该污染固定 system prompt）。
5. **硬熔断动作**：`end_run(status="failed", reason="identical_tool_failure_loop")`。绝不伪造最终回答。
6. **白盒透明**（用户 Q14 拍板 B）：新 SessionEvent `tool_failure_guard`（两级：`soft`/`hard`，含指纹 + 计数 + 动作）——过词表校验 + `gen_event_types` 同步 + 前端投影适配。诊断日志同步记录。**无上游蓝图**：pi-mono/oh-my-pi/claude-code 都没工具失败检测（只有 assistant-spin caps / transport circuit breaker）——这是自研护栏。

### 统一检索接口

7. **窄 Protocol + 平行域**：`RetrievalProvider.search(query, *, k=5, gl=None, hl=None, freshness=None) -> list[RetrievalHit]`。KB（`KnowledgeVectorStore` 继承窄 Protocol + chunk 生命周期）和 Web（`WebSearchProvider` 只实现窄 Protocol）平行。`RetrievalHit` 统一 `{citation, content, score, metadata}`——KB 的 `source_id`/`chunk_index` 和 Web 的 `url`/`title` 走 metadata dict（spec §4 一致）。不泛化、不动 Phase 11 已冻结的 `KnowledgeVectorStore`（它继承窄 Protocol 即可，零改动）。
8. **两个独立工具**（spec §8 硬约束：Web MUST 独立）：`retrieve_knowledge` + `web_search` 并存；背后各自 provider 策略类。**「同时选 KB+Web」= 模型一回合调用两个工具的 agentic 路径**，不是 Runtime 强制并行、不是合并成一个工具。

### WebSearchProvider

9. **Protocol + 默认 Tavily（手写 httpx）**：`WebSearchProvider` 实现 `RetrievalProvider`；`WebHit = {title, url, snippet, score?, raw_content?}`（snippet=最佳可用摘要；raw_content 可选全文）。Tavily 默认实现：手写 httpx POST 到 `api.tavily.com/search`，**零新依赖**（同 `MilvusKnowledgeVectorStore` 「SDK 不绑死 Core」姿势）；错误分类 timeout/401/429/5xx → `WebSearchError(category)`。未配置 `TAVILY_API_KEY` → OPTIONAL_RUNTIME 降级缺席（同 `KNOWLEDGE_COLLECTION`）。
10. **Provider 可换 = 加策略类**（用户 Q4 核心诉求）：研究验证 Tavily/Serper/Brave/Google/Bocha 都能映射到同一 Protocol（auth 放 adapter 构造器、不进 Protocol 签名；HTTP verb 由 adapter 自有）。

### web_search 工具 schema（模型可见）

11. **{query (required), recency (optional enum: day|week|month|year), k (optional int default 5)}**：`query` 支持 Google 风格 operator（`site:`/`-site:`/`after:`/`before:`/`inurl:`/`intitle:`/`filetype:`/引号/`-`/`OR`）。**不暴露 locale**（`gl`/`hl` 走 adapter 构造器/harness config——研究：Codex/Anthropic hosted 也只让模型填 query，locale 是 host config）。**不暴露 domain filters 参数**——模型用 `site:`/`-site:` 查询语法表达，adapter 翻译成 native `include_domains`/`exclude_domains`（oh-my-pi 同款，避免 schema 参数与查询语法重复 drift）。
12. **不对称：无 `read_web_source` 工具**：网页二次抓取的成本/速率/法律风险 vs KB 本地切片可控读取（Tavily `raw_content` 已在搜索时一并返回；模型要看某网页可再搜或未来加通用 `fetch_url`——独立决策）。citation `web:<url>` 保留作溯源（spec §6 要求 citation 一路携带）。

### Retrieval Fallback Policy（CRAG-inspired，不叫 CRAG）

13. **tool 侧 affordance**（用户 Q20 的 CRAG 直觉）：`retrieve_knowledge` 返回 `is_sufficient=false` 时，tool result 附带 `"hint": "知识库证据不足，可调用 web_search 工具获取外部信息"`。**决策仍由模型做出**（agentic，Q5 不变）；hint 是 tool 侧 affordance，不是 Agent Loop 特判（不违反不变量 #18）。这是 spec §8 的「轻量 Retrieval Fallback Policy」实现，**显式区别于学术 CRAG 的 Runtime 自动编排**（不做自动代调 web_search）。

### Model Fallback

14. **两级链表 + FallbackPolicy seam**（用户 Q13 升级到 (c)）：`ModelConfig` + `fallback: ModelConfig | None`；瞬时故障切 fallback、非瞬时直接报错；不切回（`never` 回复策略，YAGNI；oh-my-pi 的 `cooldown-expiry` 切回 DEFER）。`FallbackPolicy` Protocol（`resolve(error, current) -> ModelConfig | None`）作为 seam，默认实现 `TwoLevelFallbackPolicy`；未来升级 oh-my-pi 全链（role/wildcard-keyed `Record<string, string[]>`、specificity-ordered、cooldown 切回）= 换 `ChainFallbackPolicy` 实现，Agent Loop 零改动。
15. **`is_transient_model_error(error) -> bool` 共享 helper**：分类 `httpx.TimeoutException` / `httpx.HTTPStatusError`(5xx/429) / 连接错误；policy 复用不重写（未来 `ChainFallbackPolicy` 同样复用）。
16. **决策在 provider/model 层**：`create_chat_model` 升级支持 fallback；Agent Loop 不感知（不变量：Model Fallback 与 Tool Retry 分离）。
17. **配置**：`FALLBACK_MODEL_PROVIDER` / `FALLBACK_MODEL_NAME` / `FALLBACK_MODEL_BASE_URL` / `FALLBACK_MODEL_API_KEY`（已配 SenseAudio OpenAI 兼容网关 + `deepseek-v4-flash-0731`）。`PROVIDER_PRESETS` 新增 `senseaudio`。
18. **白盒透明事件**（用户 Q14 拍板 B）：新 SessionEvent `model_fallback`（含 `from_model`/`to_model`/`reason`/`usage` 明细）——过词表校验 + `gen_event_types` 同步 + 前端投影适配（前端协作点）。`usage_total` 统一归集到 run 级（不分主备）；fallback 明细走 `model_fallback` 事件。诊断日志 `llm_call` 加 `fallback_reason`/`fallback_from`/`fallback_to`。

### 测试

19. **in-process Fake 进 CI + 真实 Gate 收尾**：`FakeWebSearchProvider`（确定性 substring，同 Knowledge 域风格）；T6 真实 Gate 覆盖 Tavily 联网 + Model Fallback 真实切换（人为触发主 provider 瞬时故障）+ 同错熔断真实触发（构造模型反复同错 prompt）。同 Phase 11 同款模式。

## 后果

- 正面：模型获得 agentic web 检索 + KB/web 统一替换点；同错熔断堵住步数/token 烧穿；Model Fallback 给瞬时故障韧性；两个新 SessionEvent 让调用链全透明（白盒，deepseek-harness 风格）。
- 权衡：同错熔断精确指纹可能漏「args 抖动」场景（等实测再加规范化）；Model Fallback 两级不含质量判断（瞬时切、不判答案质量）；web 无二次读取工具（citation 只溯源）。
- 前端协作：`tool_failure_guard` + `model_fallback` 两个新事件类型需前端投影适配（后端定义形状、前端消费）。
- DEFER 新增：质量型 Model Fallback（LLM judge）、oh-my-pi 全链（role/wildcard/cooldown 切回）、`fetch_url` 通用网页抓取工具、web 二次读取工具、自动 web 检索编排（学术 CRAG）。

## 参考来源

- 用户逐项拍板：Round 1（Q1-Q6）+ Round 2（Q7-Q10）+ Round 3（Q11-Q14）+ Round 4（Q15-Q18）+ Round 5（Q19-Q23），2026-09-06
- 研究：pi-mono `packages/ai/src/utils/retry.ts` + `provider-retry.ts`（same-model retry + HTTP retry）；oh-my-pi `packages/coding-agent/src/session/retry-fallback-chains.ts` + `turn-recovery.ts`（full client-side chain）+ `packages/coding-agent/src/web/search/index.ts`（web search tool schema）；OpenAI Codex `codex-rs/core/src/tools/hosted_spec.rs`（hosted web_search）；Anthropic docs（`web_search_20250305` server tool）
- API 对比：Tavily / Serper / Brave Search / Google Custom Search / Bocha 官方文档
- 现有地基：src/agent_harness/knowledge/（Phase 11）、src/agent_harness/model/config.py、src/agent_harness/agent/runtime.py
