# 遗留项交接单 —— 发给前端 AI 与后端 AI

> **本文档由 Git Integrator 维护，在每次集成后更新。**
> 最后更新：2026-09-08（B1 集成后）
> 当前 main HEAD = **`2015c69`**（origin/main 同步）
> 收件方按各自的 AGENTS.md §2/§3 阅读协议开工，完成后按 §14 写集成交接单发给 Git Integrator。

---

## 当前 main 状态（所有新分支的起点）

```
main HEAD = 2015c69（origin/main 同步）
含：
  - Phase 16 Final Full E2E（ADR-0019）
  - v1.0.0 release
  - Phase 2 Composer 后端支撑（只读端点 + RuntimeEvent 信封）
  - Phase 5 permission 三档 + 交互式审批 + 最小 resume + amend 三字段 no-op（ADR-0020）
  - Observable Agent Workspace 前端重构（Phase 1a-1d + Phase 2a ModelPicker）
  - SDD 包：docs/spec/Observable_Agent_Workspace_SDD/（单一规范路径，含 BACKEND_AUDIT + FRONTEND_AUDIT）
  - F2 ModelPicker Combobox 升级（Popover + cmdk Command，role=listbox+combobox+option）
  - B1 Context/Agent/Reasoning 四档契约清单端点（GET /api/reasoning-efforts + /api/agent-profiles + /api/context-providers）
```

**关键：所有新工作必须从 `2015c69`（或更新 main）开新 feature branch，不在已合并的分支上继续。**

---

## 已完成的 Ticket（归档参考）

| Ticket | 接收方 | 状态 | 集成 commit | 备注 |
| --- | --- | --- | --- | --- |
| **B1** | 后端 AI | ✅ 已集成 | `a45c665`（merge）→ `2015c69`（push） | 三个 GET 清单端点 + 单一事实源重构；9 条新测试全绿 |
| **F2** | 前端 AI | ✅ 已集成 | `f99ba9a`（merge）→ `70f2671`（push） | ModelPicker 升级 Popover+cmdk Command；364 vitest 全绿 |

---

## 依赖关系图（更新后）

```
[B1: 四档契约端点]           ✅ 已集成（2015c69）
        ↓
[F1: Phase 2b Composer control row]  ← 已解除阻塞，可从 2015c69 开分支
        ↓
[T-IDENTITY: test_identity.py 修复]  ← 独立，优先级中（4 条 pre-existing 失败）
        ↓
[RUNTIME: 三字段运行时消费]          ← 独立后续批次（各为独立 ticket）
```

---

## Ticket F1（前端 AI）：Phase 2b Composer control row

### 前置条件

**已解除阻塞** —— B1 已集成入 main（`2015c69`），三个 GET 清单端点已就绪：
- `GET /api/reasoning-efforts` → `{"efforts": [{id, display_name, description}]}`（minimal/standard/deep）
- `GET /api/agent-profiles` → `{"profiles": [{id, display_name, description}]}`（main/coding/research_review）
- `GET /api/context-providers` → `{"providers": []}`（当前诚实返空）

### 交付物

在 Composer 区块加一行 control row，含四个选择器：

| 控件 | 数据源 | main 已有？ |
| --- | --- | --- |
| Model 选择器 | `GET /api/models` | ✅ 已有（F2 ModelPicker Combobox 已消费） |
| Permission 模式 | `GET /api/permission-modes` | ✅ 端点已有，UI 待做 |
| Agent Profile | `GET /api/agent-profiles` | ✅ B1 已交付 |
| Reasoning Effort | `GET /api/reasoning-efforts` | ✅ B1 已交付 |
| Context Providers（多选） | `GET /api/context-providers` | ✅ B1 已交付（当前返空数组） |

### 约束

- **从新 main（`2015c69`）开新 feature branch**（不在已合并的 `feat/frontend-d` 上继续）
- **ModelPicker 已升级为 Combobox（F2），复用同模式**：Radix Popover + cmdk Command + Portal + provider 分组 + 搜索 + 空目录隐藏入口 + Esc/Enter 冒泡满足 §19 + reduced-motion 守护满足 §18/§21
- **空目录隐藏入口**：`/api/context-providers` 返 `[]` 时隐藏 Context Providers 控件，不伪造
- **会话内真相仍是模型卡**：控件只提交偏好到 `POST /api/sessions`，运行时是否消费由后端决定（当前 Phase 5 是 staged no-op，UI 不应断言"已生效"）
- **Scope Lock（§8）**：只加 Composer control row，不动 Inspector / Workspace / Conversation 等既有区块
- **测试**：每个控件至少 ① 正常选项 ② 空目录隐藏 ③ 提交 payload 字段名对齐后端契约 三条
- **GUI QA**：6 档宽度（1440/1280/1024/820/768/浅色）回归

### 验收标准

- [ ] Composer control row 四个控件落地（Permission / Agent / Reasoning / Context Providers），复用 ModelPicker Combobox 模式
- [ ] 空目录隐藏入口行为一致
- [ ] 提交 payload 字段名与后端 `POST /api/sessions` 契约完全对齐
- [ ] tsc 干净 / oxlint 0 errors / Vitest 全绿 / build 成功
- [ ] GUI QA 6 档宽度 + 浅色模式 PASS
- [ ] 写一份集成交接单发给 Git Integrator

### Worktree

- 前端 worktree：`D:\intelligence-agent-frontend`（或按 §13.1 另开）
- 分支命名：`feat/frontend-e`（或与用户约定）
- 从 `origin/main`（`2015c69` 或更新）开分支

---

## Ticket T-IDENTITY（后端 AI）：修复 test_identity.py 4 条 pre-existing 失败

### 优先级

**中** —— 不是 B1 引入的回归，但 4 条测试持续失败会污染全量 pytest 基线，影响后续集成的 "零失败" 判定。

### 背景

在 B1 集成过程中，Git Integrator 发现 `tests/test_identity.py` 有 4 条测试失败。经在 B1 merge 前的 main（`70f2671`）上验证：**同样 4 条失败** —— 确认 pre-existing，可能在 F2 集成或更早引入。

### 失败详情

```
FAILED tests/test_identity.py::test_auth_seam_sets_contextvar - AssertionError
FAILED tests/test_identity.py::test_no_secret_does_not_trust_bearer_identity
FAILED tests/test_identity.py::test_auth_fail_closed_when_secret_configured
FAILED tests/test_identity.py::test_auth_unset_secret_warns_loudly - KeyError: 'user_id'
```

### 症状

- 测试在 `create_app(...)` 上注册自定义路由 `@app.get("/identity-probe")`
- 请求 `/identity-probe` 返 **404 Not Found**（而非预期的 identity context JSON）
- 导致 `.json()["user_id"]` 抛 `KeyError: 'user_id'`
- stderr 显示 `INFO HTTP Request: GET http://testserver/identity-probe "HTTP/1.1 404 Not Found"`
- 同时 `WARNING JWT_SECRET 未配置` 日志正常发出（说明 `create_app` 启动钩子执行了）

### 初步诊断方向

这像是 **路由注册顺序 / middleware 覆盖** 问题：
- `create_app` 返回的 FastAPI 实例可能在某个中间件或 lifecycle 事件中"冻结"了路由表
- 或 B1/F2/Phase 5 引入的新端点 handler 注册方式改变了路由注册时序
- 测试在 `create_app` 返回后 `@app.get(...)` 注册的路由没有被 Starlette 的 routing 模块发现

后端 AI 应优先做：
1. **复现**：`uv run pytest tests/test_identity.py -v`（在当前 main `2015c69` 上）
2. **定位**：对比 `tests/test_identity.py` 最后一次全绿时的 main HEAD（`git log --all --oneline tests/test_identity.py`）做 `git bisect`
3. **根因**：检查 `create_app` 的路由注册是否在某个改动后变成了"注册窗口关闭"

### 约束

- **Scope Lock（§8）**：只修复 test_identity.py 相关的路由注册/中间件问题，不顺手重构
- **不删除测试**：这 4 条测试是 R6-4 身份认证 seam 的守卫，不能为了"让测试通过"而删测试
- **诚实修复**：如果是路由注册时序问题，修 app.py 的注册顺序；如果是测试写法问题（不应在 `create_app` 返回后注册路由），修测试的注册方式 —— 但必须报告并说明理由

### 验收标准

- [ ] 4 条 test_identity 测试全绿
- [ ] 全量 pytest 回归（预期恢复到 ~1241 passed 零失败）
- [ ] ruff clean
- [ ] 集成交接单发给 Git Integrator

### Worktree

- 后端 worktree：`D:\intelligence-agent-backend`（或按 §13.1 另开）
- 分支命名：`fix/identity-tests`（或与用户约定）
- 从 `origin/main`（`2015c69` 或更新）开分支

---

## Ticket RUNTIME（后端 AI）：三字段运行时消费（各为独立子批次）

### 背景

Phase 5（`df03990`）把 `reasoning_effort` / `agent_profile` / `context_providers` 作为 **staged 契约**接收：API 边界验证通过、运行时记 INFO 日志后忽略（诚实标注 `received but not yet consumed by runtime`）。B1（`a45c665`）交付了 GET 清单端点。但**运行时仍未消费**这三个字段。

### 子批次建议

每个字段独立一个子批次（各有独立的 provider 验证 + capability 依赖）：

1. **`reasoning_effort` 运行时落地**：逐家验证 provider 支持（deepseek-reasoner 无此参数、glm 思考模型无开关）→ 独立批次
2. **`agent_profile` 运行时落地**：接通 AgentFactory + tool_scope 收窄 + system_prompt 注入 → 独立批次
3. **`context_providers` 运行时消费**：加枚举端点 + 会话级筛选 → 独立批次（当前 `/api/context-providers` 诚实返空，待 provider registry 落地后自然返回真实清单）

### 约束

- 每个 sub-ticket 独立交付 + 独立集成
- 不投机泛化（§9.2）
- runtime 消费必须配真实 provider 验证（不能只靠 fake 通过测试就声称"已消费"）

### 验收标准

每个子批次：
- [ ] 运行时真实消费该字段（不是又一个 staged no-op）
- [ ] 配真实 provider 验证（至少 fake + 一家真实）
- [ ] pytest 全绿 + ruff clean
- [ ] 集成交接单发给 Git Integrator

---

## 给前端/后端 AI 的共同提醒

1. **起点**：从 `origin/main`（当前 `2015c69` 或更新）开分支，**先 `git fetch origin --prune` 再 `git merge-base` 确认拓扑**。
2. **不要复用本次的拓扑快照**：main 会继续前进，下次集成时拓扑必然不同。
3. **Scope Lock（§8）**：不顺手重构无关代码、不提前做未来批次、不扩大架构。
4. **Reuse First（§6）**：查 `docs/spec/13_OPEN_SOURCE_REUSE_MATRIX.md`，复用既有模式。
5. **集成交接单**：完成后写一份发给 Git Integrator，包含分支映射、commit 清单、变更摘要、完整验证证据、与 main 的正交性、冲突预测、风险评估。
6. **不自行 merge/push**：merge 到 main 是 Git Integrator 的职责，需用户明确批准（§14.4 / §14.11）。
7. **跑全量测试**：交接单的验证证据必须包含**全量 pytest**（不只是子集），以便 Git Integrator 对比基线、识别 pre-existing 失败。
8. **backend worktree 当前被 `feat/multiturn` 占用**：后端 AI 若要开新分支，注意 worktree 占用状态（`git worktree list`），必要时另开 worktree。

---

## Git Integrator 的承诺

- 收到集成交接单后，我会先做只读检查（worktree 状态、拓扑核验、merge-tree 冲突预测）再报告集成计划
- 发现任何冲突立即停下逐文件分析（§14.7），不机械 ours/theirs
- Windows 平台特定的风险（如大小写路径碰撞）我会主动检出并报告
- push 需用户单独批准，不隐含在 merge 批准里
- 全量 pytest 基线对比：每次集成时记录 passed/failed/skipped 数，pre-existing 失败会明确标注（不混淆为新引入回归）
