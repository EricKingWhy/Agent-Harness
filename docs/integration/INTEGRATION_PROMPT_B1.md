# 集成 AI 执行手册 —— Ticket B1（后端 → Git Integrator）

> **发件方**：后端 AI（worktree `D:\intelligence-agent-backend`，分支 `feat/backend-d`）
> **收件方**：Git Integrator（集成 AI）
> **日期**：2026-09-08
> **任务来源**：`D:\intelligence-agent\docs\integration\HANDOFF_REMAINING_TICKETS.md` — Ticket B1

---

## 0. 你的角色

你是 Git Integrator。你的职责是：
1. 只读检查本分支（worktree 状态、拓扑核验、merge-tree 冲突预测）；
2. 将 `feat/backend-d` 集成入 `main`；
3. 集成完成后更新 `docs/PHASE_STATUS.md`；
4. push 需要**用户单独批准**（§14.4 / §14.11），不隐含在 merge 批准里。

**禁止**：机械使用 `ours` / `theirs`；为了冲突消失直接删除一侧逻辑；擅自修改冲突文件或 `git add`。

---

## 1. 分支信息

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-backend` |
| 分支 | `feat/backend-d` |
| 起点 | `origin/main` @ `431f75b` |
| 终点 | `f742cb7`（本分支 HEAD） |
| commit 数 | 1（单 commit，基于 `431f75b`） |

---

## 2. 交付物

### 2.1 三个只读 GET 清单端点

| 端点 | 返回结构 | 已知值 |
| --- | --- | --- |
| `GET /api/reasoning-efforts` | `{"efforts": [{id, display_name, description}]}` | minimal / standard / deep |
| `GET /api/agent-profiles` | `{"profiles": [{id, display_name, description}]}` | main / coding / research_review |
| `GET /api/context-providers` | `{"providers": []}` | 当前诚实返空（runtime 未装配任何 provider） |

### 2.2 单一事实源重构

将 `CreateSessionRequest` 中的 `reasoning_effort` / `agent_profile` validator 从硬编码字面量改为引用模块级常量 dict：

- `REASONING_EFFORT_DESCRIPTIONS`：`minimal` / `standard` / `deep`
- `AGENT_PROFILE_DESCRIPTIONS`：`main` / `coding` / `research_review`

**效果**：validator 的合法值集合与 GET 清单端点的返回集合引用同一份常量 → 加新档位只改一处，两边永不漂移。

### 2.3 文件清单

| 文件 | 变更类型 | 说明 |
| --- | --- | --- |
| `src/agent_harness/web/app.py` | MODIFIED | +2 模块级常量 dict；validator 引用常量；+3 GET handler |
| `tests/web/test_web_phase5_staged_endpoints.py` | CREATED | 9 条测试（3 端点 × 3 case） |
| `docs/integration/BACKEND_D_HANDOFF.md` | CREATED | 集成交接单 |

diff 范围：

```
 docs/integration/BACKEND_D_HANDOFF.md         | 165 ++++++++++++++++++++++++++
 src/agent_harness/web/app.py                  |  99 ++++++++++++++++-
 tests/web/test_web_phase5_staged_endpoints.py | 138 +++++++++++++++++++++++
 3 files changed, 398 insertions(+), 4 deletions(-)
```

---

## 3. 验证证据

### 3.1 pytest

```
1241 passed, 1 skipped, 39 deselected, 8 warnings in 145.51s
```

新增测试 9 条全绿（3 端点 × 3 case）：

```
tests/web/test_web_phase5_staged_endpoints.py::TestReasoningEfforts::test_returns_three_known_efforts PASSED
tests/web/test_web_phase5_staged_endpoints.py::TestReasoningEfforts::test_schema_locked PASSED
tests/web/test_web_phase5_staged_endpoints.py::TestReasoningEfforts::test_id_set_matches_validator PASSED
tests/web/test_web_phase5_staged_endpoints.py::TestAgentProfiles::test_returns_three_known_profiles PASSED
tests/web/test_web_phase5_staged_endpoints.py::TestAgentProfiles::test_schema_locked PASSED
tests/web/test_web_phase5_staged_endpoints.py::TestAgentProfiles::test_id_set_matches_validator PASSED
tests/web/test_web_phase5_staged_endpoints.py::TestContextProviders::test_empty_by_default_is_honest PASSED
tests/web/test_web_phase5_staged_endpoints.py::TestContextProviders::test_schema_locked PASSED
tests/web/test_web_phase5_staged_endpoints.py::TestContextProviders::test_top_level_key_stable PASSED
```

web 测试套件回归：55/55 全绿（9 新增 + 46 既有），无回归。

### 3.2 ruff

```
ruff check src/agent_harness/web/app.py tests/web/test_web_phase5_staged_endpoints.py
All checks passed!
```

> **注意**：`app.py` 存在预先存在的 ruff format 问题（基线 `431f75b` 即有）。按 §9.3 Surgical Changes，不顺手修复无关格式问题。

---

## 4. 与 main 的正交性

### 4.1 改动范围

本次改动仅涉及：
- `src/agent_harness/web/app.py`：新增 2 个模块级常量 dict + 重构 2 个 validator 引用 + 新增 3 个 GET handler
- `tests/web/test_web_phase5_staged_endpoints.py`：新增测试文件
- `docs/integration/BACKEND_D_HANDOFF.md`：新增交接单

### 4.2 正交性分析

- **不触碰 POST /api/sessions**：staged 语义不变
- **不触碰 runtime**：不消费 reasoning_effort / agent_profile / context_providers
- **不触碰既有端点实现**：只在 `list_capabilities` 之后追加新 handler
- **validator 重构是行为等价的**：合法值集合不变，错误信息从硬编码字符串改为从常量 dict 动态生成（语义不变）

### 4.3 冲突预测

- **与 feat/multiturn 的潜在冲突**：`feat/multiturn` 分支（backend A 的 Phase 5.1 工作）也在修改 `app.py`（SessionService 重构、approval queue 变更等）。如果两个分支同时集成入 main，`app.py` 可能产生 merge conflict。建议先集成本分支（B1），再让 `feat/multiturn` rebase 到新 main。
- **与前端 F1 的依赖关系**：F1 依赖本 B1 的三个 GET 端点契约就位。本 B1 集成入 main 后，F1 可从新 main 开分支。

---

## 5. 遗留项

- **context_providers 运行时消费**：当前 GET 端点诚实返空数组。待 provider registry 落地后（独立批次），本端点会自然返回真实清单，契约形态不变。
- **reasoning_effort / agent_profile 运行时消费**：当前仍是 staged no-op。运行时落地是独立批次，本次只交付清单契约。

---

## 6. 下一步

等待 Git Integrator 审核本交接单，做只读检查（worktree 状态、拓扑核验、merge-tree 冲突预测），然后集成入 main。

集成入 main 后，前端 AI 可从新 main 开 `feat/frontend-d` 分支做 F1（Phase 2b Composer control row）。
