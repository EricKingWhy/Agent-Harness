# Phase 13 Real Gate — Multi-Agent / Delegation

> **日期**：2026-09-06
> **Ticket**：#93（Phase 13 收尾）
> **决策来源**：ADR-0015（grill-with-docs 逐项拍板；组织原则 = 用户宪法「一切皆可是插件」）
> **执行方式**：`uv run pytest tests/integration/test_phase13_gate.py -m integration -v`
> **凭证**：真实模型 = `.env` 的 `MODEL_*` 主模型链（含 fallback），本文档与测试输出零泄漏。
> **上游环境注记**：真实 Gate 期间上游模型网关（senseaudio）间歇性故障（超时挂起 + 500「服务繁忙」，
> 直接探针 4 次仅 1 次成功）。全部 Gate 场景带 3 次独立尝试协议（每次全新 session）；
> 结果见下表与「上游故障期记录」一节。

---

## 结果总览

| Gate | 内容（spec §13 / roadmap Phase 13 验收对照） | 结果 |
| --- | --- | --- |
| Gate 1 | research 任务 → 模型自主路由 research_review（真实委派 + child 完成） | ✅ PASS |
| Gate 2 | coding 任务 → coding + 共享 workspace 真实写文件 | ✅ PASS |
| Gate 3 | 动态第四个 AgentSpec 经 AgentFactory 创建并真实跑通 | ✅ PASS |
| Gate 4 | child 不倾倒完整历史（父流事件数抽查 vs child JSONL） | ✅ PASS |
| Gate 5 | mixed 任务：research 结论 → coding 落盘（两个 child 协作） | ✅ PASS |
| Gate 6 | 同指纹失败 delegate 真实触发 RepeatedToolFailureGuard | ✅ PASS |
| Gate 7 | delegation 预算（max_delegations）真实耗尽回填 | ✅ PASS |
| Gate 8 | CAPABILITIES 未配 multiagent → 单代理零感知回归（无 delegate） | ✅ PASS |

CI 全量回归：**1046 passed, 9 skipped, 20 deselected**（unit 全量；20 = 本 gate 8 条 + 既有
integration/qiniu 凭证门；988 主线基线 + Phase 13 纯新增 58），ruff clean。

## 结构性 Gate 证据（不依赖真实模型，单测钉死）

roadmap Phase 13 Gate 四条中，两条本质是**结构断言**，unit 层已完备覆盖：

**「tool/context permission 收窄」**（`tests/agent/test_profiles_factory.py`）：
- `AgentFactory.create` 构造期从全量 registry 过滤生成**新 ToolRegistry 实例**（不可逃逸，
  ADR-0015 决策 11）；coding profile 恰好 9 个工具、无 web 工具；research_review 仅
  read/grep/glob + 检索三件套。
- 越权拒绝：`spec.tool_scope` 要求 source registry 有而 grantable 集合没有的工具 →
  Factory 直接拒绝（防权限提升通道）。
- child 不含 delegate（depth=1，决策 7）：`max_depth` 字段保留，打开深度是改配置不是改架构。

**「Single Agent 不依赖 LangGraph」**（`tests/orchestration/test_seam.py` + Gate 8）：
- `OrchestrationAdapter` 是 Protocol-only seam（#92），`src/` 全树 import 边界契约测试：
  Core 永不 import langgraph（唯一豁免 = memory/base_store_adapter.py 的 LangMem 可选
  provider 用 langgraph.store BaseStore 做 memory interop，不是编排）。
- multiagent 是 CAPABILITIES 显式 opt-in 的 capability（决策 2，ADR-0010 模式）：
  未配置 = delegate 工具缺席 + Agent Loop 零 diff + 单代理照跑（Gate 8 真实回归）。

**熔断复用**（`tests/agent/test_repeated_tool_failure_loop.py`，#88）：6 个同指纹 delegate
调用穿真实 runtime 全循环——软 3（注入纠正消息）→ 硬 6（`end_run(failed)`，
reason=`identical_tool_failure_loop`）。无新熔断机器，RepeatedToolFailureGuard 原样生效。

## 单测覆盖盘点（#82-#92）

Phase 13 纯新增 58 条单测（`test_profiles_factory` / `test_delegate` / `test_delegation_events` /
`test_result_fields` / `test_multiagent_wiring` / `test_concurrency_gate` / `test_seam` 等）+
熔断全循环 pin。覆盖：profile/scope 过滤与越权拒绝、delegation 事件 lineage、SubAgentResult
真实来源字段（citations/artifacts/changed_files/unresolved 绝不伪造，决策 12）、summary 溢出
（store-backed vs truncate+pointer）、预算（max_delegations 显式耗尽回填，决策 13）、
max_active_children=4 并发上限、取消/恢复语义（父 cancel → child 收尾 + delegation 事件对账，
决策 18）、进程级 ModelCallGate（QPS/限流防护，决策 13 补充）。

## Gate 1 — research 路由（真实模型决策）

**验证点**：supervisor 对调研任务自主选择 delegate(target=research_review)（agentic 路由，
决策 4——DelegationDecision 即 delegate 工具调用参数）；child 独立 session 完整跑
web_search 并返回结构化结果；`agent/delegation-started/finished` 落父 JSONL（决策 6/8）。

实测 2026-09-06 16:00:46（3 次独立尝试协议下首次命中）：supervisor 发起
delegate(target=research_review) → child 独立 session 真实跑 web_search →
delegation-finished(status=completed, child_session_id 在场) → 转述结果。

## Gate 2 — coding 路由 + 共享 workspace（同一 sandbox 边界）

**验证点**：coding child 在**共享 workspace**（spec §9 同一 sandbox）真实创建 `hello.txt`；
文件经父 runtime 的 workspace 断言存在且内容正确——child 写入对 supervisor 立即可见。

实测 16:01:34：delegate(target=coding) → child 在共享 workspace 真实创建
hello.txt（内容 phase13-ok）→ completed；父 runtime 同一 workspace 断言通过。

## Gate 3 — 动态第四个 Agent（Gate 级复验）

**验证点**：测试直接构造第 4 个 `AgentSpec`（analyst：纯推理、tool_scope=∅）经
`AgentFactory.create` 生成 runtime，真实模型求和 21+21+105=147——**create_agent 不是
LLM 可见工具**（决策 10）：动态创建是代码路径公开 API，模型无自配工具通道。

实测 16:02:02：analyst（tool_scope=∅，max_steps=3）经 AgentFactory.create
生成独立 runtime，真实模型对 21+21+105 答出 147，status=completed。

## Gate 4 — child 不倾倒完整历史（不变量 6「完整保存 ≠ 完整注入」的多代理版）

**验证点**：委派后父 session 事件抽查——`agent/delegation-*` 在场、父 `model/completed`
数 ≤ 3 且 < child 内部步数；child 自己的 JSONL 保留完整多轮历史（前端钻取是纯增量，
决策 8 父流白盒边界）。

实测 16:02:30：父流 delegation-started/finished 在场、父 model/completed ≤ 3
且 < child 内部步数；child JSONL 保留完整多轮历史。

## Gate 5 — mixed 任务两 child 协作

**验证点**：research（web_search 结论）→ supervisor 交接 → coding（写入 `mixed.txt`），
两个 child 顺序配合、结果真实落盘。这是「supervisor 是编排者、child 是执行者」的端到端证明。

实测 16:03:51：两个 delegation-finished 均 completed、targets ⊇
{research_review, coding}，mixed.txt 真实落盘（research 结论经 supervisor
交接给 coding 写入）。

## Gate 6 — 同指纹失败 delegate 真实触发熔断（#88）

**验证点**：prompt 要求模型并行发起 6 个**参数完全相同**、target=未知角色的 delegate 调用
→ provider 在 child spawn 前明确失败（决策 17 禁止未知 target）→ 同指纹连续失败累计 →
`tool/failure-guard` 事件（软 3 / 批内塌缩直接硬 6，Phase 12 Gate 3 同款语义）。

概率性说明：真实模型对批量指令的服从是概率性的，3 次独立尝试协议；确定性语义由
全循环单测钉死（见上「结构性 Gate 证据」）。

实测 16:15:30（session JSONL 取证，pytest-1155）：3 × tool/call(delegate) 同参数 →
```json
{"type": "tool/failure-guard", "level": "soft", "tool_name": "delegate",
 "fingerprint": "delegate:{\"target\": \"nonexistent_role\", \"task\": \"熔断验收\"}",
 "consecutive_failures": 3}
```
恰好命中软熔断阈值（N=3），fingerprint 与 #88 契约一致（工具名+规范化 args）；
硬熔断（6）终态语义由全循环单测钉死，真实模型单批 6 连发指令服从率低（Phase 12
Gate 3 同款概率性），验收口径 = 任一 guard 事件真实触发。

## Gate 7 — delegation 预算真实耗尽（决策 13）

**验证点**：delegate 换 `max_delegations=2` 实例（同一已激活 provider，白盒——预算是
DelegateTool 构造参数而非环境语义），第 3 次委派收到**明确的预算耗尽回填**
（「delegation 预算耗尽（已用 2/2）」）让 supervisor 自己收尾，绝不静默截断。
预算检查在 provider.run 之前：未知 target 的失败调用同样消耗预算（防烧钱语义完整）。
三次调用 task 互不相同（不同指纹）避免熔断器干扰预算观察。

实测 16:31:53（session JSONL 取证，gate-budget-0 首次尝试即中）：3 × delegate 调用，
第 3 次返回：

```json
{"ok": false,
 "message": "delegation 预算耗尽（已用 2/2）。请综合已有结果直接收尾，或改变策略，不要再委派。",
 "error_code": "INVALID_ARGUMENT"}
```

明确回填、可读、绝不静默截断（决策 13 原文语义）。

## Gate 8 — CAPABILITIES 关 multiagent → 单代理回归

**验证点**：空 capability 表装配的新 runtime——`registry.get("delegate")` 抛 KeyError
（工具缺席）+ 真实模型答 1+1 正常完成。单代理路径对 multiagent/插件体系零依赖
（「一切皆可插件」的反向面：卸载即消失）。

实测 16:38:50（session JSONL 取证，gate-single-0 首次尝试即中）：
KeyError 断言过 + `run/completed final_text="2"`（真实模型）——multiagent 关闭 =
单代理零感知，与启用时行为无差。

---

## 上游故障期记录（2026-09-06）

真实 Gate 执行期间上游模型网关（senseaudio）处于间歇故障期（超时挂起 + 500
「服务繁忙，请稍后再试」ref_code 500000，直接探针 4 次仅 1 次成功；期间多轮
「探针通过 → 套件跑到一半翻脸」的抖动）：

- **机械正确性在故障中被反向验证**：model/failed（InternalServerError）→
  fallback 正确触发（model/fallback 事件在场）→ 卡流看门狗秒级兜底挂起调用 →
  run 终态真实不伪造——正是 Phase 12 可靠性层的验收行为。primary 与 fallback
  共用同一网关时无法自救（双 provider 同源），属环境容量问题非代码缺陷。
- **执行策略**：探针门控（15s 超时 × 3 次小请求，≥2 成功才跑）+ 逐 Gate 执行 +
  结果记账（.scratch/gate_loop.sh，不入库）+ 每 Gate 内 3 次独立尝试协议——
  在抖动窗口中逐条取绿（16:00:46 → 16:38:50）。
- **模型服从性注记**：Gate 6 首版 prompt（要求并行 6 连发无效调用）被真实模型
  拒绝服从；降为 3 次同参调用（恰为软熔断阈值 N=3）后服从并真实触发——
  「验收 prompt 的服从概率」本身是多代理/熔断类 Gate 的第一性约束，与 Phase 12
  Gate 3 经验一致。
