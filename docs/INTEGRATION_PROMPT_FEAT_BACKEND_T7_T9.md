# 集成提示词：feat/backend → main（T7 #137 + T8 #138 + T9 #139）

> **分支**：`feat/backend`
> **Worktree**：`D:\intelligence-agent-backend`
> **HEAD**：`c438a1e`（feat(#139): Langfuse turn_index 埋点）
> **main HEAD**：需 `git fetch origin && git log origin/main --oneline -1` 确认
> **改动范围**：T7 会话级模型切换 + Fork API/CLI + T8 崩溃恢复 + T9 Langfuse turn_index

---

## 1. 本次交付内容

### T7 #137 — 会话级模型切换 + Fork API/CLI 接线（commit `ae553ad` + `d227a39`）

- **模型切换**：`POST /api/sessions/{id}/model` body `{provider, model_id}` → 200 `{status:"changed",provider,model_id}`
- **事件**：`model/changed`（data: `from_provider`/`from_model_id`/`to_provider`/`to_model_id`）
- **Fork**：`POST /api/sessions/{id}/forks` body `{from_seq}` → 200 `{session_id, from_seq}`
- **CLI**：`demo/live_agent.py` 的 `/model`、`/resume`、`/fork [from_seq]` 从占位改为真实接线
- **寻址收敛**：`find_catalog_entry()` 两遍匹配（条目名精确优先于 `model_name`，provider 必须一致）；`resolve_model_target()` 返回 `ModelTarget`
- **续聊追加不写 resumed**：新增 `Session.append_event()`（只 append，不修复 dangling，不写 `session/resumed`）
- **旁路追加走 live 聚合**：queue/steer/模型切换的追加优先用「在途 run 持有的 Session」
- **生成物**：`scripts/gen_event_types.py` 重新生成 `web/src/generated/event-types.ts`

### T8 #138 — 崩溃恢复：run/interrupted + Ledger reconcile（commit `ccebf9a`）

- **新事件**：`RUN_INTERRUPTED = "run/interrupted"`（信封带 `run_id`/`step_id`，data 带 `interrupted_seq` + `reason="process_restart"`）
- **单一事实源**：`RUN_TERMINAL_TYPES` frozenset（completed/failed/interrupted），fork 边界校验、中断检测、replay 都引用它
- **崩溃扫描**：`scan_interrupted_sessions()` 检测无终态 run → 补记 `run/interrupted` → 强制跑 `RecoveryCoordinator`（Ledger-first reconcile）
- **UNKNOWN 安全拒绝**：`ReconcileRequired(RecoveryError)` — UNKNOWN 工具调用无 `ReconcileCallback` 时安全拒绝，不伪造结果、不盲重跑（不变量 #14）
- **续跑守卫**：`resume_and_launch` 检测悬空 tool_call / 无终态 run 时走 `recover()` 而非 `Session.resume` 的 dangling 兜底
- **HTTP 守卫**：POST `/messages` 和 `/resume` 捕获 `RecoveryConflict` → 409（拒绝伪造「结果未知」）
- **扫描归属**：长驻会话宿主（web lifespan），CLI 子命令不扫描（单进程假设：在途 run 只存在于持有它的进程内存中）
- **同步 I/O 下放线程**：`anyio.to_thread.run_sync` 包裹 JSONL 读写

### T9 #139 — Langfuse turn_index 埋点（commit `c438a1e`）

- **turn_index**：`Session.begin_run()` 返回 `(run_id, turn_index)` 并在 `RUN_STARTED` 事件 data 里写入 `turn_index`（1-based，该 session 里第几个 run）
- **trace metadata**：`RunTracer` 接受 `turn_index` 参数并放入 trace metadata，供 Langfuse UI 按 `session_id` 过滤时区分「第 N 轮」

---

## 2. 测试结果

| 项目 | 结果 |
|---|---|
| ruff check | All checks passed |
| 全量 pytest | **1485 passed / 9 skipped / 0 failed** |
| 新增测试 | `tests/session/test_model_change.py`（26）、`tests/web/test_web_model_fork.py`（11）、`tests/model/test_model_catalog.py::TestFindCatalogEntry`（5）、`tests/recovery/test_scan_interrupted.py`（11）、`tests/session/test_fork.py::test_fork_from_interrupted_run_prefix`、`tests/web/test_web_multiturn.py::TestCrashReconcileGuard`（2）、`tests/session/test_session.py::test_begin_run_increments_turn_index`、`tests/observability/test_tracer.py::test_turn_index_passed_to_trace_metadata` |

---

## 3. 关键文件清单

### 源码（src/agent_harness/）

| 文件 | 改动概述 |
|---|---|
| `session/event.py` | +`RUN_INTERRUPTED`、+`RUN_TERMINAL_TYPES` frozenset |
| `session/session.py` | `begin_run()` 返回元组 `(run_id, turn_index)`；`append_event()` 加 `run_id`/`agent_id`/`step_id` kwargs |
| `session/service.py` | `resume_and_launch` 崩溃守卫；`scan_interrupted()` 方法；`change_model()`；`fork()` |
| `session/fork.py` | 终态检查改用 `RUN_TERMINAL_TYPES` |
| `session/interrupt.py` | **新文件**：`detect_unterminated_runs()` 纯投影检测 |
| `recovery/scan.py` | **新文件**：`scan_interrupted_sessions()` 标记中断 → 强制 Ledger reconcile |
| `recovery/coordinator.py` | +`ReconcileRequired(RecoveryError)` 异常类 |
| `recovery/__init__.py` | 导出 `InterruptionScanResult`、`ScanRecovery`、`scan_interrupted_sessions` |
| `observability/tracer.py` | `RunTracer` 接受 `turn_index` 参数 |
| `agent/runtime.py` | `begin_run()` 返回元组解包；`turn_index` 传入 `RunTracer` |
| `web/app.py` | web lifespan 启动崩溃扫描；POST `/messages` 和 `/resume` 捕获 `RecoveryConflict` → 409 |
| `cli.py` | 移除 CLI 崩溃扫描（单进程假设） |

### 测试（tests/）

| 文件 | 改动概述 |
|---|---|
| `recovery/test_scan_interrupted.py` | **新文件**：11 tests（detection cases, mark+reconcile, idempotent, completed untouched, UNKNOWN→needs_manual_reconcile, terminal backfill, real subprocess kill + resume） |
| `recovery/_crash_run_child.py` | **新文件**：subprocess writes `Session.start` → `begin_run` → user/message → tool/call, prints READY, `os._exit(9)` |
| `session/test_model_change.py` | **新文件**：26 tests |
| `session/test_fork.py` | +`test_fork_from_interrupted_run_prefix` |
| `session/test_session.py` | +`test_begin_run_increments_turn_index` |
| `web/test_web_model_fork.py` | **新文件**：11 tests |
| `web/test_web_multiturn.py` | +`TestCrashReconcileGuard`（2 tests） |
| `observability/test_tracer.py` | +`test_turn_index_passed_to_trace_metadata` |

### 生成物

| 文件 | 改动概述 |
|---|---|
| `web/src/generated/event-types.ts` | 重新生成（+`MODEL_CHANGED: 'model/changed'`、+`RUN_INTERRUPTED: 'run/interrupted'`） |

### 文档

| 文件 | 改动概述 |
|---|---|
| `docs/PHASE_STATUS.md` | T7/T8 进度记录 |
| `docs/integration/PRD_PHASE_MULTITURN_TOTAL.md` | §2.5 as-built 注（扫描归属、续跑守卫、Fork 边界） |
| `docs/integration/PRD_PHASE_MULTITURN_FRONTEND.md` | §6 崩溃恢复前端契约 |
| `CONTEXT.md` | `run/interrupted` 术语、Run 边界更新 |
| `AGENTS.md` | §16 SDD 长任务工作流协议（防指令漂移） |

---

## 4. 关单状态

| Ticket | 状态 | 说明 |
|---|---|---|
| #137 T7 模型切换 + Fork | ✅ 已关单 | 后端完成；前端 UI 部分由前端 ticket 实现 |
| #138 T8 崩溃恢复 | ✅ 已关单 | 后端完成；前端显示中断提示 + 继续/重发/忽略按钮由前端 ticket 实现 |
| #139 T9 Langfuse + DoD | ✅ 已关单 | turn_index 埋点完成；长期记忆验证通过；DoD 全量回归 green |

---

## 5. 架构审查结论

对 `feat/backend` 做了架构深化扫描（`/improve-codebase-architecture`），发现 3 个 Strong 候选、1 个 Worth exploring、1 个 Speculative：

1. **`_drive` 分解**（Strong）— 632 行 generator；建议提取 `RunContext` value object 并合并 cancel/failure 臂
2. **`SessionService` 拆分**（Strong）— 1228 行 god object；建议沿 seam 线拆分（lifecycle/approval/model-switch/recovery）
3. **Recovery 流程整合**（Strong）— `scan.py` 是 `RecoveryCoordinator.recover()` 的薄包装；建议 fold into coordinator 或 service
4. **统一 dangling/run projection**（Worth exploring）— 单次扫描同时产出 dangling + unterminated runs
5. **Handler boilerplate**（Speculative）— Domain-exception-to-HTTP middleware

这些都是 out-of-scope 重构（§8 Scope Lock），不影响本次集成。

---

## 6. 集成建议

1. `git fetch origin`
2. `git merge-base origin/main feat/backend` 确认拓扑
3. `git diff main...feat/backend --stat` 检查改动规模
4. 正向 `--no-ff` merge（如零冲突）或先回后正（如有冲突）
5. 合入后在 `D:\intelligence-agent` 启动完整项目验证前后端集成正常
6. 最后 `git push origin main`

**注意**：`web/src/generated/event-types.ts` 是生成物，合入后需确认前端 worktree 同步到最新版本。
