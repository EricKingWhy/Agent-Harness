# 集成交接单 —— Ticket B1（后端 AI）

> **本文档由后端 AI 在 Ticket B1 完成后起草，发给 Git Integrator。**
> 分支 `feat/backend-d` 从 `origin/main`（`431f75b`）起步。
> 交付物：三个只读 GET 清单端点（Context / Agent / Reasoning 四档契约）。

---

## 1. 分支映射

| 项 | 值 |
| --- | --- |
| Worktree | `D:\intelligence-agent-backend` |
| 分支 | `feat/backend-d` |
| 起点 | `origin/main` @ `431f75b` |
| 终点 | `07f47c9`（本分支 HEAD） |

---

## 2. 变更摘要

### 2.1 新增端点

| 端点 | 方法 | 返回结构 | 数据源 |
| --- | --- | --- | --- |
| `/api/reasoning-efforts` | GET | `{"efforts": [{id, display_name, description}]}` | `REASONING_EFFORT_DESCRIPTIONS` |
| `/api/agent-profiles` | GET | `{"profiles": [{id, display_name, description}]}` | `AGENT_PROFILE_DESCRIPTIONS` |
| `/api/context-providers` | GET | `{"providers": []}` | 当前 runtime 未装配任何 provider → 诚实返空 |

### 2.2 单一事实源重构

将 `CreateSessionRequest` 中的 `reasoning_effort` / `agent_profile` validator 从硬编码字面量改为引用模块级常量 dict：

- `REASONING_EFFORT_DESCRIPTIONS`：`minimal` / `standard` / `deep`
- `AGENT_PROFILE_DESCRIPTIONS`：`main` / `coding` / `research_review`

**效果**：validator 的合法值集合与 GET 清单端点的返回集合引用同一份常量 → 加新档位只改一处，两边永不漂移。

### 2.3 文件清单

| 文件 | 变更类型 | 说明 |
| --- | --- | --- |
| `src/agent_harness/web/app.py` | MODIFIED | +2 模块级常量 dict；validator 引用常量；+3 GET 端点 |
| `tests/web/test_web_phase5_staged_endpoints.py` | CREATED | 9 条测试（3 端点 × 3 case） |

---

## 3. 契约形态

### 3.1 对齐既有模式（Reuse First §6）

三个新端点的字段结构与 `/api/permission-modes` 完全一致：

```json
{
  "<plural_key>": [
    {
      "id": "<enum_value>",
      "display_name": "<human_readable>",
      "description": "<tooltip_text>"
    }
  ]
}
```

顶层 key 使用复数短名风格（`efforts` / `profiles` / `providers`），与既有 `models` / `modes` / `capabilities` 同模式。

### 3.2 空目录降级（诚实原则）

- `/api/context-providers` 当前返回 `{"providers": []}`
- 与 `/api/capabilities` 空目录降级同原则：空就是空，不伪造基础项
- 前端据空列表自行 fallback

### 3.3 不破坏 Phase 5 staged 语义

- POST `/api/sessions` 的三个 amend 字段（`reasoning_effort` / `agent_profile` / `context_providers`）仍保持 staged 接收 + 运行时 no-op
- 本次只加 GET 清单，不改 POST 行为
- Scope Lock §8：只加只读清单端点 + 测试，不做运行时消费

---

## 4. 验证证据

### 4.1 pytest

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

### 4.2 ruff

```
ruff check src/agent_harness/web/app.py tests/web/test_web_phase5_staged_endpoints.py
All checks passed!
```

> **注意**：`app.py` 存在预先存在的 ruff format 问题（非本次引入，基线 `431f75b` 即有）。按 §9.3 Surgical Changes，不顺手修复无关格式问题。

### 4.3 既有测试回归

web 测试套件 55/55 全绿（9 新增 + 46 既有），无回归。

---

## 5. 与 main 的正交性

### 5.1 改动范围

本次改动仅涉及：
- `src/agent_harness/web/app.py`：新增 2 个模块级常量 dict + 重构 2 个 validator 引用 + 新增 3 个 GET 端点 handler
- `tests/web/test_web_phase5_staged_endpoints.py`：新增测试文件

### 5.2 正交性分析

- **不触碰 POST /api/sessions**：staged 语义不变
- **不触碰 runtime**：不消费 reasoning_effort / agent_profile / context_providers
- **不触碰既有端点实现**：只在 `list_capabilities` 之后追加新 handler
- **validator 重构是行为等价的**：合法值集合不变，错误信息从硬编码字符串改为从常量 dict 动态生成（语义不变）

### 5.3 冲突预测

- **与 feat/multiturn 的潜在冲突**：`feat/multiturn` 分支（backend A 的 Phase 5.1 工作）也在修改 `app.py`（SessionService 重构、approval queue 变更等）。如果两个分支同时集成入 main，`app.py` 可能产生 merge conflict。建议先集成本分支（B1），再让 `feat/multiturn` rebase 到新 main。
- **与前端 F1 的依赖关系**：F1 依赖本 B1 的三个 GET 端点契约就位。本 B1 集成入 main 后，F1 可从新 main 开分支。

### 5.4 diff 范围

```
 docs/integration/BACKEND_D_HANDOFF.md         | 152 ++++++++++++++++++++++++++
 src/agent_harness/web/app.py                  |  99 ++++++++++++++++-
 tests/web/test_web_phase5_staged_endpoints.py | 138 +++++++++++++++++++++++
 3 files changed, 385 insertions(+), 4 deletions(-)
```

仅触及 `app.py`（+2 常量 dict / validator 引用常量 / +3 GET handler）和新增测试文件。不触碰 POST `/api/sessions` handler、不触碰 runtime、不触碰既有端点实现。

---

## 6. 遗留项

- **context_providers 运行时消费**：当前 GET 端点诚实返空数组。待 provider registry 落地后（独立批次），本端点会自然返回真实清单，契约形态不变。
- **reasoning_effort / agent_profile 运行时消费**：当前仍是 staged no-op。运行时落地是独立批次，本次只交付清单契约。

---

## 7. 下一步

等待 Git Integrator 审核本交接单，做只读检查（worktree 状态、拓扑核验、merge-tree 冲突预测），然后集成入 main。

集成入 main 后，前端 AI 可从新 main 开 `feat/frontend-d` 分支做 F1（Phase 2b Composer control row）。
