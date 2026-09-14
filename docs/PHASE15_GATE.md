# Phase 15 Gate — Langfuse 旁路观测 + 评测（#117-#125，ADR-0018）

> 日期：2026-09-07 ｜ 分支：feat/phase15（对 main 的 diff：40 文件 +3514/-109）
> 全量：**1173 passed / 9 skipped / 27 deselected / 0 failed**（基线 1136 + 新增 37）
> Lint：`ruff check src/ tests/ evaluation/` 全绿

## Gate 结果总表（5/5）

| # | Gate | 车道 | 结果 |
| --- | --- | --- | --- |
| 1 | Langfuse 关闭时 Core 正常（不变量 #21） | 默认 | ✅ PASS（trace_id=null、旁路零痕迹、事件流与 Phase 14 语义一致） |
| 2 | 真云链路：上传 → 回捞 → best-practices 审计 | integration（真云 jp） | ✅ PASS（两次真云全绿；一次因本地网络 10061 抖动失败后恢复复跑通过，见「过程记录」） |
| 3 | P0 Golden Cases 全绿（deterministic） | 默认 | ✅ PASS（tool_selection / recovery / kill_resume 三条 + 全局 dangling=0 断言） |
| 4 | 未配置云时 seed/experiment 优雅降级 | 默认 | ✅ PASS（skipped 语义，绝不触 SDK） |
| 5 | 真云 Dataset seed 幂等 + Experiment 上报 | integration（真云 jp） | ✅ PASS（重复 seed created=0；run_experiment 真实落云） |

`uv run pytest tests/integration/test_phase15_gate.py -m integration -v` → 2 passed（Gate 2/5）。
默认车道随全量：1173 passed 零失败。

## Gate 2 审计清单（官方 best-practices 固化断言，全部对真云回捞数据）

- trace name 描述性（`agent-run`）✓；session 聚合 = session_id（`propagate_attributes` 官方通道）✓
- trace metadata：run_id / agent_id / git_commit ✓；trace input=用户消息、output=最终回答 ✓
- GENERATION ×2（两次模型调用）：model 名在场、usage_details（input/output/total）如实上报（自动 cost 的前提）、response_model 元数据 ✓
- TOOL 观测：name=add、tool_call_id + session_id（Operation Ledger 对账键）✓
- context-build SPAN 在场 ✓；不发明第二套 trace identity ✓

## Eval 结果（P0 deterministic，可复现）

| Case | 断言 | 结果 |
| --- | --- | --- |
| tool_selection_add | 工具选择正确 + dangling=0 + completed | ✅ |
| recovery_guard_soft | 软熔断在场 + 恢复后 completed + dangling=0 | ✅ |
| kill_resume_confirm_success | session/resumed + 合成 tool/result 补齐（无悬空）+ 裁决 CONFIRM_SUCCESS | ✅ |

真实模型 smoke：入口 `evaluation/smoke.py`（结构性断言 + regression metadata）已就绪并经注入 fake runtime 验证管线；**真实模型调用未在本轮执行**（手动车道，烧 token）——集成后在有凭证环境运行 `python -m evaluation.smoke` 或等价入口。

## 过程记录与自审发现（code-review 双轴）

**Standards 轴（修复）**：
1. `evaluation/reports/*.json` 加入 .gitignore（运行产物不入库，数据集真相源入库）——本轮唯一需修复项。
2. ScriptedModel 升格 `src/agent_harness/model/scripted.py`（tests 同名文件变 shim）：eval runner 是项目代码，不能 import tests——语义/行为零变化（含 astream 分块与快照）。
3. 静默替换事故一次：runtime→execute_batch 的 `tracer=tracer` 参数首patch未命中（缩进漂移），真云 Gate 审计抓到（tool 观测缺席）——已修复并复跑。教训：脚本 patch 必须 assert 锚点。

**Spec 轴（ADR-0018 对照，已知边界如实登记）**：
1. D3 熔断语义澄清：wrapper 熔断覆盖**同步调用层**故障；网络层不可达由 SDK 后台队列隔离（热路径仍零阻塞、零异常泄漏）——两层各自兜底，主流程隔离保证不变。
2. D7 缺项（DEFER）：model_parameters（temperature 等）未随 generation 上报（runtime 不持温度配置）；`resumes` 恢复链 metadata 未实现（resume 语义在 web 层，本轮以 session 聚合承载恢复链）。
3. D8：tool 观测的 ledger 关联以 session_id+tool_call_id 承载（operation_id 是 Ledger 派生属性，T4 审计已记录口径）。
4. 真云审计过程发现官方语义：`trace.list` 返回观测 id、`trace.get` 返回完整对象；观测 type 为大写枚举（GENERATION/TOOL/SPAN）——Gate 断言已按真实形状固化。
5. 观测落库顺序：trace 先于子观测可见——Gate 回捞以「observations 到齐」为就绪条件（带退避）。

## 环境备注

- Langfuse 云（jp 区）密钥在 worktree `.env`（零泄漏）；集成时需同步 `LANGFUSE_*` 到 main worktree `.env`。
- 上游模型网关（senseaudio）与 Langfuse 云均出现过间歇抖动；Gate 全部按「退避复跑 + 结果登记」处理，无 FAIL 被掩盖。

## 集成后真实模型 smoke（2026-09-07，main 86adedc）

> Phase 15 合入 main 并 push 后，在 main（`D:\intelligence-agent`）执行真实模型 smoke——
> ADR-0018 D10 手动车道（deterministic 进 CI / 真实模型手动），Phase 15 闭合的最后一脚。

### 触发

```python
from evaluation.smoke import run_real_model_smoke
result = run_real_model_smoke(
    task="用 add 工具算一下 7 加 35 等于多少，然后告诉我结果。",
    session_root="evaluation/smoke_sessions",
    require_trace=True,
)
```

### 结构性结果

| 指标 | 值 |
| --- | --- |
| ok | **true** |
| error | null |
| dangling_tool_calls | 0 |
| terminal_present | true |
| usage_reported | true（prompt=631 / completion=162 / total=793） |
| trace_id_present | **true**（`d9a49a30be8ccd14df5468c2adc6851c`） |
| event_count | 9（session/started → user/message → run/started → model/completed → tool/call → tool/result → model/fallback → model/completed → run/completed） |
| duration_ms | 178646（含真实模型往返；第一轮主模型触发了 fallback 切换） |

### Langfuse 真云回捞（trace `d9a49a30...`）

6 个观测，完整 agent loop 链路：

| 类型 | 名称 | model | usage_details | parent |
| --- | --- | --- | --- | --- |
| SPAN | `agent-run`（根） | — | — | — |
| SPAN | `context-build` | — | — | agent-run |
| GENERATION | `model-call` | deepseek-v4-flash-0731 | {input:328, output:61, total:389} | agent-run |
| TOOL | `add` | — | — | agent-run |
| SPAN | `context-build` | — | — | agent-run |
| GENERATION | `model-call`（fallback） | deepseek-v4-flash-0731 | {input:303, output:101, total:404} | agent-run |

- trace.name = `agent-run`、trace.session_id = `70a7eb2e...`（D5 ID 映射正确）
- trace.metadata = `run_id, agent_id, git_commit=86adedc, session_id, usage_total`（D7 详细埋点齐全）
- 根观测 input = 用户消息、output = `根据计算结果，7 加 35 等于 42。`
- GENERATION usage 对账：389 + 404 = 793 = session `usage_total.total_tokens` ✓
- fallback 切换在第二轮 GENERATION metadata 里（fallback_from / fallback_to / fallback_reason）
- TOOL 观测 input = {first_number, second_number}、output = `ok`

### Best-practices 审计（对照官方 checklist，逐条）

| # | 检查项 | 结果 |
| --- | --- | --- |
| 1 | 一个 trace = 一个自包含工作单元 | ✅ |
| 2 | session_id 正确（多轮分组） | ✅ |
| 3 | trace/observation 名 verb-first 低基数 | ✅ |
| 4 | 每个 LLM 调用是 `generation` 类型 | ✅ |
| 5 | 工具调用是 `tool` 类型 | ✅ |
| 6 | agent loop 逐次 generation + tool 交错（不折叠） | ✅ |
| 7 | 工具观测嵌套在 agent/span 下 | ✅ |
| 8 | generation 有 model + usage_details | ✅ |
| 9 | usage_details bucket 互斥（input/output/total） | ✅ |
| 10 | 根观测有可读 input/output | ✅ |
| 11 | metadata 放运行上下文 | ✅ |
| 12 | flush 在短生命周期进程退出前调用 | ✅ |
| 13 | 手动 start_observation 配 .end() | ✅ |

### 发现的 Gap（D7 后续批次——2026-09-07 复审）

| Gap | 严重度 | 状态 | 处置 |
| --- | --- | --- | --- |
| environment=`default` | 中 | ✅ 已修（D7 批） | `LANGFUSE_TRACING_ENVIRONMENT`（Settings 缺省 `development`）经 Sink factory 透传到 SDK init |
| release=None | 低 | ✅ 已修（D7 批） | `LANGFUSE_RELEASE`（Settings 空=不塞，SDK 自决）经 Sink factory 透传到 SDK init |
| cost_details 为空 | 低 | ⏳ 云端配置项（非代码） | 在 Langfuse 项目设置定义模型定价或上传 cost_details——代码侧不消费成本字段 |
| user_id=None | 低 | 📌 DEFER web 场景 | 单用户 CLI 可接受；web 多用户接入时在 Sink 层加 user_id 入参 |
| 第一轮 generation output=None | 低 | ✅ 已修（D7 批） | `RunTracer.model_call_completed` 接受 `tool_call_names`；空 content + 有 tool_calls 时写 `<tool_calls: …>` 标记让观测层可读 |

### 修复的 bug

真实模型 smoke 首次触发暴露了 `evaluation/smoke.py` 的 fallback 构建错误：

- **根因**：`ModelConfig` 字段名 `model_name` 被误写为 `name`，且缺 `temperature` 参数、`api_key` 传了 SecretStr 而非明文——手动重建 fallback 的整段代码与 `ModelConfig` 真实签名不匹配。
- **为何此前未暴露**：所有 smoke 测试都用 `runtime_factory` 注入绕过了真实构建路径；真实模型调用是手动车道，此前从未真跑过。
- **修复**：删掉手动重建 fallback 的重复代码，直接消费 `model_config.fallback`（`ModelConfig.from_settings` 已解析两级链）。
- **回归测试**：`test_smoke_builds_runtime_with_fallback_config`——monkeypatch `create_chat_model` 返回 ScriptedModel（不烧 token），强制走完 fallback 构建分支。
- **验证**：1176 passed（+1 新增）、ruff 全绿。
