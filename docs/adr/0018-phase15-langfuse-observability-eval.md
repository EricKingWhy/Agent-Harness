# ADR-0018 — Phase 15：Langfuse 旁路观测 + 评测

日期：2026-09-07 ｜ 状态：Accepted（grill 两轮逐项拍板，用户确认） ｜ 关联：spec 12、Roadmap Phase 15、ADR-0014/0016/0017

## 背景

三层观测（SessionEvent / 诊断 JSONL / Langfuse）中前两层已在早期 Phase 建成：`logging.py`（schema 1.0，llm_call / tool_operation / retry / error 事件族，trace 链路字段 + contextvar 传播）、runtime usage 记账（model/completed 带 model+usage、run/completed 带 usage_total / cost_usd=null / trace_id=null 预埋，`runtime.py:565` TODO(Phase 15)）。本 Phase 接入第三层：Langfuse（云 jp 区）同时承担 **Trace 观测** 与 **在线/离线评测**。

用户定调：**企业级生产工程**——旁路组件，崩溃/慢绝不影响主流程，不损失主流程性能；监控要详细、便于排查。Roadmap Phase 15 交付清单中的 EvalScope Adapter 按用户指令砍掉（见 D9 Gap 报告）。

## 决策（grill 逐项拍板，用户确认）

### D1 平台与三层关系
Langfuse（https://jp.cloud.langfuse.com，用户项目）承担观测 + 评测。三层互补原则不变：SessionEvent=业务事实、JSONL=本地诊断、Langfuse=UI 观测/评测；任何一层不可替代另一层。Langfuse 是**纯旁路**：事件流与 JSONL 的语义绝不依赖它存在。

### D2 旁路定位与装配
Settings 门控（tavily/fallback 同款模式）：`LANGFUSE_PUBLIC_KEY` 为空 = 模块完全缺席（懒加载，零 import 开销）。**不做** capability descriptor（那是 Tool 能力体系）；`Degradation.OPTIONAL_OBSERVABILITY`（capability/base.py:20，CONTEXT.md 已注明「Langfuse 属此档」）的语义由模块自身实现承担——Langfuse 是该档首个使用者。

### D3 故障模式矩阵（企业级硬要求）

| 情形 | 行为 |
| --- | --- |
| 未配置（key 空） | 完全缺席，懒加载，主流程零开销 |
| SDK 初始化抛错 | 记一条 JSONL system_log 诊断行 + 本进程永久禁用旁路，主流程零感知 |
| 端点慢/挂 | SDK 自带后台批处理队列隔离主流程；wrapper 层熔断（连续失败 N 次暂停发送，指数退避有上限），熔断期丢弃计数写 JSONL 诊断行（不进 SessionEvent，Event ≠ 诊断日志） |
| 任何 SDK 异常 | 单一异常边界全吞（不变量 #21），主流程不可能看到旁路异常 |
| 进程退出 | CLI 退出前 flush；服务 graceful shutdown flush，发送等待有超时上限（不阻塞退出，丢了算旁路损失） |

**性能红线**：热路径（model call / tool 执行生命周期内）只允许内存对象构造 + contextvar 读取；零同步网络、零 `await` Langfuse、零磁盘写。SDK 全异步后台发送。

### D4 埋点缝：手工 sink，不用自动化
不用 LangChain CallbackHandler（我们拥有 Agent Loop，其自建 span 结构不可控且与手工驱动 astream 语义别扭）、不用 `@observe` 装饰器魔法（隐式把函数签名变成 trace input，泄漏面大）。埋点位置 = **现有诊断日志的生命周期点**（run 终态 / llm_call / tool_operation / SubAgent 委托点 / context 压缩），sink 模式与 JSONL 诊断行同点平行双写、各走各的 schema。SDK 在 `load_dotenv` 之后才 import（官方陷阱清单）。

### D5 ID 映射（不发明第二套 trace identity，spec 12 §4）
- Langfuse **session** = `session_id`；
- **trace** = 一次 agent run：name 描述性（如 `agent-run`），input=用户消息、output=最终回答，metadata=run_id / agent_id / git_commit / 模型链 / env，tags=agent profile、触发来源；跨进程恢复链用 metadata `resumes: <原 run_id>` 标注（kill/resume 后新 run=新 trace，靠 session 聚合）；
- **generation** = 每次 model call；
- **span(tool)** = tool operation；
- **observation type=`agent`** = SubAgent 执行（官方多 Agent 规则：无双 dispatch 节点、递归嵌套、按具体 agent_id 命名）。

### D6 内容边界
`LANGFUSE_TRACE_CONTENT=full | redacted`，默认 **full**（用户自有 dev 项目，与 JSONL dev 默认一致）。redacted：只传 metadata + 截断（输入输出截断、args/result 摘要）。redaction hook 一步到位（单一函数边界，未来接策略不再改埋点）。

### D7 详细埋点清单（用户「详细、好排查」拍板照单全收）
- **generation**：model 名与参数（temperature 等）、input 完整消息数组、output 文本、usage 三元组、latency、attempt 序号、finish_reason、provider_request_id、fallback 履历（primary→fallback 切换原因，ADR-0014 决策 18 已有 JSONL 同源数据）、error 类型/错误码；
- **span(tool)**：tool 名、args 全文（full 模式）、result message+data、逐 attempt 的 duration 与错误链、error_code、retryable、tool_call_id、**operation_id（对账 Operation Ledger）**、artifact 溢出标记、sandbox 命令内容（full 模式）；
- **span(agent)**：agent profile 名、任务描述、完整嵌套、委托深度；
- **context 态 span**：每步 context token 占用、compaction 事件；
- **trace_id 回填**：Langfuse 开启时 run/completed.data.trace_id = 真实 Langfuse trace id（前端「未追踪」灰字自动变可用）；关闭恒 null，不伪造。

### D8 JSONL 审计补缺
诊断 JSONL 已建成（schema 1.0），本轮对照 spec 12 §2 字段清单审计收尾：补 reconcile reason 进 tool_operation 行（源 Operation Ledger reconcile_meta）；cost 语义明确化——Langfuse 侧按 model+usage 自动算，事件流 cost_usd 保持 null（spec 12 未定义费率表，不伪造、不依赖旁路）。

### D9 评测架构（含 Gap 报告：EvalScope 砍掉）
- **Langfuse Datasets** 承载 cases；**真相源在 repo**（`evaluation/datasets/*.jsonl` 版本化导出 + seed 脚本推送），云端不是唯一真相；
- **Eval Runner 项目所有**（`evaluation/`：runner.py / assertions.py / reports/，spec 12 §5 形状保持），调真实 AgentRuntime（不为评测重写 Runtime），跑完作为 Langfuse **Experiment** 上报；
- **deterministic assertions 全部代码判断**（tool 选择正确率、dangling=0、recovery 成功率、kill/resume 恢复），作为 Scores 上报；LLM judge 只用于语义质量且先校准（judge-calibration 流程），本轮只搭不启用；
- **regression metadata**（spec 12 §8 全字段：app_version / prompt_version / model_provider / model_name / knowledge_version / eval_dataset_version / git_commit / timestamp…）= Experiment metadata；
- **Gap 报告**：Roadmap Phase 15 交付项「EvalScope Adapter」按用户指令砍掉，由 Langfuse Datasets+Experiments 承担同等职责——与冻结规格的偏差记录于此 ADR 与 PHASE_STATUS，不静默改规格。

### D10 Eval 环境矩阵
deterministic P0 = **ScriptedModel + 真实 AgentRuntime + 真实 tool registry**（免费、确定、可进 CI 回归）；真实模型 smoke 实验 = 手动触发，断言只做结构性检查（dangling=0、usage/trace 完整性），不进 CI，喂 Langfuse dashboard 看真实趋势。

### D11 依赖与配置
`pyproject.toml` 新增 `[project.optional-dependencies] observability = ["langfuse>=3"]`（REUSE 官方 SDK，spec 13 §4）。env 族：`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`（SecretStr 脱敏待遇）/ `LANGFUSE_BASE_URL`（SDK 用 LANGFUSE_HOST，装配层映射）/ `LANGFUSE_TRACE_CONTENT`。SDK 版本与 API 以实现期官方文档为准（skill 原则：Documentation First，不凭记忆写码）。

### D12 自审 Gate（官方 skill 硬要求）
真实链路跑通 → `langfuse-cli` 回捞刚产生的 trace → 对照官方 best-practices 页逐项审计（每次现查，不凭记忆）→ 修 Gap → 复跑，直到过审。加上 P0 四条 deterministic cases 全绿作为 Phase 15 Gate。

## P0 Golden Cases（用户确认）
① tool_selection 正确率；② dangling_tool_call=0；③ recovery（tool 失败→重试→成功）；④ kill/resume 回归（spec 12 §11 硬要求）。citation/permission 场景排 P1。

## DEFER 清单
在线 managed evaluator（LLM judge 自动跑 live traces）启用（本轮只搭）、citation/permission cases（P1）、费用预算告警、trace 采样率配置（默认全量，现量级不需要）、事件流 cost_usd 费率表（spec 12 未定义）。

## 协作与集成顺序
feat/backend（ADR-0016 流式）→ feat/phase14（ADR-0017）合入 main 之后，Phase 15 才从**合入后的 main** 开 `feat/phase15` worktree（§13.1；用户拍板 Q6=B）。B AI 的 block_id / reasoning / tool 输出流事件族是埋点的上游事实——sink 的 generation/span 结构不受影响，仅 event 词表更丰富。Phase 15 对 provider/runtime/executor 的改动是添加性埋点，预期冲突面小。
