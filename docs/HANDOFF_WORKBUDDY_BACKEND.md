# WorkBuddy 后端交接手册

> **仓库**：`intelligence-agent`
> **后端 worktree**：`D:\intelligence-agent-backend`
> **后端分支**：`feat/backend`
> **main HEAD**：`977b319`（已 push GitHub）
> **feat/backend HEAD**：`c438a1e`（= main 的祖先，已被 main 完全包含）

---

## 一、当前状态

### 已完成并合入 main 的后端工作

| Ticket | 标题 | commit | 状态 |
|---|---|---|---|
| #137 T7 | 会话级模型切换 + Fork API/CLI 接线 | `ae553ad` | ✅ OPEN（前端 UI 待做） |
| #138 T8 | 崩溃恢复——run/interrupted + Ledger reconcile | `ccebf9a` | ✅ CLOSED |
| #139 T9 | Langfuse turn_index 埋点 | `c438a1e` | ✅ CLOSED |
| #140 Fix | P0-001 续聊 SSE 序列化崩溃 / FE-04 竞态守卫 / P2-003 死代码 | `169d9a4` 等 | ✅ CLOSED |

### 后端分支拓扑

```
origin/main (977b319)
    ↑
feat/backend (c438a1e) ← 已被 main 完全包含，0 commits ahead
```

**结论**：`feat/backend` 没有未合入的后端 commit。后端侧的工作已经全部进入 main。

---

## 二、唯一剩余的 open issue

### #137 — Phase Multiturn T7: 模型切换 + Fork API/UI/CLI

这是跨端 ticket：
- **后端部分**已完成（commit `ae553ad`，已合入 main）
- **前端 UI 部分**待前端实现

后端已交付的 API：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/sessions/{id}/model` | POST | 切换会话当前模型 |
| `/api/sessions/{id}/forks` | POST | 从历史用户消息 seq 派生 child session |
| `/api/sessions/{id}/lineage` | GET | 会话谱系树（祖先 + 后代 + 边） |

详细 API 契约见 [docs/HANDOFF_FRONTEND_T7.md](/D:/intelligence-agent-backend/docs/HANDOFF_FRONTEND_T7.md)。

---

## 三、后端没有更多待做的 ticket

所有 phase-multiturn 后端 ticket 已关闭：

| # | 标题 | 状态 |
|---|---|---|
| 131 | T1 SessionService 领域层抽离 | CLOSED |
| 132 | T2 续聊端点 + WebSocket + queue/steer | CLOSED |
| 133 | T3 CLI 续聊重构 + slash 命令 | CLOSED |
| 134 | T4 压缩 bracket 升级 + 六段式摘要 | CLOSED |
| 135 | T5 大产物外置对象存储（MinIO + artifact 引用） | CLOSED |
| 136 | T6 审批 WS 推送 + HTTP 回传（fail-closed one-shot） | CLOSED |
| 137 | T7 模型切换 + Fork API/UI/CLI | OPEN（前端 UI 待做） |
| 138 | T8 崩溃恢复 + Ledger reconcile（不盲重跑） | CLOSED |
| 139 | T9 Langfuse 多轮埋点 + 长期记忆验证 + DoD 全量回归 | CLOSED |
| 140 | Spec: Agent Harness 修复 Phase — P0-001 / FE-04 / P2-003 | CLOSED |

---

## 四、测试基线

| 项目 | 结果 |
|---|---|
| ruff check | All checks passed |
| 全量 pytest | **1485 passed / 9 skipped / 0 failed** |
| pytest 默认 lane | `-m "not integration and not qiniu"`（39 deselected） |

已知 flake：`tests/web/test_web_stream.py` / `tests/web/test_web_ws_relay.py` 在某些全量运行中存在真实服务器计时失败；在隔离环境及重新运行时可通过。

---

## 五、架构深化候选（out-of-scope，供后续迭代）

`/improve-codebase-architecture` 扫描发现 3 个 Strong 候选：

1. **`AgentRuntime._drive` 分解** — 632 行 async generator；提取 `RunContext` value object 并合并 cancel/failure 臂
2. **`SessionService` 拆分** — 1228 行 god object；沿 seam 线拆分（lifecycle/approval/model-switch/recovery）
3. **Recovery 流程整合** — `scan.py` 是 `RecoveryCoordinator.recover()` 的薄包装；fold into coordinator 或 service

这些都是 §8 Scope Lock 下的 out-of-scope 重构，不影响当前功能。

---

## 六、给 WorkBuddy 的提示词

```
你是后端开发 AI（WorkBuddy），负责 intelligence-agent 项目的后端开发。

## 当前状态

- 后端分支 `feat/backend` HEAD = `c438a1e`，已被 main（`977b319`）完全包含
- 所有 phase-multiturn 后端 ticket 已关闭
- 唯一 OPEN 的 issue 是 #137（跨端 ticket，后端完成，前端 UI 待前端实现）
- 测试基线：ruff clean；pytest 1485 passed / 9 skipped / 0 failed

## 你的职责

1. 如果用户分配新的后端 ticket，使用 SDD 方式开发：
   - /implement（TDD：先红后绿）
   - /code-review（两轴：Standards + Spec）
   - 发现 bug → /diagnose-bug → 修复 → 再 /code-review
   - 循环直到零 finding
   - ruff check + 全量 pytest 通过后 commit
   - 不推送远程 GitHub（集成 AI 做的事）

2. 如果前端 AI 提出接口对齐问题，检查后端契约是否与 PRD 一致

3. 如果遇到不知道怎么做的问题，使用 /ask-matt 寻求指导

## 关键文件

- AGENTS.md — 工程规范（§16 SDD 长任务工作流协议防指令漂移）
- docs/PHASE_STATUS.md — 进度单一事实源
- docs/spec/ — 正式工程规格
- src/agent_harness/ — 后端源码
- tests/ — 测试套件

## 工作流协议（AGENTS.md §16）

每个 ticket 严格按以下顺序执行：

1. 读 spec + 现状审计
2. /implement（TDD：先红后绿；Reuse First）
3. /code-review（两轴：Standards + Spec）
   - 发现问题 → 修复 → 再 /code-review
   - 循环直到零 finding
4. ruff check + 全量 pytest
5. git add <相关文件> + git commit
6. 关单判定（§14.12）
7. 更新 docs/PHASE_STATUS.md
8. 写集成提示词到 docs/INTEGRATION_PROMPT_*.md

## 防漂移纪律

- 每个 ticket 开始前：重读 AGENTS.md §16，确认当前在哪个步骤
- 每个 ticket 完成后：更新 docs/PHASE_STATUS.md
- 不允许跳过 /code-review
- 不允许跳过测试
- 不推送远程
- 上下文被摘要后：重新读 docs/PHASE_STATUS.md 确认进度，读本节确认工作流
```

---

## 七、相关文档索引

| 文档 | 说明 |
|---|---|
| [docs/HANDOFF_FRONTEND_T7.md](/D:/intelligence-agent-backend/docs/HANDOFF_FRONTEND_T7.md) | 前端交接手册（#137 前端 UI 部分） |
| [docs/HANDOFF_FRONTEND_T7_T9.md](/D:/intelligence-agent-backend/docs/HANDOFF_FRONTEND_T7_T9.md) | 前端交接手册（T7-T9 完整版） |
| [docs/INTEGRATION_PROMPT_FEAT_BACKEND_T7_T9.md](/D:/intelligence-agent-backend/docs/INTEGRATION_PROMPT_FEAT_BACKEND_T7_T9.md) | 后端集成提示词（T7-T9） |
| [docs/PHASE_STATUS.md](/D:/intelligence-agent-backend/docs/PHASE_STATUS.md) | 进度单一事实源 |
| [AGENTS.md](/D:/intelligence-agent-backend/AGENTS.md) | 工程规范（§16 SDD 长任务工作流协议） |
