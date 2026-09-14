# ADR-0012: MCP Client 集成（Phase 8）

- 状态：Accepted（grill 2026-09-05，用户逐项拍板）
- 关联：spec 09_MCP_SKILLS_KNOWLEDGE_WEB.md / 14_IMPLEMENTATION_ROADMAP.md Phase 8 / 13_REUSE_MATRIX §4 / ADR-0010（capability registry）

## 背景

Phase 7 已交付 Capability/Plugin seam（Registry / Descriptor / 降级三分类 / CAPABILITIES env JSON / wire_capabilities 显式装配表）。Phase 8 按 roadmap 冻结范围为 MCP **Client** 侧四个交付物：① MCP Python client；② Tool discovery；③ MCPToolAdapter；④ permission/side-effect mapping。Gate 两条：Remote MCP Tool 仍经过统一 ToolExecutor；不出现双重 retry。Reuse 裁决：官方 MCP Python SDK = REUSE + ADAPT（transport/protocol/discovery 归 SDK），MCPToolAdapter 自研。

本 ADR 记录 grill 中用户逐项拍板的集成决策（参考了 oh-my-pi / Claude Code / ZCode 的 MCP 实现研究与 MCP server 生态调研）。

## 决策

1. **角色与范围**：MCP Client only（spec 冻结）。V1 只做 **tools** 原语（tools/list + tools/call）；resources / prompts / elicitation / roots 全部不做（DEFER）。
2. **Transport**：stdio + Streamable HTTP 两种（官方 SDK 抽象层，配置驱动）；被规范废弃的 SSE transport 明确排除。
3. **接入身份**：MCP = 一种 Capability Provider。`capabilities` env JSON 新增 `"mcp"` 条目，`options.servers[]` 为 server 配置；discovery 在 wiring 时执行，tool 贡献进 ToolRegistry（统一 Executor 路径，零旁路——不变量 #7）；server 不可达按 OPTIONAL_RUNTIME 降级（不变量 #21）。
4. **命名**：`mcp__{server}__{tool}`（双下划线两段，Claude Code/ZCode 惯例）；跨 server 同名按配置顺序先到先得 + 冲突显式记录（Phase 7 skills 先例）。
5. **权限映射**（交付物 ④）：MCP 工具注解 `readOnlyHint=true` → `READ_ONLY`；无注解或非只读 → `DANGER`（最严默认）；server 配置允许显式覆写个别工具级别；policy 非 full-access 时 DANGER 全部走审批关卡。side_effect：readOnlyHint 工具 READ_ONLY，其余 MUTATING。`readOnlyHint` 是 server 自报元数据而非安全边界（业界共识），故只作降级信号、永不升级权限。
6. **Retry 归口（Gate 2）**：重试语义归 ToolExecutor 唯一责任域。SDK 2.1.1 的 tools/call 无自发重试旋钮（已核实 installed source；streamable GET 流的重连仅恢复 server 主动消息、从不重执行工具调用）——实现上无需关闭动作，Gate 2 以测试钉住单次执行。
7. **生命周期**：连接时机 = wiring 时（per-server 超时，默认 30s）；未就绪/不可达 server 降级缺席 + errors 可观察。**重连只恢复连接、不隐式重执行**——调用中 transport 死亡 → 本次调用返回错误（TOOL_EXECUTION_ERROR，retryable=False），下次模型主动调用走新连接（避免对可能已有副作用的 remote 工具变相双重执行）。不做后台健康轮询（V1）。
8. **超时与输出预算**：per-server `timeout_seconds` 默认 30，映射到 adapter 生成的 Tool.timeout_seconds；MCP 工具输出在 adapter 层截断 + 截断标记（与 read 工具同一预算哲学；配置 artifact store 时自动走既有 overflow 管线）。预算单位为**字符**（`MAX_OUTPUT_CHARS = 50_000`）：预算的目的是保护模型上下文，token 数随字符数而非字节数增长——原文"50KB"为近似表述，以字符实现为准（Round 9 review 澄清）。
9. **配置 schema 与 secrets**：server 字段对齐 Claude Code 形状 `{name, transport, command?, args?, env?, cwd?, url?, headers?, timeout_seconds?, enabled?}`；`env`/`headers` 值支持 `${VAR}` / `${VAR:-default}` 进程环境变量展开（秘密间接引用，明文 token 不入库；oh-my-pi 同款——default 值形式为实现期补充，2026-09-05 review 补记），变量缺失且无默认值 → 该 server 进 errors 显式报错（不做静默丢弃——ZCode 反模式；展开后仍残留 `${...}` 形状同样响亮失败）；stdio server 启动环境 = OS 必需项白名单（C2 同款）+ 配置的 env 项，不继承全量进程 env。schema 追加 `tool_permissions?` 字段（裸工具名 → ToolPermission，承载决策 5 的"显式覆写个别工具级别"；2026-09-05 review 补记——决策 5 隐含但原 schema 漏列）。
10. **失败语义**：server 配置 schema 非法 → wiring 响亮失败（init_failed，配置错误必须响亮）；连接失败 → OPTIONAL_RUNTIME 降级缺席。
11. **预设 server**（用户拍板，写进文档模板、默认 capabilities 配置保持空 opt-in）：GitHub 官方 MCP（远程 OAuth + Docker）、Google chrome-devtools-mcp（浏览器调试）、Sentry MCP、Context7（Upstash，中厂例外——用户拍板入围）。按栈增补（AWS/Cloudflare/Figma/Stripe/Slack/Notion/JetBrains）只写文档。MCP 官方 reference 的 filesystem/git/memory/fetch 与内置工具重复，不推。
12. **测试策略**：Gate 测试用官方 SDK 的 in-process fake server（脚本化 tools/list + tools/call）做确定性替身；真实大厂 server 连通性为手动验收清单，不进 CI。
13. **OAuth**：V1 不实现 OAuth 流程（GitHub/Stripe 等远程 server 的 OAuth 登录 DEFER）；V1 远程认证走配置的 headers（值可 `${VAR}` 引用 token 环境变量）。

## 实现注记（ticket 内细化）

- Tool 契约的 `args_schema` 是 pydantic BaseModel 类，MCP 工具给的是任意 JSON Schema——adapter 以 jsonschema 校验入参（或动态 pydantic），inputSchema 原样透传给 registry 导出，**不改 Tool 契约形状**；ticket T4 落地时定稿。
- 新代码落位 `src/agent_harness/mcp/`（capability provider + adapter + config），经 Phase 7 的 `wire_capabilities` 注册表接入。

## 后果

- 正面：invariant #7/#21 在外部工具域落地；"大厂 server 预设"给用户开箱价值；Gate 可测（fake server）。
- 权衡：无 OAuth 意味着 GitHub 等远程 server V1 需要预置 PAT 环境变量；无 resources/prompts 意味着仅工具类 MCP 价值可用。
- DEFER 新增：OAuth 流程、resources/prompts 原语、MCP 工具清单 UI、server 健康轮询、`maxResultSizeChars` 类 per-tool 上限协商。

## 参考来源

- 研究：oh-my-pi mcp-config/runtime-lifecycle docs；Claude Code MCP/permissions docs；ZCode MCP docs；MCP registry preview blog
- 生态调研：github/github-mcp-server、ChromeDevTools/chrome-devtools-mcp、microsoft/playwright-mcp、getsentry/sentry-mcp、upstash/context7（star 数与维护状态为 2026-09-05 GitHub API 实时数据）
