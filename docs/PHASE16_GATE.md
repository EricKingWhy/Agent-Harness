# Phase 16 — Final Full E2E Gate

> 本文件是 Phase 16「Final Full E2E」的 **Gate 证据总表** 与过程记录。
> 冻结规格来源：`docs/adr/0019-phase16-final-full-e2e.md`（grill 三轮收敛，12 项决策 D1–D12）。
> 测试载体：`tests/integration/test_phase16_gate.py`（12 个分段独立断言）+ `tests/integration/_phase16_helpers.py`（薄编排层 + fixture）。
> 工作区：`D:\intelligence-agent-phase16`，分支 `feat/phase16`。本 Gate **未 push、未 merge**——等待用户决定（§14.4 / §14.11）。

---

## 1. Gate 6 项指标逐条裁决

| # | 指标（ADR-0019 D8 精确定义） | 结果 | 证据（测试函数 + 断言） | 备注 |
| - | ---------------------------- | ---- | ----------------------- | ---- |
| G1 | **duplicate confirmed = 0**：同一 `tool_call_id` 在 Ledger 中出现多条 `SUCCEEDED` 视为重复确认；recover 后 dangling=0 且无 UNKNOWN 残留 | ✅ PASS | `test_duplicate_confirmed_side_effect_zero`：多工具部分完成 + ABANDON 审批回调，每个 operation 恰好一个终态；reconcile-required 恰好 1 条（即原本悬挂的 PENDING 被收敛为 `NEED_RECONCILE`，未升级成幽灵 SUCCEEDED）。`test_kill_restart_reconcile_continue`：recover 后 `list_for_session` 无 UNKNOWN、无重复 SUCCEEDED。 | 与 ADR-0004「Ledger 必须 reconcile」对账；遵循 §7.13 不变量。 |
| G2 | **dangling = 0**：reconcile 后所有 PENDING/RUNNING 操作要么 SUCCEEDED 要么合成 TOOL_RESULT 收敛（无悬挂） | ✅ PASS | `test_kill_restart_reconcile_continue`：kill 子进程在 bash 执行中段 `os._exit(137)`，父进程构造全新 store/ledger，`RecoveryCoordinator.recover(session_id)` 后 `dangling == 0`、无 UNKNOWN 残留。`test_critical_path_e2e`：正常路径终态无悬挂（每个 tool_call 都有配对 ToolResult）。 | Kill 注入点：`_kill_child.py` 的 `kill_hook(stage, call_id)` 在 `os._exit(137)` 之前持久化 Ledger PENDING/RUNNING。 |
| G3 | **core recovery = all-or-nothing**：恢复后 SessionStore 历史完整、WorkspaceRegistry 重新绑定、悬挂操作被合成结果收敛；否则整体标记为恢复失败 | ✅ PASS | `test_kill_restart_reconcile_continue`：recover 后断言（a）崩溃前 `crash_events` 含 1 条 TOOL_CALL、0 条 TOOL_RESULT（操作在执行中段崩溃，事件已落盘）；（b）`WorkspaceRegistry.get(session_id)` 成功重绑到原 workspace 目录；（c）`detect_dangling(recovered.events) == []`（悬挂操作被合成 TOOL_RESULT 收敛）；（d）Ledger 无 UNKNOWN 残留。`test_docker_sandbox_restore_after_kill`（Docker daemon 在场）：容器按 `container_name` 确定性重绑 + workspace Volume 内容跨进程保留。 | RecoveryCoordinator 八步流程被覆盖；§7.12「Checkpoint 不等于副作用恢复」在此被反向验证——纯 checkpoint 无法收敛 Ledger，必须走 reconcile。 |
| G4 | **citation validity = 格式 + KB chunk 可回捞**：引用串形如 `kb:<doc>#<chunk>`，且 `service.read_source(ref)` 能取回非空原文 | ✅ PASS | `test_research_kb_insufficient_web_citation`：KB 语料与 query 零词重叠 → `is_sufficient=False`（`top_score < 0.6`）→ 编排层转入 web 工具 → 最终答案携带 `kb:legacy-guide#0` 引用；`read_source` 取回非空 chunk 文本。`test_critical_path_e2e`：final 回复引用串符合 `<source>#<chunk>` 格式。 | ADR-0019 D8 把「引用有效」收敛为「格式 + 可回捞」两条可机械验证的子条件，规避主观语义判断。 |
| G5 | **permission violation = 显式违规被阻 + 合法调用放行**：DANGER 工具无审批回调时 `PERMISSION_DENIED`（retryable=False）；READ_ONLY 工具在同策略下放行 | ✅ PASS | `test_permission_violation_blocked`：`ToolExecutor(policy=WORKSPACE_WRITE, approval_callback=None)` + `BashTool`（DANGER）→ `PERMISSION_DENIED` / `retryable=False`；同一 executor 下 `ReadTool`（READ_ONLY）正常执行。`test_mutating_tool_ledger_recorded`：合法写操作被放行且记入 Ledger（SUCCEEDED）。 | §7.11「Sandbox / Permission 是 Runtime 边界，不靠 Prompt」在此被实证——审批回调缺失即在 Runtime 层硬阻断，模型无法绕过。 |
| G6 | **Full E2E reproducible = 薄编排层确定性**：ScriptedModel 驱动的关键路径在多次运行中产出相同事件序列与工具调用链 | ✅ PASS | `test_critical_path_e2e`：4 轮关键路径（KB→Web→Add→final）由 `ScriptedModel` 喂入固定响应序列，事件类型序列与 `tool_call_id` 配对在重跑中逐字节确定。`test_replay_reproduces_session`：`replay_command(session_id, workspace_dir=tmp_path)` 渲染冻结的工具结果，事件计数在 replay 前后不变（零副作用）。`test_eval_report_gate_metrics`：同一关键路径会话产出的可计算指标（dangling=0、引用有效、无违规、无 RUN_FAILED、≥4 MODEL_COMPLETED）在重跑中一致。 | ADR-0019 D1「薄编排层」的核心收益：把 Full E2E 从「真实模型概率链」降为「确定性脚本链」，Gate 因此可重复。真实模型 smoke 留给集成后人工验证（见 §4）。 |

**Gate 结论**：6/6 PASS，12/12 分段断言全过（含 Docker 容器恢复——daemon 在场后 `test_docker_sandbox_restore_after_kill` 从 SKIP 转 PASS，详见 §3）。

---

## 2. 分段独立断言清单（ADR-0019 D1）

12 个测试函数，每个只断言自己负责的链段——CI 信号不被跨段失败污染，维护成本与信号清晰度取得平衡（D1 取舍）。

| Ticket | 测试函数 | 段 | 状态 | 耗时 |
| ------ | -------- | -- | ---- | ---- |
| #126 T1 | `test_critical_path_e2e` | 关键路径薄编排 | ✅ | 0.13s |
| #127 T2 | `test_research_kb_insufficient_web_citation` | 研究/KB/Web/引用 | ✅ | 0.03s |
| #127 T2 | `test_permission_violation_blocked` | 权限阻断 | ✅ | 0.02s |
| #128 T3 | `test_coding_edit_test_failure_retry` | coding/edit/测试失败重试 | ✅ | 0.50s |
| #128 T3 | `test_mutating_tool_ledger_recorded` | mutating-tool Ledger 对账 | ✅ | 0.09s |
| #129 T4 | `test_kill_restart_reconcile_continue` | kill/重启/reconcile | ✅ | 0.66s |
| #129 T4 | `test_duplicate_confirmed_side_effect_zero` | 重复确认归零 | ✅ | 0.69s |
| #129 T4 | `test_docker_sandbox_restore_after_kill` | Docker 沙箱恢复 | ✅ | 6.85s |
| #130 T5 | `test_replay_reproduces_session` | replay 零副作用 | ✅ | 0.04s |
| #130 T5 | `test_fork_creates_isolated_lineage` | fork 隔离 lineage | ✅ | 0.06s |
| #130 T5 | `test_langfuse_trace_structure_complete` | Langfuse trace 结构 | ✅ | 0.05s |
| #130 T5 | `test_eval_report_gate_metrics` | Eval 报告指标可计算 | ✅ | 0.03s |

**总计**：12 passed, 0 skipped, wall clock **8.25s**（含 Docker 容器恢复 6.85s）。

---

## 3. Docker probe-gated 结果（ADR-0019 D5）

`test_docker_sandbox_restore_after_kill` 采用 `_docker_available()`（`docker.from_env().ping()` 探针）+ `pytest.mark.skipif(not _docker_available())` 的 probe-gated 模式：

- **当前宿主（首次验收）**：Docker daemon 在场（Docker Desktop 29.4.1，WSL2 后端，overlayfs）→ 探针通过 → **PASS**（6.85s）。容器按 `container_name` 确定性重绑（`DockerSandbox.ensure_started` 跨进程恢复路径），workspace Volume 内容跨进程保留。
- **daemon 缺席的宿主**：探针失败 → **SKIP**（不是 FAIL），原因字符串 `docker daemon unreachable`。
- **设计意图**（D5）：Docker 存在性是环境属性，不是被测系统的正确性属性。缺席即 skip，不掩盖；出席即真集成测试。与 Phase 4 已建立的 probe-gated 实践一致。
- **验收期发现并修复的 DockerSandbox bug**：`DockerSandbox.read_text` 对不存在的文件调用 `get_archive` 时抛 `docker.errors.NotFound`（`OSError` 子类），而非 `FileNotFoundError`。`WriteTool.execute` 读 before 内容时只捕获 `(FileNotFoundError, PermissionError)`，导致 Docker 路径下的首次写操作（文件尚不存在）被这个未捕获异常拖垮。修复：`read_text` 把 `docker.errors.NotFound` 映射成 `FileNotFoundError`（`src/agent_harness/sandbox/docker.py`）。此 bug 在 daemon 缺席时被 SKIP 掩盖，首次 daemon 在场的 Gate 才暴露——正是 D5 probe-gated 设计的价值（缺席不掩盖，出席即真测）。

---

## 4. 性能基线（ADR-0019 D11 只量不裁）

D11 的原则：性能指标在本 Phase **只记录、不设阈值门**——避免把环境敏感的 wall clock 变成 Gate 的硬裁决条件。基线如下（本机：Windows 10 x64，Python 3.13.5，Docker Desktop 29.4.1 在场）。

| 维度 | 数值 | 说明 |
| ---- | ---- | ---- |
| Gate 文件全量 wall clock | **8.25s** | 12 用例全过（含收集/teardown） |
| Docker 容器恢复 | **6.85s** | 真容器 kill → restart → reconcile（占用主要耗时） |
| 关键路径 E2E | **0.13s** | 4 轮 ScriptedModel（零网络/零 token） |
| Kill/重启/reconcile | **0.66s** | 真子进程 `os._exit(137)` + 全新 store/ledger + 8 步 recover |
| 重复确认归零 | **0.69s** | 多工具部分完成 + ABANDON + Ledger inspect |
| Coding/edit/失败重试 | **0.50s** | 4 次 bash 子进程（真 LocalSubprocessSandbox） |
| 其余 7 段 | ≤ 0.09s 各 | |

**说明**：本 Phase 的所有耗时都来自确定性 fixture，无真实模型调用。真实模型 smoke 已在 main 上单独验证一次并登记（§6），Langfuse trace 结构符合 Gate 断言。

---

## 5. 过程记录与自审发现

### 5.1 关键工程取舍

- **分段独立断言（D1）**：放弃「一个巨函数跑完整链」的写法——后者一次失败会拖垮整份 CI 信号。改为每段一个函数，互相独立，编排层共用 `_phase16_helpers.py`。
- **薄编排层（D1）**：关键路径用 `ScriptedModel` 喂固定响应序列，把 Full E2E 从概率链降为确定性链——Gate 因此可重复。真实模型覆盖由 §6 遗留项承接。
- **全 fake 进 CI（D3）**：KB（FakeKnowledgeVectorStore）/ Web（脚本化）/ 模型（ScriptedModel）/ Langfuse（FakeRecorder）全部 in-process，零网络零 token。
- **真子进程 kill（D4）**：kill 测试用真 `subprocess` 跑 `_kill_child.py`，在 bash 执行中段 `os._exit(137)`——不是 mock。父进程构造**全新**的 store/ledger，强制走 `RecoveryCoordinator.recover` 的跨进程路径（不是同进程重试）。
- **mutating tool = coding 副作用（D6）**：BashTool 写文件 + EditTool 改文件，副作用以文件系统真实持久化来对账 Ledger，不靠 mock 断言。
- **trace + report 是 Gate（D12）**：Langfuse trace 结构与 Eval 报告指标本身就是 Gate 断言对象，不只是辅助观测。

### 5.2 调试期发现与修复（已被测试固化）

1. **FakeKnowledgeVectorStore 在零词重叠时仍返回 score=0.0 命中**——不能断言 `hits == []`；改为断言 `top_score < 0.6`（即 `is_sufficient=False` 的真正根因），更贴近 KB 服务真实语义。
2. **`test_` 前缀的辅助函数被 pytest 误收集**——`test_failure_then_fix_script()` 改名为 `coding_failure_then_fix_script()`，避免空 collect 警告。
3. **Windows cmd.exe 对单引号的处理与 POSIX shell 不同**——`echo '...' > file` 在 `LocalSubprocessSandbox`（`shell=True` 经 cmd.exe）下失败；改用 `python -c "open(...).write(...)"` 跨平台写文件。
4. **`ToolExecutor.registry` 是私有属性**——`executor.registry` 取不到；改为单独 `build_coding_registry(sandbox)` 传给 AgentRuntime。
5. **JsonlSessionStore 的布局是 `<root>/<session_id>/events.jsonl`**（每会话一目录），不是 `<root>/<session_id>.jsonl`——fork/replay 测试都按正确路径断言。
6. **`DockerSandbox.teardown()` 不存在**——实际方法是 `stop()`（幂等、保留 Volume）。

### 5.3 范围边界（ADR-0019 D9）

本 Phase **不重复测**前序 Phase 已覆盖的能力单元：

- 单元级的 Tool 重试 / 调度 / 并发 → Phase 4 已覆盖；
- Sandbox 边界 / Permission 单元 → Phase 5 / 各自模块测试已覆盖；
- Langfuse 旁路故障隔离 → Phase 15 已覆盖；
- replay / fork 单元契约 → Phase 14 已覆盖。

本 Phase 只测 **链段拼起来的 Gate 指标** 是否成立——典型的「集成测试补单元测试无法发现的接口缝隙」分层。

### 5.4 不变量巡检（§7）

本 Gate 在分段断言中实证了以下架构不变量：

- §7.3（append-only typed SessionEvent）——replay 测试断言事件计数不变。
- §7.7（Tool 只有一条统一执行路径）——所有 tool 都经 `ToolExecutor.execute_batch`，包括 Bash/Edit/Read/Write/KB/Web。
- §7.11（Sandbox/Permission 是 Runtime 边界）——permission 测试在 Runtime 层硬阻断。
- §7.12（Checkpoint ≠ 副作用恢复）——kill 测试只走 Ledger reconcile，不走 checkpoint 回放。
- §7.13（Operation Ledger 必须 reconcile）——kill 测试悬挂操作被合成 TOOL_RESULT 收敛。

---

## 6. 遗留与风险

| 项 | 性质 | 处置 |
| -- | ---- | ---- |
| ~~Docker sandbox 恢复测试在本机 SKIP~~ | ✅ **已解决** | daemon 在场后 PASS（6.85s）；过程中发现并修复 `DockerSandbox.read_text` 的 `NotFound→FileNotFoundError` 映射 bug（详见 §3）。 |
| ~~真实模型 smoke 未跑~~ | ✅ **已完成** | 集成后在 main 上用 `.env` 真实网关跑一次（senseaudio / deepseek-v4-flash-0731），Langfuse jp 区回捞 trace 结构：root SPAN `agent-run` + 3× GENERATION `model-call` + 3× SPAN `context-build`，metadata 含 `session_id` / `run_id` / `agent_id`——与 Gate 断言一致（`test_langfuse_trace_structure_complete`）。trace_id 示例：`b6fb7d01fb9e9362fcea6aa1906fc644`。 |
| `.env` 密钥 | 安全边界 | 本 Gate 全程用 fake；真实 smoke 用 `.env` 密钥但密钥值不进文档/commit/输出。 |
| 未 push / 未 merge | §14.4 / §14.11 | feat/phase16 已合入 main（集成记录 commit `cefdbe1`）；main 未 push GitHub——等待用户决定。 |
| `docker` SDK 未声明为 optional-dependency | 项目层缺口（非 Phase 16 scope） | `DockerSandbox` 用 `importlib.import_module("docker")` 动态加载，但 `pyproject.toml` 的 `[project.optional-dependencies]` 没有 `sandbox` 组声明 `docker`。daemon 在场但 SDK 未装的宿主会 SKIP（探针通不过）。**建议**后续 Phase 在 pyproject 加 `sandbox = ["docker>=7"]` extras 组——不在 Phase 16 scope（§8）。 |

---

## 7. 复现命令

```bash
cd D:\intelligence-agent
uv run pytest tests/integration/test_phase16_gate.py -m integration -v
# 期望：12 passed（Docker daemon 在场）；daemon 缺席则 11 passed + 1 skipped
```

全量回归（确保本 Phase 未引入跨模块回归）：

```bash
uv run pytest -q   # 默认排除 integration/qiniu；离线全量基线见 PHASE_STATUS.md
```

---

## 8. 相关产物

- ADR：`docs/adr/0019-phase16-final-full-e2e.md`
- 术语：`CONTEXT.md`「Phase 16 / Final Full E2E」段
- 测试：`tests/integration/test_phase16_gate.py`、`tests/integration/_phase16_helpers.py`、`tests/integration/_kill_child.py`（向后兼容扩展：`backend` 字段）
- Tickets：#126（T1）、#127（T2）、#128（T3）、#129（T4）、#130（T5）
- 集成手册：`docs/INTEGRATION_PROMPT_PHASE16.md`
