# Phase 2 Composer 集成提示词（集成 AI 执行手册）

> **收件人**：集成 AI（Git Integrator 角色，AGENTS.md §14）
> **任务**：把 `feat/backend-c`（SDD 包 + Phase 2 Composer 后端支撑）合入 `main` 并完成验证
> **写于**：2026-09-07，分支 tip 以 `git -C D:\intelligence-agent-backend log -1` 为准
> **红线**：永不 force-push / rebase / reset --hard；凭证零泄漏（`.env` 值不进任何输出/提交）；每次合并动作前确认 worktree 与分支（§14.2）；冲突后立即停止自动解决（§14.7）
> **前置状态**：`feat/backend-c` 从当前 `main`（`6335066`）直接分叉，merge-base = main HEAD，预期零冲突

---

## 0. 机器现状

| 路径 | 分支 | 角色 |
| --- | --- | --- |
| `D:\intelligence-agent` | `main` | 集成主战场 |
| `D:\intelligence-agent-backend` | `feat/backend-c` | Phase 2 + SDD 施工区 |

### 内容摘要（3 提交，`main..feat/backend-c`）

1. `d91050a` docs(integration) — 载入 D7 DEFER 批 + trace_url 两份集成提示词（开局载入，纯文档）
2. `e0677b4` docs(spec) — **Observable Agent Workspace SDD 包**（10 份规格文档 + BACKEND_AUDIT.md，Phase 0 产物，冻结产品需求）
3. `9eb62a5` feat(web) — **Phase 2 Composer 后端支撑**（只读端点 + RuntimeEvent 信封，SDD 06 Phase 2）

### Phase 2 代码交付（commit `9eb62a5`，纯加法，零核心 Runtime 改动）

四个加法交付物：

| 交付物 | 端点/模块 | SDD 契约 |
| --- | --- | --- |
| 模型元数据富化 | `GET /api/models` | SDD `03` §16 `ModelOption` |
| 权限模式列表 | `GET /api/permission-modes` | SDD `03` §10 |
| 能力清单 | `GET /api/capabilities` | SDD `03` §17 `CapabilityManifest` |
| RuntimeEvent 信封 | `SessionEvent`/`AgentEvent`/SSE 三路 | SDD `03` §3 `RuntimeEvent<T>` |

**关键不变量守住**：
- SSE live 帧 / replay 帧 / JSONL 行三路同形（`schema_version` + `durability` 始终；`capability` 可选）；`test_live_and_replay_frames_same_shape` 锁定
- 旧字段 `name`/`model`/`default` 作 alias 保留（前端切换期不破）
- 未知能力位省略（契约："not guessed"），仅 deepseek/qwen/zhipu 填了已验证的 `supports_tools`
- `visibility?` 字段按计划推迟 Phase 4；交互式审批推迟 Phase 5；具体 capability 的 surfaces 声明推迟 Phase 6
- `capability` 字段当前恒 None（Phase 6 注入点，非投机泛化）

**前端影响**：**零**（纯加法，所有新字段都是 JSON 加法键；前端可开始消费但旧客户端不受影响）。SDD 文档纯产物，无代码影响。

### 新依赖 / env

- **无新 Python 依赖**（未引入新第三方库）
- **无新 env**（未新增配置项；所有改动复用既有 `Settings` 字段）

---

## A. 预检查

```bash
git -C D:\intelligence-agent fetch origin --prune
git -C D:\intelligence-agent-backend status --short   # 必须干净（Phase 2 已 commit）
git worktree list --porcelain
# 确认分支映射（§14.2）：
git -C D:\intelligence-agent branch --show-current        # → main
git -C D:\intelligence-agent-backend branch --show-current  # → feat/backend-c
# 确认起点：
git -C D:\intelligence-agent rev-parse main               # → 6335066…
git merge-base main feat/backend-c                       # → 6335066…（= main HEAD，干净分叉）
```

预期：`feat/backend-c` 工作树干净，merge-base 等于 main HEAD → 合并是 fast-forward 候选。

## B. 先回后正 + 合入（§14.6）

```bash
# 正向预演：在 feature 分支上先合 main，暴露任何冲突
git -C D:\intelligence-agent-backend merge origin/main   # 预期 "Already up to date"（merge-base = main HEAD）
# 正合入 main（--no-ff 保留分支拓扑；本例 fast-forward 也可，但 --no-ff 便于追溯集成点）
git -C D:\intelligence-agent merge --no-ff feat/backend-c -m "Merge feat/backend-c: SDD 包 + Phase 2 Composer 后端支撑——只读端点（model/permission/capability manifest）+ RuntimeEvent 信封（schema_version/durability/capability），纯加法，零核心 Runtime 改动"
```

**冲突预测**：**预期零冲突**。`feat/backend-c` 从当前 main 直接分叉，merge-base = main HEAD。若出现意外冲突（最可能 `docs/` 追加行），按 §14.7 立即停止，逐文件分析两边语义，**不得机械取 ours/theirs**。

## C. 验证 Gate（main 侧为准）

```bash
cd D:\intelligence-agent
uv sync                              # 无新依赖，幂等同步
uv run pytest -q                     # 基线：1195 passed / 9 skipped / 27 deselected（main 现状），零失败
                                     # 集成后预期 +15 测试（11 event envelope + 4 phase2 endpoints）
                                     # → 约 1210 passed（±个位数波动不得失败）
uv run ruff check src/ tests/        # 清洁（Phase 2 已过 ruff）
git diff --check                     # 无 whitespace / conflict-marker 残留
```

**关注点**：
- `tests/evaluation/test_eval_skeleton.py` 的 2 个 langfuse 云上传测试在当前机器失败（`ModuleNotFoundError: No module named 'langfuse'`）——这是 **pre-existing** 状态（与本次集成无关），不算回归。若 main 侧该模块一直被跳过/独立环境运行，按既有约定处理。
- 新增测试全部应在 `tests/web/` 下：`test_event_envelope.py`（11）、`test_web_phase2_endpoints.py`（4）、扩展的 `test_web_models.py`（+4）。

**可选冒烟**（非合入前提）：
```bash
uv run python -c "
from agent_harness.web.app import create_app
from agent_harness.config import Settings
from fastapi.testclient import TestClient
app = create_app(Settings(_env_file=None, model_api_key='sk-test', enable_cors=False))
c = TestClient(app)
print('models:', c.get('/api/models').json()['models'][0].keys())
print('permission-modes:', [m['id'] for m in c.get('/api/permission-modes').json()['modes']])
print('capabilities:', c.get('/api/capabilities').json())
"
```
预期：models 第一条带 `id`/`display_name`/`is_default`/`is_available`/`metadata_source`/`schema_version` 等键；permission-modes 返 `['read-only', 'workspace-write', 'danger-full-access']`；capabilities 返 `{'capabilities': []}`。

## D. Push 与收尾

1. 全绿后**最后一步**（需用户明确批准，§14.4）：
   ```bash
   git -C D:\intelligence-agent push origin main
   ```
2. `docs/PHASE_STATUS.md` 追加集成记录条目（验证数字 / 冲突情况 / push 时间）
3. 向用户报告：
   - 完成什么（SDD 包 + Phase 2 四交付物合入 main）
   - 改了哪些文件（23 files +5369/-18，其中 docs/spec 占 13 files +4396，代码 7 files +669/-18，测试 3 files +361）
   - 测试结果（pytest 通过数 / ruff 清洁）
   - commit 区间（`d91050a..9eb62a5`，3 commits）
   - 遗留项（见下）

### 遗留项（交接给后续 Phase）

- **Phase 3 Backend lead 剩余**：Phase 2 已交付事件信封骨架，Phase 3 还需稳定 LLM/工具生命周期事件 + settled assistant event（SDD 06 Phase 3）。事件信封的字段已在本次就位，Phase 3 主要做运行时发射侧的稳定化。
- **Phase 4 visibility 字段**：信封已留扩展位，Phase 4 Timeline 做密度时加。
- **Phase 5 交互式审批**：`GET /api/permission-modes` 已暴露 mode 列表，Phase 5 做 runtime 侧的 async ApprovalCallback + 暂停机制。
- **Phase 6 capability surfaces**：`CapabilityDescriptor.surfaces/actions` 字段已加，Phase 6 装配真实 capability 时填具体声明。
- **Code review 5 条 judgement calls**（已在 review 报告记录，不影响合入）：`_CAPABILITY_FIELDS` 在 `declared_capabilities()` 与 `_render_model_option` 两处重复定义是首要技术债，建议 Phase 3 或独立 tightening 批次收敛为单一迭代源。

## E. 异常处理

- **意外冲突**：停下报告用户（§14.7）。逐文件分析 main 与 feat/backend-c 各自动机，推荐语义并集方案，等待批准。禁止 `git checkout --ours/--theirs` 机械解决。
- **测试失败**：
  - 若是新增的 15 个测试失败 → Phase 2 实现问题，回到 `D:\intelligence-agent-backend` 修复，不合入。
  - 若是既有测试失败 → 确认是否 pre-existing（对比 main 集成前的运行结果）。若是新引入的回归，停下报告。
- **ruff 报错**：回到 backend worktree 修复，不在 main 侧直接改。
- **push 失败**（网络/权限）：如实报告，不自动重试到 force-push（§14.4 红线）。

---

## 附：本批次 Scope Lock 清单（合入前最后核对）

**做了**：
- ✅ 扩展 `PROVIDER_PRESETS` 加能力位（仅已知值）
- ✅ `GET /api/models` 富化 + 旧字段 alias
- ✅ `GET /api/permission-modes` + `PERMISSION_MODE_DESCRIPTIONS`
- ✅ `GET /api/capabilities` + `CapabilityDescriptor` 加 Optional surfaces/actions
- ✅ RuntimeEvent 信封三字段（schema_version/durability/capability）
- ✅ SSE live/replay/控制帧同形带信封
- ✅ JSONL 行 round-trip + 旧行回落兼容
- ✅ 15 新测试全绿 + 既有测试不破
- ✅ ruff 清洁

**没做（推迟）**：
- ❌ `visibility` 字段（Phase 4）
- ❌ 交互式审批 runtime（Phase 5）
- ❌ 具体 capability 的 surfaces/actions 声明（Phase 6）
- ❌ AgentRuntime / ToolExecutor / RunManager 核心逻辑改动
- ❌ SSE → WebSocket 迁移
- ❌ 既有测试断言修改（只加法扩展）
