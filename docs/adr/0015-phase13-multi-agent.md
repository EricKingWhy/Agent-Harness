# ADR-0015: Phase 13 Multi-Agent / Delegation

- 状态：Accepted
- 日期：2026-09-06
- 关联：spec 10_MULTI_AGENT_DELEGATION / 08_PLUGIN_CAPABILITY_SYSTEM / 14_IMPLEMENTATION_ROADMAP Phase 13 / ADR-0010（Capability 显式装配）/ ADR-0014（可靠性三件套：熔断、fallback、看门狗——本阶段全部被 child 继承）/ 不变量 #7 #18 #19 #20
- 上下文：Multi-Agent 是正式 V1 能力，MUST 建立在单一 AgentRuntime 之上（不变量 #19）。用户拍板的宪法级约束：**一切皆可插件**——LangGraph、subagent 机制本身都是可装卸、可替换的插件（参照 pi 插件中心 pi.dev/packages 的安装/卸载/替换模型）。上游调研（pi / oh-my-pi / Codex / Claude Code / ZCode）见 grill 记录。

## 决策

### 顶层范围（Round 1）

1. **7 项交付全做；LangGraph = 可插拔编排适配器**：V1 不实现具体图，只定义 OrchestrationAdapter 接口位（Graph State → agent node 调 AgentRuntime → 结果写回；Graph Checkpoint 永不替代 Operation Ledger）。未来接 LangGraph = 写一个 adapter 实现，Core 零改动；卸载 = 删配置，单代理照跑（spec §10 验收原生满足）。
2. **插件化宪法（本 ADR 的组织原则）**：`multiagent` 是一个 CAPABILITIES 显式注册的 capability（同 knowledge/websearch 模式，ADR-0010），贡献 delegate 工具 + SubagentProvider + child 运行注册表；**AgentProfile/AgentSpec 是核心域对象**（Runtime 本来就消费 max_steps/system prompt 概念），不进插件。禁用插件 = main 失去 delegate 工具、纯单代理照常运行；换插件 = 换 SubagentProvider 实现（不变量 #18：不写进 Agent Loop 特判）。
3. **spawn-only**：V1 无 fork（fork boundary 是 Phase 14 地盘）；`SubagentProvider` Protocol 留 seam，V1 唯一实现 = in-process（直接构造 AgentRuntime 执行 child run）；subprocess/remote(ACP) 未来换实现。
4. **Supervisor = main profile + delegate 工具**：零新编排组件。DelegationDecision（action/target/task/constraints）即 delegate 工具调用的参数；路由决策是模型的 tool call（agentic）；delegate 经统一 ToolExecutor（不变量 #7）。
5. **并发 = 阻塞并行**：模型一轮可发多个 delegate tool_call，executor 既有管线 gather 并发 + 保序回填 + Ledger 记账（Phase 4 轮子）。V1 不做异步 park/revive（Phase 14+）。
6. **child = 独立 Session**：同一 store 下独立 session_id + 独立 JSONL；父 Session 只持久化 `agent/delegation-started` / `agent/delegation-finished` 两条事件（含 task、child_session_id、result 摘要）；Operation Ledger 的 `agent_id` 落真实 agent 身份（现有 "default" seam 的正主）。lineage = delegation 事件里的 child_session_id 引用（Phase 14 lineage tree 直接消费）。
7. **深度 V1 = 1**：child 的 tool_scope 不含 delegate（Claude Code 模式）；`AgentSpec.max_depth` 字段保留，打开深度是改配置不是改架构。
8. **父流白盒**：delegation start/finish 两事件进父 JSONL + SSE 镜像；child 详细过程在 child 自己的 JSONL（前端钻取是纯增量，未适配前父流即可读）。

### Profile 与工具（Round 2）

9. **三内置 profile（Python 常量，tool_scope 显式声明，无隐式默认）**：
   - `main`（supervisor）：coding ∪ research 全量 + delegate
   - `coding`：read/write/edit/apply_patch/bash/grep/glob/git_status/git_diff（spec §8 集合，无 web）
   - `research_review`：read/grep/glob（只读三件套，review 要看共享 workspace 的真实文件）+ knowledge/web/mcp 只读工具
10. **动态创建边界**：`AgentFactory.create(AgentSpec)` 是公开 API（validate permissions/capabilities → 构造），Gate「动态创建第四个 Agent」由测试直接构造第四个 AgentSpec 走 factory 满足；**create_agent 不作为 LLM 可见工具**（LLM 自配工具 = 权限提升通道；spec §2「不是让 LLM 任意生成」）。DEFER 且将来必须过权限校验。
11. **child 的 tool_scope 实现机制**：AgentFactory 构造期从全量 registry 过滤生成**新 registry 实例**（不可逃逸）；校验 `spec.tool_scope ⊆ parent 可授予集合`，越权 = Factory 拒绝（防权限提升）。approval/auto_approve 与 PermissionPolicy 直接传递（child 危险操作走同一审批面）。

### 结果与预算（Round 2）

12. **SubAgentResult 字段（真实来源，绝不伪造）**：
    - 真实产出：`agent_id` / `status`（child run 终态）/ `summary`（child 最终回答）/ `artifacts`（child 的 artifact/created 收集）/ `citations`（child 检索命中收集）/ `unresolved`（child system prompt 强制末尾自报，无则空）
    - 推导产出：`changed_files`（child 事件中 write/edit/apply_patch 参数推导，不跑 git）
    - DEFER：`tests`（无真实来源，V1 省略字段）
    - **大产物溢出（不变量 #15）**：summary 超限（8KB）→ 全文走 child 侧 artifact 溢出管线，父拿压缩摘要 + artifact ref，按需 read——用户拍板「结构化交付 + 大产物摘要/引用化」
13. **预算三旋钮（出厂值，可覆盖）**：`max_delegations=8`（每 run，防烧钱）/ `max_active_children=4`（并行上限）/ child `max_steps=10`。**超预算 = delegate 返回明确失败（"delegation 预算耗尽"）让 supervisor 模型自己收尾，绝不静默截断**（用户强调）。
14. **模型策略**：V1 唯一策略 `model_policy="inherit"`——child 继承主模型链（同 create_chat_model + fallback + 流式看门狗），fallback/看门狗对 child 自动生效零新代码。per-profile 模型列表等真实账单数据说话。
15. **Termination 四件套**（作用域不混淆）：Agent `max_steps`（child 10）/ Supervisor `max_delegations`（8）/ `max_active_children`（4）/ **repeated-delegation 熔断**——复用 RepeatedToolFailureGuard 指纹机制，指纹 = (target_profile, task 哈希)，软硬同款（软：注入纠正消息；硬：终止 run）。
16. **child 失败语义**：child run 失败 → `SubAgentResult.status=failed` + unresolved 说明回填，重试与否由 supervisor 模型决定（换措辞再 delegate 或放弃），框架不自动重试。
17. **delegate 工具 schema**：`{target: str(预定义 profile 名), task: str, constraints?: string[]}`；禁止 target=未注册 profile（明确报错列出可选）。
18. **kill/resume 语义**：child run 复用 stall 看门狗与 cancel 语义；父 run 中断时未完成的 delegation 走既有 dangling tool/result 合成机制，child session 留档可查、不自动复活（重新委派 = supervisor resume 后自己决定）。

## 后果

- 正面：subagent 编排成为可装卸插件（用户宪法）；单代理路径零回归（capability 未启用时 Runtime 无感知）；可靠性三件套对 child 自动继承；lineage/钻取/Phase 14 fork 全部有挂点。
- 权衡：opt-in 意味着集成后默认单代理（手册已注明）；depth=1 砍掉深层委派场景（字段保留可开）；create_agent 不开放给 LLM（未来真实需求出现再设计权限面）。
- DEFER：LangGraph adapter 实现、fork、异步 park/revive、多轮 child 交互（steer/revive）、markdown 文件发现、per-profile 模型列表、tests 字段、create_agent 工具。
