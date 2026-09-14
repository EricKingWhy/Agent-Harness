# 12 — Observability / Evaluation

## 1. 三层观测

### Durable SessionEvent
业务事实、Replay/Resume/Fork/UI 的基础。

### Diagnostic JSONL Log
Debug、性能、异常细节。

### Langfuse
Trace / Span / UI Observability，可开可关。

它们互补，不能互相替代。

## 2. Diagnostic Log

开发模式默认完整记录：
- model request/response metadata；
- tool input/output；
- attempt；
- error_code；
- duration；
- provider latency；
- token usage；
- cost；
- stack trace；
- fallback reason；
- reconcile reason。

大输出转 Artifact，不直接把数百 KB/MB 写成单行日志。

默认不做敏感信息脱敏是当前开发环境选择，但实现 SHOULD 保留未来 redaction hook。

## 3. Trace 层级

推荐：

```text
Agent Run
├─ supervisor
├─ research agent
│  ├─ model
│  ├─ retrieve_knowledge
│  └─ web_search
├─ coding agent
│  ├─ model
│  ├─ read/edit/apply_patch
│  └─ bash
└─ final synthesis
```

统一 metadata：
- session_id
- run_id
- agent_id
- step_id
- tool_call_id
- operation_id

## 4. Langfuse Adapter

REUSE 官方 SDK。

要求：
- graceful no-op；
- tracing failure 不影响 Agent；
- Session/Run/Agent/Tool ID 映射一致；
- 不发明另一套 trace identity。

## 5. Evaluation

项目自己拥有 Golden Dataset：

```text
evaluation/
├─ cases.jsonl
├─ runner.py
├─ assertions.py
└─ reports/
```

Eval Runner 调真实 AgentRuntime，不为了 EvalScope 重写 Runtime。

## 6. Deterministic First

优先代码判断：

- tool_selected_accuracy
- citation_valid_rate
- task_success_rate
- recovery_success_rate
- dangling_tool_call_count
- unnecessary_tool_rate
- permission_violation_count
- duplicate_side_effect_count

LLM Judge 只用于：
- 答案完整性；
- evidence support；
- review quality；
- 难以完全 deterministic 的语义质量。

不得把所有指标揉成一个无法解释的总分。

## 7. EvalScope

EvalScope 作为 thin Adapter：

```text
project-owned runner
→ real Agent Runtime
→ normalized result
→ EvalScope adapter
→ report
```

不是 Core 依赖。

## 8. Regression Metadata

每次 Eval 记录：

```text
app_version
prompt_version
model_provider
model_name
knowledge_version
memory_provider/version
eval_dataset_version
git_commit
timestamp
```

否则分数不可解释。

## 9. 初始 Gate

建议：
- P0 deterministic cases = 100%
- dangling tool call = 0
- duplicate confirmed side effects = 0
- core recovery = 100%
- citation validity = 100%
- permission violations = 0
- task success 达到经真实数据校准的阈值

## 10. Final Full E2E

至少覆盖：

```text
existing Session
→ Main
→ Research
→ retrieve_knowledge insufficient
→ rewrite
→ web_search + citation
→ Main
→ Coding
→ grep/read/edit/apply_patch
→ pytest fail
→ Agent debug
→ modify again
→ Tool running
→ kill Python
→ restart/resume
→ restore Sandbox
→ Operation reconcile
→ restore ToolResult consistency
→ pytest pass
→ Review
→ final answer
→ SessionEvent replay
→ Langfuse Trace
→ Eval report
```

## 11. Acceptance Criteria

- JSONL 可 tail/grep；
- Langfuse 可定位耗时和 Tool retry；
- Langfuse 关闭时 Core 正常；
- Eval 可重复运行；
- Kill/Resume case 纳入回归；
- Citation 有真实来源；
- Regression report 可对比版本。
