# 集成提示词 — 架构深化候选 1 + 2 + 3（feat/backend）

> 给集成 AI 的可直接粘贴提示词。配套阅读：`docs/PHASE_STATUS.md` 2026-09-10 条目。

---

## 0. 前置状态

- **分支**：`feat/backend`
- **基线**：`977b319`（= 当前 `main` tip）
- **范围**：3 个 commit（候选 1 / 候选 2 / 候选 3）
- **性质**：**纯结构重构 + 文档**，**零行为变化**

---

## 1. 变更清单

### 候选 1 — `_TerminalContext` 收拢 `_drive` 两个终态臂

**文件**：`src/agent_harness/agent/runtime.py`（1101 → 1135 行）

- 新增 `_TerminalContext` dataclass（`_RunFinalizer` 之后），承载取消臂 / 异常臂共享的收尾上下文（`session` / `run_id` / `steps` / `terminal` / `streamer` / `model_coord` / `tracer` / `ctx_span` / `generation`）。
- 两个方法：
  - `interrupt_streams()` —— streamer 中断 + `drain_transitions()` 落 `MODEL_FALLBACK` 事件；**返回**追加的事件列表。
  - `close_observability(*, error_type, reason, cancelled)` —— `model/failed` 事件 + `ctx_span` / `generation` / tracer 收口；**返回**追加的事件列表。
- **关键设计**：两方法返回事件列表，由调用方决定 yield 策略——
  - 异常臂：`for streamed in ctx.interrupt_streams(): yield to_agent_event(streamed)`
  - 取消臂：**丢弃返回值，不 yield**（`GeneratorExit` / `CancelledError` 下生成器正在关闭，禁止产出）
  - 这正是两臂原本唯一的差异，收拢时必须保住。
- `_drive`：622 → 598 行。

### 候选 2 — 拆分 `SessionService` god object

**主文件**：`src/agent_harness/session/service.py`（1228 → 996 行）

**新增三个兄弟模块**：

| 新文件 | 行数 | 内容 |
|---|---|---|
| `src/agent_harness/session/errors.py` | 66 | 14 个领域异常类（`SessionServiceError` 及子类）逐字搬移 |
| `src/agent_harness/session/model_switch.py` | 219 | `current_model_selection` / `amend_with_session_model` / `default_model_id` / `is_default_selection` / `ModelTarget` / `resolve_model_target` / `ModelChange` / `append_model_change` / `inherit_parent_model` / `assert_model_resolvable` |
| `src/agent_harness/session/approval.py` | 150 | `build_approval_callback`（三种路由）+ `InteractiveCallbackHolder`（延迟绑定容器） |

**兼容性保证（集成时必须核对）**：

1. `SessionService` 保留为门面，`service.py` 通过 `__all__` + 别名重新导出全部公开符号 →
   `from agent_harness.session.service import SessionNotFound` 等**所有既有导入路径不变**。
2. 私有名引用不变：
   - `service.py` 内 `_InteractiveCallbackHolder = InteractiveCallbackHolder`（别名）
   - 测试直接调用的 `SessionService._validate_workspace_name` 与 `SessionService._build_approval_callback` 签名与行为不变
3. **`build_runtime` 必须以模块级名字驻留 `service.py`**——
   `tests/web/test_web_phase5_permission.py:39` 执行
   `monkeypatch.setattr(service_module, "build_runtime", _fake_build)`。
   **迁移时不可把该 import 删掉或改成局部导入。**
4. `_build_approval_callback` 现在是薄委托，把原先对 `self._state` 的两处依赖
   （`approval_queues` 字典 / `settings.approval_timeout_seconds`）显式传参。

### 候选 3 — 启动扫描单进程假设提升为架构约束

**决策**：**不合并** `recovery/scan.py` 进 `RecoveryCoordinator`。

理由：`scan.py` 不是薄包装——它含独立编排（遍历全部 session / 标记中断 / 三分类结论 / 单会话失败不阻断），与 `recover()`（单 session 8 步编排）是**不同职责层次**；合并会降低内聚、让 coordinator 更 god。

**改为文档化**：

- `CONTEXT.md` 新增 glossary 条目 **`StartupInterruptionScan`**，含：
  - 「先标记中断，再 reconcile」固定顺序及不变量 #12 / #14 依据
  - **单进程假设约束**：只能在「持有该会话的进程」启动时扫描一次（唯一调用点 = web `lifespan`）
  - **安全规则**：禁止在与长驻服务并发的短命命令（CLI run / 子命令）里扫描——会把别的进程在途 run 误标中断 → 两边各自推算 seq 撞号（违反不变量 #22）
  - 多进程 / 多 worker 需跨进程 run lease，属后续 Phase
- `src/agent_harness/recovery/scan.py` 模块 docstring 增加与该条目的互链。

---

## 2. 验收证据

| 项目 | 结果 |
|---|---|
| `ruff check .` | ✅ All checks passed |
| `tests/session/` + `tests/web/test_web_phase5_permission.py` + `tests/test_web_api.py` + `tests/test_cli_fork.py` | ✅ **247 passed / 0 failed / 0 errors** |
| 与重构前基线对比 | ✅ 数字逐字一致 |
| `git status -- tests/` | ✅ **空（测试文件零改动）** |
| 全量 `pytest tests/` | 1484 passed / 9 skipped / **1 failed** |

**关于那 1 例失败**：
`tests/web/test_web_batch51_spec_contract.py::test_approval_queue_gc_after_run_completes`
——**已知计时 flake，与本次改动无关**（隔离复跑必过）。交接手册已备案「`tests/web/test_web_stream.py` / `test_web_ws_relay.py` 在某些全量运行中存在真实服务器计时失败」；该测试同样依赖真实 HTTP 服务器 + `asyncio.sleep(0.1)` 宽限窗口。

---

## 3. 集成步骤

```bash
# 1. 切到集成 worktree 的 main
cd D:/intelligence-agent
git checkout main

# 2. 合并 feat/backend（预期快进或普通合并，无冲突）
git merge feat/backend

# 3. 门禁
uv run ruff check .
uv run pytest tests/session/ tests/web/test_web_phase5_permission.py \
              tests/test_web_api.py tests/test_cli_fork.py -q
# 期望：247 passed

# 4. 全量
uv run pytest tests/ -q
# 期望：1484+ passed / 9 skipped；如有 test_approval_queue_gc_after_run_completes
#       失败，隔离复跑确认是否 flake

# 5. 推送
git push origin main
```

---

## 4. 集成时需注意

1. **`service.py` 的 `__all__` 顺序**：ruff 规则 `RUF022` 要求 sorted；当前已满足，
   若合并时手工调整请保持排序，否则 ruff 会红。
2. **不要"顺手"把 `session/approval.py` 的 `build_approval_callback` 内联回 `service.py`**——
   它刻意把对 `self._state` 的依赖转为显式参数，这是拆分的价值所在。
3. **`session/model_switch.py` 对 `AmendOptions` 采用延迟导入**（函数内 `from ...service import AmendOptions`），
   以避免 model_switch ↔ service 循环导入。若未来把 `AmendOptions` 也移出，可去掉该延迟导入。
4. **候选 3 是文档变更**，不涉及可执行代码；但 `CONTEXT.md` 的新约束是**架构红线**，
   后续任何"在 CLI 里加启动扫描"的提案都应先对照该条目。
5. **本批未推送远程**，由集成 AI 负责 push。

---

## 5. 遗留 / 未决（Scope 外，仅报告）

- `service.py` 仍有约 996 行，`SessionService` 仍有 ~28 个方法。本轮按「零行为变化」验收标准只做了
  **低风险的模块级抽取**；进一步的方法级拆分（lifecycle / queue / lineage 等 mixin 或
  delegation）会改动 `SessionService` 的结构与 `self` 语义，超出本次 scope，未做。
- 全量测试中的真实服务器计时 flake 是既存问题，本批未处理。
