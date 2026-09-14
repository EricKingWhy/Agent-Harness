# Phase 5 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend-c` 的 Phase 5 批次（permission 三档 + 交互式审批 + 最小 resume + amend 三字段 no-op）合入 `main` 并完成验证
> **写于**：2026-09-07
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏（`.env` 值不进任何输出/提交）；每次合并动作前确认 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）；每个需批准动作单独显式确认（§14.11）

---

## 0. 机器现状

| 路径 | 分支 | 角色 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | 集成主战场（Phase 16 + v1.0.0 已就位） |
| `D:\intelligence-agent-backend` | `feat/backend-c` | Phase 5 施工区 |

### 起点（已核对）

```
merge-base(main, feat/backend-c) = a9fae2b09cb223abc7119b06487c75816f485cba   ← Phase 2 commit
main HEAD                       = 98e3cc17c58d0ab7b93dd7ec30252a1b4e6baddd
feat/backend-c HEAD             = c960be24345e9eda3d228d0f53ce068ac52dbf3d
```

**关键事实**：main 自 Phase 2 之后又走了 **18 个 commit**（Phase 16 全量收尾 + v1.0.0 release + `dev.sh` + ADR-0019-phase16 等）。Phase 5 只在 `a9fae2b` 之上加了 **1 个 commit**（`c960be2`）。**这次合并不是 fast-forward**——main 已显著领先。

### Phase 5 唯一提交内容（commit `c960be2`，16 files +854/-32）

| 类别 | 文件 | 改动摘要 |
| --- | --- | --- |
| 契约 | `src/agent_harness/session/event.py` | 新增 `TOOL_APPROVAL_REQUESTED = "tool/approval-requested"` 事件类型（durable） |
| 契约 | `src/agent_harness/tooling/approval.py` | `ApprovalCallback` 类型从 `Callable[..., ApprovalResponse]` 改成 `Callable[..., Awaitable[ApprovalResponse]]`（同步 → async，**破坏性类型变更**，但唯一执行点 `executor.py:699` 已同步迁移） |
| 核心运行时 | `src/agent_harness/tooling/executor.py` | `_check_approval` → `async def`；两处调用点改 `await` |
| 新模块 | `src/agent_harness/tooling/approval_queue.py` | **新增** `PendingApprovalQueue`（session 级，`asyncio.Future` 驱动：register/wait_for/resolve） |
| 装配 | `src/agent_harness/assembly.py` | `build_runtime` 签名加 `permission_mode` / `auto_approve`（deprecated alias）/ `approval_callback`（已是 async）+ 三个 amend no-op 字段（reasoning_effort/agent_profile/context_providers，各记一条 INFO 日志后忽略） |
| Web | `src/agent_harness/web/app.py` | `CreateSessionRequest` 加 `permission_mode` 三档 + 三 amend 字段（带 validator）+ 保留 `auto_approve` alias；新增 `ApproveRequest`/`ResumeRequest` schema；`/approve` 端点从 seam 变真功能（resolve queue）；新增 `/resume` 端点（续跑已终结 session） |
| 契约前端 | `web/src/generated/event-types.ts` | `gen_event_types.py` 重生成，加 `TOOL_APPROVAL_REQUESTED` |
| SDD 文档 | `docs/spec/Observable_Agent_Workspace_SDD/03_RUNTIME_EVENT_CONTRACT.md` | 追加 Phase 5 staged session controls 段（三 amend 字段，标 `phase: staged`） |
| SDD 文档 | `docs/spec/Observable_Agent_Workspace_SDD/08_DECISION_LOG.md` | 追加 **ADR-0019**（Stage Composer controls before runtime consumption）⚠️ **编号与 main 撞车，见冲突处理** |
| 测试 | `tests/web/test_web_phase5_permission.py`（新）+ `tests/web/test_web_phase5_approval.py`（新） | +10 测试（6 permission routing + 4 interactive approval） |
| 测试 | `tests/test_assembly.py`、`tests/tooling/test_approval_gate.py`、`tests/integration/_kill_child.py`、`tests/mcp_client/test_gate.py`、`tests/session/test_event_store.py` | callback 同步→async 迁移 + EVENT_TYPES 期望集补 `tool/approval-requested` |

### Phase 5 不变量守住

- **不动 SSE 既有字段顺序**（`tool/approval-requested` 是新类型，不改既有事件）
- **`permission_mode` 是审批阈值，不是硬墙**：`read-only` 意为「写/危险工具需审批」而非「禁止」；硬墙语义留后续 ADR
- **三个 amend 字段诚实 no-op**：`build_runtime` 收到后只记 INFO 日志（明确标注 `received but not yet consumed by runtime`），运行时不消费
- **`auto_approve` 完整向后兼容**：只传 `auto_approve=true` 旧行为不变；`permission_mode` 与 `auto_approve` 同传时前者优先
- **ApprovalCallback async 化全链路迁移**：全仓唯一执行点（`executor.py:699`）+ 4 个测试注入点全部 `async def`
- **不孤儿 session**：交互式审批 callback 用 `session_holder` dict 闭包延迟注入，`Session.start` 仍发生在 `build_runtime` 之后
- **resume 是续跑，不是精确恢复**：追加 user_input 续接对话，不做 Operation Ledger 幂等重放
- **未触及 AgentRuntime / RunManager 核心逻辑**

### 新依赖 / env

- **无新 Python 依赖**（未引入新第三方库）
- **无新 env**（复用既有 `Settings`）

---

## A. 预检查

```bash
# 1. 拉最新远端
git -C D:\intelligence-agent fetch origin --prune

# 2. 确认 worktree / branch 映射（§14.2）
git worktree list --porcelain
git -C D:\intelligence-agent branch --show-current          # → main
git -C D:\intelligence-agent-backend branch --show-current  # → feat/backend-c

# 3. 确认两侧工作树状态
git -C D:\intelligence-agent status --short               # 必须 clean（集成的起点要稳）
git -C D:\intelligence-agent-backend status --short       # 必须 clean（Phase 5 已 commit）

# 4. 复核起点（必须与上文 §0 一致）
git -C D:\intelligence-agent rev-parse main                                              # → 98e3cc17…
git -C D:\intelligence-agent-backend rev-parse feat/backend-c                           # → c960be24…
git -C D:\intelligence-agent merge-base main feat/backend-c                             # → a9fae2b0…
git -C D:\intelligence-agent log --oneline a9fae2b..main                                # 18 commits（Phase 16 + v1.0.0 + dev.sh …）
git -C D:\intelligence-agent-backend log --oneline a9fae2b..feat/backend-c              # 1 commit（c960be2 Phase 5）
```

**预期**：feat/backend-c 工作树干净；main 工作树干净；merge-base = `a9fae2b`；两侧分支映射无误。

---

## B. 先回后正 + 合入（§14.6）

> ⚠️ 这次合并**不是 fast-forward**。按 AGENTS §14.6「先回后正」：先在 feature worktree 上合 main 暴露冲突，确认稳定后再正合入 main。

### B.1 先回：在 backend worktree 上合 main（暴露冲突）

```bash
git -C D:\intelligence-agent-backend merge origin/main -m "integrate main into feat/backend-c before Phase 5 upstream merge"
```

**冲突预测**：

| 文件 | 双侧改动 | 预期 | 处理 |
| --- | --- | --- | --- |
| `tests/integration/_kill_child.py` | main：第 45-50 行附近（`WorkspaceRegistry(backend=config.get(...))` 让 sandbox backend 可配置）；feat/backend-c：第 34-40 行（新增 `_approve_all` async 辅助）+ 第 99 行（`approval_callback=_approve_all` 替换同步 lambda） | **大概率干净自动合并**（行段不重叠） | 若干净 → 直接进入下一步；若报冲突 → 见下方语义并集方案 |

**`_kill_child.py` 若冲突的并集方案**（两边语义都保留，不机械取 ours/theirs）：
```python
# —— feat/backend-c 侧（保留）——
from agent_harness.tooling.approval import ApprovalRequest
async def _approve_all(_req: ApprovalRequest) -> ApprovalResponse:
    """bash 是 DANGER 级：需要审批 callback 显式放行。"""
    return ApprovalResponse(approved=True)

# —— main 侧（保留）——
async def main() -> None:
    ...
    backend = config.get("backend", "local")
    workspaces = WorkspaceRegistry(root / "ws", backend=backend)
    ...

# —— feat/backend-c 侧（保留）——
        approval_callback=_approve_all,
```
两边改动在不同函数/不同行，**没有任何语义重叠**——async 化是 ApprovalCallback 协议迁移，`backend=config.get(...)` 是 sandbox 配置透传。最终代码同时包含两者即可。

### B.2 ⚠️ ADR-0019 编号撞车（**不是 git 冲突，是语义冲突**）

**事实**：
- main 已占用 **ADR-0019**：`docs/adr/0019-phase16-final-full-e2e.md`（已合入并发布 v1.0.0）
- feat/backend-c 的 `docs/spec/Observable_Agent_Workspace_SDD/08_DECISION_LOG.md` 追加了 **ADR-0019 — Stage Composer controls before runtime consumption**

**这两个是不同文件**，git 不会报冲突（main 没改 `08_DECISION_LOG.md`，feat/backend-c 没改 `docs/adr/`）。但**编号撞车**必须人工修正：

**处理（在 B.1 merge 完成后、commit 前）**：
1. 打开 `docs/spec/Observable_Agent_Workspace_SDD/08_DECISION_LOG.md`，把我那条 `### ADR-0019 — Stage Composer controls before runtime consumption` 改成 `### ADR-0020 — Stage Composer controls before runtime consumption`
2. 全仓搜 `ADR-0019` 出现处，凡指 Phase 5 那条的引用一并改成 ADR-0020（main 的 ADR-0019 指 phase16，保留不动）
3. 若 main 上已有 ADR-0020 占位 → 顺延到 ADR-0021，以此类推（先 `git -C D:\intelligence-agent log -- docs/adr/` 看最新编号）
4. **不要**把 Phase 5 那条 ADR 拆成独立的 `docs/adr/0020-*.md` 文件——它原本就记录在 SDD 包的 decision log 里，保持原结构，只改编号

**这是文档编号修订，不是代码改动**，可以直接在 main 侧工作树修（不属于 backend worktree 范畴）。

### B.3 正合入 main

```bash
# 回到 main worktree
git -C D:\intelligence-agent merge --no-ff feat/backend-c -m "Merge feat/backend-c: Phase 5——permission 三档 + 交互式审批 + 最小 resume + amend 三字段 no-op（SDD 06 Phase 5 + 03 amend）"
```

**`--no-ff` 必需**：保留 Phase 5 的分支拓扑，便于追溯集成点。

---

## C. 验证 Gate（main 侧为准）

```bash
cd D:\intelligence-agent
uv sync                              # 无新依赖，幂等同步
uv run pytest -q                     # 基线核实见下
uv run ruff check src/ tests/        # 必须清洁
git diff --check                     # 无 whitespace / conflict-marker 残留
```

### 测试基线

- **main 集成前**（`98e3cc1`）：Phase 16 Gate 全绿，约 **1210 passed / 9 skipped / 27 deselected**（以集成前实际跑一遍为准，记下数字）
- **Phase 5 新增**：+10 测试（`test_web_phase5_permission.py` 6 + `test_web_phase5_approval.py` 4）
- **集成后预期**：约 **1220 passed**（±个位数波动不得新增失败）

**关注点**：
- `tests/evaluation/test_eval_skeleton.py` 的 3 个 langfuse 云上传测试在当前机器失败（`ModuleNotFoundError: No module named 'langfuse'`）——这是 **pre-existing** 状态（集成前后都失败），不算回归。
- `tests/session/test_event_store.py::test_all_event_types_registered` 已把 `tool/approval-requested` 加进期望集，**不会**因为新事件类型而失败。
- 若 `_kill_child.py` 自动合并干净但 Kill 测试失败 → 检查合并后 async `_approve_all` 与 main 的 `backend=config.get(...)` 是否在同一文件里都保留（B.1 语义并集未丢一侧）。
- 若 `test_assembly.py` 或 `test_approval_gate.py` 失败 → 检查 callback 是否全链路 `async def`（Phase 5 已迁，合并不应回退）。

### 可选冒烟（非合入前提）

```bash
uv run python -c "
from agent_harness.web.app import create_app
from agent_harness.config import Settings
from fastapi.testclient import TestClient
app = create_app(Settings(_env_file=None, model_api_key='sk-test', enable_cors=False))
c = TestClient(app)
# Phase 5 路由核对
r = c.post('/api/sessions', json={'permission_mode': 'read-only', 'task': 'ping'})
print('status:', r.status_code, 'session_id:', r.json().get('session_id'))
r2 = c.post('/api/sessions', json={'permission_mode': 'bogus', 'task': 'ping'})
print('invalid mode →', r2.status_code)  # 期望 422
r3 = c.post('/api/sessions', json={'auto_approve': True, 'task': 'ping'})
print('legacy auto_approve →', r3.status_code)  # 期望 200（向后兼容）
"
```
预期：合法 mode 200；非法 mode 422；legacy `auto_approve` 200。

---

## D. Push 与收尾

1. **`docs/PHASE_STATUS.md` 追加 Phase 5 集成记录**（main 侧已改过这文件，feat/backend-c 没动 → 合并后直接在 main 工作树追加即可，不是冲突）：
   - 验证数字（pytest passed/skipped/deselected）
   - 合并方向（`feat/backend-c` → `main`，merge commit hash）
   - `_kill_child.py` 是否冲突 + 处理方式
   - ADR-0019 → ADR-0020 重编号记录
   - 集成时间

2. 全绿 + 文档更新后，**最后一步**（需用户明确批准，§14.4）：
   ```bash
   git -C D:\intelligence-agent push origin main
   ```

3. 向用户报告（§11 交付清单）：
   - **完成什么**：Phase 5（permission 三档 + 交互式审批 + 最小 resume + amend 三字段 no-op）合入 main
   - **改了哪些文件**：16 files +854/-32（Phase 5 commit）+ `_kill_child.py` 合并修订（如有）+ `08_DECISION_LOG.md` ADR 重编号 + `PHASE_STATUS.md` 追加
   - **测试结果**：pytest passed 数 / ruff 清洁
   - **commit 区间**：`a9fae2b..c960be2`（1 commit Phase 5）+ merge commit
   - **冲突情况**：`_kill_child.py`（如有）+ ADR-0019 重编号
   - **遗留项**（见下）

### 遗留项（交接给后续 Phase）

- **`reasoning_effort` 运行时落地**：逐家验证 provider 支持（deepseek-reasoner 无此参数、glm 思考模型无开关）→ 独立批次
- **`agent_profile` 运行时落地**：接通 AgentFactory + tool_scope 收窄 + system_prompt 注入 → 独立批次
- **`context_providers` 运行时落地**：加枚举端点 + 会话级筛选 → 独立批次
- **硬墙 `permission_mode`**（真正禁止而非审批）：当前是审批阈值，硬墙语义留后续 ADR
- **精确恢复**（中断点续执行）：最小 resume 只做续跑，Operation Ledger 幂等重放留后续
- **前端消费**：`tool/approval-requested` 事件契约已就位，前端在 Phase 5/f32 做交互审批 UI；`permission_mode` 路由契约已就位，前端 Composer 做选档 UI

---

## E. 异常处理

- **`_kill_child.py` 冲突**：停下报告用户（§14.7）。按 B.1 语义并集方案处理——async `_approve_all` 与 `backend=config.get(...)` 在不同函数，两者都保留。**禁止 `git checkout --ours/--theirs`**。
- **ADR-0019 重编号后发现 main 已有 ADR-0020**：顺延到下一个空号（ADR-0021 …），不挤占既有编号。
- **测试失败**：
  - 若是新增的 10 个 Phase 5 测试失败 → Phase 5 实现问题，回到 `D:\intelligence-agent-backend` 修复，不合入。
  - 若是既有测试失败 → 对比 main 集成前的运行结果，确认是否 pre-existing（langfuse 那 3 个是已知 pre-existing）。若是新引入回归，停下报告。
  - 若是 `_kill_child.py` 相关的 Kill 测试失败 → 检查 async migration 是否被合并丢失（B.1 并集未保留 `_approve_all` 或 `backend=config.get(...)` 任一侧）。
- **ruff 报错**：回到 backend worktree 修复，不在 main 侧直接改代码。
- **push 失败**（网络/权限）：如实报告，不自动重试到 force-push（§14.4 红线）。
- **任何说不清的冲突**：立即停下，逐文件分析 main 与 feat/backend-c 各自动机，推荐语义并集方案，等待用户批准。

---

## 附：本批次 Scope Lock 清单（合入前最后核对）

**做了**：
- ✅ `permission_mode` 三档替换 `auto_approve`（保留 deprecated alias 完整向后兼容）
- ✅ `ApprovalCallback` 同步→async 全链路迁移（类型 + 唯一执行点 + 4 个测试注入点）
- ✅ `PendingApprovalQueue`（session 级，asyncio.Future 驱动）
- ✅ `tool/approval-requested` durable 事件类型 + EVENT_TYPES 注册 + 前端契约 artifact 重生成
- ✅ `/approve` 端点从 seam 变真功能（登记 + resolve + 404/409 语义）
- ✅ `/resume` 端点（续跑已终结 session，409 拒绝在途 run）
- ✅ 三 amend 字段（reasoning_effort/agent_profile/context_providers）契约接收 + 运行时 no-op（INFO 日志诚实标注）
- ✅ SDD `03_RUNTIME_EVENT_CONTRACT.md` 契约修订（Phase 5 staged 段）
- ✅ ADR 记录（编号待重排，见 §B.2）
- ✅ 10 新测试全绿 + 既有测试不破 + ruff 清洁

**没做（推迟）**：
- ❌ 三 amend 字段的运行时落地（各为独立后续批次）
- ❌ 硬墙 `permission_mode`（真正禁止语义，留 ADR）
- ❌ 精确恢复（Operation Ledger 幂等重放）
- ❌ AgentRuntime / RunManager / ToolExecutor 核心算法改动（只做协议 async 化，不动调度/重试逻辑）
- ❌ SSE → WebSocket 迁移
- ❌ 前端 UI（后端契约就位即可）
